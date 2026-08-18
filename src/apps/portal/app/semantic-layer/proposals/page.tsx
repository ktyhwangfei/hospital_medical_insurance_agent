'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  acceptSemanticProposal,
  listSemanticProposals,
  publishSemanticProposal,
  rejectSemanticProposal,
  resolveDimensionProposal,
  reviewSemanticProposal,
  type DimensionReviewConclusion,
  type SemanticProposal,
  type SemanticProposalEvidence,
  type SemanticProposalStatus,
  type SemanticProposalType,
} from '@/lib/policy-knowledge-api'

const ACTIVE_STATUSES = new Set<SemanticProposalStatus>(['proposed', 'reviewing', 'accepted'])

const TYPE_LABELS: Record<SemanticProposalType, string> = {
  metric: '指标提议',
  value: '值域提议',
  dimension: '维度候选',
}

const TYPE_FILTERS: Array<{ key: SemanticProposalType | 'all'; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'metric', label: '只看指标提议' },
  { key: 'value', label: '只看值域提议' },
  { key: 'dimension', label: '只看维度候选' },
]

const STATUS_LABELS: Record<SemanticProposalStatus, string> = {
  proposed: '待审核',
  reviewing: '审核中',
  accepted: '已通过',
  published: '已发布',
  rejected: '已驳回',
  stale: '已失效',
  superseded: '已替代',
}

