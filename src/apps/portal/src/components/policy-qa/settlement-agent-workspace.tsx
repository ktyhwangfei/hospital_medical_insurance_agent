'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  LoaderCircle,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  ShieldQuestion,
} from 'lucide-react'

import PolicyComposer from '@/components/policy-qa/policy-composer'
import PolicyMessageList from '@/components/policy-qa/policy-message-list'
import FeeItemBreakdownList from '@/components/policy-qa/fee-item-breakdown-list'
import SettlementBillView from '@/components/policy-qa/settlement-bill-view'
import SettlementResultBlock from '@/components/policy-qa/settlement-result-block'
import SettlementTimeBrowser from '@/components/policy-qa/settlement-time-browser'
import { fetchSessionDecomposition, feeReadAuthHeaders } from '@/lib/fee-decomposition-api'
import {
  toFeeDecomposition,
  toPolicyQAResult,
  type PolicyQAFeeDecomposition,
  type PolicyQAResult,
} from '@/lib/policy-qa-stream'
import type {
  PatientSummaryDTO,
  SettlementDecompositionChain,
  SettlementListItemDTO,
} from '@/lib/policy-qa-settlement-list'
import { parsePolicyQACommand } from '@/lib/policy-qa-session'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 结算解释智能体工作区（设计 §4.2）。
 *
 * 主输入 = 时间选择器（不是结算单搜索框）：选时段 → 时段结算列表 →
 * 选中结算单后仅加载并展示费用分解；需要解释时由用户在中央对话主动提问。
 */

const EXPLANATION_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation'

async function fetchSettlementExplanation(settlementId: string): Promise<PolicyQAResult> {
  const params = new URLSearchParams({ settlement_id: settlementId })
  // 旧 GET 与费用分解同权：读取同样携带 fee_decomposition:read 令牌（后端已强制）
  const response = await fetch(`${EXPLANATION_URL}?${params.toString()}`, {
    headers: feeReadAuthHeaders(),
  })
  if (!response.ok) {
    throw new Error(`结算解释查询失败（HTTP ${response.status}）`)
  }
  const payload = (await response.json()) as { result?: unknown } & Record<string, unknown>
  // 端点直接返回 PolicyQAPublicResult（非 { result: ... } 包装）
  const raw = payload.result ?? payload
  return toPolicyQAResult(raw)
}

