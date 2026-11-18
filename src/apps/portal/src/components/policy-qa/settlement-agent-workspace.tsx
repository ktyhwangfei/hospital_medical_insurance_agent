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
import SettlementBillPane from '@/components/policy-qa/settlement-bill-pane'
import SettlementResultBlock from '@/components/policy-qa/settlement-result-block'
import SettlementTimeBrowser from '@/components/policy-qa/settlement-time-browser'
import { buildBillCompareMessage } from '@/lib/policy-qa-bill-compare'
import { toPolicyQAResult, type PolicyQAResult } from '@/lib/policy-qa-stream'
import {
  parsePolicyQACommand,
  type PolicyQAChatMessage,
} from '@/lib/policy-qa-session'
import {
  fetchSettlementBill,
  type SettlementBillDTO,
  type SettlementListItemDTO,
} from '@/lib/policy-qa-settlement-list'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 结算解释智能体工作区（设计 §4.2）。
 *
 * 主输入 = 时间选择器（不是结算单搜索框）：选时段 → 时段结算列表 →
 * 点单看费用构成富块 → 可针对此单追问（走 stream，已锚定）。
 *
 * Issue #87 第一批：点选扩展为最多两张——选中两张后右侧按时间生成两个
 * tab（默认最新一张，可切换），此时提问按两张单对比作答，不做金额加总：
 * 住院-住院复用 `GET /policy-qa/settlement-explanation?compare_with=`；
 * 含门诊/门特的两张走两张费用分解的确定性核对（门诊不在住院语义模型内）。
 * 布局：选中后两列——左列患者定位/时段列表/对话流，右列解释区（一张或
 * 两张同一位置，两张时出 tab），宽屏 sticky（用户现场确认口径）。
 */

const EXPLANATION_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation'
const BILL_COMPARE_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/settlement-bill-compare'

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

