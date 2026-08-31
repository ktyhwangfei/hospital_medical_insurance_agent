'use client'

/**
 * usePolicyQAStream —— 政策问答持续对话 SSE hook
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §6.2
 *
 * 与 useChatStream 的差异：
 * - 面向 POST /policy-qa/stream，事件名为后端原始名（context_need / memory_update /
 *   reasoning_step / step / result / done），不复用 readSseStream 的 SseEventType 白名单
 * - 持有会话级状态：sessionId（跨轮复用）/ anchor / memories / messages / lastContextNeed
 * - snake_case → camelCase 转换统一在本 hook 内完成（§6.3），组件层只见 camelCase
 * - 降级友好：任一 Runtime 事件解析失败只记日志，不阻塞 step/result 主流程
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  applyContextNeed,
  clearPersistedSessionId,
  emptyAnchor,
  loadPersistedSessionId,
  newSessionId,
  persistSessionId,
  resetTurnFlags,
  restoreSessionState,
  toContextNeed,
  toMemoryCard,
  upsertMemory,
  type ContextNeedSnapshot,
  type MemoryCard,
  type PolicyQAChatMessage,
  type RawContextNeed,
  type RawMemoryUpdate,
  type SessionAnchor,
  type TrajectoryResponseDTO,
} from '@/lib/policy-qa-session'
import {
  parseSseBlock,
  sanitizePublicPayload,
  toPolicyQAResult,
  type PolicyQAResult,
} from '@/lib/policy-qa-stream'

// ── 本轮执行步骤（对话流顶部的轻量 trace）─────────────────────────

export interface PolicyQATurnStep {
  step: string
  status: 'pending' | 'running' | 'done' | 'error' | 'streaming'
  publicMessage?: string
}

export interface SessionEscalationInfo {
  taskId: string
  status: string
  reply: string
  reason: string
}

export interface UsePolicyQAStreamReturn {
  /** 跨轮不变的会话 ID */
  sessionId: string
  anchor: SessionAnchor
  memories: MemoryCard[]
  messages: PolicyQAChatMessage[]
  lastContextNeed: ContextNeedSnapshot | null
  /** 当前轮执行步骤（流式期间更新） */
  steps: PolicyQATurnStep[]
  isStreaming: boolean
  error: string | null
  /** 刷新后是否正在从持久化轨迹恢复 */
  restoring: boolean
  /** 会话生命周期状态（active/suspended/escalated/closed；unknown=尚未查询） */
  sessionStatus: string
  statusReason: string
  /** 最近一次升级工单（含医保办回复） */
  escalation: SessionEscalationInfo | null
  /**
   * 发起一轮对话。settlementId 缺省时复用 anchor.settlementId；
   * 两者皆空返回 false（调用方提示用户先锚定结算单号）；
   * 非活跃会话（挂起/升级中）拒绝发送。
   */
  send: (question: string, opts?: { settlementId?: string }) => Promise<boolean>
  /** 新建会话：新 sessionId + 清空记忆/消息/锚点/持久化 */
  resetSession: () => void
  /** 挂起当前会话 */
  suspendSession: (reason?: string) => Promise<void>
  /** 恢复挂起会话并重建轨迹 */
  resumeSession: () => Promise<void>
  /** 升级问题至医保办 */
  escalateSession: (question: string, reason?: string) => Promise<void>
  /** 医保办回复升级工单（dev 模拟入口）；成功后本地状态转 active 并展示回复 */
  resolveEscalation: (reply: string) => Promise<boolean>
  /** 局部更新锚点（如 @换患者） */
  updateAnchor: (patch: Partial<SessionAnchor>) => void
  /** 关闭主体切换横幅 */
  dismissSubjectChange: () => void
  /** 向对话流追加一条本地消息（如 @指令 的确认提示） */
  appendLocalMessage: (msg: PolicyQAChatMessage) => void
}

const STREAM_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/stream'
const SESSIONS_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/sessions'

