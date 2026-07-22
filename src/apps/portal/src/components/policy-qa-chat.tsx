'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Loader2, Search, ChevronDown, ChevronRight, Info } from 'lucide-react'
import ThinkingChain from '@/components/thinking-chain'
import type { ThinkingStep } from '@/components/thinking-chain'
import ExecutionTracePanel from '@/components/execution-trace-panel'
import type { TraceEventItem } from '@/components/execution-trace-panel'
import ResultStatusBar from '@/components/result-status-bar'
import PolicyAnswerCard from '@/components/policy-answer-card'
import SettlementExplanationPage from '@/components/settlement-explanation-page'
import type { SettlementExplanationData } from '@/lib/settlement-explanation-types'
import type {
  TreatmentItem,
  FeeBreakdownItem,
  EvidenceItem,
} from '@/components/policy-answer-card'

interface PolicyQAStep {
  step: string
  status: 'pending' | 'running' | 'done' | 'error' | 'streaming'
  detail?: Record<string, unknown>
  /** 用户可展示的结构化数据 */
  publicDetail?: Record<string, unknown>
  /** ★ 用户可展示的纯文本摘要（优先渲染） */
  publicMessage?: string
  chunk?: string
  error?: string
  startTime?: number
  endTime?: number
}

/** RAG 政策卡片 */
interface PolicyCardItem {
  title: string
  clause: string
  evidenceText: string
  matchedReason: string
  ruleType?: string
  score?: number
}

// ── 数据防泄漏：过滤 SSE 数据中禁止展示的字段 ──────────────────
const FORBIDDEN_KEY_PATTERNS = [
  'reasoning', 'reasoning_content', 'chain_of_thought', 'thought',
  'scratchpad', 'debug', 'internal', 'prompt', 'messages',
  'raw_response', 'tool_calls', 'agent_trace',
]

function stripForbiddenFields(obj: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(obj)) {
    const keyLower = key.toLowerCase()
    const isForbidden = FORBIDDEN_KEY_PATTERNS.some(p => keyLower.includes(p))
    if (isForbidden) continue
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      result[key] = stripForbiddenFields(value as Record<string, unknown>)
    } else if (Array.isArray(value)) {
      result[key] = (value as unknown[]).map(item =>
        item !== null && typeof item === 'object' && !Array.isArray(item)
          ? stripForbiddenFields(item as Record<string, unknown>)
          : item
      )
    } else {
      result[key] = value
    }
  }
  return result
}

const EXAMPLE_QUESTIONS = [
  '统筹自付为什么是 4962.67 元？',
  '这次住院的报销比例是多少？',
  '起付线是怎么计算的？',
  '某项费用为什么不报销/不在医保内？',
] as const

