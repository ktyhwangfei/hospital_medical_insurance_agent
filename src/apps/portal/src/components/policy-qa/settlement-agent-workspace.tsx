'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  LoaderCircle,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  ShieldQuestion,
} from 'lucide-react'

import PolicyComposer from '@/components/policy-qa/policy-composer'
import PolicyMessageList from '@/components/policy-qa/policy-message-list'
import SettlementResultBlock from '@/components/policy-qa/settlement-result-block'
import SettlementTimeBrowser from '@/components/policy-qa/settlement-time-browser'
import { toPolicyQAResult, type PolicyQAResult } from '@/lib/policy-qa-stream'
import {
  parsePolicyQACommand,
  type PolicyQAChatMessage,
} from '@/lib/policy-qa-session'
import type { SettlementListItemDTO } from '@/lib/policy-qa-settlement-list'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 结算解释智能体工作区（设计 §4.2）。
 *
 * 主输入 = 时间选择器（不是结算单搜索框）：选时段 → 时段结算列表 →
 * 点单看费用构成富块 → 可针对此单追问（走 stream，已锚定）。
 *
 * Issue #87 第一批：点选扩展为最多两张——选中两张后右侧按时间生成两个
 * tab（默认最新一张，可切换），此时提问按两张单对比作答（复用既有
 * `GET /policy-qa/settlement-explanation?compare_with=` 能力，不做金额加总）。
 * 布局：选中后两列——左列患者定位/时段列表/对话流，右列解释区（一张或
 * 两张同一位置，两张时出 tab），宽屏 sticky（用户现场确认口径）。
 */

const EXPLANATION_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation'

/** 单笔解释 / 两单对比共用同一既有端点；compareWith 提供时进入对比模式。 */
async function fetchSettlementExplanation(
  settlementId: string,
  opts?: { compareWith?: string; question?: string },
): Promise<PolicyQAResult> {
  const params = new URLSearchParams({ settlement_id: settlementId })
  if (opts?.compareWith) params.set('compare_with', opts.compareWith)
  if (opts?.question) params.set('question', opts.question)
  const response = await fetch(`${EXPLANATION_URL}?${params.toString()}`)
  if (!response.ok) {
    // 门诊单号不属于住院费用构成语义模型（后端映射为 404），给出可执行口径而非 HTTP 码
    if (response.status === 404) {
      throw new Error('该结算单暂不支持费用构成解释（当前仅覆盖住院结算单），可在对话中直接提问。')
    }
    throw new Error(`结算解释查询失败（HTTP ${response.status}）`)
  }
  const payload = (await response.json()) as { result?: unknown } & Record<string, unknown>
  // 端点直接返回 PolicyQAPublicResult（非 { result: ... } 包装）
  const raw = payload.result ?? payload
  return toPolicyQAResult(raw)
}

/** 单张结算单的解释加载状态（逐单缓存，避免切 tab 反复拉取）。 */
interface ExplanationState {
  status: 'loading' | 'ready' | 'error'
  result?: PolicyQAResult
  error?: string
}

/** 按结算日期升序（未知日期排最后）；tab 顺序与「较早一张为对比基准」共用此排序。 */
function sortBySettlementDate(items: SettlementListItemDTO[]): SettlementListItemDTO[] {
  return [...items].sort((a, b) => {
    const keyA = a.settlementDate || '\uffff' // 未知日期排最后
    const keyB = b.settlementDate || '\uffff'
    if (keyA === keyB) return 0
    return keyA < keyB ? -1 : 1
  })
}

/** 门诊单：右侧解释区（住院费用构成语义模型）暂不覆盖，门诊问答走对话流。 */
function isOutpatient(item: SettlementListItemDTO): boolean {
  return item.serviceType.includes('门诊')
}

/** 由对比结果组装一条对话消息（本地追加；对比走 REST 端点，不占 SSE 轮次）。 */
function toCompareMessage(result: PolicyQAResult): PolicyQAChatMessage {
  return {
    role: 'assistant',
    content: result.answer,
    answerStatus: result.answerStatus,
    calculationSteps: result.calculationSteps,
    definition: result.definition,
    warnings: result.warnings,
    caseContext: result.caseContext,
    citations: result.citations,
    uncertainties: result.uncertainties,
    verificationSummary: result.verificationSummary,
  }
}

