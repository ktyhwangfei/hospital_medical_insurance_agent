import type { SkillGovernanceStatus, SkillWorkbenchSummary } from '@/lib/types'

interface SkillGovernanceSummaryProps {
  summary: SkillWorkbenchSummary | null
  activeStatus: SkillGovernanceStatus | null
  onStatusChange: (status: SkillGovernanceStatus | null) => void
}

const summaryItems: Array<{
  label: string
  field: keyof Pick<SkillWorkbenchSummary, 'total' | 'healthy' | 'needs_evaluation' | 'pending_approval' | 'test_active'>
  status: SkillGovernanceStatus | null
}> = [
  { label: '全部', field: 'total', status: null },
  { label: '健康', field: 'healthy', status: 'healthy' },
  { label: '待评测', field: 'needs_evaluation', status: 'needs_evaluation' },
  { label: '待审批', field: 'pending_approval', status: 'pending_approval' },
  { label: 'Test Active', field: 'test_active', status: null },
]

export default function SkillGovernanceSummary({
  summary,
  activeStatus,
  onStatusChange,
}: SkillGovernanceSummaryProps) {
  return (
    <section aria-label="治理摘要" className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 md:grid-cols-5">
      {summaryItems.map((item) => {
        const selected = item.status !== null && activeStatus === item.status
        return (
          <button
            key={item.field}
            type="button"
            aria-pressed={selected}
            onClick={() => onStatusChange(selected ? null : item.status)}
            className="min-h-20 bg-white px-4 py-3 text-left transition-colors hover:bg-slate-50 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 aria-pressed:bg-blue-50"
          >
            <span className="block text-xs font-medium text-slate-500">{item.label}</span>
            <span className="mt-1 block text-2xl font-semibold tabular-nums text-slate-950">
              {summary ? summary[item.field] : '—'}
            </span>
          </button>
        )
      })}
    </section>
  )
}
