import type { SkillEvalRunResponse } from '@/lib/types'

interface SkillEvalMetricStripProps {
  latest: SkillEvalRunResponse | null
  state?: 'loading' | 'ready' | 'unavailable'
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export default function SkillEvalMetricStrip({ latest, state = 'ready' }: SkillEvalMetricStripProps) {
  const metrics = latest?.metrics
  const values = state === 'ready' ? [
    metrics && metrics.total > 0 ? percent(metrics.passed / metrics.total) : '—',
    latest?.baseline_version_id && metrics ? percent(metrics.baseline_top1_accuracy) : '无活动基线',
    metrics ? String(metrics.regression_count) : '—',
    metrics && metrics.required_total >= 0
      ? `${metrics.required_passed}/${metrics.required_total}`
      : '—',
  ] : ['—', '—', '—', '—']

  return (
    <div className="border-b border-slate-200">
      {state === 'loading' && (
        <p role="status" aria-label="正在加载评测证据" className="bg-slate-50 px-4 py-2 text-xs text-slate-600">
          正在加载评测证据…
        </p>
      )}
      <dl className="grid grid-cols-2 divide-x divide-y divide-slate-200 lg:grid-cols-4 lg:divide-y-0">
        {['候选通过率', '活动基线通过率', '新增回归', '必测通过数'].map((label, index) => (
          <div key={label} className="min-w-0 px-4 py-4">
            <dt className="text-xs font-medium text-slate-500">{label}</dt>
            <dd className="mt-1 break-words text-xl font-semibold tabular-nums text-slate-950">{values[index]}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