export default function PolicyQAChat() {
  const [settlementId, setSettlementId] = useState('1671213')
  const [question, setQuestion] = useState('')
  const [activeQuestion, setActiveQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [steps, setSteps] = useState<PolicyQAStep[]>([])
  const [treatments, setTreatments] = useState<TreatmentItem[]>([])
  const [feeBreakdown, setFeeBreakdown] = useState<FeeBreakdownItem[]>([])
  const [evidence, setEvidence] = useState<EvidenceItem[]>([])
  const [policyCards, setPolicyCards] = useState<PolicyCardItem[]>([])
  const [settlementEvidence, setSettlementEvidence] = useState<EvidenceItem[]>([])
  const [calculationSteps, setCalculationSteps] = useState<EvidenceItem[]>([])
  const [patientView, setPatientView] = useState('')
  const [officeView, setOfficeView] = useState('')
  const [ragMiss, setRagMiss] = useState(false)
  const [selectedView, setSelectedView] = useState<'patient' | 'office'>('patient')
  // 真实数据库查询状态
  const [realSettlementData, setRealSettlementData] = useState<SettlementExplanationData | null>(null)
  const [dataSourceError, setDataSourceError] = useState('')
  const [dataSourceLoading, setDataSourceLoading] = useState(false)
  // 处理进度折叠状态
  const [progressCollapsed, setProgressCollapsed] = useState(false)

  // ── 问答执行链路状态 ──
  const [traceEvents, setTraceEvents] = useState<TraceEventItem[]>([])
  const [runStatus, setRunStatus] = useState<'running' | 'success' | 'failed'>('running')
  const [canAnswer, setCanAnswer] = useState(false)
  const [partialAnswer, setPartialAnswer] = useState(false)
  const [canAnswerReason, setCanAnswerReason] = useState('')
  const [missingItems, setMissingItems] = useState<string[]>([])
  const [targetFeeItem, setTargetFeeItem] = useState('')
  const [targetField, setTargetField] = useState('')
  const [subFlow, setSubFlow] = useState('')

  // ── 计算已完成步骤数 ─────────────────────────────────────
  const completedCount = steps.filter((s) => s.status === 'done').length

  // ── 判断当前问题是否为统筹自付类 ─────────────────────────
  const isTongChouQuestion = /统筹自付|分段计算|起付线|报销比例|个人负担/.test(activeQuestion)

  // ── 提交查询 ─────────────────────────────────────────────
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim() || isLoading) return

    const userMessage = question.trim()
    setIsLoading(true)
    setActiveQuestion(userMessage)
    setSteps([])
    setTreatments([])
    setFeeBreakdown([])
    setEvidence([])
    setPolicyCards([])
    setSettlementEvidence([])
    setCalculationSteps([])
    setPatientView('')
    setOfficeView('')
    setRagMiss(false)
    setSelectedView('patient')
    setRealSettlementData(null)
    setDataSourceError('')
    setDataSourceLoading(false)
    setProgressCollapsed(false) // 默认展开执行链路
    setTraceEvents([])
    setRunStatus('running')
    setCanAnswer(false)
    setPartialAnswer(false)
    setCanAnswerReason('')
    setMissingItems([])
    setTargetFeeItem('')
    setTargetField('')
    setSubFlow('')

    // 构建请求
    const request = {
      question: userMessage,
      settlement_id: settlementId || '1671213',
      user_id: 'demo',        // ★ 持久化用：需与 useApiContext 的 userId 一致
      role: 'cashier',         // ★ 持久化用：用户角色
    }

    // ── SSE 流式请求 ──────────────────────────────────────
    try {
      const response = await fetch('/api/v1/medical-insurance-ai-agent/policy-qa/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No reader available')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          // 解析 SSE event: 前缀
          let eventType = "step"  // 默认
          let dataStr = ""
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
            continue
          }
          if (line.startsWith('data: ')) {
            dataStr = line.slice(6).trim()
          } else {
            continue
          }
          if (dataStr === '[DONE]') {
            break
          }

          try {
            const rawData = JSON.parse(dataStr)
            // ★ 防泄漏：过滤禁止展示的字段
            const data = stripForbiddenFields(rawData as Record<string, unknown>)

            // ── 处理 result 事件（只提取结果数据，不覆写步骤）──
            if (eventType === 'result') {
              const resultData = data.result as Record<string, unknown> | undefined
              if (resultData) {
                if (resultData.patient_view) setPatientView(String(resultData.patient_view))
                if (resultData.office_view) setOfficeView(String(resultData.office_view))
                if (resultData.policy_evidence && Array.isArray(resultData.policy_evidence)) {
                  setPolicyCards((resultData.policy_evidence as Array<Record<string, unknown>>).map(c => ({
                    title: String(c.title || ''),
                    clause: String(c.clause || ''),
                    evidenceText: String(c.evidence_text || c.evidenceText || ''),
                    matchedReason: String(c.matched_reason || c.matchedReason || ''),
                    ruleType: String(c.rule_type || c.ruleType || ''),
                    score: Number(c.score || 0),
                  })))
                }
                // ★ 提取结算溯源证据
                if (resultData.settlement_evidence && Array.isArray(resultData.settlement_evidence)) {
                  setSettlementEvidence((resultData.settlement_evidence as Array<Record<string, unknown>>).map(e => ({
                    item: String(e.item || ''),
                    value: Number(e.value || 0),
                    sourceTable: String(e.source_table || e.sourceTable || ''),
                    policyRule: String(e.policy_rule && typeof e.policy_rule === 'object'
                      ? JSON.stringify(e.policy_rule)
                      : e.policy_rule || ''),
                    calculation: String(e.calculation && typeof e.calculation === 'object'
                      ? JSON.stringify(e.calculation)
                      : e.calculation || ''),
                  })))
                }
                // ★ 提取分段计算步骤
                if (resultData.calculation_steps && Array.isArray(resultData.calculation_steps)) {
                  setCalculationSteps((resultData.calculation_steps as Array<Record<string, unknown>>).map(step => ({
                    item: `第${step.segment_index}段 (${Number(step.lower).toLocaleString('zh-CN')}-${Number(step.upper) === Infinity || !step.upper ? '∞' : Number(step.upper).toLocaleString('zh-CN')}元)`,
                    value: Number(step.pay || 0),
                    sourceTable: `段内金额: ${Number(step.amount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                    policyRule: String(step.policy_source || '未关联政策条文'),
                    calculation: `基础比例 ${(Number(step.base_ratio) * 100).toFixed(0)}% × 人员系数 ${(Number(step.person_ratio) * 100).toFixed(0)}% = 实际比例 ${(Number(step.actual_ratio) * 100).toFixed(0)}%\n${Number(step.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} × ${(Number(step.actual_ratio) * 100).toFixed(0)}% = ${Number(step.pay).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                  })))
                }
                // ★ 提取 can_answer / trace_events
                if (typeof resultData.can_answer === 'boolean') {
                  setCanAnswer(resultData.can_answer as boolean)
                }
                if (typeof resultData.partial_answer === 'boolean') {
                  setPartialAnswer(resultData.partial_answer as boolean)
                }
                if (resultData.can_answer_reason) {
                  setCanAnswerReason(String(resultData.can_answer_reason))
                }
                if (resultData.missing_items && Array.isArray(resultData.missing_items)) {
                  setMissingItems(resultData.missing_items as string[])
                }
                if (resultData.trace_events && Array.isArray(resultData.trace_events)) {
                  const events = resultData.trace_events as Array<Record<string, unknown>>
                  setTraceEvents(events.map(e => ({
                    step_id: String(e.step_id || ''),
                    step_name: String(e.step_name || ''),
                    step_number: Number(e.step_number || 0),
                    status: (e.status || 'pending') as TraceEventItem['status'],
                    duration_ms: Number(e.duration_ms || 0),
                    summary: String(e.summary || ''),
                    details: e.details as Record<string, unknown> | undefined,
                    error: e.error ? String(e.error) : undefined,
                  })))
                  setRunStatus('success')
                }
              }
            }

            // ── 处理 trace_event 事件（单步实时溯源）──
            else if (eventType === 'trace_event') {
              const evt = data as Record<string, unknown>
              if (evt.step_id) {
                const newEvent: TraceEventItem = {
                  step_id: String(evt.step_id),
                  step_name: String(evt.step_name || ''),
                  step_number: Number(evt.step_number || 0),
                  status: (evt.status || 'running') as TraceEventItem['status'],
                  duration_ms: Number(evt.duration_ms || 0),
                  summary: String(evt.summary || ''),
                  details: evt.detail as Record<string, unknown> | undefined,
                  error: evt.error ? String(evt.error) : undefined,
                }
                setTraceEvents((prev) => {
                  const idx = prev.findIndex((t) => t.step_id === newEvent.step_id)
                  if (idx >= 0) {
                    const updated = [...prev]
                    updated[idx] = { ...updated[idx], ...newEvent }
                    return updated
                  }
                  return [...prev, newEvent]
                })
              }
            }

            // ── 处理 step 事件 ──
            else if (data.step && data.status) {
              const stepData: PolicyQAStep = {
                step: String(data.step),
                status: String(data.status) as PolicyQAStep['status'],
                detail: data.detail as Record<string, unknown> | undefined,
                publicDetail: (data.public_detail || data.publicDetail) as Record<string, unknown> | undefined,
                publicMessage: String(data.public_message || data.publicMessage || ''),
                chunk: typeof data.chunk === 'string' ? data.chunk : undefined,
                error: typeof data.error === 'string' ? data.error : undefined,
              }

              // ★ 提取 RAG 政策卡片（search_policy_rules 步骤 done 时）
              if (data.step === 'search_policy_rules' && data.status === 'done') {
                const cards = data.policy_cards || data.policyCards
                if (cards && Array.isArray(cards)) {
                  setPolicyCards(cards.map((c: Record<string, unknown>) => ({
                    title: String(c.title || ''),
                    clause: String(c.clause || ''),
                    evidenceText: String(c.evidence_text || c.evidenceText || ''),
                    matchedReason: String(c.matched_reason || c.matchedReason || ''),
                    ruleType: String(c.rule_type || c.ruleType || ''),
                    score: Number(c.score || 0),
                  })))
                }
                // 检测 RAG 未命中
                const pd = (data.public_detail || data.publicDetail) as Record<string, unknown> | undefined
                if (pd && pd.rag_miss) {
                  setRagMiss(true)
                }
              }

              // ★ 提取双视角解释（generate_explanation 步骤 done 时）
              if (data.step === 'generate_explanation' && data.status === 'done') {
                if (data.patient_view || data.patientView) {
                  setPatientView(String(data.patient_view || data.patientView || ''))
                }
                if (data.office_view || data.officeView) {
                  setOfficeView(String(data.office_view || data.officeView || ''))
                }
              }

              // ★ 提取 trace_result 步骤中的执行链路和可回答性
              if (data.step === 'trace_result' && data.status === 'done') {
                const detail = data.detail as Record<string, unknown> | undefined
                if (detail) {
                  if (typeof detail.can_answer === 'boolean') {
                    setCanAnswer(detail.can_answer as boolean)
                  }
                  if (typeof detail.partial_answer === 'boolean') {
                    setPartialAnswer(detail.partial_answer as boolean)
                  }
                  if (detail.can_answer_reason) {
                    setCanAnswerReason(String(detail.can_answer_reason))
                  }
                  if (detail.missing_items && Array.isArray(detail.missing_items)) {
                    setMissingItems(detail.missing_items as string[])
                  }
                  if (detail.target_fee_item) {
                    setTargetFeeItem(String(detail.target_fee_item))
                  }
                  if (detail.target_field) {
                    setTargetField(String(detail.target_field))
                  }
                  if (detail.sub_flow) {
                    setSubFlow(String(detail.sub_flow))
                  }
                  if (detail.trace_events && Array.isArray(detail.trace_events)) {
                    const events = detail.trace_events as Array<Record<string, unknown>>
                    setTraceEvents(events.map(e => ({
                      step_id: String(e.step_id || ''),
                      step_name: String(e.step_name || ''),
                      step_number: Number(e.step_number || 0),
                      status: (e.status || 'pending') as TraceEventItem['status'],
                      duration_ms: Number(e.duration_ms || 0),
                      summary: String(e.summary || ''),
                      details: e.details as Record<string, unknown> | undefined,
                      error: e.error ? String(e.error) : undefined,
                    })))
                    setRunStatus('success')
                  }
                  if (detail.status) {
                    setRunStatus(detail.status as 'running' | 'success' | 'failed')
                  }
                }
              }

              // 直接更新步骤状态
              setSteps((prev) => {
                const existing = prev.findIndex((s) => s.step === data.step)
                if (existing >= 0) {
                  const updated = [...prev]
                  updated[existing] = {
                    ...updated[existing],
                    ...stepData,
                    endTime: data.status === 'done' ? Date.now() : updated[existing].endTime,
                  }
                  return updated
                }
                return [...prev, {
                  ...stepData,
                  startTime: Date.now()
                }]
              })

              // 提取费用分解数据（calculate_explanation 步骤完成时）
              if (data.step === 'calculate_explanation' && data.status === 'done' && data.detail) {
                const detail = data.detail as Record<string, unknown>

                // 提取待遇分解
                if (detail.treatment && typeof detail.treatment === 'object') {
                  const treatment = detail.treatment as Record<string, number>
                  const treatmentItems: TreatmentItem[] = [
                    { label: '总费用', value: treatment.total_fee || 0, variant: 'primary' },
                    { label: '医保内', value: treatment.in_scope || 0, variant: 'primary' },
                    { label: '起付线', value: treatment.deductible || 0 },
                    { label: '统筹支付', value: treatment.pooling_payment || 0 },
                    { label: '统筹自付', value: treatment.pooling_self_pay || 0 },
                    { label: '大额支付', value: treatment.major_payment || 0 },
                    { label: '大额自付', value: treatment.major_self_pay || 0 },
                    { label: '个人应负', value: treatment.personal_liability || 0 },
                    { label: '医保外', value: treatment.out_of_scope || 0 },
                  ]
                  setTreatments(treatmentItems)
                }

                // 提取费用分解
                const fees = detail.fees || detail.fee_breakdown
                if (fees && typeof fees === 'object' && 'categories' in fees) {
                  const feesData = fees as { categories: Array<{ category: string; total_amount: number; in_scope_amount: number; out_of_scope_amount: number }> }
                  const feeBreakdownItems: FeeBreakdownItem[] = feesData.categories.map(cat => ({
                    label: cat.category,
                    amount: cat.total_amount,
                    description: `医保内 ${cat.in_scope_amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元，医保外 ${cat.out_of_scope_amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元`,
                  }))
                  setFeeBreakdown(feeBreakdownItems)
                }

                // 提取分段计算数据
                if (detail.segments && typeof detail.segments === 'object') {
                  const segments = detail.segments as {
                    total_pay: number
                    segments: Array<{
                      lower: number
                      upper: number
                      amount: number
                      base_ratio: number
                      person_ratio: number
                      actual_ratio: number
                      pay: number
                      calculation: string
                      rule_id: string
                      policy_source: string
                    }>
                  }

                  const segmentEvidence: EvidenceItem[] = segments.segments.map((seg, idx) => ({
                    item: `第${idx + 1}段 (${seg.lower.toLocaleString('zh-CN')}-${seg.upper === Infinity ? '∞' : seg.upper.toLocaleString('zh-CN')}元)`,
                    value: seg.pay,
                    sourceTable: `段内金额: ${seg.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                    policyRule: seg.policy_source || '未关联政策条文',
                    calculation: `基础比例 ${seg.base_ratio * 100}% × 人员系数 ${seg.person_ratio * 100}% = 实际比例 ${seg.actual_ratio * 100}%\n${seg.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} × ${seg.actual_ratio * 100}% = ${seg.pay.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                  }))

                  segmentEvidence.push({
                    item: '统筹自付合计',
                    value: segments.total_pay,
                    sourceTable: '分段计算合计',
                    policyRule: '各段自付金额之和',
                    calculation: segments.segments.map((s, i) => `第${i + 1}段: ${s.pay.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`).join(' + ') + ` = ${segments.total_pay.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}元`,
                  })

                  setEvidence(prev => [...prev, ...segmentEvidence])
                }

                // 提取溯源证据
                if (detail.evidence && Array.isArray(detail.evidence)) {
                  setEvidence(detail.evidence as EvidenceItem[])
                }
              }
            }
          } catch {
            // 忽略解析错误
          }
        }
      }
    } catch (error) {
      console.warn('[Policy QA] SSE 不可达', error)
      // SSE 失败时不再模拟步骤，REST 端点仍会尝试查询
    }

    // ── 真实数据库查询：调用 settlement-explanation REST 端点 ──
    if (/统筹自付|分段计算|起付线|报销比例|个人负担/.test(userMessage)) {
      setDataSourceLoading(true)
      setDataSourceError('')
      setRealSettlementData(null)
      try {
        const realApiUrl = `/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation?settlement_id=${encodeURIComponent(settlementId || '1671213')}&question=${encodeURIComponent(userMessage)}`
        const realResp = await fetch(realApiUrl)
        if (!realResp.ok) {
          const errText = await realResp.text()
          throw new Error(errText || `HTTP ${realResp.status}`)
        }
        const realData = await realResp.json() as SettlementExplanationData
        setRealSettlementData(realData)
      } catch (err) {
        console.error('[Policy QA] 真实数据库查询失败:', err)
        setDataSourceError(String(err))
        setRealSettlementData(null)
      } finally {
        setDataSourceLoading(false)
      }
    }

    setIsLoading(false)
  }

  // ── 渲染 ──────────────────────────────────────────────────

  const showEmptyState =
    !isLoading &&
    !dataSourceLoading &&
    !activeQuestion &&
    steps.length === 0 &&
    traceEvents.length === 0 &&
    !realSettlementData

  return (
    <div className="grid gap-4 lg:grid-cols-[440px_1fr]">
      {/* Left rail: 输入 + 运行态/链路（桌面端更像控制台，信息密度更高） */}
      <section className="space-y-4 lg:sticky lg:top-6 self-start">
        {/* ══════════════════════════════════════════════════════
            QueryPanel — 结算单号 + 问题输入 + 查询按钮
            ══════════════════════════════════════════════════════ */}
        <div className="rounded-2xl border border-slate-200/70 bg-white/70 p-5 shadow-[0_12px_40px_rgba(15,23,42,0.06)] backdrop-blur">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid gap-3">
              <div className="grid gap-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-700">结算单号</label>
                  <span className="text-[11px] font-mono text-slate-400">支持粘贴</span>
                </div>
                <Input
                  value={settlementId}
                  onChange={(e) => setSettlementId(e.target.value)}
                  placeholder="例如 1671213"
                  disabled={isLoading}
                  className="h-9 bg-white/60 max-w-[160px]"
                />
              </div>

              <div className="grid gap-2">
                <label className="text-xs font-semibold text-slate-700">问题</label>
                <Input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="例如：统筹自付为什么是 4962.67 元？"
                  disabled={isLoading}
                  className="h-9 bg-white/60"
                />
              </div>

              <Button
                type="submit"
                disabled={isLoading || !question.trim()}
                className="h-9 bg-[#2563EB] hover:bg-[#2563EB]/90 text-white"
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <Search className="h-4 w-4 mr-1" />
                )}
                查询
              </Button>
            </div>

            {/* 状态标识行 */}
            <div className="flex items-center gap-2 text-xs flex-wrap">
              <span className="bg-slate-100/80 text-slate-700 px-2 py-0.5 rounded-md font-medium ring-1 ring-slate-200/60">
                身份：收费员
              </span>

              {/* 数据来源标识 */}
              {realSettlementData ? (
                realSettlementData.data_source === 'REAL_DB' && !realSettlementData.mock_used ? (
                  <span className="bg-[#059669]/10 text-[#059669] border border-[#059669]/25 px-2 py-0.5 rounded-md font-mono text-[11px]">
                    真实数据库 REAL_DB
                  </span>
                ) : realSettlementData.mock_used ? (
                  <span className="bg-[#D97706]/10 text-[#D97706] border border-[#D97706]/25 px-2 py-0.5 rounded-md font-mono text-[11px]">
                    当前为模拟数据，不可用于产品验证
                  </span>
                ) : null
              ) : !isLoading && steps.length === 0 ? (
                <span className="text-slate-400 font-mono text-[11px]">未查询</span>
              ) : null}
            </div>
          </form>
        </div>

        {/* ══════════════════════════════════════════════════════
            问答执行链路（trace_events 驱动）
            ══════════════════════════════════════════════════════ */}
        {traceEvents.length > 0 && (
          <ExecutionTracePanel traceEvents={traceEvents} isLoading={isLoading} />
        )}

        {/* 回退：旧版步骤（当无 traceEvents 时使用 ThinkingChain） */}
        {steps.length > 0 && traceEvents.length === 0 && (
          <div className="bg-white/70 border border-slate-200/70 rounded-2xl overflow-hidden backdrop-blur">
            <button
              type="button"
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50/60 transition-colors text-left"
              onClick={() => setProgressCollapsed(!progressCollapsed)}
            >
              <div className="flex items-center gap-2">
                {progressCollapsed ? (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                )}
                <span className="text-sm font-semibold text-slate-900">处理进度</span>
                {isLoading && (
                  <span className="text-[11px] text-slate-400 font-mono animate-pulse">处理中...</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 font-mono">
                  {completedCount}/{steps.length} 步骤完成
                </span>
              </div>
            </button>

            {!progressCollapsed && (
              <div className="border-t border-slate-200/70">
                <ThinkingChain steps={steps as ThinkingStep[]} isLoading={isLoading} />
              </div>
            )}
          </div>
        )}

        {/* ══════════════════════════════════════════════════════
            解释对象指示器
            ══════════════════════════════════════════════════════ */}
        {targetFeeItem && !isLoading && (
          <div className="flex items-center gap-2 bg-white/60 border border-slate-200/70 rounded-xl px-3 py-2 text-sm backdrop-blur">
            <span className="text-slate-500">解释对象：</span>
            <span className="font-semibold text-slate-800">{targetFeeItem}</span>
            {targetField && (
              <span className="text-[11px] font-mono text-slate-400">({targetField})</span>
            )}
            {subFlow && (
              <span className="text-[10px] bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded-full">
                {subFlow}
              </span>
            )}
          </div>
        )}

        {/* ══════════════════════════════════════════════════════
            Result Status Bar — 可回答性状态
            ══════════════════════════════════════════════════════ */}
        {runStatus !== 'running' && (
          <ResultStatusBar
            runStatus={runStatus}
            canAnswer={canAnswer}
            partialAnswer={partialAnswer}
            canAnswerReason={canAnswerReason}
            missingItems={missingItems}
          />
        )}
      </section>

      {/* Right: 结果区（空态/加载/结果/错误） */}
      <section className="space-y-4 min-w-0">
        {/* 空态：引导用户更快上手 */}
        {showEmptyState && (
          <div className="rounded-2xl border border-slate-200/70 bg-white/65 p-6 shadow-[0_12px_40px_rgba(15,23,42,0.06)] backdrop-blur">
            <div className="flex items-start justify-between gap-6">
              <div className="space-y-2">
                <div className="text-sm font-semibold text-slate-900">从哪里开始？</div>
                <p className="text-sm text-slate-600 leading-relaxed">
                  先填写结算单号，再用一句话描述你想解释的字段或费用项目（越具体越快）。
                </p>
                <ul className="mt-3 space-y-1.5 text-sm text-slate-600">
                  <li className="flex gap-2">
                    <span className="mt-2 size-1.5 rounded-full bg-blue-500/70 shrink-0" />
                    返回政策条文与匹配原因（可追溯）
                  </li>
                  <li className="flex gap-2">
                    <span className="mt-2 size-1.5 rounded-full bg-blue-500/70 shrink-0" />
                    输出患者/院端两种表述，方便沟通
                  </li>
                </ul>
              </div>

              <div className="hidden sm:block rounded-2xl bg-gradient-to-br from-blue-600 to-sky-500 p-[1px]">
                <div className="rounded-2xl bg-slate-950/90 px-4 py-3">
                  <div className="text-[11px] font-mono text-slate-300">TIP</div>
                  <div className="mt-1 text-xs text-slate-100">
                    尝试问：<span className="font-semibold">“统筹自付为什么是 X 元？”</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-5">
              <div className="text-xs font-semibold text-slate-700 mb-2">示例问题</div>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_QUESTIONS.map((q) => (
                  <Button
                    key={q}
                    type="button"
                    variant="outline"
                    size="xs"
                    className="bg-white/70 hover:bg-white"
                    onClick={() => setQuestion(q)}
                  >
                    {q}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 真实数据库查询加载中 — 骨架屏 */}
        {dataSourceLoading && (
          <div className="space-y-4 animate-pulse">
            {/* Conclusion card skeleton */}
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b border-slate-200">
                <div className="w-4 h-4 rounded bg-slate-200" />
                <div className="h-3.5 bg-slate-200 rounded w-28" />
              </div>
              <div className="px-8 py-8 text-center space-y-4">
                <div className="h-3 bg-slate-200 rounded w-16 mx-auto" />
                <div className="h-12 bg-slate-200 rounded w-48 mx-auto" />
                <div className="h-4 bg-slate-200 rounded w-64 mx-auto" />
                <div className="flex justify-center gap-2">
                  <div className="h-5 bg-slate-200 rounded w-16" />
                  <div className="h-5 bg-slate-200 rounded w-20" />
                  <div className="h-5 bg-slate-200 rounded w-14" />
                </div>
              </div>
            </div>

            {/* Dual-view tabs skeleton */}
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b border-slate-200">
                <div className="w-4 h-4 rounded bg-slate-200" />
                <div className="h-3.5 bg-slate-200 rounded w-20" />
              </div>
              <div className="px-5 pt-4 pb-4">
                <div className="flex gap-1 mb-4">
                  <div className="h-8 bg-slate-200 rounded-md w-24" />
                  <div className="h-8 bg-slate-200 rounded-md w-24" />
                </div>
                <div className="h-24 bg-slate-200 rounded-lg w-full" />
              </div>
            </div>

            {/* Two-column grid skeleton: calculate + settlement facts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
                  <div className="w-4 h-4 rounded bg-slate-200" />
                  <div className="h-3.5 bg-slate-200 rounded w-20" />
                </div>
                <div className="px-4 py-4 space-y-3">
                  <div className="h-3 bg-slate-200 rounded w-3/4" />
                  <div className="h-3 bg-slate-200 rounded w-5/6" />
                  <div className="h-3 bg-slate-200 rounded w-2/3" />
                  <div className="h-3 bg-slate-200 rounded w-4/5" />
                </div>
              </div>
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
                  <div className="w-4 h-4 rounded bg-slate-200" />
                  <div className="h-3.5 bg-slate-200 rounded w-28" />
                </div>
                <div className="divide-y divide-slate-100">
                  {[1,2,3,4,5].map((i) => (
                    <div key={i} className="flex items-center justify-between px-4 py-2.5">
                      <div className="h-3 bg-slate-200 rounded w-16" />
                      <div className="h-3 bg-slate-200 rounded w-20" />
                      <div className="h-3 bg-slate-200 rounded w-24" />
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Policy evidence skeleton */}
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200">
                <div className="w-4 h-4 rounded bg-slate-200" />
                <div className="h-3.5 bg-slate-200 rounded w-20" />
              </div>
              <div className="px-4 py-3 space-y-2">
                <div className="h-4 bg-slate-200 rounded w-full" />
                <div className="h-4 bg-slate-200 rounded w-5/6" />
              </div>
            </div>

            <div className="flex items-center justify-center gap-2 text-sm text-slate-400 pt-1">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>正在查询真实数据库...</span>
            </div>
          </div>
        )}

        {/* 真实数据库查询失败 */}
        {dataSourceError && !dataSourceLoading && (
          <div className="bg-white border border-red-200 rounded-xl p-6">
            <div className="flex items-start gap-3">
              <span className="text-[#DC2626] text-lg leading-none mt-0.5">✕</span>
              <div>
                <div className="text-sm font-semibold text-[#DC2626]">真实数据库查询失败</div>
                <div className="text-sm text-slate-600 mt-1 leading-relaxed">{dataSourceError}</div>
                <div className="text-xs text-slate-500 mt-2">
                  请检查数据库连接和结算单号。当前不会展示 mock 数据。
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 真实数据库查询成功 — 展示 SettlementExplanationPage */}
        {realSettlementData && !dataSourceLoading && <SettlementExplanationPage data={realSettlementData} />}

        {/* 无法回答 — show reason */}
        {!isLoading && runStatus === 'success' && !canAnswer && (
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="flex items-start gap-3">
              <Info className="h-5 w-5 text-slate-400 shrink-0 mt-0.5" />
              <div>
                <div className="text-sm font-semibold text-slate-700">当前无法提供答案</div>
                <div className="text-sm text-slate-500 mt-1 leading-relaxed">
                  {canAnswerReason ||
                    '系统未获取到足够的结算字段或政策依据来回答该问题。请尝试调整问题表述，或检查结算单号是否正确。'}
                </div>
                {missingItems.length > 0 && (
                  <div className="mt-2">
                    <div className="text-xs text-slate-400 mb-1">缺少以下信息：</div>
                    <ul className="space-y-1">
                      {missingItems.map((item, i) => (
                        <li key={i} className="text-xs text-slate-500 flex items-center gap-1.5">
                          <span className="w-1 h-1 rounded-full bg-slate-300 shrink-0" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 非统筹自付问题：canAnswer 或 partialAnswer 时显示 */}
        {!isLoading && (canAnswer || partialAnswer) && !isTongChouQuestion && (
          <>
            <PolicyAnswerCard
              treatments={treatments}
              feeBreakdown={feeBreakdown}
              evidence={evidence}
              policyCards={policyCards}
            />

            {/* 双视角解释 — 浅色主题标签页 */}
            {(patientView || officeView) && (
              <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                {/* 标签切换 */}
                <div className="flex border-b border-slate-200">
                  <button
                    type="button"
                    onClick={() => setSelectedView('patient')}
                    className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors ${
                      selectedView === 'patient'
                        ? 'text-[#2563EB] border-b-2 border-[#2563EB] bg-blue-50/50'
                        : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    患者视角
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedView('office')}
                    className={`flex-1 px-4 py-2.5 text-sm font-medium transition-colors ${
                      selectedView === 'office'
                        ? 'text-[#2563EB] border-b-2 border-[#2563EB] bg-blue-50/50'
                        : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    院端视角
                  </button>
                </div>
                {/* 内容区域 */}
                <div className="p-4 text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
                  {selectedView === 'patient'
                    ? patientView ||
                      '暂无患者视角解释。请检查后端服务是否正常运行，或尝试重新提问。'
                    : officeView ||
                      '暂无院端视角解释。请检查后端服务是否正常运行，或尝试重新提问。'}
                </div>
              </div>
            )}
          </>
        )}

        {/* 初始加载状态（尚无步骤） */}
        {isLoading && steps.length === 0 && !dataSourceLoading && (
          <div className="bg-white border border-slate-200 rounded-xl p-6">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 animate-spin text-[#2563EB]" />
              <span className="text-sm text-slate-500">处理中...</span>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
