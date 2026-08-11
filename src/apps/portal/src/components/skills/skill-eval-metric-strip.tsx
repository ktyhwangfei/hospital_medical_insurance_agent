import type { SkillEvalRunResponse } from '@/lib/types'

interface SkillEvalMetricStripProps {
  latest: SkillEvalRunResponse | null
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export default function SkillEvalMetricStrip({ latest }: SkillEvalMetricStripProps) {
  const metrics = latest?.metrics
  const values = [
    metrics && metrics.total > 0 ? percent(metrics.passed / metrics.total) : '—',
    latest?.baseline_version_id && metrics ? percent(metrics.baseline_top1_accuracy) : '无活动基线',
    metrics ? String(metrics.regression_count) : '—',
    metrics && metrics.required_total >= 0
      ? `${metrics.required_passed}/${metrics.required_total}`
      : '—',
  ]

  return (
    <dl className="grid grid-cols-2 divide-x divide-y divide-slate-200 border-b border-slate-200 lg:grid-cols-4 lg:divide-y-0">
      {['候选通过率', '活动基线通过率', '新增回归', '必测通过数'].map((label, index) => (
        <div key={label} className="min-w-0 px-4 py-4">
          <dt className="text-xs font-medium text-slate-500">{label}</dt>
          <dd className="mt-1 break-words text-xl font-semibold tabular-nums text-slate-950">{values[index]}</dd>
        </div>
      ))}
    </dl>
  )
}