export default function SettlementAgentWorkspace({
  onStreamingChange,
}: {
  onStreamingChange?: (streaming: boolean) => void
}) {
  const stream = usePolicyQAStream({ mode: 'settlement_explain', storageScope: 'settlement' })
  const [selectedItems, setSelectedItems] = useState<SettlementListItemDTO[]>([])
  const [explanations, setExplanations] = useState<Record<string, ExplanationState>>({})
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [comparing, setComparing] = useState(false)
  const [input, setInput] = useState('')

  const busy = stream.isStreaming || comparing
  useEffect(() => {
    onStreamingChange?.(busy)
  }, [busy, onStreamingChange])

  const ensureExplanation = useCallback(async (settlementId: string) => {
    let skip = false
    setExplanations((prev) => {
      const current = prev[settlementId]
      if (current && current.status !== 'error') {
        skip = true
        return prev
      }
      return { ...prev, [settlementId]: { status: 'loading' } }
    })
    if (skip) return
    try {
      const result = await fetchSettlementExplanation(settlementId)
      setExplanations((prev) => ({ ...prev, [settlementId]: { status: 'ready', result } }))
    } catch (e) {
      setExplanations((prev) => ({
        ...prev,
        [settlementId]: {
          status: 'error',
          error: e instanceof Error ? e.message : '结算解释查询失败',
        },
      }))
    }
  }, [])

  // 点选/取消点选（Issue #87：最多两张，上限拦截在列表组件内）
  const handleToggle = useCallback(
    (item: SettlementListItemDTO) => {
      const exists = selectedItems.some((p) => p.settlementId === item.settlementId)
      let next: SettlementListItemDTO[]
      if (exists) {
        next = selectedItems.filter((p) => p.settlementId !== item.settlementId)
      } else {
        if (selectedItems.length >= 2) return
        next = [...selectedItems, item]
        // 门诊单不请求住院费用构成解释（右侧改为诚实说明，门诊问答走对话流）
        if (!isOutpatient(item)) void ensureExplanation(item.settlementId)
      }
      setSelectedItems(next)
      // 任何选择变化后默认聚焦最新一张（按结算日期；未知日期视为最新兜底）
      const sorted = sortBySettlementDate(next)
      const nextActive = sorted.length > 0 ? sorted[sorted.length - 1].settlementId : null
      setActiveTabId(nextActive)
      stream.updateAnchor({
        settlementId: nextActive,
        subjectChanged: false,
        subjectChangeMsg: null,
      })
    },
    [selectedItems, ensureExplanation, stream.updateAnchor],
  )

  // 患者定位/换人（临时方案）：换人时清掉上一患者的选中结算单、解释与锚点，
  // 禁止跨患者锚定（Issue #87 患者身份口径）
  const handlePatientChange = useCallback(() => {
    setSelectedItems([])
    setExplanations({})
    setActiveTabId(null)
    stream.updateAnchor({ settlementId: null, subjectChanged: false, subjectChangeMsg: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.updateAnchor])

  // @换结算 指令：单选该单并解释（不依赖时段列表是否覆盖该单）
  const handleCommandSelect = useCallback(
    (settlementId: string) => {
      const item: SettlementListItemDTO = {
        settlementId,
        settlementDate: '',
        personType: '',
        insuranceType: '',
        serviceType: '',
        totalAmount: null,
        coverageStatus: 'complete',
      }
      setSelectedItems([item])
      setActiveTabId(settlementId)
      stream.updateAnchor({ settlementId, subjectChanged: false, subjectChangeMsg: null })
      void ensureExplanation(settlementId)
    },
    [ensureExplanation, stream.updateAnchor],
  )

  const sendQuestion = async (question: string) => {
    if (!question.trim() || busy) return
    if (stream.sessionStatus !== 'active' && stream.sessionStatus !== 'unknown') return
    const command = parsePolicyQACommand(question)
    if (command.kind === 'new_session') {
      stream.resetSession()
      return
    }
    if (command.kind === 'switch_settlement') {
      handleCommandSelect(command.settlementId)
      return
    }
    // 选中两张：问题按两张单对比作答（基准 = 较早一张；金额逐单呈现，不加总）
    if (command.kind === 'question' && selectedItems.length === 2) {
      const [older, newer] = sortBySettlementDate(selectedItems)
      stream.appendLocalMessage({ role: 'user', content: command.question })
      if (selectedItems.some(isOutpatient)) {
        // 既有对比链路只覆盖住院费用构成；门诊单不得塞进住院对比逻辑
        stream.appendLocalMessage({
          role: 'assistant',
          content:
            '两张单中含门诊结算单，当前对比仅支持两张住院结算单。请先取消门诊单再对比；门诊费用问题可只选该门诊单后在对话中直接提问。',
          answerStatus: 'unavailable',
          uncertainties: ['门诊与住院结算单的对比未生成，未核对任何金额。'],
        })
        return
      }
      setComparing(true)
      try {
        const result = await fetchSettlementExplanation(older.settlementId, {
          compareWith: newer.settlementId,
          question: command.question,
        })
        stream.appendLocalMessage(toCompareMessage(result))
      } catch (e) {
        stream.appendLocalMessage({
          role: 'assistant',
          content: `两张结算单对比查询失败：${e instanceof Error ? e.message : '服务暂时不可用'}。请稍后重试，或先取消一张只看单笔解释。`,
          answerStatus: 'unavailable',
          uncertainties: ['对比结果未生成，未核对任何金额。'],
        })
      } finally {
        setComparing(false)
      }
      return
    }
    const settlementId =
      command.kind === 'question' ? activeTabId ?? stream.anchor.settlementId : null
    if (command.kind === 'question' && settlementId) {
      await stream.send(command.question, { settlementId })
      return
    }
    await stream.send(question)
  }

  const handleSend = () => {
    const question = input.trim()
    if (!question) return
    setInput('')
    void sendQuestion(question)
  }

  const canOperate =
    stream.sessionStatus === 'active' && stream.messages.length > 0 && !busy
  const lastUserQuestion =
    [...stream.messages].reverse().find((m) => m.role === 'user')?.content ?? ''
  const currentPublicMessage = stream.steps.at(-1)?.publicMessage
  const composerSettlementId = activeTabId ?? stream.anchor.settlementId

  const sortedSelected = sortBySettlementDate(selectedItems)
  const comparingBaseline = sortedSelected.length === 2 ? sortedSelected[0] : null
  const activeExplanation = activeTabId ? explanations[activeTabId] : undefined

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-slate-950">结算解释</h1>
            <p className="text-sm text-slate-500">
              按时间段浏览结算单，点开单据查看费用构成解释；选两张可对比提问。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5" data-testid="policy-qa-session-actions">
            <button
              type="button"
              onClick={stream.resetSession}
              disabled={busy || stream.restoring}
              aria-label="新会话"
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              新会话
            </button>
            {canOperate ? (
              <>
                <button
                  type="button"
                  onClick={() => void stream.suspendSession()}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  <PauseCircle className="size-3.5" aria-hidden />
                  挂起
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const question = input.trim() || lastUserQuestion
                    if (question) void stream.escalateSession(question)
                  }}
                  disabled={!input.trim() && !lastUserQuestion}
                  className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                >
                  <ShieldQuestion className="size-3.5" aria-hidden />
                  升级医保办
                </button>
              </>
            ) : null}
          </div>
        </div>
      </header>

      {stream.sessionStatus === 'suspended' ? (
        <div
          role="status"
          data-testid="policy-qa-suspended-banner"
          className="flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"
        >
          <span>
            会话已挂起{stream.statusReason ? `：${stream.statusReason}` : ''}，可稍后恢复继续。
          </span>
          <button
            type="button"
            onClick={() => void stream.resumeSession()}
            className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700"
          >
            <PlayCircle className="size-3.5" aria-hidden />
            恢复对话
          </button>
        </div>
      ) : null}

      {stream.sessionStatus === 'escalated' ? (
        <div
          role="status"
          data-testid="policy-qa-escalated-banner"
          className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          <p>已升级至医保办人工处理，本会话暂停提问。医保办回复后重新进入本页即可看到答复。</p>
        </div>
      ) : null}

      {stream.escalation?.reply ? (
        <div
          data-testid="policy-qa-escalation-reply"
          className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
        >
          <p className="mb-1 font-medium">医保办回复</p>
          <p className="whitespace-pre-wrap">{stream.escalation.reply}</p>
        </div>
      ) : null}

      {stream.restoring ? (
        <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          正在恢复上次会话…
        </div>
      ) : null}

      {/*
        选中结算单后分两列：左列 = 患者定位/时段列表/对话流/输入框，
        右列（aside）= 解释区——一张为单笔解释，两张为按时间的两个 tab
        （默认最新）。解释区一张/两张都在同一右侧位置（Issue #87 用户确认口径）。
      */}
      <div
        className={
          selectedItems.length > 0
            ? 'grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,440px)]'
            : 'space-y-6'
        }
      >
        <div className="min-w-0 space-y-6">
          {/* 主输入：患者定位 + 时间选择器 + 时段列表（临时患者定位，正式由登录态取代） */}
          <SettlementTimeBrowser
            selectedIds={selectedItems.map((item) => item.settlementId)}
            onToggle={handleToggle}
            onPatientChange={handlePatientChange}
          />

          {/* 针对选中单的追问对话流（含两单对比问答）；结算会话口径：不重复展示核验摘要/计算依据 */}
          {stream.messages.length > 0 ? (
            <PolicyMessageList messages={stream.messages} settlementConversation />
          ) : null}

          {busy && currentPublicMessage ? (
            <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
              <LoaderCircle className="size-4 animate-spin" aria-hidden />
              <span>{currentPublicMessage}</span>
            </div>
          ) : null}
          {comparing ? (
            <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
              <LoaderCircle className="size-4 animate-spin" aria-hidden />
              正在对比两张结算单…
            </div>
          ) : null}

          {selectedItems.length === 2 && comparingBaseline ? (
            <p
              data-testid="settlement-compare-hint"
              className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-xs leading-5 text-slate-500"
            >
              {selectedItems.some(isOutpatient)
                ? '已选两张，其中含门诊结算单。对比暂仅支持两张住院结算单；门诊费用请只选该门诊单后在对话中直接提问。'
                : `已选两张结算单，提问将按两张对比作答（以较早一张 ${comparingBaseline.settlementDate || comparingBaseline.settlementId} 为基准，金额逐单呈现不加总）；只想问其中一张，先取消另一张的选择。`}
            </p>
          ) : null}

          <PolicyComposer
            mode="settlement_explain"
            settlementId={composerSettlementId}
            value={input}
            onChange={setInput}
            onSend={handleSend}
            isStreaming={busy}
            disabled={
              stream.sessionStatus === 'suspended' ||
              stream.sessionStatus === 'escalated' ||
              stream.sessionStatus === 'closed'
            }
          />

          <p className="text-center text-xs leading-5 text-slate-400">
            回答仅供解释参考，不作为报销或结算依据。
          </p>
        </div>

        {/* 右侧解释区：一张 = 单笔费用构成；两张 = 按时间两个 tab（默认最新） */}
        {selectedItems.length > 0 ? (
          <aside
            data-testid="settlement-explanation-aside"
            aria-label="结算单解释"
            className="min-w-0 space-y-3 xl:sticky xl:top-4"
          >
            {selectedItems.length === 2 ? (
              <div
                role="tablist"
                aria-label="结算单切换"
                data-testid="settlement-compare-tabs"
                className="flex w-fit items-center gap-1 rounded-full bg-slate-100 p-1"
              >
                {sortedSelected.map((item) => {
                  const active = item.settlementId === activeTabId
                  return (
                    <button
                      key={item.settlementId}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      data-testid={`settlement-tab-${item.settlementId}`}
                      onClick={() => setActiveTabId(item.settlementId)}
                      className={[
                        'rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
                        active
                          ? 'bg-white text-slate-900 shadow-sm'
                          : 'text-slate-500 hover:text-slate-900',
                      ].join(' ')}
                    >
                      {item.settlementDate || '日期待定'} · {item.settlementId}
                    </button>
                  )
                })}
              </div>
            ) : null}
            {activeTabId ? (
              <SettlementExplanationPane
                settlementId={activeTabId}
                serviceType={
                  selectedItems.find((item) => item.settlementId === activeTabId)
                    ?.serviceType ?? ''
                }
                state={activeExplanation}
              />
            ) : null}
          </aside>
        ) : null}
      </div>
    </section>
  )
}

/** 单张结算单的解释展示：门诊说明 / 加载中 / 失败 / 富块三态。 */
function SettlementExplanationPane({
  settlementId,
  serviceType,
  state,
}: {
  settlementId: string
  serviceType: string
  state?: ExplanationState
}) {
  if (serviceType.includes('门诊')) {
    return (
      <div
        role="note"
        data-testid="settlement-outpatient-note"
        className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600"
      >
        结算单 {settlementId} 是门诊单据，右侧费用构成解释暂只覆盖住院结算单。请在左下输入框直接提问门诊费用问题（如「这笔门诊为什么自付这么多」），系统会按门诊结算链路作答。
      </div>
    )
  }
  if (!state || state.status === 'loading') {
    return (
      <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
        正在生成结算单 {settlementId} 的费用构成解释…
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div
        role="alert"
        className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        {state.error}
      </div>
    )
  }
  return state.result ? (
    <SettlementResultBlock settlementId={settlementId} result={state.result} />
  ) : null
}
