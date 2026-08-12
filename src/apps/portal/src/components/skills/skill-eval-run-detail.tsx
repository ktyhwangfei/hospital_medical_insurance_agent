'use client'

import type { SkillEvalResultResponse, SkillEvalRunResponse } from '@/lib/types'

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

/** 评测运行详情：门禁指标卡片 + 逐用例路由差异表。纯展示，displayName 由父级注入。 */
export default function RunDetail({
  run,
  displayName,
}: {
  run: SkillEvalRunResponse
  displayName: (id: string | null | undefined) => string
}) {
  const m = run.metrics
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
