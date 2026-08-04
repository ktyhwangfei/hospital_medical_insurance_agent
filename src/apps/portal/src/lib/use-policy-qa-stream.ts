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
  emptyAnchor,
  mergeReasoningSteps,
  newSessionId,
  parseSseBlock,
  resetTurnFlags,
  toContextNeed,
  toMemoryCard,
  toReasoningStep,
  upsertMemory,
  type ContextNeedSnapshot,
  type MemoryCard,
  type PolicyQAChatMessage,
  type RawContextNeed,
  type RawMemoryUpdate,
  type RawReasoningStep,
  type ReasoningStep,
  type SessionAnchor,
} from '@/lib/policy-qa-session'

// ── 本轮执行步骤（对话流顶部的轻量 trace）─────────────────────────

export interface PolicyQATurnStep {
  step: string
  status: 'pending' | 'running' | 'done' | 'error' | 'streaming'
  publicMessage?: string
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
  /**
   * 发起一轮对话。settlementId 缺省时复用 anchor.settlementId；
   * 两者皆空返回 false（调用方提示用户先锚定结算单号）。
   */
  send: (question: string, opts?: { settlementId?: string }) => Promise<boolean>
  /** 新建会话：新 sessionId + 清空记忆/消息/锚点 */
  resetSession: () => void
  /** 局部更新锚点（如 @换患者） */
  updateAnchor: (patch: Partial<SessionAnchor>) => void
  /** 关闭主体切换横幅 */
  dismissSubjectChange: () => void
  /** 向对话流追加一条本地消息（如 @指令 的确认提示） */
  appendLocalMessage: (msg: PolicyQAChatMessage) => void
}

const STREAM_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/stream'

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

export function usePolicyQAStream(): UsePolicyQAStreamReturn {
  const [sessionId, setSessionId] = useState<string>(() => newSessionId())
  const [anchor, setAnchor] = useState<SessionAnchor>(() => emptyAnchor())
  const [memories, setMemories] = useState<MemoryCard[]>([])
  const [messages, setMessages] = useState<PolicyQAChatMessage[]>([])
  const [lastContextNeed, setLastContextNeed] = useState<ContextNeedSnapshot | null>(null)
  const [steps, setSteps] = useState<PolicyQATurnStep[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  // ── SSE 事件分发（每个事件独立 try/catch，失败不阻塞主流程）────
  const dispatchEvent = useCallback(
    (event: string, data: unknown, turnContextNeed: { current: ContextNeedSnapshot | null }) => {
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
            const step = toReasoningStep((data ?? {}) as RawReasoningStep)
            if (step.stepId) {
              updateLastAssistant(setMessages, (msg) => ({
                ...msg,
                reasoning: [...(msg.reasoning ?? []), step],
              }))
            }
            break
          }
          case 'step': {
            const d = (data ?? {}) as Record<string, unknown>
            const stepName = typeof d.step === 'string' ? d.step : ''
            if (!stepName) break
            const status = String(d.status ?? 'running') as PolicyQATurnStep['status']
            const publicMessage = typeof d.public_message === 'string' ? d.public_message : undefined
            setSteps((prev) => {
              const idx = prev.findIndex((s) => s.step === stepName)
              if (idx >= 0) {
                const next = [...prev]
                next[idx] = { ...next[idx], status, publicMessage: publicMessage ?? next[idx].publicMessage }
                return next
              }
              return [...prev, { step: stepName, status, publicMessage }]
            })
            // 流式文本 chunk 累积到当前 assistant 消息
            if (typeof d.chunk === 'string' && d.chunk) {
              updateLastAssistant(setMessages, (msg) => ({ ...msg, content: msg.content + d.chunk }))
            }
            break
          }
          case 'result': {
            const payload = (data ?? {}) as Record<string, unknown>
            const result = (payload.result ?? payload) as Record<string, unknown>
            const patientView = typeof result.patient_view === 'string' ? result.patient_view : ''
            const officeView = typeof result.office_view === 'string' ? result.office_view : ''
            const canAnswerReason =
              typeof result.can_answer_reason === 'string' ? result.can_answer_reason : ''
            const finalSteps = Array.isArray(result.reasoning_steps)
              ? (result.reasoning_steps as RawReasoningStep[]).map(toReasoningStep)
              : []
            updateLastAssistant(setMessages, (msg) => {
              const merged: ReasoningStep[] = mergeReasoningSteps(msg.reasoning ?? [], finalSteps)
              // 无有效回答时的兜底：引导用户咨询医保办/当地医保局（不生成猜测内容）
              const unavailableReply =
                '当前无法基于已有结算数据给出准确、可靠的费用解释。\n\n' +
                '为避免误导，本系统不生成猜测性回答。建议您携带医保结算单前往医院医保办（收费窗口）咨询，' +
                '或拨打当地医保局服务热线咨询。\n\n本回答仅供参考，不作为报销或结算依据。'
              return {
                ...msg,
                content:
                  msg.content ||
                  patientView ||
                  officeView ||
                  canAnswerReason ||
                  unavailableReply,
                reasoning: merged,
                contextNeed: turnContextNeed.current ?? undefined,
                calculationSteps: Array.isArray(result.calculation_steps)
                  ? (result.calculation_steps as Array<{ step_name: string; description: string }>)
                  : undefined,
                definition: (result.definition ?? undefined) as
                  | { name: string; plain_text: string; excludes?: string[] }
                  | undefined,
                warnings: Array.isArray(result.warnings)
                  ? (result.warnings as string[])
                  : undefined,
                caseContext: (result.case_context ?? undefined) as {
                  person_type?: string | null
                  deductible?: number | null
                  basic_pooling_payment?: number | null
                  basic_pooling_self_pay?: number | null
                  large_amount_payment?: number | null
                  large_amount_self_pay?: number | null
                  personal_total_pay?: number | null
                } | undefined,
              }
            })
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
                dispatchEvent(evt.event, evt.data, turnContextNeed)
                // 出让微任务队列给 React 渲染（与 readSseStream 相同理由）
                await new Promise<void>((resolve) => setTimeout(resolve, 0))
              }
            }
          }
          // 处理尾部残留
          const tail = parseSseBlock(buffer)
          if (tail) dispatchEvent(tail.event, tail.data, turnContextNeed)
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

      setIsStreaming(false)
      return true
    },
    [dispatchEvent, isStreaming],
  )

  // ── 新会话 ───────────────────────────────────────────────────
  const resetSession = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setSessionId(newSessionId())
    setAnchor(emptyAnchor())
    setMemories([])
    setMessages([])
    setLastContextNeed(null)
    setSteps([])
    setError(null)
    setIsStreaming(false)
  }, [])

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
    send,
    resetSession,
    updateAnchor,
    dismissSubjectChange,
    appendLocalMessage,
  }
}
