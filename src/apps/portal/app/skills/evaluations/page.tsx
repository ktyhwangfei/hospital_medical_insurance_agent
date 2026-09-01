'use client'

import { Suspense, useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  AlertCircle,
  BarChart3,
  ChevronDown,
  ChevronRight,
  Database,
  FlaskConical,
  Plus,
  Wrench,
} from 'lucide-react'

import {
  createSkillEvalBenchmark,
  createSkillEvalCase,
  deleteSkillEvalCase,
  listAllSkillEvalRuns,
  listInfraSkills,
  listSkillEvalBenchmarks,
  listSkillEvalCases,
  listSkillEvalDatasetVersions,
  listSkillEvalTasks,
} from '@/lib/api-client'
import OutpatientSelfTestPanel from '@/components/skills/outpatient-self-test-panel'
import RunDetail from '@/components/skills/skill-eval-run-detail'
import SkillEvalLaunchPanel from '@/components/skills/skill-eval-launch-panel'
import SkillEvalSuitePanel from '@/components/skills/skill-eval-suite-panel'
import { ApiClientError } from '@/lib/types'
import type {
  SkillEvalBenchmarkResponse,
  SkillEvalCaseListResponse,
  SkillEvalDatasetVersionResponse,
  SkillEvalRunListResponse,
  SkillEvalRunResponse,
  SkillEvalTaskResponse,
} from '@/lib/types'
import { useSkillNameMap } from '@/lib/use-skill-name-map'

type Workspace = 'dataset' | 'run' | 'analysis' | 'improvement'

const WORKSPACES: Array<{ id: Workspace; label: string; icon: typeof Database }> = [
  { id: 'dataset', label: '数据集', icon: Database },
  { id: 'run', label: '运行与实验', icon: FlaskConical },
  { id: 'analysis', label: 'Benchmark 分析', icon: BarChart3 },
  { id: 'improvement', label: '问题与改进', icon: Wrench },
]

const RUN_STATUS_TONE: Record<string, string> = {
  passed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
  running: 'bg-blue-50 text-blue-700',
  cancelled: 'bg-slate-100 text-slate-500',
  error: 'bg-rose-50 text-rose-700',
}

const RUN_STATUS_LABEL: Record<string, string> = {
  passed: '通过',
  failed: '未通过',
  running: '运行中',
  cancelled: '已取消',
  error: '异常',
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.detail.message : fallback
}

