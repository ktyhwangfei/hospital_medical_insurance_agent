'use client'

import { useEffect, useState } from 'react'
import { AlertCircle, RefreshCw, Wrench } from 'lucide-react'

import {
  createSkillEvalImprovementTask,
  listSkillEvalFailureClusters,
  retestSkillEvalRun,
} from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import type {
  SkillEvalDimension,
  SkillEvalFailureClusterResponse,
  SkillEvalResultResponse,
  SkillEvalRunResponse,
} from '@/lib/types'

const DIFF_LABEL: Record<string, string> = {
  unchanged_pass: '持续通过',
  unchanged_fail: '持续失败',
  new_pass: '新增通过',
  new_failure: '新增失败',
  route_changed: '路由变更',
}

const DIFF_TONE: Record<string, string> = {
  unchanged_pass: 'text-emerald-700',
  new_pass: 'text-emerald-700',
  unchanged_fail: 'text-slate-500',
  new_failure: 'text-rose-700',
  route_changed: 'text-amber-700',
}

const DIMENSIONS: Array<[SkillEvalDimension, string]> = [
  ['route', '路由'],
  ['behavior', '行为'],
  ['calculation', '计算'],
  ['policy_content', '政策内容'],
  ['citation', '引用'],
  ['answer_quality', '回答质量'],
  ['safety', '安全'],
]

