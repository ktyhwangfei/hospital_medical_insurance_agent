'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { FlaskConical, Layers3, RefreshCw, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getSkillGovernanceWorkbench } from '@/lib/api-client'
import type {
  MetricInputSpec,
  SkillExecutionContract,
  SkillGovernanceStatus,
  SkillWorkbenchItem,
} from '@/lib/types'

const ACTION_LABELS: Record<string, string> = {
  explain: '解释',
  query: '查询',
  guide: '导办',
  verify: '核验',
  compare: '对比',
  evaluate: '评估',
  analyze: '分析',
}

const OBJECT_LABELS: Record<string, string> = {
  settlement: '医保结算',
  policy: '医保政策',
  expense: '医疗费用',
  patient: '患者',
  audit: '审核风险',
  drg_dip: 'DRG/DIP',
  medical_record: '病案',
  appeal: '申诉',
  order: '医嘱',
  task: '任务',
}

const STATUS_LABELS: Record<SkillGovernanceStatus, string> = {
  healthy: '治理正常',
  needs_evaluation: '待评测',
  pending_approval: '待审批',
  gate_failed: '门禁未通过',
  artifact_changed: '制品有变更',
}

const STATUS_CLASSES: Record<SkillGovernanceStatus, string> = {
  healthy: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  needs_evaluation: 'border-amber-200 bg-amber-50 text-amber-700',
  pending_approval: 'border-blue-200 bg-blue-50 text-blue-700',
  gate_failed: 'border-red-200 bg-red-50 text-red-700',
  artifact_changed: 'border-violet-200 bg-violet-50 text-violet-700',
}

const EMPTY_CONTRACT: SkillExecutionContract = {
  version: 2,
  common: { context_inputs: [], metric_inputs: [] },
  profiles: [],
}

const CONTROL_CLASS = 'h-8 rounded-lg border border-slate-200 bg-white px-2.5 text-sm text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100'

function metricName(metric: MetricInputSpec) {
  return metric.alias?.trim() || metric.metric_code
}

function searchableText(item: SkillWorkbenchItem) {
  const contract = item.execution_contract ?? EMPTY_CONTRACT
  return [
    item.skill_id,
    item.skill_name,
    item.description,
    ACTION_LABELS[item.business_action] ?? item.business_action,
    OBJECT_LABELS[item.business_object] ?? item.business_object,
    ...contract.common.metric_inputs.flatMap((metric) => [metric.metric_code, metric.alias, metric.purpose]),
    ...contract.profiles.flatMap((profile) => [
      profile.name,
      profile.purpose,
      ...profile.metric_inputs?.flatMap((metric) => [metric.metric_code, metric.alias, metric.purpose]) ?? [],
    ]),
  ].filter(Boolean).join(' ').toLowerCase()
}

function uniqueMetricCount(contract: SkillExecutionContract) {
  return new Set([
    ...contract.common.metric_inputs.map((metric) => metric.metric_code),
    ...contract.profiles.flatMap((profile) => profile.metric_inputs?.map((metric) => metric.metric_code) ?? []),
  ]).size
}

