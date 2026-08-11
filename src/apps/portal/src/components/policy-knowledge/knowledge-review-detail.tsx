'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  RefreshCw,
  RotateCcw,
  Settings2,
  SkipForward,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useApiContext } from '@/lib/api-context'
import {
  approveChangeSet,
  getChangeSet,
  listDecisionTasks,
  listSemanticMetrics,
  PolicyKnowledgeApiError,
  rejectChangeSet,
  resolveDecisionTask,
  returnKnowledgeReview,
  reviewKnowledge,
  type ChangeSetItem,
  type ChangeItemType,
  type DecisionTask,
  type KnowledgeChangeSet,
  type KnowledgeItem,
  type RiskLevel,
} from '@/lib/policy-knowledge-api'
import { ReextractConfigDialog, type ReextractScope } from './reextract-config-dialog'
import RuleTraceDrawer from './rule-trace-drawer'

type ReasonAction = 'return' | 'reject'

type ItemReviewKind = 'approved' | 'rejected' | 'returned'

type TableColumn = { code: string; label: string; kind: 'id' | 'dimension' | 'number' | 'long' }

// 政策规则对象（zcgz）列顺序：政策文档 → 单元 → 规则 → 维度 → 数值 → 元信息。
// [来源: 语义层设计文档 §4.2/§4.3 19 个指标；用户迭代 16-2 要求的排列顺序]
const RULE_OBJECT_ORDER: string[] = [
  'policy_id',
  'fact_id',
  'unit',
  'rule_id',
  'insu_type',
  'med_type',
  'hosp_lv',
  'psn_type',
  'setl_type',
  'payment_ratio',
  'personal_payment_ratio',
  'deductible_amount',
  'cap_amount',
  'amount_band',
  'time_period',
  'admission_order',
  'priority',
  'rule_type',
  'rule_value',
  'business_sentence',
  'source_text',
  'clause_id',
]

const RULE_OBJECT_DEFAULT_LABELS: Record<string, string> = {
  policy_id: '政策文件ID',
  fact_id: '单元ID',
  unit: '所属单元',
  rule_id: '规则ID',
  insu_type: '险种类别',
  med_type: '医疗类别',
  hosp_lv: '医疗机构等级',
  psn_type: '人群标签',
  setl_type: '结算方式',
  payment_ratio: '支付比例',
  personal_payment_ratio: '个人支付比例',
  deductible_amount: '起付金额',
  cap_amount: '封顶金额',
  amount_band: '金额分段',
  time_period: '时间周期',
  admission_order: '住院次数',
  priority: '规则优先级',
  rule_type: '规则类型',
  rule_value: '规则值',
  business_sentence: '业务描述',
  source_text: '原始政策文本',
  clause_id: '条款ID',
}

// 默认展示列：业务核心列——规则类型、人群/等级/分段维度、数值、规则值、原文。
// 所属单元由分组标题行展示（见表格 tbody 分组渲染）；内部 ID 列默认隐藏，可在"列设置"勾选。
const DEFAULT_VISIBLE_COLUMNS: string[] = [
  'rule_type',
  'psn_type',
  'hosp_lv',
  'amount_band',
  'payment_ratio',
  'personal_payment_ratio',
  'rule_value',
  'source_text',
]

function columnKind(code: string): TableColumn['kind'] {
  if (['policy_id', 'fact_id', 'rule_id', 'clause_id'].includes(code)) return 'id'
  if (['payment_ratio', 'personal_payment_ratio', 'deductible_amount', 'cap_amount', 'amount_band', 'admission_order'].includes(code)) return 'number'
  if (['unit', 'rule_value', 'business_sentence', 'source_text'].includes(code)) return 'long'
  return 'dimension'
}

// 按规则类型预设默认展示列：业务列为主，数值列按类型挂载。
const RULE_TYPE_PRESETS: Array<{ type: string; columns: string[] }> = [
  {
    type: '支付比例',
    columns: ['rule_type', 'psn_type', 'hosp_lv', 'amount_band', 'payment_ratio', 'personal_payment_ratio', 'rule_value', 'source_text'],
  },
  {
    type: '起付',
    columns: ['rule_type', 'psn_type', 'hosp_lv', 'amount_band', 'deductible_amount', 'rule_value', 'source_text'],
  },
  {
    type: '封顶',
    columns: ['rule_type', 'psn_type', 'hosp_lv', 'cap_amount', 'rule_value', 'source_text'],
  },
  {
    type: '资格',
    columns: ['rule_type', 'psn_type', 'hosp_lv', 'rule_value', 'source_text'],
  },
]

function presetForType(ruleType: string | undefined): string[] {
  if (!ruleType) return [...DEFAULT_VISIBLE_COLUMNS]
  const matched = RULE_TYPE_PRESETS.find((preset) => ruleType.includes(preset.type))
  return matched ? [...matched.columns] : [...DEFAULT_VISIBLE_COLUMNS]
}

/** 判断当前可见列集合是否精确匹配某个规则类型预设，用于列设置下拉回显。 */
function matchedPresetType(visibleCodes: string[] | null): string {
  if (!visibleCodes) return ''
  for (const preset of RULE_TYPE_PRESETS) {
    if (preset.columns.length === visibleCodes.length && preset.columns.every((code) => visibleCodes.includes(code))) {
      return preset.type
    }
  }
  return ''
}

const COLUMN_STORAGE_KEY = 'policy-review-table-columns-v2'

