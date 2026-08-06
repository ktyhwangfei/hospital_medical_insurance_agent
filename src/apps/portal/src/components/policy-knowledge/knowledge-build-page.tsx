'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, CircleDot, Clock3, Plus, RefreshCw, Send } from 'lucide-react'

import {
  listEligibleKnowledgeUnits,
  listKnowledgeBuildTasks,
  PolicyKnowledgeApiError,
  type EligibleKnowledgeUnit,
  type KnowledgeBuildTask,
  type KnowledgeBuildTaskStatus,
} from '@/lib/policy-knowledge-api'
import { useApiContext } from '@/lib/api-context'
import { BuildContextBar, KnowledgeFlow } from './knowledge-governance-shared'
import { KnowledgeBuildWizard } from './knowledge-build-wizard'

type KnowledgeBuildPageProps = {
  navigation: React.ReactNode
}

const BUILDING_STATUSES: KnowledgeBuildTaskStatus[] = ['QUEUED', 'RUNNING']

export function KnowledgeBuildPage({ navigation }: KnowledgeBuildPageProps) {
  const { userId } = useApiContext()
  const [units, setUnits] = useState<EligibleKnowledgeUnit[]>([])
  const [tasks, setTasks] = useState<KnowledgeBuildTask[]>([])
  const [loadingEligible, setLoadingEligible] = useState(true)
  const [loadingTasks, setLoadingTasks] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [eligibleReady, setEligibleReady] = useState(false)
  const [tasksReady, setTasksReady] = useState(false)
  const [semanticUnavailable, setSemanticUnavailable] = useState(false)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // 迭代 16 性能优化：eligible-units（~0.8s）与 tasks（~10ms）独立并行加载，
  // 任务表先渲染，摘要/按钮等 eligible 到达后再更新，避免被慢接口阻塞首屏。
  const loadEligible = useCallback(async () => {
    setLoadingEligible(true)
    setEligibleReady(false)
    try {
      const nextUnits = await listEligibleKnowledgeUnits()
      setUnits(nextUnits)
      setEligibleReady(true)
      setSemanticUnavailable(false)
    } catch (reason) {
      setEligibleReady(false)
      setSemanticUnavailable(isUnavailableError(reason))
      setLoadError(errorMessage(reason))
    } finally {
      setLoadingEligible(false)
    }
  }, [])

  const loadTasks = useCallback(async () => {
    setLoadingTasks(true)
    setTasksReady(false)
    try {
      const nextTasks = await listKnowledgeBuildTasks()
      setTasks(nextTasks)
      setTasksReady(true)
    } catch (reason) {
      setTasksReady(false)
      setLoadError((current) => current ?? errorMessage(reason))
    } finally {
      setLoadingTasks(false)
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoadError(null)
    await Promise.all([loadEligible(), loadTasks()])
  }, [loadEligible, loadTasks])

  useEffect(() => {
    let active = true
    void listEligibleKnowledgeUnits()
      .then((nextUnits) => {
        if (!active) return
        setUnits(nextUnits)
        setEligibleReady(true)
      })
      .catch((reason) => {
        if (!active) return
        setSemanticUnavailable(isUnavailableError(reason))
        setLoadError(errorMessage(reason))
      })
      .finally(() => {
        if (active) setLoadingEligible(false)
      })
    void listKnowledgeBuildTasks()
      .then((nextTasks) => {
        if (!active) return
        setTasks(nextTasks)
        setTasksReady(true)
      })
      .catch((reason) => {
        if (!active) return
        setLoadError((current) => current ?? errorMessage(reason))
      })
      .finally(() => {
        if (active) setLoadingTasks(false)
      })
    return () => {
      active = false
    }
  }, [])

  const availableCount = eligibleReady
    ? units.filter((unit) => unit.availability !== 'CLAIMED').length
    : null

  async function handleCreated() {
    setWizardOpen(false)
    setNotice('已生成待审知识')
    await refresh()
  }

  return (
    <div className="space-y-4">
      <div data-testid="knowledge-build-section-nav">{navigation}</div>
      <div data-testid="knowledge-build-section-context">
        <BuildContextBar
          availableUnitCount={availableCount}
          semanticContractVersion={null}
        />
      </div>
      <div data-testid="knowledge-build-section-flow">
        <KnowledgeFlow current="build" />
      </div>

      <section
        aria-label="知识构建摘要"
        data-testid="knowledge-build-section-summary"
        className="space-y-3 pt-1"
      >
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-emerald-700">单元 → 知识构建</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">知识构建</h2>
            <p className="mt-1 text-sm text-slate-500">从审核通过的单元生成待审知识，构建结果不会直接发布。</p>
          </div>
          <button
            type="button"
            disabled={!eligibleReady || semanticUnavailable}
            onClick={() => {
              setNotice(null)
              setWizardOpen(true)
            }}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-emerald-700 px-3.5 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(4,120,87,0.3)] transition-all hover:bg-emerald-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
          >
            <Plus className="size-4" />
            新建构建任务
          </button>
        </div>

        {notice && (
          <div role="status" className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700">
            <CheckCircle2 className="size-4" />
            {notice}
          </div>
        )}
        {loadError && (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="size-4" />
            <span>{loadError}</span>
            <button type="button" onClick={() => void refresh()} className="ml-auto inline-flex items-center gap-1 font-semibold hover:underline">
              <RefreshCw className="size-3.5" />重试
            </button>
          </div>
        )}
        {semanticUnavailable && (
          <Link href="/semantic-layer/metrics" className="inline-flex text-sm font-semibold text-emerald-700 hover:underline">
            前往语义层查看
          </Link>
        )}

        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 xl:grid-cols-5">
          <SummaryCard label="可构建单元" value={availableCount} loading={loadingEligible} icon={<CircleDot className="size-4 text-emerald-600" />} />
          <SummaryCard label="构建中" value={tasksReady ? tasks.filter((task) => BUILDING_STATUSES.includes(task.status)).length : null} loading={loadingTasks} icon={<RefreshCw className="size-4 text-sky-600" />} />
          <SummaryCard label="等待审核" value={tasksReady ? tasks.filter((task) => task.status === 'WAITING_REVIEW').length : null} loading={loadingTasks} icon={<Clock3 className="size-4 text-amber-600" />} />
          <SummaryCard label="待发布" value={tasksReady ? tasks.filter((task) => task.status === 'APPROVED_PENDING_RELEASE').length : null} loading={loadingTasks} icon={<Send className="size-4 text-violet-600" />} />
          <SummaryCard label="已发布" value={tasksReady ? tasks.filter((task) => task.status === 'PUBLISHED').length : null} loading={loadingTasks} icon={<CheckCircle2 className="size-4 text-emerald-600" />} />
        </div>
      </section>

      <section
        aria-labelledby="knowledge-build-task-title"
        data-testid="knowledge-build-section-tasks"
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <div>
            <h3 id="knowledge-build-task-title" className="text-sm font-semibold tracking-tight text-slate-900">构建任务</h3>
            <p className="mt-0.5 text-xs text-slate-500">进度仅展示服务端已处理单元，不估算中间进度。</p>
          </div>
          <span className="font-mono text-xs tabular-nums text-slate-400">{loadingTasks ? '加载中' : tasksReady ? `${tasks.length} 个任务` : '数据不可用'}</span>
        </div>
        <TaskTable tasks={tasks} loading={loadingTasks} ready={tasksReady} />
      </section>

      {wizardOpen && (
        <KnowledgeBuildWizard
          eligibleUnits={units}
          userId={userId}
          onClose={() => setWizardOpen(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}

function SummaryCard({ label, value, loading, icon }: { label: string; value: number | null; loading: boolean; icon: React.ReactNode }) {
  return (
    <article aria-label={`${label}摘要`} className="flex items-center justify-between gap-3 bg-white px-5 py-4">
      <div className="min-w-0">
        <p className="text-xs font-medium text-slate-500">{label}</p>
        {loading ? (
          <div className="mt-2 h-6 w-16 animate-pulse rounded bg-slate-100" aria-hidden="true" />
        ) : (
          <p className="mt-1.5 text-2xl font-semibold tabular-nums tracking-tight text-slate-900">{value ?? '暂无统计'}</p>
        )}
      </div>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-50 ring-1 ring-slate-100">{icon}</span>
    </article>
  )
}

function TaskTable({ tasks, loading, ready }: { tasks: KnowledgeBuildTask[]; loading: boolean; ready: boolean }) {
  if (loading) {
    return (
      <div aria-label="正在加载构建任务" className="w-full overflow-x-auto">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className={`flex items-center gap-6 px-4 py-3.5 ${index < 3 ? 'border-b border-slate-100' : ''}`}
          >
            <div className="h-3 w-44 animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-16 animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-20 animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-16 animate-pulse rounded bg-slate-100" />
            <div className="h-1 w-32 animate-pulse rounded-full bg-slate-100" />
            <div className="h-4 w-16 animate-pulse rounded-full bg-slate-100" />
            <div className="ml-auto h-3 w-24 animate-pulse rounded bg-slate-100" />
          </div>
        ))}
      </div>
    )
  }
  if (!ready) return <p className="px-4 py-10 text-center text-sm font-medium text-red-600">构建任务数据不可用，请稍后重试。</p>
  if (!tasks.length) return <p className="px-4 py-10 text-center text-sm text-slate-400">暂无构建任务，请从审核通过的单元新建任务。</p>

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full min-w-[1180px] border-collapse text-left text-xs">
        <thead className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
          <tr className="border-b border-slate-200">
            {['任务名称 / ID', '来源单元', '契约版本', '当前阶段', '真实进度', '状态', '结果', '操作'].map((heading) => (
              <th key={heading} scope="col" className="px-4 py-2.5 font-medium">{heading}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {tasks.map((task) => {
            const progress = taskProgress(task)
            const error = task.units.find((unit) => unit.error_message)?.error_message
            const canReview = task.status === 'WAITING_REVIEW' && task.result_change_set_id

            return (
              <tr key={task.task_id} className="align-top text-slate-700 transition-colors hover:bg-slate-50/70">
                <td className="px-4 py-3">
                  <p className="max-w-56 font-medium text-slate-900">{task.name}</p>
                  <p className="mt-1 font-mono text-[10px] text-slate-400">{task.task_id}</p>
                </td>
                <td className="px-4 py-3">
                  <p>{task.units.length} 个单元</p>
                  <p className="mt-1 max-w-40 truncate text-[10px] text-slate-400">{[...new Set(task.units.map((unit) => unit.doc_title))].join('、')}</p>
                </td>
                <td className="px-4 py-3 font-mono text-[11px]">{task.semantic_contract_version}</td>
                <td className="px-4 py-3">{taskStage(task.status)}</td>
                <td className="px-4 py-3">
                  <div className="flex min-w-24 items-center gap-2">
                    <div className="h-1 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-emerald-500 transition-[width] duration-500" style={{ width: `${progress}%` }} />
                    </div>
                    <span className="w-8 text-right font-medium tabular-nums">{progress}%</span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] tabular-nums text-slate-400">{task.processed_units}/{task.units.length}</p>
                </td>
                <td className="px-4 py-3"><StatusBadge status={task.status} /></td>
                <td className="max-w-64 px-4 py-3">
                  {error ? <span className="text-red-700">{error}</span> : <TaskResult task={task} />}
                </td>
                <td className="px-4 py-3">
                  {canReview ? (
                    <Link href={`/policy-knowledge/knowledge/review/${encodeURIComponent(task.result_change_set_id!)}`} className="font-semibold text-emerald-700 hover:text-emerald-800 hover:underline">进入审核</Link>
                  ) : <span className="text-slate-300">—</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function taskProgress(task: KnowledgeBuildTask): number {
  if (['WAITING_REVIEW', 'APPROVED_PENDING_RELEASE', 'PUBLISHED'].includes(task.status)) return 100
  if (!task.units.length) return 0
  return Math.max(0, Math.min(100, Math.round((task.processed_units / task.units.length) * 100)))
}

function taskStage(status: KnowledgeBuildTaskStatus): string {
  if (status === 'QUEUED' || status === 'RUNNING') return '知识构建'
  if (status === 'WAITING_REVIEW') return '知识审核'
  if (status === 'APPROVED_PENDING_RELEASE') return '发布准备'
  if (status === 'PUBLISHED') return '已发布'
  if (status === 'RETURNED') return '退回重建'
  return '构建结束'
}

function TaskResult({ task }: { task: KnowledgeBuildTask }) {
  const summaryLabels: Array<[keyof KnowledgeBuildTask['result_summary'], string]> = [
    ['additions', '新增'],
    ['modifications', '修改'],
    ['replacements', '替代'],
    ['expirations', '失效'],
    ['unchanged', '未变化'],
  ]
  const values = summaryLabels.flatMap(([key, label]) => {
    const value = task.result_summary[key]
    return typeof value === 'number' && value > 0 ? [`${label} ${value}`] : []
  })
  const state = task.status === 'WAITING_REVIEW'
    ? '已生成待审知识'
    : task.status === 'APPROVED_PENDING_RELEASE'
      ? '审核通过，待发布'
      : task.status === 'PUBLISHED'
        ? '已发布'
        : task.status === 'RETURNED'
          ? '已退回重建'
          : task.status === 'REJECTED'
            ? '审核未通过'
            : task.status === 'CANCELLED'
              ? '任务已取消'
              : task.status === 'FAILED'
                ? '构建失败'
                : '—'

  return (
    <div>
      <p>{state}</p>
      {!!values.length && <p className="mt-1 text-[10px] leading-4 text-slate-500">{values.join(' · ')}</p>}
      {task.issue_count > 0 && <p className="mt-1 text-[10px] font-medium text-amber-700">待处理问题 {task.issue_count}</p>}
    </div>
  )
}

function isUnavailableError(error: unknown): boolean {
  return error instanceof PolicyKnowledgeApiError && error.status === 503
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '知识构建数据加载失败'
}

function StatusBadge({ status }: { status: KnowledgeBuildTaskStatus }) {
  const [label, tone] = ({
    QUEUED: ['排队中', 'bg-slate-100 text-slate-600'],
    RUNNING: ['构建中', 'bg-sky-50 text-sky-700'],
    WAITING_REVIEW: ['待审核', 'bg-amber-50 text-amber-700'],
    APPROVED_PENDING_RELEASE: ['待发布', 'bg-teal-50 text-teal-700'],
    PUBLISHED: ['已发布', 'bg-emerald-50 text-emerald-700'],
    RETURNED: ['已退回', 'bg-orange-50 text-orange-700'],
    REJECTED: ['已拒绝', 'bg-red-50 text-red-700'],
    FAILED: ['失败', 'bg-red-50 text-red-700'],
    CANCELLED: ['已取消', 'bg-slate-100 text-slate-500'],
  } as const)[status]

  return <span className={`inline-flex rounded-md px-2 py-1 text-[10px] font-semibold ring-1 ring-inset ring-black/[0.03] ${tone}`}>{label}</span>
}