/** 两张结算单费用分解交给模型生成对比解释（模型不可用时前端降级为账面核对）。 */
async function fetchBillCompareExplanation(
  older: SettlementListItemDTO,
  newer: SettlementListItemDTO,
  question: string,
): Promise<PolicyQAResult> {
  const response = await fetch(BILL_COMPARE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      items: [
        { settlement_id: older.settlementId, service_type: older.serviceType },
        { settlement_id: newer.settlementId, service_type: newer.serviceType },
      ],
      question,
    }),
  })
  if (!response.ok) {
    throw new Error(`模型解释不可用（HTTP ${response.status}）`)
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

/** 单张结算单的费用构成/费用明细加载状态（每张 tab 独立缓存）。 */
interface BillState {
  status: 'loading' | 'ready' | 'error'
  bill?: SettlementBillDTO
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

/** 门诊单右侧同样展示费用构成/明细，只是不再生成住院口径的文字解释。 */
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
  const [bills, setBills] = useState<Record<string, BillState>>({})
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

  const ensureBill = useCallback(async (item: SettlementListItemDTO) => {
    let skip = false
    setBills((prev) => {
      const current = prev[item.settlementId]
      if (current && current.status !== 'error') {
        skip = true
        return prev
      }
      return { ...prev, [item.settlementId]: { status: 'loading' } }
    })
    if (skip) return
    try {
      const bill = await fetchSettlementBill(item.settlementId, item.serviceType)
      setBills((prev) => ({ ...prev, [item.settlementId]: { status: 'ready', bill } }))
    } catch (e) {
      setBills((prev) => ({
        ...prev,
        [item.settlementId]: {
          status: 'error',
          error: e instanceof Error ? e.message : '结算单费用数据查询失败',
        },
      }))
    }
  }, [])

  // 两张对比时按需取费用分解（优先用点选时已缓存的结果）
  const loadBillForCompare = useCallback(
    async (item: SettlementListItemDTO): Promise<SettlementBillDTO> => {
      const cached = bills[item.settlementId]
      if (cached?.status === 'ready' && cached.bill) return cached.bill
      const bill = await fetchSettlementBill(item.settlementId, item.serviceType)
      setBills((prev) => ({ ...prev, [item.settlementId]: { status: 'ready', bill } }))
      return bill
    },
    [bills],
  )

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
        // 每张单都要在右侧展示费用构成/费用明细；门诊单不请求住院文字解释
        void ensureBill(item)
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
    [selectedItems, ensureExplanation, ensureBill, stream.updateAnchor],
  )

  // 患者定位/换人（临时方案）：换人时清掉上一患者的选中结算单、解释与锚点，
  // 禁止跨患者锚定（Issue #87 患者身份口径）
  const handlePatientChange = useCallback(() => {
    setSelectedItems([])
    setExplanations({})
    setBills({})
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
      void ensureBill(item)
      void ensureExplanation(settlementId)
    },
    [ensureBill, ensureExplanation, stream.updateAnchor],
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
      const hasOutpatient = selectedItems.some(isOutpatient)
      setComparing(true)
      try {
        if (hasOutpatient) {
          // 门诊/门特不在住院语义模型内：两张费用分解交给模型生成解释，
          // 模型不可用时降级为确定性账面核对，仍按两张单作答
          const [olderBill, newerBill] = await Promise.all([
            loadBillForCompare(older),
            loadBillForCompare(newer),
          ])
          try {
            const result = await fetchBillCompareExplanation(older, newer, command.question)
            stream.appendLocalMessage(toCompareMessage(result))
          } catch {
            const fallback = buildBillCompareMessage({ older, newer, olderBill, newerBill })
            stream.appendLocalMessage({
              ...fallback,
              uncertainties: [
                ...(fallback.uncertainties ?? []),
                '模型解释暂时不可用，以上为账面核对。',
              ],
            })
          }
        } else {
          const result = await fetchSettlementExplanation(older.settlementId, {
            compareWith: newer.settlementId,
            question: command.question,
          })
          stream.appendLocalMessage(toCompareMessage(result))
        }
      } catch (e) {
        stream.appendLocalMessage({
          role: 'assistant',
          content: `两张结算单对比失败：${e instanceof Error ? e.message : '服务暂时不可用'}。请稍后重试，或先取消一张只看单笔解释。`,
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
  const activeBill = activeTabId ? bills[activeTabId] : undefined
  const activeItem = activeTabId
    ? selectedItems.find((item) => item.settlementId === activeTabId) ?? {
        settlementId: activeTabId,
        settlementDate: '',
        personType: '',
        insuranceType: '',
        serviceType: '',
        totalAmount: null,
        coverageStatus: 'complete' as const,
      }
    : null

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
              {`已选两张结算单，提问将按两张对比作答（以较早一张 ${comparingBaseline.settlementDate || comparingBaseline.settlementId} 为基准，金额逐单呈现不加总，不作合规判断）；只想问其中一张，先取消另一张的选择。`}
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
            {activeItem ? (
              <SettlementExplanationPane
                item={activeItem}
                billState={activeBill}
                explanationState={activeExplanation}
              />
            ) : null}
          </aside>
        ) : null}
      </div>
    </section>
  )
}

/**
 * 单张结算单右侧栏：费用构成 + 费用明细（门诊/门特/住院一致），
 * 住院另附可展开的文字解释与政策来源（文字在上方表格之后，不抢主视觉）。
 */
function SettlementExplanationPane({
  item,
  billState,
  explanationState,
}: {
  item: SettlementListItemDTO
  billState?: BillState
  explanationState?: ExplanationState
}) {
  const settlementId = item.settlementId

  if (!billState || billState.status === 'loading') {
    return (
      <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
        <LoaderCircle className="size-4 animate-spin" aria-hidden />
        正在加载结算单 {settlementId} 的费用构成与费用明细…
      </div>
    )
  }
  if (billState.status === 'error' || !billState.bill) {
    return (
      <div
        role="alert"
        className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        {billState.error ?? '结算单费用数据暂不可用。'}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <SettlementBillPane bill={billState.bill} />
      {isOutpatient(item) ? null : explanationState?.status === 'ready' &&
        explanationState.result ? (
        <details
          data-testid="settlement-answer-details"
          className="rounded-2xl border border-slate-200 bg-white shadow-sm"
        >
          <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-700">
            查看文字解释与政策来源
          </summary>
          <div className="px-3 pb-3">
            <SettlementResultBlock
              settlementId={settlementId}
              result={explanationState.result}
            />
          </div>
        </details>
      ) : explanationState?.status === 'error' ? (
        <p className="px-1 text-xs text-amber-700">{explanationState.error}</p>
      ) : (
        <p role="status" className="flex items-center gap-2 px-1 text-xs text-slate-500">
          <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
          正在生成结算单 {settlementId} 的文字解释…
        </p>
      )}
    </div>
  )
}