export function KnowledgeReviewDetail({ changeSetId }: { changeSetId: string }) {
  const { userId } = useApiContext()
  const router = useRouter()
  const [changeSet, setChangeSet] = useState<KnowledgeChangeSet | null>(null)
  const [decisionTasks, setDecisionTasks] = useState<DecisionTask[]>([])
  const [unitFilter, setUnitFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [changeTypeFilter, setChangeTypeFilter] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [reviewFilter, setReviewFilter] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchSubmitting, setBatchSubmitting] = useState(false)
  const [itemReviews, setItemReviews] = useState<Record<string, ItemReviewKind>>({})
  const [itemReason, setItemReason] = useState<{ itemId: string; action: 'reject' | 'return' } | null>(null)
  const [itemReasonText, setItemReasonText] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [reviewingItemId, setReviewingItemId] = useState<string | null>(null)
  const [resolvingTaskId, setResolvingTaskId] = useState<string | null>(null)
  const [reasonAction, setReasonAction] = useState<ReasonAction | null>(null)
  const [reason, setReason] = useState('')
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set())
  const [metricLabels, setMetricLabels] = useState<Record<string, string>>({})
  const [visibleCodes, setVisibleCodes] = useState<string[] | null>(null)
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [reextractScope, setReextractScope] = useState<ReextractScope | null>(null)
  const [traceRuleId, setTraceRuleId] = useState<string | null>(null)
  const loadSequence = useRef(0)
  const actionInFlight = useRef(false)

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current
    setLoading(true)
    setError('')
    try {
      const [nextChangeSet, nextTasks] = await Promise.all([
        getChangeSet(changeSetId),
        listDecisionTasks('', '', changeSetId),
      ])
      if (sequence !== loadSequence.current) return
      setChangeSet(nextChangeSet)
      setDecisionTasks(nextTasks.filter((task) => task.blocking_scope === changeSetId))
    } catch (reasonValue) {
      if (sequence !== loadSequence.current) return
      setError(reasonValue instanceof Error ? reasonValue.message : '审核详情加载失败')
    } finally {
      if (sequence === loadSequence.current) setLoading(false)
    }
  }, [changeSetId])

  useEffect(() => {
    const sequence = ++loadSequence.current
    void Promise.all([
      getChangeSet(changeSetId),
      listDecisionTasks('', '', changeSetId),
    ])
      .then(([nextChangeSet, nextTasks]) => {
        if (sequence !== loadSequence.current) return
        setChangeSet(nextChangeSet)
        setDecisionTasks(nextTasks.filter((task) => task.blocking_scope === changeSetId))
      })
      .catch((reasonValue) => {
        if (sequence !== loadSequence.current) return
        setError(reasonValue instanceof Error ? reasonValue.message : '审核详情加载失败')
      })
      .finally(() => {
        if (sequence === loadSequence.current) setLoading(false)
      })
    return () => {
      loadSequence.current += 1
    }
  }, [changeSetId])

  // 语义层指标名映射：用户在语义层重命名指标后，审核详情表头随之更新。
  useEffect(() => {
    let active = true
    listSemanticMetrics()
      .then((metrics) => {
        if (!active) return
        const labels: Record<string, string> = {}
        for (const metric of metrics) {
          const code = metric.metric_code.split('.').pop() ?? metric.metric_code
          if (metric.name) labels[code] = metric.name
        }
        setMetricLabels(labels)
      })
      .catch(() => {
        // 语义层不可用时回退默认标签，不阻塞审核。
      })
    return () => {
      active = false
    }
  }, [])

  const columnLabel = useCallback((code: string): string => {
    return metricLabels[code] ?? RULE_OBJECT_DEFAULT_LABELS[code] ?? code
  }, [metricLabels])

  const dominantRuleType = useMemo(() => {
    if (!changeSet) return undefined
    const counts = new Map<string, number>()
    for (const item of changeSet.items) {
      const candidate = parseCandidateKnowledge(item)
      const ruleType = candidate?.fields.find((field) => field.field_code === 'rule_type')?.raw_value
      if (typeof ruleType === 'string' && ruleType.trim()) {
        counts.set(ruleType, (counts.get(ruleType) ?? 0) + 1)
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
  }, [changeSet])

  // 列可见性：优先沿用用户最近一次选择（localStorage），否则按规则类型预设。
  useEffect(() => {
    if (!changeSet) return
    try {
      const raw = window.localStorage.getItem(COLUMN_STORAGE_KEY)
      if (raw) {
        const parsed: unknown = JSON.parse(raw)
        if (Array.isArray(parsed) && parsed.every((code) => typeof code === 'string')) {
          setVisibleCodes(parsed as string[])
          return
        }
      }
    } catch {
      // 存储损坏时按预设回退。
    }
    setVisibleCodes(presetForType(dominantRuleType))
  }, [changeSet, dominantRuleType])

  function updateVisibleColumns(codes: string[]) {
    setVisibleCodes(codes)
    try {
      window.localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(codes))
    } catch {
      // 隐私模式等场景忽略持久化失败。
    }
  }

  function toggleColumn(code: string) {
    if (!visibleCodes) return
    const next = visibleCodes.includes(code)
      ? visibleCodes.filter((item) => item !== code)
      : [...visibleCodes, code]
    updateVisibleColumns(next)
  }

  function applyPreset(ruleType: string) {
    updateVisibleColumns(presetForType(ruleType))
  }

  const unitOptions = changeSet?.source_units ?? []

  // 各筛选维度候选选项：基于全部 items 聚合，避免切换筛选时选项跳动。
  const filterOptions = useMemo(() => {
    const ruleTypes = new Set<string>()
    const changeTypes = new Set<ChangeItemType>()
    const riskLevels = new Set<RiskLevel>()
    for (const item of changeSet?.items ?? []) {
      const candidate = parseCandidateKnowledge(item)
      const ruleTypeField = candidate?.fields.find((field) => field.field_code === 'rule_type')
      const ruleTypeText = ruleTypeField ? structuredFieldValue(ruleTypeField.raw_value) : ''
      if (ruleTypeText && ruleTypeText !== '—') ruleTypes.add(ruleTypeText)
      changeTypes.add(item.change_type)
      riskLevels.add(item.risk_level)
    }
    return {
      ruleTypes: [...ruleTypes].sort(),
      changeTypes: [...changeTypes],
      riskLevels: [...riskLevels],
    }
  }, [changeSet])

  const visibleItems = useMemo(() => {
    if (!changeSet) return []
    return changeSet.items.filter((item) => {
      if (unitFilter && item.unit_id !== unitFilter) return false
      if (changeTypeFilter && item.change_type !== changeTypeFilter) return false
      if (riskFilter && item.risk_level !== riskFilter) return false
      if (typeFilter) {
        const candidate = parseCandidateKnowledge(item)
        const ruleTypeField = candidate?.fields.find((field) => field.field_code === 'rule_type')
        const text = ruleTypeField ? structuredFieldValue(ruleTypeField.raw_value) : ''
        if ((text === '—' ? '' : text) !== typeFilter) return false
      }
      if (reviewFilter) {
        const review = itemReviews[item.item_id] ?? 'pending'
        if (review !== reviewFilter) return false
      }
      return true
    })
  }, [changeSet, unitFilter, typeFilter, changeTypeFilter, riskFilter, reviewFilter, itemReviews])

  // 按单元分组：每组 { key, title=完整条款路径, subtitle=叶子原文, items }。
  // 纯按单元归属，不做人群重定向（分段比例原文即在职职工，退休仅（四）公式）。
  const unitGroups = useMemo(() => {
    if (!changeSet) return []
    const groups = new Map<string, { key: string; title: string; subtitle: string; items: ChangeSetItem[] }>()
    const ensureGroup = (key: string) => {
      const existing = groups.get(key)
      if (existing) return existing
      const unit = changeSet.source_units.find((candidate) => candidate.unit_id === key)
      const path = unit?.path ?? [key]
      const group = {
        key,
        title: path.join(' / '),
        subtitle: path[path.length - 1] ?? '',
        items: [] as ChangeSetItem[],
      }
      groups.set(key, group)
      return group
    }
    // 第一遍：按条款出现顺序建组（保证（四）公式单元按原文位置靠后，不被提前插入）
    for (const item of visibleItems) {
      ensureGroup(item.unit_id)
    }
    // 第二遍：填入规则
    for (const item of visibleItems) {
      groups.get(item.unit_id)?.items.push(item)
    }
    return [...groups.values()]
  }, [changeSet, visibleItems])

  // 仅"有效候选 + 未审核"的行可勾选，用于批量通过。
  const selectableIds = useMemo(
    () =>
      new Set(
        visibleItems
          .filter((item) => parseCandidateKnowledge(item) && !itemReviews[item.item_id])
          .map((item) => item.item_id),
      ),
    [visibleItems, itemReviews],
  )
  const effectiveSelectedIds = useMemo(
    () => new Set([...selectedIds].filter((id) => selectableIds.has(id))),
    [selectedIds, selectableIds],
  )
  const allSelectableChecked =
    selectableIds.size > 0 && [...selectableIds].every((id) => effectiveSelectedIds.has(id))
  const hasActiveFilter = Boolean(
    unitFilter || typeFilter || changeTypeFilter || riskFilter || reviewFilter,
  )

  // 表头列 = 固定顺序的 19 个政策规则对象字段，按用户可见性选择过滤。
  const tableColumns: TableColumn[] = useMemo(() => {
    const codes = visibleCodes ?? RULE_OBJECT_ORDER
    return RULE_OBJECT_ORDER
      .filter((code) => codes.includes(code))
      .map((code) => ({ code, label: columnLabel(code), kind: columnKind(code) }))
  }, [visibleCodes, columnLabel])

  const pendingTasks = decisionTasks.filter((task) => task.status === 'PENDING')
  const highRisk = Boolean(
    (changeSet?.risk_summary.HIGH ?? 0) > 0
      || (changeSet?.risk_summary.CRITICAL ?? 0) > 0
      || changeSet?.items.some((item) => item.risk_level === 'HIGH' || item.risk_level === 'CRITICAL'),
  )
  const approveEligible = changeSet?.status === 'PENDING_REVIEW' || changeSet?.status === 'NEEDS_DECISION'
  const returnOrRejectEligible = changeSet?.status === 'PENDING_REVIEW'
  const invalidCandidateCount = changeSet?.items.filter((item) => !parseCandidateKnowledge(item)).length ?? 0
  const candidateSetEmpty = changeSet?.items.length === 0
  const allCandidateSnapshotsValid = Boolean(
    changeSet && changeSet.items.length > 0 && invalidCandidateCount === 0,
  )
  const approveBlocked = submitting
    || !approveEligible
    || highRisk
    || pendingTasks.length > 0
    || !allCandidateSnapshotsValid

  async function resolveTask(task: DecisionTask, action: 'accept_recommendation' | 'skip') {
    if (resolvingTaskId || actionInFlight.current) return
    actionInFlight.current = true
    setResolvingTaskId(task.task_id)
    setError('')
    try {
      await resolveDecisionTask(task.task_id, {
        action,
        by: userId,
        ...(action === 'accept_recommendation' ? { option: task.recommended_option } : {}),
      })
      await load()
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '问题处理失败')
    } finally {
      actionInFlight.current = false
      setResolvingTaskId(null)
    }
  }

  async function performLifecycle(action: 'approve' | ReasonAction) {
    if (submitting || actionInFlight.current || !changeSet) return
    const note = reason.trim()
    if (action !== 'approve' && !note) return
    actionInFlight.current = true
    setSubmitting(true)
    setError('')
    try {
      if (action === 'approve') {
        await approveChangeSet(changeSetId, userId)
      } else if (action === 'return') {
        await returnKnowledgeReview(changeSetId, userId, note)
      } else {
        await rejectChangeSet(changeSetId, userId, note)
      }
      setReasonAction(null)
      setReason('')
      router.push('/policy-knowledge/knowledge/review')
      router.refresh()
    } catch (reasonValue) {
      const message = reasonValue instanceof Error ? reasonValue.message : '审核操作失败'
      if (reasonValue instanceof PolicyKnowledgeApiError && reasonValue.status === 409) {
        try {
          setChangeSet(await getChangeSet(changeSetId))
        } catch {
          // 保留服务端冲突信息，当前数据无法刷新时不伪造新状态。
        }
      }
      setError(message)
    } finally {
      actionInFlight.current = false
      setSubmitting(false)
    }
  }

  function openReasonDialog(action: ReasonAction) {
    if (submitting) return
    setReason('')
    setReasonAction(action)
  }

  // ── 行级审核意见（迭代 16：单条通过/拒绝/退回，走 reviewKnowledge 落库留痕）──

  async function reviewItem(item: ChangeSetItem, kind: Exclude<ItemReviewKind, 'returned'>, note?: string) {
    const candidate = parseCandidateKnowledge(item)
    if (!candidate || reviewingItemId || submitting || actionInFlight.current) return
    actionInFlight.current = true
    setReviewingItemId(item.item_id)
    setError('')
    try {
      await reviewKnowledge(candidate.knowledge_id, {
        doc_id: item.doc_id,
        unit_id: candidate.unit_id,
        knowledge_id: candidate.knowledge_id,
        extraction_id: candidate.extraction_id ?? null,
        status: kind,
        reviewed_by: userId,
        note: note ?? null,
      })
      setItemReviews((previous) => ({ ...previous, [item.item_id]: kind }))
      setItemReason(null)
      setItemReasonText('')
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '单条审核记录失败')
    } finally {
      actionInFlight.current = false
      setReviewingItemId(null)
    }
  }

  // ── 批量通过（多选勾选后逐条走 reviewKnowledge 落库留痕）──
  async function batchApproveSelected() {
    if (batchSubmitting || submitting || actionInFlight.current) return
    const targets = visibleItems.filter((item) => effectiveSelectedIds.has(item.item_id))
    if (targets.length === 0) return
    actionInFlight.current = true
    setBatchSubmitting(true)
    setError('')
    try {
      for (const item of targets) {
        const candidate = parseCandidateKnowledge(item)
        if (!candidate) continue
        await reviewKnowledge(candidate.knowledge_id, {
          doc_id: item.doc_id,
          unit_id: candidate.unit_id,
          knowledge_id: candidate.knowledge_id,
          extraction_id: candidate.extraction_id ?? null,
          status: 'approved',
          reviewed_by: userId,
          note: null,
        })
        setItemReviews((previous) => ({ ...previous, [item.item_id]: 'approved' }))
      }
      setSelectedIds(new Set())
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : '批量审核部分失败，请重试未通过项')
    } finally {
      actionInFlight.current = false
      setBatchSubmitting(false)
    }
  }

  function toggleSelect(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (allSelectableChecked) {
        for (const id of selectableIds) next.delete(id)
      } else {
        for (const id of selectableIds) next.add(id)
      }
      return next
    })
  }

  function clearFilters() {
    setUnitFilter('')
    setTypeFilter('')
    setChangeTypeFilter('')
    setRiskFilter('')
    setReviewFilter('')
  }

  function openItemReason(item: ChangeSetItem, action: 'reject' | 'return') {
    if (reviewingItemId || submitting) return
    setItemReasonText('')
    setItemReason({ itemId: item.item_id, action })
  }

  async function confirmItemReason() {
    if (!itemReason || !itemReasonText.trim() || reviewingItemId) return
    const item = changeSet?.items.find((candidate) => candidate.item_id === itemReason.itemId)
    if (!item) return
    if (itemReason.action === 'return') {
      // 后端单条审核仅支持 approved/rejected；退回以 rejected + 标记化原因落库。
      await reviewItem(item, 'rejected', `[退回重提取] ${itemReasonText.trim()}`)
      setItemReviews((previous) => ({ ...previous, [item.item_id]: 'returned' as const }))
    } else {
      await reviewItem(item, 'rejected', itemReasonText.trim())
    }
  }

  if (loading) {
    return (
      <section aria-labelledby="knowledge-review-detail-title" className="space-y-3 pt-2">
        <h2 id="knowledge-review-detail-title" className="text-xl font-semibold tracking-tight text-slate-900">
          知识审核详情
        </h2>
        <p className="font-mono text-xs text-slate-500">{changeSetId}</p>
        <div aria-label="正在加载审核详情" className="flex justify-center py-20">
          <Loader2 className="size-5 animate-spin text-slate-400" />
        </div>
      </section>
    )
  }

  if (!changeSet) {
    return (
      <div className="space-y-3 pt-2">
        {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        <p className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-400">
          审核结果不存在或暂不可用
        </p>
      </div>
    )
  }

  return (
    <section aria-labelledby="knowledge-review-detail-title" className="space-y-4 pt-2">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href="/policy-knowledge/knowledge/review"
          className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
        >
          <ChevronLeft className="size-3.5" />返回审核列表
        </Link>
        <span className="font-mono text-[10px] text-slate-400">{changeSet.change_set_id}</span>
        <button
          type="button"
          aria-label="刷新审核详情"
          onClick={() => void load()}
          disabled={loading || submitting}
          className="ml-auto rounded-md border border-slate-200 p-1.5 text-slate-400 hover:bg-slate-50 disabled:opacity-40"
        >
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      <header className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="flex flex-wrap items-center gap-2">
          <div>
            <p className="text-xs font-semibold text-emerald-700">{changeSet.doc_title}</p>
            <h2 id="knowledge-review-detail-title" className="mt-1 text-xl font-semibold tracking-tight text-slate-900">
              知识审核详情
            </h2>
          </div>
          <span className="ml-auto rounded bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">
            {statusLabel(changeSet.status)}
          </span>
        </div>
      </header>

      {error && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <DecisionIssues
        tasks={decisionTasks}
        expandedTasks={expandedTasks}
        resolvingTaskId={resolvingTaskId}
        onToggle={(taskId) => setExpandedTasks((current) => {
          const next = new Set(current)
          if (next.has(taskId)) next.delete(taskId)
          else next.add(taskId)
          return next
        })}
        onResolve={resolveTask}
      />

      <section aria-labelledby="review-table-title" className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="space-y-3 border-b border-slate-100 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <h3 id="review-table-title" className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-slate-900">
              <FileText className="size-4 text-emerald-600" />结构化知识列表
            </h3>
            <span className="ml-auto font-mono text-[11px] tabular-nums text-slate-400">
              {visibleItems.length} / {changeSet.items.length} 条
              {effectiveSelectedIds.size > 0 ? ` · 已选 ${effectiveSelectedIds.size}` : ''}
            </span>
            <div className="relative">
              <button
                type="button"
                aria-label="表格列设置"
                aria-expanded={columnsOpen}
                onClick={() => setColumnsOpen((current) => !current)}
                className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
              >
                <Settings2 className="size-3.5" />列设置
                <span className="rounded bg-slate-100 px-1 font-mono text-[10px] tabular-nums text-slate-500">{tableColumns.length}</span>
              </button>
              {columnsOpen && (
                <ColumnSettingsPanel
                  visibleCodes={visibleCodes ?? DEFAULT_VISIBLE_COLUMNS}
                  labels={metricLabels}
                  dominantRuleType={dominantRuleType}
                  onToggle={toggleColumn}
                  onShowAll={() => updateVisibleColumns([...RULE_OBJECT_ORDER])}
                  onApplyPreset={applyPreset}
                />
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <select
              aria-label="按单元筛选"
              value={unitFilter}
              onChange={(event) => setUnitFilter(event.target.value)}
              className="h-8 max-w-[140px] shrink-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500"
            >
              <option value="">全部单元</option>
              {unitOptions.map((unit) => (
                <option key={`${unit.unit_id}:${unit.unit_revision_id}`} value={unit.unit_id}>
                  {unit.path.join(' / ') || unit.unit_id}
                </option>
              ))}
            </select>
            <select
              aria-label="按规则类型筛选"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
              className="h-8 max-w-[140px] shrink-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500"
            >
              <option value="">全部规则类型</option>
              {filterOptions.ruleTypes.map((ruleType) => (
                <option key={ruleType} value={ruleType}>{ruleType}</option>
              ))}
            </select>
            <select
              aria-label="按变更类型筛选"
              value={changeTypeFilter}
              onChange={(event) => setChangeTypeFilter(event.target.value)}
              className="h-8 max-w-[140px] shrink-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500"
            >
              <option value="">全部变更类型</option>
              {filterOptions.changeTypes.map((changeType) => (
                <option key={changeType} value={changeType}>{changeTypeLabel(changeType)}</option>
              ))}
            </select>
            <select
              aria-label="按风险等级筛选"
              value={riskFilter}
              onChange={(event) => setRiskFilter(event.target.value)}
              className="h-8 max-w-[140px] shrink-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500"
            >
              <option value="">全部风险等级</option>
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as RiskLevel[])
                .filter((level) => filterOptions.riskLevels.includes(level))
                .map((level) => (
                  <option key={level} value={level}>{riskLabel(level)}风险</option>
                ))}
            </select>
            <select
              aria-label="按审核状态筛选"
              value={reviewFilter}
              onChange={(event) => setReviewFilter(event.target.value)}
              className="h-8 max-w-[140px] shrink-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs outline-none transition-colors focus:border-emerald-500"
            >
              <option value="">全部审核状态</option>
              <option value="pending">未处理</option>
              <option value="approved">已通过</option>
              <option value="rejected">已拒绝</option>
              <option value="returned">已退回</option>
            </select>
            {hasActiveFilter && (
              <button
                type="button"
                onClick={clearFilters}
                className="h-8 shrink-0 rounded-lg px-2 text-xs font-medium text-slate-500 hover:text-slate-800"
              >
                清空筛选
              </button>
            )}
            {effectiveSelectedIds.size > 0 && (
              <button
                type="button"
                onClick={() => void batchApproveSelected()}
                disabled={batchSubmitting}
                className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition-all hover:bg-emerald-700 active:scale-[0.98] disabled:opacity-40"
              >
                {batchSubmitting ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
                {batchSubmitting ? '批量审核中…' : `批量通过 ${effectiveSelectedIds.size} 条`}
              </button>
            )}
            {effectiveSelectedIds.size > 0 && approveEligible && (
              <button
                type="button"
                onClick={() => setReextractScope({ kind: 'batch', itemIds: [...effectiveSelectedIds] })}
                disabled={batchSubmitting || submitting}
                title="用不同提示词或大模型对选中条目重新提取"
                className={`${effectiveSelectedIds.size > 0 ? '' : 'ml-auto '}inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-40`}
              >
                <RefreshCw className="size-3.5" />
                批量重新提取 {effectiveSelectedIds.size} 条
              </button>
            )}
          </div>
        </div>

        {changeSet.items.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 px-3 py-12 text-center text-xs text-slate-400">
            当前没有可展示的待审规则
          </p>
        ) : visibleItems.length === 0 ? (
          <p className="px-4 py-12 text-center text-xs text-slate-400">当前筛选下没有候选知识</p>
        ) : (
          <div className="w-full overflow-auto max-h-[62vh]">
            <table className="w-full min-w-[1250px] border-collapse text-left text-xs">
              <thead className="sticky top-0 z-10 bg-white text-[11px] font-medium uppercase tracking-wider text-slate-400">
                <tr className="border-b border-slate-200">
                  <th scope="col" className="w-10 whitespace-nowrap px-3 py-2.5 text-left font-medium">
                    <input
                      type="checkbox"
                      aria-label={allSelectableChecked ? '取消全选' : '全选可审核项'}
                      checked={allSelectableChecked}
                      ref={(el) => {
                        if (el) el.indeterminate = !allSelectableChecked && effectiveSelectedIds.size > 0
                      }}
                      onChange={toggleSelectAll}
                      disabled={selectableIds.size === 0}
                      className="size-3.5 rounded border-slate-300 accent-emerald-600"
                    />
                  </th>
                  {tableColumns.map((field) => (
                    <th
                      key={field.code}
                      scope="col"
                      className={`whitespace-nowrap px-3 py-2.5 text-left font-medium ${field.kind === 'long' ? 'min-w-60' : 'min-w-28'}`}
                    >
                      {field.label}
                    </th>
                  ))}
                  <th scope="col" className="min-w-32 whitespace-nowrap px-3 py-2.5 text-left font-medium">置信度</th>
                  <th scope="col" className="min-w-44 whitespace-nowrap px-3 py-2.5 text-left font-medium">单条操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {unitGroups.map((group) => (
                  <>
                    {/* 分组标题行：按人群=人群名；按单元=条款路径+叶子原文 */}
                    <tr className="bg-slate-50/90">
                      <td colSpan={tableColumns.length + 3} className="px-4 py-2.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="inline-flex shrink-0 items-center gap-1 rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold text-slate-500 ring-1 ring-slate-200">
                            <FileText className="size-3 text-emerald-600" />
                            {group.items.length} 条候选
                          </span>
                          <span className="truncate text-[11px] font-medium text-slate-500" title={group.title}>
                            {group.title}
                          </span>
                        </div>
                        {group.subtitle && (
                          <p className="mt-1 text-[12px] leading-5 text-slate-800">
                            {group.subtitle}
                          </p>
                        )}
                      </td>
                    </tr>
                    {group.items.map((item) => (
                      <ReviewTableRow
                        key={item.item_id}
                        item={item}
                        columns={tableColumns}
                        unitPath={unitPathOf(changeSet, item.unit_id)}
                        review={itemReviews[item.item_id] ?? null}
                        reviewing={reviewingItemId === item.item_id}
                        selectable={selectableIds.has(item.item_id)}
                        selected={effectiveSelectedIds.has(item.item_id)}
                        batchSubmitting={batchSubmitting}
                        canReextract={approveEligible}
                        onToggleSelect={() => toggleSelect(item.item_id)}
                        onApprove={() => void reviewItem(item, 'approved')}
                        onReject={() => openItemReason(item, 'reject')}
                        onReturn={() => openItemReason(item, 'return')}
                        onReextract={() => setReextractScope({
                          kind: 'single',
                          itemId: item.item_id,
                          extractedFields: extractCandidateFieldCodes(item.after),
                        })}
                        onViewTrace={() => setTraceRuleId(
                          item.canonical_rule?.rule_id ?? item.rule_id
                        )}
                      />
                    ))}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <footer className="sticky bottom-3 flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-lg shadow-slate-200/50 backdrop-blur">
        <div className="mr-auto text-[11px] text-slate-500">
          <p className="font-medium text-slate-600">
            当前审核身份：{userId}{userId === 'demo' ? '（演示身份）' : ''}
          </p>
          <p className="mt-0.5">
            {!approveEligible
              ? changeSet?.status === 'APPROVED'
                ? '该变更集已审核通过，无法再次审核；如需上线请前往「发布管理」创建正式版本'
                : changeSet
                  ? `该变更集当前状态为「${statusLabel(changeSet.status)}」，无法执行审核动作`
                  : '当前变更集状态不允许审核'
              : candidateSetEmpty
                ? '候选集合为空，无法通过审核'
                : invalidCandidateCount > 0
                  ? invalidCandidateCount === 1
                    ? '存在 1 个候选快照异常/缺失，无法通过审核'
                    : `存在 ${invalidCandidateCount} 个候选快照异常/缺失，无法通过审核`
                  : highRisk
                    ? '存在高风险规则，需退回或拒绝后处理'
                    : pendingTasks.length > 0
                      ? `仍有 ${pendingTasks.length} 个风险项待处理`
                      : `已满足条件，点击「整批通过审核」将全部 ${changeSet.items.length} 条候选标记为通过，可进入发布管理创建正式版本`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => openReasonDialog('reject')}
          disabled={submitting || !returnOrRejectEligible}
          className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40"
        >
          <X className="size-3.5" />拒绝
        </button>
        <button
          type="button"
          onClick={() => openReasonDialog('return')}
          disabled={submitting || !returnOrRejectEligible}
          className="inline-flex items-center gap-1 rounded-lg border border-amber-300 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-40"
        >
          <RotateCcw className="size-3.5" />退回重新构建
        </button>
        <button
          type="button"
          onClick={() => void performLifecycle('approve')}
          disabled={approveBlocked}
          title="将本批全部候选知识一次性标记为审核通过，随后可在「发布管理」创建正式版本"
          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-emerald-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
          整批通过审核
        </button>
      </footer>

      <ItemReasonDialog
        itemReason={itemReason}
        reason={itemReasonText}
        reviewing={Boolean(reviewingItemId)}
        onReasonChange={setItemReasonText}
        onClose={() => {
          if (!reviewingItemId) setItemReason(null)
        }}
        onConfirm={() => void confirmItemReason()}
      />

      <ReasonDialog
        action={reasonAction}
        reason={reason}
        submitting={submitting}
        onReasonChange={setReason}
        onClose={() => {
          if (!submitting) setReasonAction(null)
        }}
        onConfirm={() => {
          if (reasonAction) void performLifecycle(reasonAction)
        }}
      />

      {reextractScope && (
        <ReextractConfigDialog
          changeSetId={changeSetId}
          scope={reextractScope}
          onClose={() => setReextractScope(null)}
          onComplete={() => {
            setReextractScope(null)
            setSelectedIds(new Set())
            void load()
          }}
        />
      )}

      <RuleTraceDrawer
        open={traceRuleId !== null}
        ruleId={traceRuleId}
        onOpenChange={(open) => { if (!open) setTraceRuleId(null) }}
      />
    </section>
  )
}

function unitPathOf(changeSet: KnowledgeChangeSet, unitId: string): string {
  const unit = changeSet.source_units.find((candidate) => candidate.unit_id === unitId)
  return unit ? unit.path.join(' / ') : unitId
}

function extractCandidateFieldCodes(after: Record<string, unknown> | null): string[] {
  // 从候选快照的 fields（field_code）提取已提取字段，供重提取诊断对比契约指标
  const fields = (after?.fields ?? []) as Array<{ field_code?: string; field_name?: string }>
  return fields.map((field) => field.field_code).filter((code): code is string => Boolean(code))
}

function ReviewTableRow({
  item,
  columns,
  unitPath,
  review,
  reviewing,
  selectable,
  selected,
  batchSubmitting,
  canReextract,
  onToggleSelect,
  onApprove,
  onReject,
  onReturn,
  onReextract,
  onViewTrace,
}: {
  item: ChangeSetItem
  columns: TableColumn[]
  unitPath: string
  review: ItemReviewKind | null
  reviewing: boolean
  selectable: boolean
  selected: boolean
  batchSubmitting: boolean
  canReextract: boolean
  onToggleSelect: () => void
  onApprove: () => void
  onReject: () => void
  onReturn: () => void
  onReextract: () => void
  onViewTrace: () => void
}) {
  const candidate = parseCandidateKnowledge(item)
  const invalid = candidate === null
  const confidence = candidate?.confidence.overall ?? null
  const uncertainties = candidate?.confidence.uncertainties ?? []

  // 行内字段值映射：候选字段优先，元字段（规则ID/政策/单元/条款/原文）从项上下文补全。
  const fieldValues: Record<string, string> = {}
  for (const field of candidate?.fields ?? []) {
    fieldValues[field.field_code] = structuredFieldValue(field.raw_value)
  }
  if (candidate) {
    fieldValues.rule_id = fieldValues.rule_id ?? item.rule_id
    fieldValues.policy_id = fieldValues.policy_id ?? item.doc_id
    fieldValues.fact_id = fieldValues.fact_id ?? candidate.unit_id
    fieldValues.unit = fieldValues.unit ?? unitPath
    fieldValues.clause_id = fieldValues.clause_id ?? unitPath
    fieldValues.source_text = fieldValues.source_text ?? candidate.source_text
    fieldValues.business_sentence = fieldValues.business_sentence ?? candidate.business_sentence
  }

  return (
    <tr className="align-top text-slate-700 transition-colors hover:bg-slate-50/70">
      <td className="px-3 py-3 text-left align-middle">
        {selectable && (
          <input
            type="checkbox"
            aria-label={selected ? '取消选择该条' : '选择该条'}
            checked={selected}
            onChange={onToggleSelect}
            disabled={batchSubmitting}
            className="size-3.5 rounded border-slate-300 accent-emerald-600"
          />
        )}
      </td>
      {columns.map((field) => {
        const value = fieldValues[field.code] ?? ''
        if (field.code === 'rule_id') {
          return (
            <td key={field.code} className="max-w-44 px-3 py-3">
              {invalid ? (
                <p role="alert" className="text-xs font-medium text-red-700">
                  候选快照异常/缺失：{item.change_type === 'EXPIRE' ? '失效项必须包含 before 快照' : `${item.change_type} 必须包含 after 快照`}
                </p>
              ) : (
                <div className="flex items-center gap-1.5">
                  <span className={`inline-flex shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${changeTypeStyle(item.change_type)}`}>
                    {changeTypeLabel(item.change_type)}
                  </span>
                  <span className="truncate font-mono text-[11px] text-slate-700" title={value}>{value}</span>
                </div>
              )}
            </td>
          )
        }
        return (
          <td
            key={field.code}
            className={`px-3 py-3 align-top text-left ${field.kind === 'long' ? 'max-w-60' : field.kind === 'id' ? 'max-w-44' : 'max-w-40'}`}
          >
            {value ? (
              <span
                className={`block truncate text-left text-[11px] leading-4 ${field.kind === 'id' ? 'font-mono text-slate-600' : field.kind === 'number' ? 'font-medium tabular-nums text-slate-700' : 'text-slate-600'}`}
                title={value}
              >
                {value}
              </span>
            ) : (
              <span className="text-slate-300">—</span>
            )}
          </td>
        )
      })}
      <td className="w-40 px-3 py-3">
        {confidence === null ? (
          <span className="text-xs text-slate-400">—</span>
        ) : (
          <div className="min-w-28">
            <div className="flex items-center justify-between gap-2">
              <span className={`font-semibold tabular-nums ${confidence < 0.3 ? 'text-red-600' : confidence < 0.6 ? 'text-amber-600' : 'text-slate-700'}`}>置信度 {Math.round(confidence * 100)}%</span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${confidence < 0.3 ? 'bg-red-400' : confidence < 0.6 ? 'bg-amber-400' : 'bg-emerald-500'}`} style={{ width: `${Math.round(confidence * 100)}%` }} />
            </div>
            <p className="mt-1 text-[10px] tabular-nums text-slate-400">原文一致 {formatScore(candidate?.confidence.source_fidelity ?? null)}</p>
            {uncertainties.length > 0 && (
              <p className="mt-1 line-clamp-1 text-[10px] text-amber-700" title={uncertainties.join('；')}>
                {uncertainties[0]}
              </p>
            )}
          </div>
        )}
      </td>
      <td className="px-3 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
        {review ? (
          <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-semibold ${reviewStyle(review)}`}>
            <Check className="size-3" />
            {review === 'approved' ? '已通过' : review === 'returned' ? '已退回' : '已拒绝'}
          </span>
        ) : invalid ? (
          <span className="text-[11px] text-slate-400">候选异常，仅可查看详情</span>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={reviewing}
              onClick={onApprove}
              title="单条通过：仅标记本行为已审核，不改变整批状态，也不会发布"
              className="rounded-md bg-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-white transition-all hover:bg-emerald-700 active:scale-[0.98] disabled:opacity-40"
            >
              {reviewing ? '处理中…' : '通过'}
            </button>
            <button
              type="button"
              disabled={reviewing}
              onClick={onReject}
              className="rounded-md border border-red-200 px-2.5 py-1.5 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:opacity-40"
            >
              拒绝
            </button>
            <button
              type="button"
              disabled={reviewing}
              onClick={onReturn}
              className="rounded-md border border-amber-300 px-2.5 py-1.5 text-[11px] font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-40"
            >
              退回
            </button>
            {canReextract && (
              <button
                type="button"
                disabled={reviewing}
                onClick={onReextract}
                title="重新提取：换提示词或大模型重提本条，重提后需重新审核"
                className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                <RefreshCw className="size-3" />重提取
              </button>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={onViewTrace}
          className="rounded-md border border-slate-300 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 hover:bg-slate-50"
        >
          查看溯源
        </button>
        </div>
      </td>
    </tr>
  )
}

function changeTypeLabel(type: ChangeItemType): string {
  return {
    ADD: '新增',
    MODIFY: '修改',
    REPLACE: '替代',
    EXPIRE: '失效',
    SEMANTIC_CHANGE: '语义调整',
  }[type] ?? type
}

function ColumnSettingsPanel({
  visibleCodes,
  labels,
  dominantRuleType,
  onToggle,
  onShowAll,
  onApplyPreset,
}: {
  visibleCodes: string[]
  labels: Record<string, string>
  dominantRuleType: string | undefined
  onToggle: (code: string) => void
  onShowAll: () => void
  onApplyPreset: (ruleType: string) => void
}) {
  const label = (code: string) => labels[code] ?? RULE_OBJECT_DEFAULT_LABELS[code] ?? code
  return (
    <div className="absolute right-0 top-full z-20 mt-1.5 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-[0_8px_24px_-8px_rgba(15,23,42,0.18)]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-slate-800">展示列</span>
        <button
          type="button"
          onClick={onShowAll}
          className="rounded-md px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-50"
        >
          全部显示
        </button>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <label className="text-[11px] text-slate-500">按规则类型预设</label>
        <select
          aria-label="按规则类型预设列"
          value={matchedPresetType(visibleCodes)}
          onChange={(event) => {
            const value = event.target.value
            if (value === '__all__') onShowAll()
            else if (value) onApplyPreset(value)
          }}
          className="h-7 flex-1 rounded-md border border-slate-200 bg-white px-1.5 text-[11px] outline-none focus:border-emerald-500"
        >
          <option value="">自定义（当前列组合无匹配预设）</option>
          {RULE_TYPE_PRESETS.map((preset) => (
            <option key={preset.type} value={preset.type}>{preset.type}类</option>
          ))}
          <option value="__all__">全部字段</option>
        </select>
      </div>
      <p className="mt-2 border-t border-slate-100 pt-2 text-[10px] text-slate-400">
        当前规则类型：{dominantRuleType ?? '未分类'}（无历史选择时按其预设展示）
      </p>
      <div className="mt-2 grid max-h-64 grid-cols-2 gap-x-2 gap-y-1 overflow-y-auto">
        {RULE_OBJECT_ORDER.map((code) => (
          <label key={code} className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-600">
            <input
              type="checkbox"
              checked={visibleCodes.includes(code)}
              onChange={() => onToggle(code)}
              className="size-3.5 rounded border-slate-300 accent-emerald-600"
            />
            <span className="truncate" title={label(code)}>{label(code)}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

/** 结构化字段值扁平化为可读文本（不输出 JSON），对象/数组递归展开。 */
function structuredFieldValue(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value.map((item) => structuredFieldValue(item)).filter(Boolean).join('、')
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const subject = record.subject
    const predicate = record.predicate
    const object = record.object
    if (subject != null || predicate != null || object != null) {
      return [subject, predicate, object].filter((part) => part != null && part !== '').join('')
    }
    for (const key of ['name', 'value', 'text']) {
      const primary = record[key]
      if (primary != null && primary !== '') return structuredFieldValue(primary)
    }
    const parts = Object.entries(record)
      .filter(([key, item]) => item != null && item !== '' && key !== 'highlight')
      .map(([key, item]) => `${key} ${structuredFieldValue(item)}`)
    return parts.join('，')
  }
  return String(value)
}

function changeTypeStyle(type: ChangeItemType): string {
  return {
    ADD: 'bg-emerald-50 text-emerald-700',
    MODIFY: 'bg-amber-50 text-amber-700',
    REPLACE: 'bg-sky-50 text-sky-700',
    EXPIRE: 'bg-red-50 text-red-700',
    SEMANTIC_CHANGE: 'bg-violet-50 text-violet-700',
  }[type] ?? 'bg-slate-100 text-slate-600'
}

function reviewStyle(review: ItemReviewKind): string {
  if (review === 'approved') return 'bg-emerald-50 text-emerald-700'
  if (review === 'returned') return 'bg-amber-50 text-amber-700'
  return 'bg-red-50 text-red-700'
}

function DecisionIssues({
  tasks,
  expandedTasks,
  resolvingTaskId,
  onToggle,
  onResolve,
}: {
  tasks: DecisionTask[]
  expandedTasks: Set<string>
  resolvingTaskId: string | null
  onToggle: (taskId: string) => void
  onResolve: (task: DecisionTask, action: 'accept_recommendation' | 'skip') => void
}) {
  return (
    <section aria-labelledby="review-issues-title" className="rounded-2xl border border-amber-200 bg-amber-50/40 p-4">
      <div className="flex items-center gap-2">
        <AlertTriangle className="size-4 text-amber-600" />
        <h3 id="review-issues-title" className="text-sm font-semibold text-slate-900">需人工确认的风险项</h3>
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
          {tasks.filter((task) => task.status === 'PENDING').length} 项待处理
        </span>
      </div>
      <p className="mt-1.5 text-[11px] leading-4 text-slate-500">
        系统自动检测出证据缺失、值域未映射、低置信的规则，需逐条确认；未处理完将阻断整批通过。
      </p>

      {tasks.length === 0 ? (
        <p className="mt-3 text-xs text-slate-500">未检测到证据缺失、值域未映射或低置信规则，可直接通过审核。</p>
      ) : (
        <div className="mt-3 space-y-2">
          {tasks.map((task) => {
            const pending = task.status === 'PENDING'
            const skipped = task.status === 'SKIPPED'
              || (task.status === 'RESOLVED' && task.decision?.action === 'skip')
            const expanded = expandedTasks.has(task.task_id)
            const ruleId = typeof task.evidence.rule_id === 'string' ? task.evidence.rule_id : ''
            return (
              <article key={task.task_id} className="rounded-xl border border-amber-100 bg-white p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${riskStyle(task.risk_level)}`}>
                    {riskLabel(task.risk_level)}风险
                  </span>
                  <span className="font-mono text-[10px] text-slate-400">{task.task_id}</span>
                  <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] ${pending ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>
                    {pending ? '待处理' : skipped ? '已跳过' : '已处理'}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium text-slate-800">{task.question}</p>
                <p className="mt-1 text-xs text-emerald-700">
                  建议：{readableValue(task.recommended_option.detail ?? task.recommended_option.action)}
                </p>
                {expanded && (
                  <div className="mt-2 space-y-1 rounded-lg bg-slate-50 p-2 text-[11px] text-slate-600">
                    {task.alternatives.length > 0
                      ? task.alternatives.map((option, index) => (
                        <p key={index}>候选 {String.fromCharCode(65 + index)}：{readableValue(option.detail ?? option.action)}</p>
                      ))
                      : <p>当前没有其他候选方案</p>}
                  </div>
                )}
                <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2">
                  <button
                    type="button"
                    disabled={!pending || Boolean(resolvingTaskId)}
                    onClick={() => onResolve(task, 'accept_recommendation')}
                    className="rounded-md bg-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-emerald-700 disabled:opacity-40"
                  >
                    {resolvingTaskId === task.task_id ? '处理中…' : '接受建议'}
                  </button>
                  <button
                    type="button"
                    disabled={!pending || Boolean(resolvingTaskId)}
                    onClick={() => onResolve(task, 'skip')}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                  >
                    <SkipForward className="size-3" />跳过
                  </button>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => onToggle(task.task_id)}
                    className="rounded-md border border-slate-200 px-2.5 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"
                  >
                    查看候选
                  </button>
                  {ruleId ? (
                    <span className="ml-auto font-mono text-[10px] text-slate-400" title="关联规则ID">
                      {ruleId}
                    </span>
                  ) : (
                    <span className="ml-auto text-[11px] text-slate-400">暂无规则上下文</span>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function ItemReasonDialog({
  itemReason,
  reason,
  reviewing,
  onReasonChange,
  onClose,
  onConfirm,
}: {
  itemReason: { itemId: string; action: 'reject' | 'return' } | null
  reason: string
  reviewing: boolean
  onReasonChange: (reason: string) => void
  onClose: () => void
  onConfirm: () => void
}) {
  const isReturn = itemReason?.action === 'return'
  const title = isReturn ? '退回该条知识' : '拒绝该条知识'
  const fieldLabel = isReturn ? '退回原因（将记录为拒绝并建议重新提取）' : '拒绝原因'
  return (
    <Dialog open={itemReason !== null} onOpenChange={(open) => {
      if (!open && !reviewing) onClose()
    }}>
      <DialogContent aria-label={title} showCloseButton={!reviewing}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            单条审核意见将随来源可追溯地落库，不影响整批状态流转。
          </DialogDescription>
        </DialogHeader>
        <label className="space-y-1 text-xs font-medium text-slate-700">
          <span>{fieldLabel}</span>
          <textarea
            aria-label={fieldLabel}
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            disabled={reviewing}
            rows={4}
            className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-emerald-500 disabled:opacity-60"
          />
        </label>
        <DialogFooter>
          <button
            type="button"
            onClick={onClose}
            disabled={reviewing}
            className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 disabled:opacity-40"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={reviewing || !reason.trim()}
            className={`rounded-lg px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 ${isReturn ? 'bg-amber-600' : 'bg-red-600'}`}
          >
            {reviewing ? '提交中…' : isReturn ? '确认退回' : '确认拒绝'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ReasonDialog({
  action,
  reason,
  submitting,
  onReasonChange,
  onClose,
  onConfirm,
}: {
  action: ReasonAction | null
  reason: string
  submitting: boolean
  onReasonChange: (reason: string) => void
  onClose: () => void
  onConfirm: () => void
}) {
  const isReturn = action === 'return'
  const title = isReturn ? '退回重新构建' : '拒绝'
  const fieldLabel = isReturn ? '退回原因' : '拒绝原因'
  return (
    <Dialog open={action !== null} onOpenChange={(open) => {
      if (!open && !submitting) onClose()
    }}>
      <DialogContent aria-label={title} showCloseButton={!submitting}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            原因将随审核结论保存，构建人员可据此处理。
          </DialogDescription>
        </DialogHeader>
        <label className="space-y-1 text-xs font-medium text-slate-700">
          <span>{fieldLabel}</span>
          <textarea
            aria-label={fieldLabel}
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            disabled={submitting}
            rows={4}
            className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-emerald-500 disabled:opacity-60"
          />
        </label>
        <DialogFooter>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 disabled:opacity-40"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={submitting || !reason.trim()}
            className={`rounded-lg px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 ${isReturn ? 'bg-amber-600' : 'bg-red-600'}`}
          >
            {submitting ? '提交中…' : isReturn ? '确认退回' : '确认拒绝'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function parseCandidateKnowledge(item: ChangeSetItem | null): KnowledgeItem | null {
  const snapshot = item?.change_type === 'EXPIRE' ? item.before : item?.after
  return isKnowledgeItem(snapshot) ? snapshot : null
}

function isKnowledgeItem(value: unknown): value is KnowledgeItem {
  if (!isRecord(value)) return false
  if (!isNonEmptyString(value.knowledge_id)) return false
  if (!isNonEmptyString(value.unit_id)) return false
  if (typeof value.extraction_id !== 'string') return false
  if (value.relationship_source !== 'persisted' && value.relationship_source !== 'legacy_match') return false
  if (!isNonEmptyString(value.business_sentence)) return false
  if (!isNonEmptyString(value.source_text)) return false
  if (!Array.isArray(value.fields) || !value.fields.every(isKnowledgeField)) return false
  if (!Array.isArray(value.standardized_fields) || !value.standardized_fields.every(isStandardizedField)) return false
  if (!isConfidence(value.confidence)) return false
  if (!Array.isArray(value.citations) || !value.citations.every(isCitation)) return false
  if (value.evidences !== undefined && (!Array.isArray(value.evidences) || !value.evidences.every(isEvidence))) return false
  if (value.semantic_bindings !== undefined && (!Array.isArray(value.semantic_bindings) || !value.semantic_bindings.every(isSemanticBinding))) return false
  return true
}

function isKnowledgeField(value: unknown): value is KnowledgeItem['fields'][number] {
  return isRecord(value)
    && isNonEmptyString(value.field_code)
    && typeof value.field_name === 'string'
    && 'raw_value' in value
}

function isStandardizedField(value: unknown): value is KnowledgeItem['standardized_fields'][number] {
  return isRecord(value)
    && isNonEmptyString(value.source_field)
    && 'source_value' in value
    && isNonEmptyString(value.status)
    && isNullableString(value.metric_code)
    && isNullableString(value.metric_name)
    && isNullableString(value.value_domain)
    && 'standard_value' in value
    && isNullableString(value.binding_id)
}

function isConfidence(value: unknown): value is KnowledgeItem['confidence'] {
  return isRecord(value)
    && isFiniteNumber(value.completeness)
    && isNullableFiniteNumber(value.accuracy)
    && isFiniteNumber(value.source_fidelity)
    && isFiniteNumber(value.model_confidence)
    && isNullableFiniteNumber(value.value_domain_compliance)
    && isFiniteNumber(value.overall)
    && Array.isArray(value.uncertainties)
    && value.uncertainties.every((item) => typeof item === 'string')
}

function isCitation(value: unknown): value is KnowledgeItem['citations'][number] {
  return isRecord(value) && isNonEmptyString(value.evidence) && isNonEmptyString(value.title)
}

function isEvidence(value: unknown): boolean {
  return isRecord(value)
    && isNonEmptyString(value.evidence_id)
    && isNonEmptyString(value.document_version_id)
    && isNonEmptyString(value.unit_id)
    && isNullableString(value.clause_path)
    && (value.page_no === null || isFiniteNumber(value.page_no))
    && isNonEmptyString(value.exact_quote)
    && (value.start_offset === null || isFiniteNumber(value.start_offset))
    && (value.end_offset === null || isFiniteNumber(value.end_offset))
    && isNonEmptyString(value.evidence_role)
}

function isSemanticBinding(value: unknown): boolean {
  return isRecord(value)
    && isNonEmptyString(value.policy_field)
    && isNullableString(value.semantic_field)
    && isNullableString(value.concept)
    && isNullableString(value.value_domain)
    && isNonEmptyString(value.status)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value)
}

function readableValue(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try { return JSON.stringify(value) } catch { return String(value) }
}

function formatScore(value: number | null): string {
  return value == null ? '暂无统计' : `${Math.round(value * 100)}%`
}

function riskLabel(level: RiskLevel): string {
  if (level === 'CRITICAL') return '重大'
  if (level === 'HIGH') return '高'
  if (level === 'MEDIUM') return '中'
  return '低'
}

function riskStyle(level: RiskLevel): string {
  if (level === 'CRITICAL' || level === 'HIGH') return 'bg-red-50 text-red-700'
  if (level === 'MEDIUM') return 'bg-amber-50 text-amber-700'
  return 'bg-slate-100 text-slate-600'
}

function statusLabel(status: KnowledgeChangeSet['status']): string {
  const labels: Record<KnowledgeChangeSet['status'], string> = {
    DRAFT: '构建草稿',
    NEEDS_DECISION: '存在待处理问题',
    PENDING_REVIEW: '等待审核',
    APPROVED: '审核通过',
    REJECTED: '已拒绝',
    RETURNED: '已退回',
    PUBLISHED: '已发布',
    FAILED: '构建失败',
  }
  return labels[status]
}