async function fetchJson(url: string, init?: RequestInit): Promise<{ ok: boolean; status: number; data: unknown }> {
  const response = await fetch(url, init)
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    // 非 JSON 响应按空处理
  }
  return { ok: response.ok, status: response.status, data }
}

function isTurnStepStatus(value: unknown): value is PolicyQATurnStep['status'] {
  return (
    value === 'pending' ||
    value === 'running' ||
    value === 'done' ||
    value === 'error' ||
    value === 'streaming'
  )
}

/** 更新最后一条 assistant 消息（本轮 in-flight 消息） */
function updateLastAssistant(
  setMessages: React.Dispatch<React.SetStateAction<PolicyQAChatMessage[]>>,
  updater: (msg: PolicyQAChatMessage) => PolicyQAChatMessage,
): void {
  setMessages((prev) => {
    for (let i = prev.length - 1; i >= 0; i--) {
      if (prev[i].role === 'assistant') {
        const next = [...prev]
        next[i] = updater(prev[i])
        return next
      }
    }
    return prev
  })
}

function applyPublicResult(
  msg: PolicyQAChatMessage,
  result: PolicyQAResult,
  contextNeed: ContextNeedSnapshot | null,
  qaTurnId?: string,
): PolicyQAChatMessage {
  return {
    ...msg,
    content: result.answer,
    answerStatus: result.answerStatus,
    contextNeed: contextNeed ?? undefined,
    calculationSteps: result.calculationSteps,
    definition: result.definition,
    warnings: result.warnings,
    caseContext: result.caseContext,
    citations: result.citations,
    uncertainties: result.uncertainties,
    verificationSummary: result.verificationSummary,
    // 仅在消息尚未锁定 ID 时写入；result 与 done 不一致时以首轮锁定的为准
    qaTurnId: msg.qaTurnId ?? qaTurnId,
  }
}