function SkillCard({ item }: { item: SkillWorkbenchItem }) {
  const contract = item.execution_contract ?? EMPTY_CONTRACT
  const commonMetrics = contract.common.metric_inputs

  return (
    <article
      data-testid={`skill-overview-${item.skill_id}`}
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
    >
      <header className="border-b border-slate-100 px-4 py-3.5 sm:px-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold tracking-tight text-slate-900">{item.skill_name}</h2>
              <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                {item.skill_id}
              </span>
              {item.linked_draft_id && item.artifact_status === 'unregistered' ? (
                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">草稿</span>
              ) : (
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_CLASSES[item.governance_status]}`}>
                  {STATUS_LABELS[item.governance_status]}
                </span>
              )}
            </div>
            <p className="mt-1 max-w-4xl text-sm leading-5 text-slate-600">
              {item.description?.trim() || '尚未补充能力说明'}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span>{ACTION_LABELS[item.business_action] ?? item.business_action} · {OBJECT_LABELS[item.business_object] ?? item.business_object}</span>
            <span>v{item.semantic_version}</span>
            <span>{contract.profiles.length} 个场景</span>
            <span>{uniqueMetricCount(contract)} 个业务指标</span>
            <Link
              href={`/skills/evaluations?skill=${encodeURIComponent(item.skill_id)}`}
              className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1.5 font-medium text-white hover:bg-blue-700"
            >
              <FlaskConical className="size-3.5" aria-hidden="true" />
              测评
            </Link>
          </div>
        </div>
        {commonMetrics.length > 0 && (
          <p className="mt-2 text-xs leading-5 text-slate-500">
            <span className="font-medium text-slate-700">公共指标：</span>
            {commonMetrics.map(metricName).join('、')}
          </p>
        )}
      </header>

      {contract.profiles.length > 0 ? (
        <div data-testid="scenario-grid" className="grid grid-cols-1 gap-px bg-slate-100 md:grid-cols-2 xl:grid-cols-3">
          {contract.profiles.map((profile) => {
            const metrics = profile.metric_inputs ?? []
            return (
              <section key={profile.profile_id} className="min-w-0 bg-white px-4 py-3.5 sm:px-5">
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600">
                    <Layers3 className="size-3.5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-slate-800">{profile.name}</h3>
                    <p className="mt-0.5 text-xs leading-5 text-slate-500">
                      {profile.purpose?.trim() || '尚未补充场景说明'}
                    </p>
                  </div>
                </div>
                <p className="mt-2 border-t border-dashed border-slate-100 pt-2 text-xs leading-5 text-slate-500">
                  <span className="font-medium text-slate-700">依赖指标：</span>
                  {metrics.length > 0 ? metrics.map(metricName).join('、') : '无场景专属指标'}
                </p>
              </section>
            )
          })}
        </div>
      ) : (
        <div className="px-5 py-5 text-center text-sm text-slate-400">尚未配置执行场景</div>
      )}
    </article>
  )
}

export default function SkillCapabilityOverview() {
  const [items, setItems] = useState<SkillWorkbenchItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const [query, setQuery] = useState('')
  const [action, setAction] = useState('')
  const [object, setObject] = useState('')

  useEffect(() => {
    let active = true
    getSkillGovernanceWorkbench({ page: 1, page_size: 50 })
      .then((response) => {
        if (active) setItems(response.items)
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [reload])

  const actions = useMemo(() => [...new Set(items.map((item) => item.business_action))].filter(Boolean).sort(), [items])
  const objects = useMemo(() => [...new Set(items.map((item) => item.business_object))].filter(Boolean).sort(), [items])
  const normalizedQuery = query.trim().toLowerCase()
  const filteredItems = useMemo(() => items.filter((item) => (
    (!action || item.business_action === action)
    && (!object || item.business_object === object)
    && (!normalizedQuery || searchableText(item).includes(normalizedQuery))
  )), [action, items, normalizedQuery, object])
  const sceneCount = items.reduce((total, item) => total + (item.execution_contract?.profiles.length ?? 0), 0)
  const draftCount = items.filter((item) => item.linked_draft_id && item.artifact_status === 'unregistered').length
  const metricCount = new Set(items.flatMap((item) => {
    const contract = item.execution_contract ?? EMPTY_CONTRACT
    return [
      ...contract.common.metric_inputs.map((metric) => metric.metric_code),
      ...contract.profiles.flatMap((profile) => profile.metric_inputs?.map((metric) => metric.metric_code) ?? []),
    ]
  })).size
  const hasFilters = Boolean(query || action || object)
  const clearFilters = () => {
    setQuery('')
    setAction('')
    setObject('')
  }
  const retry = () => {
    setLoading(true)
    setError(null)
    setReload((value) => value + 1)
  }

  return (
    <div className="py-5">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Skill 能力与场景概览</h1>
          <p className="mt-1 text-sm text-slate-500">
            {items.length} 个 Skill{draftCount > 0 && <span className="text-amber-600"> · {draftCount} 个草稿</span>} · {sceneCount} 个场景 · {metricCount} 个业务指标
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <label className="relative block min-w-0 sm:w-64">
            <span className="sr-only">搜索 Skill、场景或业务指标</span>
            <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-slate-400" aria-hidden="true" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="搜索 Skill、场景或业务指标"
              placeholder="搜索 Skill、场景或指标"
              className="pl-8"
            />
          </label>
          <select aria-label="业务动作" value={action} onChange={(event) => setAction(event.target.value)} className={CONTROL_CLASS}>
            <option value="">全部动作</option>
            {actions.map((value) => <option key={value} value={value}>{ACTION_LABELS[value] ?? value}</option>)}
          </select>
          <select aria-label="业务对象" value={object} onChange={(event) => setObject(event.target.value)} className={CONTROL_CLASS}>
            <option value="">全部对象</option>
            {objects.map((value) => <option key={value} value={value}>{OBJECT_LABELS[value] ?? value}</option>)}
          </select>
        </div>
      </div>

      {loading ? (
        <div role="status" aria-label="正在加载 Skill 概览" className="space-y-3">
          {[0, 1, 2].map((index) => <div key={index} className="h-40 animate-pulse rounded-xl border border-slate-200 bg-white" />)}
        </div>
      ) : error ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-5 py-6 text-center text-sm text-red-700">
          <p>{error}</p>
          <Button type="button" variant="outline" size="sm" className="mt-3 bg-white" onClick={retry}>
            <RefreshCw aria-hidden="true" />重试
          </Button>
        </div>
      ) : filteredItems.length > 0 ? (
        <div className="space-y-3">
          {filteredItems.map((item) => <SkillCard key={item.skill_id} item={item} />)}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white px-5 py-10 text-center">
          <p className="text-sm font-medium text-slate-600">{hasFilters ? '没有符合条件的 Skill' : '暂无 Skill'}</p>
          {hasFilters && <Button type="button" variant="outline" size="sm" className="mt-3" onClick={clearFilters}>清除筛选</Button>}
        </div>
      )}
    </div>
  )
}