/** 评测运行详情：门禁指标卡片 + 逐用例路由差异表。纯展示，displayName 由父级注入。 */
export default function RunDetail({
  run,
  displayName,
  onRetested,
}: {
  run: SkillEvalRunResponse
  displayName: (id: string | null | undefined) => string
  onRetested?: (run: SkillEvalRunResponse) => void
}) {
  const m = run.metrics
  const dimensionSummary = run.dimension_summary ?? []
  const failureAttributions = run.failure_attributions ?? []
  const trajectorySummary = run.trajectory_summary ?? []
  const [clusters, setClusters] = useState<SkillEvalFailureClusterResponse[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!run.benchmark_id) return
    let active = true
    listSkillEvalFailureClusters(run.run_id)
      .then((items) => { if (active) setClusters(items) })
      .catch(() => {
        if (active) {
          setClusters((run.failure_clusters ?? []).map((cluster) => ({
            cluster,
            improvement_tasks: [],
          })))
        }
      })
    return () => { active = false }
  }, [run])

  async function createImprovement(clusterId: string): Promise<void> {
    setBusy(clusterId)
    setError(null)
    try {
      const created = await createSkillEvalImprovementTask(clusterId)
      setClusters((current) => current.map((item) => (
        item.cluster.cluster_id === clusterId
          ? { ...item, improvement_tasks: [...item.improvement_tasks, created] }
          : item
      )))
    } catch (reason) {
      setError(reason instanceof ApiClientError ? reason.detail.message : '创建改进任务失败')
    } finally {
      setBusy(null)
    }
  }

  async function retest(): Promise<void> {
    setBusy('retest')
    setError(null)
    try {
      onRetested?.(await retestSkillEvalRun(run.run_id))
    } catch (reason) {
      setError(reason instanceof ApiClientError ? reason.detail.message : '复测失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div data-testid={`eval-run-detail-${run.run_id}`} className="space-y-3 border-t border-slate-100 p-3">
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <Metric label="Top1 准确率" value={`${(m.top1_accuracy * 100).toFixed(0)}%`} />
        <Metric label="基线 Top1" value={`${(m.baseline_top1_accuracy * 100).toFixed(0)}%`} />
        <Metric label="必测通过" value={`${m.required_passed}/${m.required_total}`} />
        <Metric label="回归数" value={String(m.regression_count)} tone={m.regression_count > 0 ? 'bad' : undefined} />
        <Metric
          label="误接管新增"
          value={String(m.new_false_takeover_count)}
          tone={m.new_false_takeover_count > 0 ? 'bad' : undefined}
        />
        <Metric label="版本" value={run.version_id} mono />
        <Metric label="测试集" value={`v${run.suite_version}`} />
        <Metric
          label="门禁"
          value={m.gate_passed ? '通过' : '未过'}
          tone={m.gate_passed ? 'good' : 'bad'}
        />
      </div>

      {run.benchmark_id ? (
        <>
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <h4 className="text-xs font-semibold text-slate-700">端到端维度</h4>
              <button
                type="button"
                onClick={() => void retest()}
                disabled={busy !== null}
                className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                复测
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-7">
              {DIMENSIONS.map(([dimension, label]) => {
                const summary = dimensionSummary.find((item) => item.dimension === dimension)
                const problemCount = summary
                  ? summary.failed + summary.blocked + summary.needs_review + summary.invalid_dataset
                  : 0
                return (
                  <div key={dimension} className="rounded-md border border-slate-100 px-2 py-1.5">
                    <div className="text-slate-500">{label}</div>
                    <div className={problemCount ? 'font-semibold text-rose-700' : 'font-semibold text-slate-800'}>
                      {summary ? `${summary.passed}/${summary.total} 通过` : '未配置'}
                    </div>
                    {summary?.blocked ? <div className="text-amber-700">{summary.blocked} 阻塞</div> : null}
                    {summary?.needs_review ? <div className="text-blue-700">{summary.needs_review} 待复核</div> : null}
                  </div>
                )
              })}
            </div>
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold text-slate-700">失败归因与改进</h4>
            {clusters.length ? (
              <div className="space-y-2">
                {clusters.map(({ cluster, improvement_tasks: tasks }) => (
                  <div key={cluster.cluster_id} className="rounded-md border border-rose-100 bg-rose-50/40 p-2 text-xs">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="font-mono font-semibold text-rose-800">{cluster.failure_code}</div>
                        <div className="mt-0.5 text-slate-600">
                          {cluster.owner_type} / {cluster.stage} / {cluster.task_ids.length} 个任务
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void createImprovement(cluster.cluster_id)}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1 rounded-md bg-slate-900 px-2 py-1 font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                      >
                        <Wrench className="h-3.5 w-3.5" />
                        创建改进任务
                      </button>
                    </div>
                    {tasks.map((task) => (
                      <div key={task.task_id} className="mt-2 text-blue-800">
                        <span>{`改进任务 ${task.task_id}`}</span>（{task.status}）
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400">当前运行没有失败簇</p>
            )}
          </div>

          {failureAttributions.length || trajectorySummary.length ? (
            <details className="rounded-md border border-slate-100 p-2 text-xs">
              <summary className="cursor-pointer font-medium text-slate-700">查看归因证据与公开轨迹</summary>
              <div className="mt-2 space-y-1 text-slate-600">
                {failureAttributions.map((item, index) => (
                  <div key={`${item.task_id}-${item.failure_code}-${index}`}>
                    {item.task_id}: {item.failure_code}，证据 {item.evidence_refs.join('、') || '无'}
                  </div>
                ))}
                {trajectorySummary.map((step, index) => (
                  <div key={`${step.task_id}-${step.sequence}-${index}`}>
                    {step.task_id}: {step.stage} / {step.action} / {step.status}
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </>
      ) : null}

      {error ? (
        <div role="alert" className="flex items-center gap-1.5 rounded-md bg-rose-50 px-2 py-1.5 text-xs text-rose-700">
          <AlertCircle className="h-3.5 w-3.5" /> {error}
        </div>
      ) : null}

      <div>
        <h4 className="mb-1.5 text-xs font-semibold text-slate-600">逐用例路由差异</h4>
        {run.results.length > 0 ? (
          <div className="overflow-x-auto rounded-md border border-slate-100">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-2 py-1">用例</th>
                  <th className="px-2 py-1">差异</th>
                  <th className="px-2 py-1">候选</th>
                  <th className="px-2 py-1">基线</th>
                  <th className="px-2 py-1">置信度(候选/基线)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {run.results.map((rc: SkillEvalResultResponse) => (
                  <tr key={rc.case_id}>
                    <td className="px-2 py-1 font-mono text-slate-500">{rc.case_id}</td>
                    <td className={`px-2 py-1 font-medium ${DIFF_TONE[rc.diff] ?? 'text-slate-600'}`}>
                      {DIFF_LABEL[rc.diff] ?? rc.diff}
                    </td>
                    <td className="px-2 py-1">{displayName(rc.candidate_skill_id)}</td>
                    <td className="px-2 py-1">{displayName(rc.baseline_skill_id)}</td>
                    <td className="px-2 py-1 text-slate-500">
                      {rc.candidate_confidence.toFixed(2)} / {rc.baseline_confidence.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-slate-400">无逐用例结果</p>
        )}
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  tone,
  mono,
}: {
  label: string
  value: string
  tone?: 'good' | 'bad'
  mono?: boolean
}) {
  const toneClass =
    tone === 'good'
      ? 'text-emerald-700'
      : tone === 'bad'
        ? 'text-rose-700'
        : 'text-slate-800'
  return (
    <div className="rounded-md bg-slate-50 px-2 py-1.5">
      <div className="text-slate-400">{label}</div>
      <div className={`font-semibold ${toneClass} ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  )
}