export function usePolicyQAStream(): UsePolicyQAStreamReturn {
  const [sessionId, setSessionId] = useState<string>(() => newSessionId())
  const [anchor, setAnchor] = useState<SessionAnchor>(() => emptyAnchor())
  const [memories, setMemories] = useState<MemoryCard[]>([])
  const [messages, setMessages] = useState<PolicyQAChatMessage[]>([])
  const [lastContextNeed, setLastContextNeed] = useState<ContextNeedSnapshot | null>(null)
  const [steps, setSteps] = useState<PolicyQATurnStep[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Issue #30：会话生命周期状态与轨迹恢复
  const [restoring, setRestoring] = useState(false)
  const [sessionStatus, setSessionStatus] = useState('unknown')
  const [statusReason, setStatusReason] = useState('')
  const [escalation, setEscalation] = useState<SessionEscalationInfo | null>(null)

  // 异步 send 内需要读取最新锚点 / 会话，使用 ref 避免闭包过期
  // （ref 在 effect 中同步，避免 render 期间写 ref）
  const anchorRef = useRef(anchor)
  const sessionIdRef = useRef(sessionId)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    anchorRef.current = anchor
  }, [anchor])
  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  // ── 刷新恢复：挂载时从持久化轨迹重建会话（Issue #30 §六）──
  useEffect(() => {
    const persisted = loadPersistedSessionId()
    if (!persisted) return
    let cancelled = false
    void (async () => {
      setRestoring(true)
      try {
        const { ok, data } = await fetchJson(
          `${SESSIONS_URL}/${encodeURIComponent(persisted)}/trajectory?user_id=demo`,
        )
        if (cancelled) return
        if (ok && data && typeof data === 'object') {
          const trajectory = data as TrajectoryResponseDTO
          const restored = restoreSessionState(trajectory)
          setSessionId(trajectory.session_id)
          setAnchor(restored.anchor)
          setMemories(restored.memories)
          setMessages(restored.messages)
          setSessionStatus(trajectory.status)
          setStatusReason(trajectory.status_reason ?? '')
          // 恢复升级工单信息（含医保办回复）
          const detail = await fetchJson(
            `${SESSIONS_URL}/${encodeURIComponent(persisted)}?user_id=demo`,
          )
          if (!cancelled && detail.ok && detail.data && typeof detail.data === 'object') {
            const esc = (detail.data as { escalation?: Record<string, unknown> }).escalation
            if (esc && esc.task_id) {
              setEscalation({
                taskId: String(esc.task_id),
                status: String(esc.status ?? ''),
                reply: String(esc.reply ?? ''),
                reason: String(esc.reason ?? ''),
              })
            }
          }
        } else {
          // 会话不存在（服务端重启/内存存储）：清除残留，开新会话
          clearPersistedSessionId()
        }
      } catch {
        if (!cancelled) clearPersistedSessionId()
      } finally {
        if (!cancelled) setRestoring(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // ── SSE 事件分发（每个事件独立 try/catch，失败不阻塞主流程）────
  const dispatchEvent = useCallback(
    (
      event: string,
      data: unknown,
      turnContextNeed: { current: ContextNeedSnapshot | null },
      turnResultReceived: { current: boolean },
      turnQaTurnId: { current: string | undefined },
    ) => {
      try {
        switch (event) {
          case 'context_need': {
            const cn = toContextNeed((data ?? {}) as RawContextNeed)
            turnContextNeed.current = cn
            setLastContextNeed(cn)
            setMemories((prev) => applyContextNeed(prev, cn))
            setAnchor((prev) => ({
              ...prev,
              // 同步后端回显的结算单与话题（话题标签展示）
              settlementId: cn.settlementId ?? prev.settlementId,
              topic: cn.topic ?? prev.topic,
              ...(cn.subjectChanged
                ? {
                    subjectChanged: true,
                    subjectChangeMsg: `已切换业务主体，旧结算/患者上下文已清除（政策记忆保留）`,
                  }
                : {}),
            }))
            break
          }
          case 'memory_update': {
            const mu = (data ?? {}) as RawMemoryUpdate
            if (mu.memory) {
              const card = toMemoryCard(mu.memory)
              setMemories((prev) => upsertMemory(prev, card))
            }
            break
          }
          case 'reasoning_step': {
            // Policy QA 不向 UI 暴露或保存模型推理轨迹。
            break
          }
          case 'step': {
            const d = (data ?? {}) as Record<string, unknown>
            const publicMessage = typeof d.public_message === 'string' ? d.public_message : undefined
            if (!publicMessage) break
            const status = isTurnStepStatus(d.status) ? d.status : 'running'
            // 只保留当前公开进度文案，不保存内部步骤名或历史执行轨迹。
            setSteps([{ step: 'progress', status, publicMessage }])
            break
          }
          case 'result': {
            const payload = (data ?? {}) as Record<string, unknown>
            const rawQaTurnId = payload.qa_turn_id
            const eventQaTurnId = typeof rawQaTurnId === 'string' ? rawQaTurnId : undefined
            const result = toPolicyQAResult(payload.result)
            turnResultReceived.current = true
            if (eventQaTurnId) {
              turnQaTurnId.current = eventQaTurnId
            }
            updateLastAssistant(setMessages, (msg) =>
              applyPublicResult(msg, result, turnContextNeed.current, eventQaTurnId),
            )
            break
          }
          case 'done': {
            // done 与 result 必须共享同一 qa_turn_id；不一致视为流契约错误，不覆盖消息
            const payload = (data ?? {}) as Record<string, unknown>
            const doneQaTurnId =
              typeof payload.qa_turn_id === 'string' ? payload.qa_turn_id : undefined
            if (doneQaTurnId && doneQaTurnId !== turnQaTurnId.current) {
              console.warn(
                `[usePolicyQAStream] qa_turn_id 契约不一致: result=${turnQaTurnId.current} done=${doneQaTurnId}，保留首轮 ID`,
              )
            }
            break
          }
          case 'error': {
            const d = (data ?? {}) as Record<string, unknown>
            const message = typeof d.message === 'string' ? d.message : '政策问答服务异常'
            setError(message)
            updateLastAssistant(setMessages, (msg) => ({
              ...msg,
              content:
                msg.content ||
                `暂无法回答该问题：${message}\n\n` +
                  '建议您核对结算单号后重试；如有疑问，请携带结算单前往医院医保办（收费窗口）' +
                  '或拨打当地医保局服务热线咨询。\n\n本回答仅供参考，不作为报销或结算依据。',
            }))
            break
          }
          default:
            // done / trace_event 等事件不改变会话状态
            break
        }
      } catch (e) {
        // 降级原则：单个 Runtime 事件解析失败只记日志
        console.warn(`[usePolicyQAStream] 事件 ${event} 解析失败（已忽略）`, e)
      }
    },
    [],
  )

  // ── 发起一轮对话 ─────────────────────────────────────────────
  const send = useCallback(
    async (question: string, opts?: { settlementId?: string }): Promise<boolean> => {
      const text = question.trim()
      const settlementId = opts?.settlementId ?? anchorRef.current.settlementId
      if (!text || !settlementId || isStreaming) return false
      // 挂起/升级中的会话拒绝新问答（后端同样拦截，双保险）
      if (
        sessionStatus === 'suspended' ||
        sessionStatus === 'escalated' ||
        sessionStatus === 'closed'
      ) {
        setError('当前会话已挂起或升级中，请先恢复会话或新建会话。')
        return false
      }
      persistSessionId(sessionIdRef.current)

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setIsStreaming(true)
      setError(null)
      setSteps([])
      setMemories(resetTurnFlags)
      setAnchor((prev) => ({
        ...prev,
        settlementId,
        subjectChanged: false,
        subjectChangeMsg: null,
      }))
      // 用户消息 + 占位 assistant 消息（in-flight）
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: text },
        { role: 'assistant', content: '' },
      ])

      const turnContextNeed: { current: ContextNeedSnapshot | null } = { current: null }
      const turnResultReceived = { current: false }
      const turnQaTurnId: { current: string | undefined } = { current: undefined }

      try {
        const response = await fetch(STREAM_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: text,
            settlement_id: settlementId,
            session_id: sessionIdRef.current,
            user_id: 'demo',
            role: 'cashier',
          }),
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (!response.body) throw new Error('浏览器不支持流式响应')

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) {
              buffer += decoder.decode()
              break
            }
            buffer += decoder.decode(value, { stream: true })
            const blocks = buffer.split(/\r?\n\r?\n/)
            buffer = blocks.pop() ?? ''
            for (const block of blocks) {
              const evt = parseSseBlock(block)
              if (evt) {
                dispatchEvent(
                  evt.event,
                  sanitizePublicPayload(evt.data),
                  turnContextNeed,
                  turnResultReceived,
                  turnQaTurnId,
                )
                // 出让微任务队列给 React 渲染（与 readSseStream 相同理由）
                await new Promise<void>((resolve) => setTimeout(resolve, 0))
              }
            }
          }
          // 处理尾部残留
          const tail = parseSseBlock(buffer)
          if (tail) {
            dispatchEvent(
              tail.event,
              sanitizePublicPayload(tail.data),
              turnContextNeed,
              turnResultReceived,
              turnQaTurnId,
            )
          }
        } finally {
          reader.releaseLock()
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          const message = e instanceof Error ? e.message : String(e)
          console.warn('[usePolicyQAStream] SSE 请求失败', e)
          setError(message)
          updateLastAssistant(setMessages, (msg) => ({
            ...msg,
            content:
              msg.content ||
              `服务暂时不可用，请稍后重试。\n\n如持续异常，请联系医院信息科或携带结算单前往医保办咨询。\n\n本回答仅供参考，不作为报销或结算依据。`,
          }))
        }
      }

      if (!controller.signal.aborted && !turnResultReceived.current) {
        const unavailable = toPolicyQAResult(undefined)
        updateLastAssistant(setMessages, (msg) =>
          applyPublicResult(msg, unavailable, turnContextNeed.current),
        )
      }

      setIsStreaming(false)
      return true
    },
    [dispatchEvent, isStreaming, sessionStatus],
  )

  // ── 新会话 ───────────────────────────────────────────────────
  const resetSession = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    const sid = newSessionId()
    setSessionId(sid)
    persistSessionId(sid)
    setAnchor(emptyAnchor())
    setMemories([])
    setMessages([])
    setLastContextNeed(null)
    setSteps([])
    setError(null)
    setIsStreaming(false)
    setSessionStatus('active')
    setStatusReason('')
    setEscalation(null)
  }, [])

  // ── 会话生命周期动作（Issue #30）──────────────────────────
  const suspendSession = useCallback(async (reason = '') => {
    const { ok, data } = await fetchJson(
      `${SESSIONS_URL}/${encodeURIComponent(sessionIdRef.current)}/suspend?user_id=demo`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      },
    )
    if (ok && data && typeof data === 'object') {
      const body = data as { status?: string; status_reason?: string }
      setSessionStatus(body.status ?? 'suspended')
      setStatusReason(body.status_reason ?? '')
    }
  }, [])

  const resumeSession = useCallback(async () => {
    const { ok, data } = await fetchJson(
      `${SESSIONS_URL}/${encodeURIComponent(sessionIdRef.current)}/resume?user_id=demo`,
      { method: 'POST' },
    )
    if (ok && data && typeof data === 'object') {
      const body = data as {
        status?: string
        status_reason?: string
        trajectory?: TrajectoryResponseDTO
      }
      setSessionStatus(body.status ?? 'active')
      setStatusReason(body.status_reason ?? '')
      if (body.trajectory) {
        const restored = restoreSessionState(body.trajectory)
        setAnchor(restored.anchor)
        setMemories(restored.memories)
        setMessages(restored.messages)
      }
    }
  }, [])

  const escalateSession = useCallback(async (question: string, reason = '') => {
    const { ok, data } = await fetchJson(
      `${SESSIONS_URL}/${encodeURIComponent(sessionIdRef.current)}/escalate?user_id=demo`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, reason }),
      },
    )
    if (ok && data && typeof data === 'object') {
      const esc = (data as { escalation?: Record<string, unknown> }).escalation
      setSessionStatus('escalated')
      if (esc && esc.task_id) {
        setEscalation({
          taskId: String(esc.task_id),
          status: String(esc.status ?? ''),
          reply: String(esc.reply ?? ''),
          reason: String(esc.reason ?? ''),
        })
      }
    }
  }, [])

  const resolveEscalation = useCallback(async (reply: string) => {
    const taskId = escalation?.taskId
    if (!taskId || !reply.trim()) return false
    const { ok, data } = await fetchJson(
      `${SESSIONS_URL.replace('/sessions', '')}/escalations/${encodeURIComponent(taskId)}/resolve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply, resolved_by: 'dev-simulated' }),
      },
    )
    if (ok && data && typeof data === 'object') {
      setSessionStatus('active')
      setStatusReason('')
      setEscalation((prev) =>
        prev ? { ...prev, status: 'completed', reply } : prev,
      )
      return true
    }
    return false
  }, [escalation?.taskId])

  const updateAnchor = useCallback((patch: Partial<SessionAnchor>) => {
    setAnchor((prev) => ({ ...prev, ...patch }))
  }, [])

  const dismissSubjectChange = useCallback(() => {
    setAnchor((prev) => ({ ...prev, subjectChanged: false, subjectChangeMsg: null }))
  }, [])

  const appendLocalMessage = useCallback((msg: PolicyQAChatMessage) => {
    setMessages((prev) => [...prev, msg])
  }, [])

  return {
    sessionId,
    anchor,
    memories,
    messages,
    lastContextNeed,
    steps,
    isStreaming,
    error,
    restoring,
    sessionStatus,
    statusReason,
    escalation,
    send,
    resetSession,
    suspendSession,
    resumeSession,
    escalateSession,
    resolveEscalation,
    updateAnchor,
    dismissSubjectChange,
    appendLocalMessage,
  }
}
