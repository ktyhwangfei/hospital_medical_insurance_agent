'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ChevronRight, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import Link from 'next/link'

import {
  listChangeSets,
  listDecisionTasks,
  type DecisionTask,
  type KnowledgeChangeSet,
  type RiskLevel,
} from '@/lib/policy-knowledge-api'

type ReviewView = 'pending' | 'all' | 'completed' | 'issues'

const REVIEW_VIEWS: Array<{ id: ReviewView; label: string }> = [
  { id: 'pending', label: '待审核' },
  { id: 'all', label: '全部审核' },
  { id: 'completed', label: '已完成' },
  { id: 'issues', label: '仅看待处理问题' },
]

const PENDING_STATUSES = new Set<KnowledgeChangeSet['status']>([
  'NEEDS_DECISION',
  'PENDING_REVIEW',
])

const COMPLETED_STATUSES = new Set<KnowledgeChangeSet['status']>([
  'APPROVED',
  'REJECTED',
  'RETURNED',
  'PUBLISHED',
  'FAILED',
])

const STATUS_LABELS: Record<KnowledgeChangeSet['status'], string> = {
  DRAFT: '构建草稿',
  NEEDS_DECISION: '存在待处理问题',
  PENDING_REVIEW: '等待审核',
  APPROVED: '审核通过',
  REJECTED: '已拒绝',
  RETURNED: '已退回',
  PUBLISHED: '已发布',
  FAILED: '构建失败',
}