export default function SettlementAgentWorkspace({
  onStreamingChange,
}: {
  onStreamingChange?: (streaming: boolean) => void
}) {
  const stream = usePolicyQAStream({ mode: 'settlement_explain', storageScope: 'settlement' })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 已定位患者（脱敏摘要）：渲染结算单式样的病人基本信息块
  const [patient, setPatient] = useState<PatientSummaryDTO | null>(null)
  // 当前选中的时段列表项：侧栏显示所选交易的日期和医疗类别
  const [selectedItem, setSelectedItem] = useState<SettlementListItemDTO | null>(null)
  const [explanation, setExplanation] = useState<PolicyQAResult | null>(null)
  // 门诊/门特单（decompositionChain 非 null）的费用分解结果，与住院 explanation 互斥
  const [decomposition, setDecomposition] = useState<PolicyQAFeeDecomposition | null>(null)
  const [explanationLoading, setExplanationLoading] = useState(false)
  const [explanationError, setExplanationError] = useState<string | null>(null)
  // 当前患者的时段候选单：@换结算 命令只能命中这些条目（不猜链路、不跨患者锚定）
  const [candidates, setCandidates] = useState<SettlementListItemDTO[]>([])
  const [input, setInput] = useState('')
  // 选择器和列表在问答区上方；结果就绪后滚到中央对话，右侧面板继续粘住视口
  const resultRef = useRef<HTMLDivElement | null>(null)
  const explanationRequest = useRef(0)
  const composerSettlementId = selectedId ?? stream.anchor.settlementId
  const restoredDecomposition = [...stream.messages].reverse().find((message) =>
    message.feeDecomposition?.settlementFacts?.identifier === composerSettlementId,
  )?.feeDecomposition
  const decompositionChain = selectedItem?.decompositionChain ?? decomposition?.settlementFacts?.chain ?? restoredDecomposition?.settlementFacts?.chain
  // 面板与聊天同源（同一 (session, settlement) 分解实例）：轨迹里同单最新载荷优先，
  // 选单时拉取的端点结果兜底，不再存在选单时刻冻结导致的口径切换
  const displayedDecomposition = restoredDecomposition ?? decomposition

  useEffect(() => {
    onStreamingChange?.(stream.isStreaming)
  }, [stream.isStreaming, onStreamingChange])

  // 结果就绪后滚入视野（长列表场景：账单在列表下方，不滚动用户看不到）
  const resultReady = !!displayedDecomposition || !!explanation || !!explanationError
  useEffect(() => {
    if (!resultReady) return
    const el = resultRef.current
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [resultReady, composerSettlementId])

  // 患者定位/换人（临时方案）：换人时清掉上一患者的选中结算单与解释，
  // 避免跨患者串台；定位本身由 SettlementTimeBrowser 内聚管理
  const handlePatientChange = useCallback((next: PatientSummaryDTO | null) => {
    explanationRequest.current += 1
    setExplanationLoading(false)
    setPatient(next)
    setSelectedId(null)
    setSelectedItem(null)
    setExplanation(null)
    setDecomposition(null)
    setExplanationError(null)
    setCandidates([])
    stream.resetSession()
  }, [stream])

  // 新会话只重置对话：保留当前患者、时段列表与候选（列表项仍可见即可继续命令选单），
  // 清选单/解释/锚点并作废旧解释响应（R6）。换人仍走 handlePatientChange。
  const handleNewSession = useCallback(() => {
    explanationRequest.current += 1
    setExplanationLoading(false)
    setSelectedId(null)
    setSelectedItem(null)
    setExplanation(null)
    setDecomposition(null)
    setExplanationError(null)
    stream.resetSession()
  }, [stream])

  // 点选结算单 → 锚定会话 + 拉取费用构成解释；
  // 门诊/门特单走会话共享分解端点（fetchSessionDecomposition，与聊天同一实例），
  // 住院单走 settlement-explanation
  const handleSelect = useCallback(
    (
      settlementId: string,
      decompositionChain: SettlementDecompositionChain = null,
      item?: SettlementListItemDTO,
    ) => {
      const requestId = ++explanationRequest.current
      setSelectedId(settlementId)
      setSelectedItem((prev) => item ?? (prev?.settlementId === settlementId ? prev : null))
      setExplanation(null)
      setDecomposition(null)
      setExplanationError(null)
      // 一次对话绑定一张结算单，切单时保留服务端历史、清空当前解释。
      // resetSession 返回新会话 ID：共享分解实例按 (session, settlement) 键控，
      // 必须用与后续流式问答相同的会话 ID 取数。
      const sessionId = stream.resetSession()
      // 锚定当前单（追问走 stream.send 复用该锚点）
      stream.updateAnchor({ settlementId, subjectChanged: false, subjectChangeMsg: null })
      setExplanationLoading(true)
      void (async () => {
        try {
          if (decompositionChain === 'outpatient' || decompositionChain === 'special') {
            const response = await fetchSessionDecomposition(sessionId, settlementId, decompositionChain)
            if (requestId !== explanationRequest.current) return
            const result = toFeeDecomposition(response)
            if (!result) {
              setExplanationError('费用分解结果未通过公开契约校验，请稍后重试或联系医保办。')
              return
            }
            setDecomposition(result)
            setExplanationLoading(false)
          } else {
            const result = await fetchSettlementExplanation(settlementId)
            if (requestId !== explanationRequest.current) return
            setExplanation(result)
          }
        } catch (e) {
          if (requestId !== explanationRequest.current) return
          setExplanationError(e instanceof Error ? e.message : '结算解释查询失败')
        } finally {
          if (requestId === explanationRequest.current) setExplanationLoading(false)
        }
      })()
    },
    [stream],
  )

  const sendQuestion = async (question: string) => {
    if (!question.trim() || stream.isStreaming) return
    if (stream.sessionStatus !== 'active' && stream.sessionStatus !== 'unknown') return
    const command = parsePolicyQACommand(question)
    if (command.kind === 'new_session') {
      handleNewSession()
      return
    }
    if (command.kind === 'switch_settlement') {
      // 复用列表点击入口：链路/日期/类型全部取自当前候选条目；候选外单号提示调整时段，
      // 不凭长短号猜医疗类别，也不跨患者直接锚定（评审问题 6）。
      const matched = candidates.find((item) => item.settlementId === command.settlementId)
      if (!matched) {
        setExplanationError(
          `结算单 ${command.settlementId} 不在当前患者的候选结算单中，请调整时段后从列表选单。`,
        )
        return
      }
      handleSelect(matched.settlementId, matched.decompositionChain ?? null, matched)
      return
    }
    const settlementId =
      command.kind === 'question' ? selectedId ?? stream.anchor.settlementId : null
    if (command.kind === 'question' && settlementId) {
      await stream.send(command.question, { settlementId, ...(decompositionChain ? { decompositionChain } : {}) })
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

  // 点字段提问：门诊/门特措辞分开——「门特」是门特分解链路的显式路由信号（policy_qa_routes）
  const askField = (label: string) => {
    const question = decompositionChain === 'special'
      ? `这笔门特结算的「${label}」是怎么算的？`
      : `这笔门诊费用的「${label}」是怎么算的？`
    void sendQuestion(question)
  }
  const canOperate =
    stream.sessionStatus === 'active' && stream.messages.length > 0 && !stream.isStreaming
  const lastUserQuestion =
    [...stream.messages].reverse().find((m) => m.role === 'user')?.content ?? ''
  const currentPublicMessage = stream.steps.at(-1)?.publicMessage

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-slate-950">结算解释</h1>
            <p className="text-sm text-slate-500">
              选中结算单后查看右侧费用明细；需要解释时，在中间对话框提问。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5" data-testid="policy-qa-session-actions">
            <button
              type="button"
              onClick={handleNewSession}
              disabled={stream.isStreaming || stream.restoring}
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

      {/* 主输入：患者定位 + 时间选择器 + 时段列表（临时患者定位，正式由登录态取代） */}
      <fieldset disabled={stream.isStreaming || stream.restoring || ['suspended', 'escalated', 'closed'].includes(stream.sessionStatus)} className="min-w-0" aria-label="选择结算单"><SettlementTimeBrowser
        selectedId={selectedId}
        onSelect={(item) => handleSelect(item.settlementId, item.decompositionChain ?? null, item)}
        onPatientChange={handlePatientChange}
        onCandidatesChange={setCandidates}
      /></fieldset>

      <div
        ref={resultRef}
        className={[
          'scroll-mt-4',
          decompositionChain
            ? 'grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,440px)]'
            : '',
        ].join(' ')}
      >
        <div data-testid="settlement-chat-column" className="min-w-0 space-y-5">
          {!decompositionChain && explanationLoading ? (
            <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
              <LoaderCircle className="size-4 animate-spin" aria-hidden />
              正在生成结算单 {selectedId} 的费用构成解释…
            </div>
          ) : null}
          {!decompositionChain && !explanationLoading && explanationError ? (
            <div
              role="alert"
              className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
            >
              {explanationError}
            </div>
          ) : null}
          {!decompositionChain && !explanationLoading && !explanationError && explanation && selectedId ? (
            <SettlementResultBlock settlementId={selectedId} result={explanation} />
          ) : null}

          {stream.messages.length > 0 ? (
            <PolicyMessageList
              messages={stream.messages}
              patient={patient}
              onAskField={askField}
              showSettlementBill={!displayedDecomposition}
              settlementConversation
            />
          ) : null}

          {stream.isStreaming && currentPublicMessage ? (
            <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
              <LoaderCircle className="size-4 animate-spin" aria-hidden />
              <span>{currentPublicMessage}</span>
            </div>
          ) : null}

          <PolicyComposer
            mode="settlement_explain"
            settlementId={composerSettlementId}
            value={input}
            onChange={setInput}
            onSend={handleSend}
            isStreaming={stream.isStreaming}
            disabled={
              explanationLoading || stream.restoring ||
              stream.sessionStatus === 'suspended' ||
              stream.sessionStatus === 'escalated' ||
              stream.sessionStatus === 'closed'
            }
          />

          <p className="text-center text-xs leading-5 text-slate-400">
            回答仅供解释参考，不作为报销或结算依据。
          </p>
        </div>

        {decompositionChain ? (
          <aside
            aria-label="当前结算单费用信息"
            data-testid="settlement-details-sidebar"
            className="min-w-0 xl:sticky xl:top-4 xl:max-h-[calc(100vh-6rem)] xl:overflow-y-auto"
          >
            <header className="mb-4 border-b border-slate-200 pb-3">
              <h2 className="text-sm font-semibold text-slate-900">交易信息与费用明细</h2>
            </header>
            {explanationLoading ? (
              <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
                <LoaderCircle className="size-4 animate-spin" aria-hidden />
                正在加载本单费用分解…
              </div>
            ) : null}
            {!explanationLoading && explanationError ? (
              <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {explanationError}
              </div>
            ) : null}
            {!explanationLoading && !explanationError && displayedDecomposition ? (
              <div className="space-y-5">
                <SettlementBillView
                  feeDecomposition={displayedDecomposition}
                  patient={patient}
                  showFieldExplanations={false}
                  settlementId={composerSettlementId ?? undefined}
                  settlementDate={selectedItem?.settlementDate ?? displayedDecomposition.settlementFacts?.tradeDate ?? undefined}
                  serviceType={selectedItem?.serviceType}
                />
                <section aria-label="费用明细" className="min-w-0 space-y-2">
                  <h3 className="text-sm font-semibold text-slate-900">费用明细</h3>
                  <FeeItemBreakdownList items={displayedDecomposition.feeItems ?? []} />
                </section>
              </div>
            ) : null}
          </aside>
        ) : null}
      </div>
    </section>
  )
}