function EvaluationsContent() {
  const skillFilter = useSearchParams().get('skill')
  const router = useRouter()
  const skillNameMap = useSkillNameMap()
  const [skillOptions, setSkillOptions] = useState<Array<{ skill_id: string; skill_name: string }>>([])
  useEffect(() => {
    let alive = true
    listInfraSkills()
      .then((skills) => {
        if (alive) setSkillOptions(skills.map((s) => ({ skill_id: s.skill_id, skill_name: s.skill_name })))
      })
      .catch(() => {
        // 拉取失败时选择器留空，用户仍可通过 ?skill= 深链进入
      })
    return () => {
      alive = false
    }
  }, [])
  const displayName = useCallback((id: string | null | undefined) => (
    id ? (skillNameMap.get(id) ?? id) : '通用'
  ), [skillNameMap])

  const [workspace, setWorkspace] = useState<Workspace>('dataset')
  const [selectedSuiteId, setSelectedSuiteId] = useState<string | null>(null)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [selectedBenchmarkId, setSelectedBenchmarkId] = useState<string | null>(null)
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [cases, setCases] = useState<SkillEvalCaseListResponse | null>(null)
  const [tasks, setTasks] = useState<SkillEvalTaskResponse[]>([])
  const [datasets, setDatasets] = useState<SkillEvalDatasetVersionResponse[]>([])
  const [benchmarks, setBenchmarks] = useState<SkillEvalBenchmarkResponse[]>([])
  const [runs, setRuns] = useState<SkillEvalRunListResponse>({ items: [], total: 0 })
  const [newQuestion, setNewQuestion] = useState('')
  const [benchmarkName, setBenchmarkName] = useState('门诊费用解释基准')
  const [runtimeVersion, setRuntimeVersion] = useState('current')
  const [dataSourceMode, setDataSourceMode] = useState('configured')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadOverview = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [caseResponse, runResponse, benchmarkResponse] = await Promise.all([
        listSkillEvalCases({ suiteId: selectedSuiteId ?? undefined }),
        listAllSkillEvalRuns(skillFilter ? { skillId: skillFilter, limit: 50 } : { limit: 50 }),
        listSkillEvalBenchmarks(skillFilter ?? undefined),
      ])
      setCases(caseResponse)
      setRuns(runResponse)
      setBenchmarks(benchmarkResponse.items)
      setSelectedBenchmarkId((current) => (
        benchmarkResponse.items.some((item) => item.benchmark_id === current)
          ? current
          : (benchmarkResponse.items[0]?.benchmark_id ?? null)
      ))
    } catch (reason) {
      setError(errorMessage(reason, '加载评测中心失败'))
    } finally {
      setLoading(false)
    }
  }, [selectedSuiteId, skillFilter])

  const loadDataset = useCallback(async () => {
    if (!selectedSuiteId) {
      setTasks([])
      setDatasets([])
      return
    }
    try {
      const [taskResponse, versionResponse] = await Promise.all([
        listSkillEvalTasks(selectedSuiteId),
        listSkillEvalDatasetVersions(selectedSuiteId),
      ])
      const ordered = [...versionResponse.items].sort((a, b) => b.version_number - a.version_number)
      setTasks(taskResponse.items)
      setDatasets(ordered)
      setSelectedDatasetId((current) => (
        ordered.some((item) => item.dataset_version_id === current)
          ? current
          : (ordered[0]?.dataset_version_id ?? null)
      ))
    } catch (reason) {
      setError(errorMessage(reason, '加载数据集资产失败'))
    }
  }, [selectedSuiteId])

  useEffect(() => { void Promise.resolve().then(loadOverview) }, [loadOverview])
  useEffect(() => { void Promise.resolve().then(loadDataset) }, [loadDataset])

  const selectedBenchmark = benchmarks.find((item) => item.benchmark_id === selectedBenchmarkId)
  const selectedDataset = datasets.find((item) => item.dataset_version_id === selectedDatasetId)
  const effectiveDataset = datasets.find(
    (item) => item.dataset_version_id === selectedBenchmark?.dataset_version_id,
  ) ?? selectedDataset
  const activeSkillId = skillFilter ?? selectedBenchmark?.skill_id ?? null
  const enabledTasks = tasks.filter((task) => task.enabled)
  const visibleCases = cases?.items.filter((item) => (
    !skillFilter || item.expected_skill_id === skillFilter
  )) ?? []

  async function addCase(): Promise<void> {
    const question = newQuestion.trim()
    if (!question || !skillFilter) return
    setBusy(true)
    setError(null)
    try {
      await createSkillEvalCase({
        suite_id: selectedSuiteId ?? 'EVS_platform_routing',
        question_template: question,
        expected_skill_id: skillFilter,
      })
      setNewQuestion('')
      await loadOverview()
    } catch (reason) {
      setError(errorMessage(reason, '新增路由断言失败'))
    } finally {
      setBusy(false)
    }
  }

  async function removeCase(caseId: string): Promise<void> {
    try {
      await deleteSkillEvalCase(caseId)
      await loadOverview()
    } catch (reason) {
      setError(errorMessage(reason, '删除路由断言失败'))
    }
  }

  async function createBenchmark(): Promise<void> {
    if (!skillFilter || !selectedDatasetId || !benchmarkName.trim()) return
    setBusy(true)
    setError(null)
    try {
      const created = await createSkillEvalBenchmark({
        name: benchmarkName.trim(),
        skill_id: skillFilter,
        dataset_version_id: selectedDatasetId,
        environment_snapshot: {
          runtime_version: runtimeVersion.trim(),
          data_source_mode: dataSourceMode.trim(),
        },
        evaluator_plan_id: 'deterministic_v1',
      })
      setBenchmarks((current) => [created, ...current])
      setSelectedBenchmarkId(created.benchmark_id)
      setWorkspace('run')
    } catch (reason) {
      setError(errorMessage(reason, '创建 Benchmark 失败'))
    } finally {
      setBusy(false)
    }
  }

  function acceptRun(run: SkillEvalRunResponse): void {
    setRuns((current) => ({
      items: [run, ...current.items.filter((item) => item.run_id !== run.run_id)],
      total: current.items.some((item) => item.run_id === run.run_id)
        ? current.total
        : current.total + 1,
    }))
    setExpandedRun(run.run_id)
    setWorkspace('analysis')
  }

  return (
    <div className="mt-4 space-y-4 pb-8">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">Skill 评测中心</h2>
        <p className="text-sm text-slate-600">
          维护端到端任务，冻结可重复的数据集，运行 Benchmark，并把失败转成可跟踪的改进任务。
        </p>
        {skillFilter ? (
          <p className="text-xs text-slate-500">
            当前 Skill：<Link href={`/skills/${encodeURIComponent(skillFilter)}`} className="font-medium text-blue-700 hover:underline">
              {displayName(skillFilter)}
            </Link>
          </p>
        ) : (
          <p className="text-xs text-amber-700">
            选择 Skill 进入评测（也可从 Skill 详情页进入）：
            <select
              aria-label="选择 Skill"
              data-testid="eval-skill-select"
              value=""
              onChange={(event) => {
                if (event.target.value) {
                  router.replace(`/skills/evaluations?skill=${encodeURIComponent(event.target.value)}`)
                }
              }}
              className="ml-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs"
            >
              <option value="">选择 Skill…</option>
              {skillOptions.map((skill) => (
                <option key={skill.skill_id} value={skill.skill_id}>
                  {skill.skill_name}
                </option>
              ))}
            </select>
          </p>
        )}
      </header>

      <section aria-label="当前评测上下文" className="sticky top-0 z-10 rounded-xl border border-slate-200 bg-white/95 p-3 shadow-sm backdrop-blur">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs md:grid-cols-4 xl:grid-cols-7">
          <ContextValue label="Skill" value={activeSkillId ? displayName(activeSkillId) : '未锁定'} />
          <ContextValue label="测评集" value={selectedSuiteId ?? '未选择'} mono />
          <ContextValue label="数据集版本" value={effectiveDataset ? `v${effectiveDataset.version_number}` : '未冻结'} />
          <ContextValue label="Benchmark" value={selectedBenchmark?.name ?? '未选择'} />
          <ContextValue label="候选" value="运行时选择" />
          <ContextValue label="基线" value="待接入隔离执行" />
          <ContextValue label="任务数" value={String(effectiveDataset?.task_snapshots.length ?? enabledTasks.length)} />
        </dl>
      </section>

      <nav aria-label="评测工作区" role="tablist" className="flex overflow-x-auto border-b border-slate-200">
        {WORKSPACES.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={workspace === id}
            onClick={() => setWorkspace(id)}
            className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium ${
              workspace === id
                ? 'border-blue-700 text-blue-800'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </nav>

      {error ? (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      ) : null}

      {workspace === 'dataset' ? (
        <div className="space-y-4">
          <SkillEvalSuitePanel
            skillId={skillFilter}
            selectedSuiteId={selectedSuiteId}
            onSelect={setSelectedSuiteId}
          />

          {skillFilter === 'mzsettlement_verify_skill' ? (
            <OutpatientSelfTestPanel
              suiteId={selectedSuiteId}
              onDatasetChanged={() => void loadDataset()}
            />
          ) : null}

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">冻结版本与 Benchmark</h3>
                <p className="mt-1 text-xs text-slate-500">
                  当前测评集有 {enabledTasks.length} 条启用任务，已冻结 {datasets.length} 个不可变版本。
                </p>
              </div>
              <select
                aria-label="选择数据集版本"
                value={selectedDatasetId ?? ''}
                onChange={(event) => setSelectedDatasetId(event.target.value)}
                className="h-9 rounded-md border border-slate-200 bg-white px-2 text-sm"
              >
                <option value="">请选择数据集版本</option>
                {datasets.map((dataset) => (
                  <option key={dataset.dataset_version_id} value={dataset.dataset_version_id}>
                    v{dataset.version_number}，{dataset.task_snapshots.length} 条任务
                  </option>
                ))}
              </select>
            </div>

            <div className="mt-3 grid gap-3 md:grid-cols-4 md:items-end">
              <Field label="Benchmark 名称" value={benchmarkName} onChange={setBenchmarkName} />
              <Field label="运行时版本" value={runtimeVersion} onChange={setRuntimeVersion} />
              <Field label="数据源模式" value={dataSourceMode} onChange={setDataSourceMode} />
              <button
                type="button"
                onClick={() => void createBenchmark()}
                disabled={busy || !skillFilter || !selectedDatasetId || !runtimeVersion.trim() || !dataSourceMode.trim()}
                className="h-9 rounded-md bg-blue-700 px-3 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
              >
                创建 Benchmark
              </button>
            </div>
          </section>

          <details className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <summary className="cursor-pointer text-sm font-semibold text-slate-800">
              历史路由断言（{visibleCases.length}）
            </summary>
            {skillFilter ? (
              <div className="mt-3 flex gap-2">
                <input
                  aria-label="新增路由问题"
                  value={newQuestion}
                  onChange={(event) => setNewQuestion(event.target.value)}
                  placeholder="输入问题模板"
                  className="h-9 min-w-0 flex-1 rounded-md border border-slate-200 px-2 text-sm"
                />
                <button
                  type="button"
                  onClick={() => void addCase()}
                  disabled={busy || !newQuestion.trim()}
                  className="inline-flex h-9 items-center gap-1 rounded-md border border-slate-300 px-3 text-sm font-medium text-slate-700 disabled:opacity-50"
                >
                  <Plus className="h-4 w-4" /> 新增
                </button>
              </div>
            ) : null}
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {visibleCases.map((item) => (
                <div key={item.case_id} className="flex items-start justify-between gap-2 rounded-md bg-slate-50 p-2 text-xs">
                  <div>
                    <div className="font-medium text-slate-800">{item.question_template}</div>
                    <div className="mt-0.5 text-slate-500">{item.source_type}</div>
                  </div>
                  <button type="button" onClick={() => void removeCase(item.case_id)} className="text-rose-700 hover:underline">
                    删除
                  </button>
                </div>
              ))}
              {!visibleCases.length ? <p className="text-xs text-slate-400">暂无路由断言</p> : null}
            </div>
          </details>
        </div>
      ) : null}

      {workspace === 'run' ? (
        <div className="space-y-4">
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <label className="block text-xs font-medium text-slate-600">
              选择 Benchmark
              <select
                value={selectedBenchmarkId ?? ''}
                onChange={(event) => setSelectedBenchmarkId(event.target.value)}
                className="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
              >
                <option value="">请选择 Benchmark</option>
                {benchmarks.map((benchmark) => (
                  <option key={benchmark.benchmark_id} value={benchmark.benchmark_id}>
                    {benchmark.name}（{benchmark.benchmark_id}）
                  </option>
                ))}
              </select>
            </label>
          </section>
          <SkillEvalLaunchPanel
            key={activeSkillId ?? 'no-skill'}
            skillId={activeSkillId}
            benchmarkId={selectedBenchmarkId}
            taskCount={effectiveDataset?.task_snapshots.length ?? enabledTasks.length}
            onLaunched={acceptRun}
          />
        </div>
      ) : null}

      {workspace === 'analysis' ? (
        <RunList
          title="Benchmark 运行"
          items={runs.items}
          loading={loading}
          expandedRun={expandedRun}
          setExpandedRun={setExpandedRun}
          displayName={displayName}
          onRetested={acceptRun}
        />
      ) : null}

      {workspace === 'improvement' ? (
        <RunList
          title="失败运行与改进"
          items={runs.items.filter((run) => run.status !== 'passed')}
          loading={loading}
          expandedRun={expandedRun}
          setExpandedRun={setExpandedRun}
          displayName={displayName}
          onRetested={acceptRun}
        />
      ) : null}
    </div>
  )
}

function ContextValue({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-slate-400">{label}</dt>
      <dd className={`truncate font-medium text-slate-800 ${mono ? 'font-mono' : ''}`} title={value}>{value}</dd>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs font-medium text-slate-600">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-9 w-full rounded-md border border-slate-200 px-2 text-sm"
      />
    </label>
  )
}

function RunList({
  title,
  items,
  loading,
  expandedRun,
  setExpandedRun,
  displayName,
  onRetested,
}: {
  title: string
  items: SkillEvalRunResponse[]
  loading: boolean
  expandedRun: string | null
  setExpandedRun: (runId: string | null) => void
  displayName: (id: string | null | undefined) => string
  onRetested: (run: SkillEvalRunResponse) => void
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-slate-900">{title}</h3>
      {loading ? (
        <div className="space-y-2" aria-label="加载运行记录">
          <div className="h-10 rounded-md bg-slate-100" />
          <div className="h-10 rounded-md bg-slate-100" />
        </div>
      ) : items.length ? (
        <div className="space-y-2">
          {items.map((run) => {
            const expanded = expandedRun === run.run_id
            return (
              <div key={run.run_id} className="rounded-lg border border-slate-100">
                <button
                  type="button"
                  data-testid={`eval-run-row-${run.run_id}`}
                  onClick={() => setExpandedRun(expanded ? null : run.run_id)}
                  className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg p-3 text-left hover:bg-slate-50"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {expanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
                    <span className="font-medium text-slate-800">{displayName(run.skill_id)}</span>
                    <span className={`rounded px-1.5 py-0.5 text-xs ${RUN_STATUS_TONE[run.status] ?? 'bg-slate-100 text-slate-500'}`}>
                      {RUN_STATUS_LABEL[run.status] ?? run.status}
                    </span>
                    <span className="text-xs text-slate-500">{run.metrics.passed}/{run.metrics.total} 通过</span>
                  </span>
                  <span className="text-xs text-slate-400">{new Date(run.created_at).toLocaleString('zh-CN')}</span>
                </button>
                {expanded ? <RunDetail run={run} displayName={displayName} onRetested={onRetested} /> : null}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="py-6 text-center text-sm text-slate-400">暂无匹配的评测运行</p>
      )}
    </section>
  )
}

export default function SkillEvaluationsPage() {
  return (
    <Suspense fallback={<div className="mt-4 text-sm text-slate-400">加载中...</div>}>
      <EvaluationsContent />
    </Suspense>
  )
}
