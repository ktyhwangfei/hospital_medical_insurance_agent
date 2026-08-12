'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  acceptSemanticProposal,
  listSemanticProposals,
  publishSemanticProposal,
  rejectSemanticProposal,
  reviewSemanticProposal,
  type SemanticProposal,
  type SemanticProposalEvidence,
  type SemanticProposalStatus,
  type SemanticProposalType,
} from '@/lib/policy-knowledge-api'

const ACTIVE_STATUSES = new Set<SemanticProposalStatus>(['proposed', 'reviewing', 'accepted'])

const STATUS_LABELS: Record<SemanticProposalStatus, string> = {
  proposed: '待审核',
  reviewing: '审核中',
  accepted: '已通过',
  published: '已发布',
  rejected: '已驳回',
}

const TRIGGER_LABELS: Record<SemanticProposal['trigger_source'], string> = {
  EXTRACTION_UNKNOWN: '政策抽取未知概念',
  DEMAND_GAP: '问答需求缺口',
  DATA_SCAN: '数据扫描',
  DERIVATION_PATTERN: '派生模式',
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

function proposalLabel(proposal: SemanticProposal): string {
  return proposal.metric_draft?.metric_code
    ?? proposal.value_draft?.standard_value
    ?? proposal.concept
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
      <dl className="grid gap-x-5 gap-y-2 text-xs sm:grid-cols-2">
        {fields.filter(([, value]) => value !== null && value !== undefined && value !== '').map(([label, value]) => (
          <div key={label} className="grid grid-cols-[5rem_1fr] gap-2">
            <dt className="text-slate-500">{label}</dt>
            <dd className="break-all text-slate-700">{String(value)}</dd>
          </div>
        ))}
        {lists.filter(([, values]) => values?.length).map(([label, values]) => (
          <div key={label} className="grid grid-cols-[5rem_1fr] gap-2 sm:col-span-2">
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
}: ProposalCardProps) {
  const label = proposalLabel(proposal)
  const terminal = proposal.status === 'published' || proposal.status === 'rejected'
  const evidenceSummary = proposal.evidence[0]?.excerpt
    ?? proposal.value_draft?.evidence
    ?? '已记录结构化来源证据'

  return (
    <Card className="border border-slate-200 bg-white/90 shadow-sm hover:shadow-sm">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{TRIGGER_LABELS[proposal.trigger_source]}</Badge>
          <span className="text-xs text-slate-500">出现 {proposal.occurrence_count} 次</span>
          <span className="text-xs text-slate-500">可信度 {Math.round(proposal.confidence * 100)}%</span>
        </div>
        <CardTitle className="mt-2 text-slate-900">
          {proposal.proposal_type === 'metric' ? proposal.metric_draft?.name : proposal.concept}
        </CardTitle>
        <CardAction>
          <Badge variant={proposal.status === 'rejected' ? 'destructive' : 'secondary'}>
            {STATUS_LABELS[proposal.status]}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        {proposal.proposal_type === 'metric' ? (
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <p><span className="text-slate-500">建议代号：</span><code className="font-medium text-blue-700">{label}</code></p>
            <p><span className="text-slate-500">语义类型：</span>{proposal.metric_draft?.semantic_type ?? '待确认'}</p>
          </div>
        ) : (
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <p><span className="text-slate-500">所属值域：</span><code className="font-medium text-blue-700">{proposal.value_draft?.domain_code}</code></p>
            <p><span className="text-slate-500">建议标准值：</span>{proposal.value_draft?.standard_value}</p>
            {proposal.suggested_mappings.map((mapping) => (
              <p key={`${mapping.binding_id}-${mapping.source_value}`} className="sm:col-span-2">
                <span className="text-slate-500">建议映射：</span>{mapping.source_value} → {mapping.standard_value}
              </p>
            ))}
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
            {proposal.evidence.map((evidence) => <Evidence key={evidence.source_ref} evidence={evidence} />)}
          </section>
        )}
        {rejecting && (
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
        <CardFooter className="justify-end gap-2">
          <Button type="button" variant="outline" aria-label={`驳回 ${label}`} onClick={onRejectStart} disabled={pending}>驳回</Button>
          <Button type="button" aria-label={`通过并发布 ${label}`} onClick={onAccept} disabled={pending}>
            {pending ? '处理中…' : '通过并发布'}
          </Button>
        </CardFooter>
      )}
    </Card>
  )
}

export default function SemanticProposalsPage() {
  const [activeTab, setActiveTab] = useState<SemanticProposalType>('metric')
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
    Promise.all([listSemanticProposals('metric'), listSemanticProposals('value')])
      .then(([metrics, values]) => {
        if (!cancelled) setProposals([...metrics, ...values].filter((item) => ACTIVE_STATUSES.has(item.status)))
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

  const visible = proposals.filter((proposal) => proposal.proposal_type === activeTab)

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
      {success && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{success}</div>}
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as SemanticProposalType)}>
        <TabsList aria-label="语义提议类型" variant="line" className="h-10">
          <TabsTrigger value="metric" className="px-4">指标提议</TabsTrigger>
          <TabsTrigger value="value" className="px-4">值域提议</TabsTrigger>
        </TabsList>
        {(['metric', 'value'] as const).map((type) => (
          <TabsContent key={type} value={type} className="mt-3 space-y-3">
            {visible.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white/60 px-6 py-12 text-center text-sm text-slate-600">
                暂无待审核{type === 'metric' ? '指标' : '值域'}提议
              </div>
            ) : visible.map((proposal) => (
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
              />
            ))}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