const TRIGGER_LABELS: Record<SemanticProposal['trigger_source'], string> = {
  EXTRACTION_UNKNOWN: '政策抽取未知概念',
  DEMAND_GAP: '问答需求缺口',
  DATA_SCAN: '数据扫描',
  DERIVATION_PATTERN: '派生模式',
  CONFLICT_PARTITION: '规则冲突诊断',
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

function proposalLabel(proposal: SemanticProposal): string {
  return proposal.metric_draft?.metric_code
    ?? proposal.value_draft?.standard_value
    ?? proposal.dimension_candidate?.suggested_code
    ?? proposal.concept
}

function DimensionEvidence({ proposal }: { proposal: SemanticProposal }) {
  const candidate = proposal.dimension_candidate
  if (!candidate) return null
  const evidence = candidate.evidence
  return (
    <div className="space-y-4 rounded-lg border border-blue-100 bg-blue-50/40 p-4 text-sm">
      <section aria-label="冲突来源" className="space-y-2">
        <h3 className="font-medium text-slate-900">冲突来源</h3>
        <dl className="grid gap-2 text-xs">
          <div><dt className="text-slate-500">已知身份</dt><dd>{Object.entries(evidence.identity_signature.known_values).map(([key, value]) => `${key}=${value}`).join('；') || '无'}</dd></div>
          <div><dt className="text-slate-500">未知身份字段</dt><dd>{evidence.unknown_identity_fields.join('；') || '无'}</dd></div>
          <div><dt className="text-slate-500">冲突值</dt><dd>{evidence.conflict_values.map((value) => `${value.raw_value} → ${value.canonical_value}`).join('；')}</dd></div>
          <div><dt className="text-slate-500">规则 / 条款</dt><dd>{evidence.rule_ids.join('、')} / {evidence.source_clause_ids.join('、')}</dd></div>
          <div><dt className="text-slate-500">抽取快照</dt><dd className="break-all">{evidence.extraction_snapshot_id} · {evidence.extraction_contract_version}</dd></div>
        </dl>
        {evidence.evidence_texts.map((text, index) => <blockquote key={`${index}-${text}`} className="border-l-2 border-blue-300 pl-3 text-slate-700">{text}</blockquote>)}
      </section>
      <section aria-label="候选分区映射" className="overflow-x-auto">
        <h3 className="mb-2 font-medium text-slate-900">为何怀疑缺少维度</h3>
        <table className="w-full border-collapse text-left text-xs">
          <thead><tr className="border-b border-blue-200 text-slate-500"><th className="py-2 pr-3">候选值</th><th className="py-2 pr-3">对应规则值</th><th className="py-2">规则</th></tr></thead>
          <tbody>{evidence.partition_mappings.map((mapping) => (
            <tr key={mapping.canonical_phrase} className="border-b border-blue-100 last:border-0">
              <td className="py-2 pr-3">{mapping.display_phrase}</td>
              <td className="py-2 pr-3 font-mono">{mapping.canonical_value}</td>
              <td className="py-2">{mapping.rule_ids.join('、')}</td>
            </tr>
          ))}</tbody>
        </table>
      </section>
      <div className="flex flex-wrap gap-2 text-xs text-slate-700">
        <Badge variant="outline">覆盖率 {Math.round(Number(evidence.coverage) * 100)}%</Badge>
        <Badge variant="outline">排他性 {Math.round(Number(evidence.exclusivity) * 100)}%</Badge>
        <Badge variant="outline">{candidate.evidence_grade === 'single_observation' ? '单次观测证据' : '文档内重复证据'}</Badge>
        {evidence.competing_axis_candidates.length > 0 && <Badge variant="destructive">竞争分区 {evidence.competing_axis_candidates.join('、')}</Badge>}
      </div>
    </div>
  )
}

function Evidence({ evidence }: { evidence: SemanticProposalEvidence }) {
  const fields: Array<[string, string | number | undefined | null]> = [
    ['来源引用', evidence.source_ref],
    ['文档', evidence.doc_id],
    ['规则单元', evidence.unit_id],
    ['抽取记录', evidence.extraction_id],
    ['需求缺口', evidence.gap_signature],
    ['数据表', evidence.table_name],
    ['字段', evidence.field_name],
    ['非空率', evidence.non_null_rate],
    ['不同值数', evidence.distinct_count],
    ['基础指标', evidence.base_metric_code],
    ['算子', evidence.operator],
  ]
  const lists: Array<[string, string[] | undefined]> = [
    ['代表问题', evidence.representative_questions],
    ['样例值', evidence.sample_values],
    ['观测', evidence.observations],
    ['规则', evidence.rule_ids],
  ]

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      {evidence.excerpt && <blockquote className="mb-3 text-sm leading-6 text-slate-800">{evidence.excerpt}</blockquote>}
      <dl className="grid gap-y-2 text-xs">
        {fields.filter(([, value]) => value !== null && value !== undefined && value !== '').map(([label, value]) => (
          <div key={label} className="grid grid-cols-[5rem_1fr] gap-2">
            <dt className="text-slate-500">{label}</dt>
            <dd className="break-all text-slate-700">{String(value)}</dd>
          </div>
        ))}
        {lists.filter(([, values]) => values?.length).map(([label, values]) => (
          <div key={label} className="grid grid-cols-[5rem_1fr] gap-2">
            <dt className="text-slate-500">{label}</dt>
            <dd className="text-slate-700">{values?.join('；')}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

interface ProposalCardProps {
  proposal: SemanticProposal
  expanded: boolean
  pending: boolean
  rejecting: boolean
  rejectReason: string
  onToggle: () => void
  onAccept: () => void
  onRejectStart: () => void
  onRejectCancel: () => void
  onRejectReasonChange: (value: string) => void
  onReject: () => void
  onResolve: (
    conclusion: DimensionReviewConclusion,
    suggestedName: string,
    suggestedCode: string,
    reason: string,
  ) => void
}

function ProposalCard({
  proposal,
  expanded,
  pending,
  rejecting,
  rejectReason,
  onToggle,
  onAccept,
  onRejectStart,
  onRejectCancel,
  onRejectReasonChange,
  onReject,
  onResolve,
}: ProposalCardProps) {
  const candidate = proposal.dimension_candidate
  const [conclusion, setConclusion] = useState<DimensionReviewConclusion | ''>('')
  const [suggestedName, setSuggestedName] = useState(candidate?.suggested_name ?? '')
  const [suggestedCode, setSuggestedCode] = useState(candidate?.suggested_code ?? '')
  const [resolutionReason, setResolutionReason] = useState('')
  const label = proposalLabel(proposal)
  const terminal = ['published', 'rejected', 'stale', 'superseded'].includes(proposal.status)
  const evidenceSummary = proposal.evidence[0]?.excerpt
    ?? proposal.value_draft?.evidence
    ?? '已记录结构化来源证据'

  return (
    <Card className="border border-slate-200 bg-white/90 shadow-sm hover:shadow-sm">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={proposal.proposal_type === 'dimension' ? 'default' : proposal.proposal_type === 'metric' ? 'secondary' : 'outline'}>
            {TYPE_LABELS[proposal.proposal_type]}
          </Badge>
          <Badge variant="outline">{TRIGGER_LABELS[proposal.trigger_source]}</Badge>
          <span className="text-xs text-slate-500">出现 {proposal.occurrence_count} 次</span>
          <span className="text-xs text-slate-500">可信度 {Math.round(proposal.confidence * 100)}%</span>
        </div>
        <CardTitle className="mt-2 text-slate-900">
          {proposal.proposal_type === 'metric' ? proposal.metric_draft?.name : candidate?.suggested_name ?? proposal.concept}
        </CardTitle>
        <CardAction>
          <Badge variant={proposal.status === 'rejected' ? 'destructive' : 'secondary'}>
            {STATUS_LABELS[proposal.status]}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        {proposal.proposal_type === 'metric' ? (
          <div className="grid gap-2 text-sm">
            <p><span className="text-slate-500">建议代号：</span><code className="font-medium text-blue-700">{label}</code></p>
            <p><span className="text-slate-500">语义类型：</span>{proposal.metric_draft?.semantic_type ?? '待确认'}</p>
          </div>
        ) : proposal.proposal_type === 'value' ? (
          <div className="grid gap-2 text-sm">
            <p><span className="text-slate-500">所属值域：</span><code className="font-medium text-blue-700">{proposal.value_draft?.domain_code}</code></p>
            <p><span className="text-slate-500">建议标准值：</span>{proposal.value_draft?.standard_value}</p>
            {proposal.suggested_mappings.map((mapping) => (
              <p key={`${mapping.binding_id}-${mapping.source_value}`}>
                <span className="text-slate-500">建议映射：</span>{mapping.source_value} → {mapping.standard_value}
              </p>
            ))}
          </div>
        ) : (
          <div className="grid gap-2 text-sm">
            <p><span className="text-slate-500">建议维度：</span><code className="font-medium text-blue-700">{candidate?.suggested_code ?? '待命名'}</code></p>
            <div className="flex flex-wrap items-center gap-1"><span className="text-slate-500">候选值：</span>{candidate?.candidate_values.map((value) => <Badge key={value.code ?? value.label} variant="outline">{value.label}</Badge>)}</div>
          </div>
        )}
        <p className="line-clamp-2 text-sm leading-6 text-slate-600">{evidenceSummary}</p>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-expanded={expanded}
          aria-label={`${expanded ? '收起' : '展开'} ${label} 证据`}
          onClick={onToggle}
          disabled={pending}
        >
          {expanded ? <ChevronUp /> : <ChevronDown />}
          {expanded ? '收起证据' : `展开证据 (${proposal.evidence.length})`}
        </Button>
        {expanded && (
          <section aria-label={`${label} 证据详情`} className="space-y-2">
            {proposal.proposal_type === 'dimension'
              ? <DimensionEvidence proposal={proposal} />
              : proposal.evidence.map((evidence) => <Evidence key={evidence.source_ref} evidence={evidence} />)}
          </section>
        )}
        {rejecting && proposal.proposal_type !== 'dimension' && (
          <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3">
            <label htmlFor={`reject-${proposal.proposal_id}`} className="block text-sm font-medium text-red-900">
              驳回原因 {label}
            </label>
            <Input
              id={`reject-${proposal.proposal_id}`}
              value={rejectReason}
              onChange={(event) => onRejectReasonChange(event.target.value)}
              placeholder="请说明概念重复或证据不足等原因"
              disabled={pending}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="destructive"
                size="sm"
                aria-label={`确认驳回 ${label}`}
                disabled={pending || !rejectReason.trim()}
                onClick={onReject}
              >
                确认驳回
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={onRejectCancel} disabled={pending}>取消</Button>
            </div>
          </div>
        )}
      </CardContent>
      {!terminal && !rejecting && (
        proposal.proposal_type === 'dimension' ? (
          <CardFooter className="grid gap-3 border-t border-slate-100 bg-slate-50/60 py-4">
            <label className="grid gap-1 text-xs text-slate-600">
              建模结论 {label}
              <select
                aria-label={`建模结论 ${label}`}
                value={conclusion}
                onChange={(event) => setConclusion(event.target.value as DimensionReviewConclusion)}
                className="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900"
                disabled={pending}
              >
                <option value="">请选择</option>
                <option value="new_dimension">新增维度</option>
                <option value="metric_split_required">应拆分指标</option>
                <option value="temporal_version">时间版本差异</option>
                <option value="value_normalization">值归一化问题</option>
                <option value="extraction_incomplete">抽取不完整</option>
                <option value="insufficient_evidence">证据不足</option>
                <option value="rejected">驳回候选</option>
              </select>
            </label>
            <label className="grid gap-1 text-xs text-slate-600">审核说明<Input value={resolutionReason} onChange={(event) => setResolutionReason(event.target.value)} disabled={pending} /></label>
            {conclusion === 'new_dimension' && <>
              <label className="grid gap-1 text-xs text-slate-600">维度名称<Input value={suggestedName} onChange={(event) => setSuggestedName(event.target.value)} disabled={pending} /></label>
              <label className="grid gap-1 text-xs text-slate-600">维度 code<Input value={suggestedCode} onChange={(event) => setSuggestedCode(event.target.value)} disabled={pending} /></label>
            </>}
            <Button
              type="button"
              className="justify-self-end"
              aria-label={`提交建模结论 ${label}`}
              disabled={pending || !conclusion || (conclusion === 'new_dimension' && (!suggestedName.trim() || !suggestedCode.trim()))}
              onClick={() => conclusion && onResolve(conclusion, suggestedName, suggestedCode, resolutionReason)}
            >
              {pending ? '处理中…' : '提交建模结论'}
            </Button>
          </CardFooter>
        ) : (
          <CardFooter className="justify-end gap-2">
            <Button type="button" variant="outline" aria-label={`驳回 ${label}`} onClick={onRejectStart} disabled={pending}>驳回</Button>
            <Button type="button" aria-label={`通过并发布 ${label}`} onClick={onAccept} disabled={pending}>
              {pending ? '处理中…' : '通过并发布'}
            </Button>
          </CardFooter>
        )
      )}
    </Card>
  )
}

export default function SemanticProposalsPage() {
  const [typeFilter, setTypeFilter] = useState<SemanticProposalType | 'all'>('all')
  const [proposals, setProposals] = useState<SemanticProposal[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [success, setSuccess] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([
      listSemanticProposals('metric'),
      listSemanticProposals('value'),
      listSemanticProposals('dimension'),
    ])
      .then(([metrics, values, dimensions]) => {
        if (!cancelled) {
          // 统一审核队列：三类提议合并后按更新时间倒序，不按类型拆分
          setProposals(
            [...metrics, ...values, ...dimensions]
              .filter((item) => ACTIVE_STATUSES.has(item.status))
              .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
          )
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(errorMessage(error))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const updateProposal = (proposal: SemanticProposal) => {
    setProposals((current) => current.map((item) => item.proposal_id === proposal.proposal_id ? proposal : item))
  }

  const beginMutation = (proposalId: string) => {
    setPendingId(proposalId)
    setActionError('')
    setSuccess('')
  }

  const ensureReviewing = async (proposal: SemanticProposal) => {
    if (proposal.status !== 'proposed') return proposal
    const reviewed = await reviewSemanticProposal(proposal.proposal_id)
    updateProposal(reviewed)
    return reviewed
  }

  const toggleEvidence = async (proposal: SemanticProposal) => {
    const opening = !expanded.has(proposal.proposal_id)
    setExpanded((current) => {
      const next = new Set(current)
      if (opening) next.add(proposal.proposal_id)
      else next.delete(proposal.proposal_id)
      return next
    })
    if (!opening || proposal.status !== 'proposed') return
    beginMutation(proposal.proposal_id)
    try {
      await ensureReviewing(proposal)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setPendingId(null)
    }
  }

  const acceptAndPublish = async (proposal: SemanticProposal) => {
    beginMutation(proposal.proposal_id)
    try {
      let current = await ensureReviewing(proposal)
      if (current.status === 'reviewing') {
        current = await acceptSemanticProposal(current.proposal_id)
        updateProposal(current)
      }
      const published = await publishSemanticProposal(current.proposal_id)
      updateProposal(published)
      setSuccess(`${proposalLabel(proposal)} 已通过并发布`)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setPendingId(null)
    }
  }

  const reject = async (proposal: SemanticProposal) => {
    if (!rejectReason.trim()) return
    beginMutation(proposal.proposal_id)
    try {
      const current = await ensureReviewing(proposal)
      const rejected = await rejectSemanticProposal(current.proposal_id, rejectReason)
      updateProposal(rejected)
      setRejectingId(null)
      setRejectReason('')
      setSuccess(`${proposalLabel(proposal)} 已驳回`)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setPendingId(null)
    }
  }

  const resolveDimension = async (
    proposal: SemanticProposal,
    conclusion: DimensionReviewConclusion,
    suggestedName: string,
    suggestedCode: string,
    reason: string,
  ) => {
    beginMutation(proposal.proposal_id)
    try {
      const resolved = await resolveDimensionProposal(proposal.proposal_id, {
        conclusion,
        suggested_name: suggestedName.trim(),
        suggested_code: suggestedCode.trim(),
        reason: reason.trim(),
      })
      updateProposal(resolved)
      setSuccess(`${proposalLabel(proposal)} 建模结论已提交`)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setPendingId(null)
    }
  }

  const visible = typeFilter === 'all'
    ? proposals
    : proposals.filter((proposal) => proposal.proposal_type === typeFilter)
  const countByType = proposals.reduce<Record<string, number>>((acc, proposal) => {
    acc[proposal.proposal_type] = (acc[proposal.proposal_type] ?? 0) + 1
    return acc
  }, {})

  if (loading) {
    return (
      <div aria-live="polite" className="space-y-3 py-4">
        <p className="text-sm text-slate-600">正在加载提议…</p>
        {[0, 1].map((item) => <div key={item} className="h-32 animate-pulse rounded-xl bg-slate-200/70" />)}
      </div>
    )
  }

  if (loadError) {
    return <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{loadError}</div>
  }

  return (
    <div className="space-y-4 pb-8">
      {actionError && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{actionError}</div>}
      {success && (
        <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          <span>{success}</span>
          <Link className="underline underline-offset-2 hover:text-emerald-900" href="/semantic-layer">去语义层查看</Link>
          <Link className="underline underline-offset-2 hover:text-emerald-900" href="/policy-knowledge/knowledge/build">去重新抽取</Link>
        </div>
      )}
      <div role="group" aria-label="提议类型筛选" className="flex flex-wrap items-center gap-2">
        {TYPE_FILTERS.map(({ key, label }) => {
          const active = typeFilter === key
          const count = key === 'all' ? proposals.length : countByType[key] ?? 0
          return (
            <Button
              key={key}
              type="button"
              size="sm"
              variant={active ? 'default' : 'outline'}
              aria-pressed={active}
              onClick={() => setTypeFilter(key)}
            >
              {`${label}（${count}）`}
            </Button>
          )
        })}
      </div>
      {visible.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white/60 px-6 py-12 text-center text-sm text-slate-600">
          暂无待审核提议
        </div>
      ) : (
        <div aria-label="语义提议统一列表" className="space-y-3">
          {visible.map((proposal) => (
            <ProposalCard
              key={proposal.proposal_id}
              proposal={proposal}
              expanded={expanded.has(proposal.proposal_id)}
              pending={pendingId === proposal.proposal_id}
              rejecting={rejectingId === proposal.proposal_id}
              rejectReason={rejectingId === proposal.proposal_id ? rejectReason : ''}
              onToggle={() => void toggleEvidence(proposal)}
              onAccept={() => void acceptAndPublish(proposal)}
              onRejectStart={() => { setRejectingId(proposal.proposal_id); setRejectReason(''); setActionError('') }}
              onRejectCancel={() => { setRejectingId(null); setRejectReason('') }}
              onRejectReasonChange={setRejectReason}
              onReject={() => void reject(proposal)}
              onResolve={(conclusion, name, code, reason) => void resolveDimension(proposal, conclusion, name, code, reason)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