export function KnowledgeReviewPage() {
  const [changeSets, setChangeSets] = useState<KnowledgeChangeSet[]>([])
  const [decisionTasks, setDecisionTasks] = useState<DecisionTask[]>([])
  const [view, setView] = useState<ReviewView>('pending')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const loadSequence = useRef(0)

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current
    setLoading(true)
    setError('')
    try {
      const [nextChangeSets, nextDecisionTasks] = await Promise.all([
        listChangeSets(),
        listDecisionTasks(),
      ])
      if (sequence !== loadSequence.current) return
      setChangeSets(nextChangeSets)
      setDecisionTasks(nextDecisionTasks)
    } catch (reason) {
      if (sequence !== loadSequence.current) return
      setError(reason instanceof Error ? reason.message : '审核数据加载失败')
    } finally {
      if (sequence === loadSequence.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const sequence = ++loadSequence.current
    void Promise.all([listChangeSets(), listDecisionTasks()])
      .then(([nextChangeSets, nextDecisionTasks]) => {
        if (sequence !== loadSequence.current) return
        setChangeSets(nextChangeSets)
        setDecisionTasks(nextDecisionTasks)
      })
      .catch((reason) => {
        if (sequence !== loadSequence.current) return
        setError(reason instanceof Error ? reason.message : '审核数据加载失败')
      })
      .finally(() => {
        if (sequence === loadSequence.current) setLoading(false)
      })
    return () => {
      loadSequence.current += 1
    }
  }, [])

  const pendingIssuesByScope = useMemo(() => {
    const counts = new Map<string, number>()
    for (const task of decisionTasks) {
      if (task.status !== 'PENDING' || !task.blocking_scope) continue
      counts.set(task.blocking_scope, (counts.get(task.blocking_scope) ?? 0) + 1)
    }
    return counts
  }, [decisionTasks])

  const visibleChangeSets = changeSets.filter((changeSet) => {
    if (view === 'pending') return PENDING_STATUSES.has(changeSet.status)
    if (view === 'completed') return COMPLETED_STATUSES.has(changeSet.status)
    if (view === 'issues') return (pendingIssuesByScope.get(changeSet.change_set_id) ?? 0) > 0
    return true
  })

  return (
    <section aria-labelledby="knowledge-review-title" className="space-y-4 pt-2">
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <p className="text-xs font-semibold text-emerald-700">构建结果审核</p>
          <h2 id="knowledge-review-title" className="mt-1 text-xl font-semibold tracking-tight text-slate-900">
            知识审核
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            在一个上下文中核对来源、结构化规则、语义差异和阻断问题。
          </p>
        </div>
        <button
          type="button"
          aria-label="刷新审核列表"
          onClick={() => void load()}
          disabled={loading}
          className="ml-auto rounded-lg border border-slate-200 bg-white p-2 text-slate-500 transition-colors hover:bg-slate-50 disabled:opacity-40"
        >
          <RefreshCw className={`size-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </header>

      <div role="group" aria-label="审核视图筛选" className="flex w-fit flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
        {REVIEW_VIEWS.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={view === item.id}
            onClick={() => setView(item.id)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
              view === item.id
                ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200'
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div aria-label="正在加载审核列表" className="flex justify-center py-20">
          <Loader2 className="size-5 animate-spin text-slate-400" />
        </div>
      ) : error ? null : visibleChangeSets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-400">
          暂无审核任务
        </div>
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          {visibleChangeSets.map((changeSet) => (
            <ReviewCard
              key={changeSet.change_set_id}
              changeSet={changeSet}
              pendingIssueCount={pendingIssuesByScope.get(changeSet.change_set_id) ?? 0}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function ReviewCard({
  changeSet,
  pendingIssueCount,
}: {
  changeSet: KnowledgeChangeSet
  pendingIssueCount: number
}) {
  const risk = highestRisk(changeSet.risk_summary)

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-emerald-50 p-2 text-emerald-700 ring-1 ring-inset ring-emerald-600/10">
          <ShieldCheck className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold tracking-tight text-slate-900">{changeSet.doc_title}</h3>
          <p className="mt-0.5 font-mono text-[10px] text-slate-400">{changeSet.change_set_id}</p>
        </div>
        <span className="rounded bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">
          {STATUS_LABELS[changeSet.status]}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-slate-100 ring-1 ring-slate-100 sm:grid-cols-4">
        <Metric label="来源已审核单元" value={`${changeSet.source_units.length} 个`} />
        <Metric label="新增" value={changeSet.summary.additions} tone="emerald" />
        <Metric label="修改" value={changeSet.summary.modifications} tone="amber" />
        <Metric label="替代" value={changeSet.summary.replacements} tone="orange" />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <span className={`rounded px-2 py-1 text-[10px] font-semibold ${riskStyle(risk)}`}>
          {riskLabel(risk)}风险
        </span>
        <span className={`inline-flex items-center gap-1 text-xs ${pendingIssueCount > 0 ? 'font-semibold text-amber-700' : 'text-slate-400'}`}>
          <AlertTriangle className="size-3.5" />待处理问题 {pendingIssueCount} 项
        </span>
        <Link
          href={`/policy-knowledge/knowledge/review/${encodeURIComponent(changeSet.change_set_id)}`}
          className="ml-auto inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white shadow-[0_1px_2px_rgba(4,120,87,0.25)] transition-all hover:bg-emerald-800 active:scale-[0.98]"
        >
          进入审核 <ChevronRight className="size-3.5" />
        </Link>
      </div>
    </article>
  )
}

function Metric({
  label,
  value,
  tone = 'slate',
}: {
  label: string
  value: string | number
  tone?: 'slate' | 'emerald' | 'amber' | 'orange'
}) {
  const tones = {
    slate: 'text-slate-800',
    emerald: 'text-emerald-700',
    amber: 'text-amber-700',
    orange: 'text-orange-700',
  }
  return (
    <div className="bg-white px-3 py-2.5">
      <p className="text-[10px] font-medium tracking-wide text-slate-400">{label}</p>
      <p className={`mt-0.5 font-semibold tabular-nums ${tones[tone]}`}>{label} {value}</p>
    </div>
  )
}

function highestRisk(summary: Record<string, number>): RiskLevel {
  return (['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as RiskLevel[])
    .find((level) => (summary[level] ?? 0) > 0) ?? 'LOW'
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
