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
  filterable: boolean
}> = [
  { label: '全部待办', field: 'total', status: null, filterable: true },
  { label: '待评测', field: 'needs_evaluation', status: 'needs_evaluation', filterable: true },
  { label: '待审批', field: 'pending_approval', status: 'pending_approval', filterable: true },
  { label: '健康', field: 'healthy', status: 'healthy', filterable: true },
  { label: 'Test Active', field: 'test_active', status: null, filterable: false },
]

export default function SkillGovernanceSummary({
  summary,
  activeStatus,
  onStatusChange,
}: SkillGovernanceSummaryProps) {
  return (
    <section aria-label="待办分组" className="flex min-h-10 overflow-x-auto border-b border-slate-200 bg-white">
      {summaryItems.map((item) => {
        const selected = item.filterable && activeStatus === item.status
        const content = (
          <>
            <span>{item.label}</span>
            <span className="font-semibold tabular-nums text-slate-900">{summary ? summary[item.field] : '—'}</span>
          </>
        )
        return item.filterable ? (
          <button
            key={item.field}
            type="button"
            aria-pressed={selected}
            onClick={() => onStatusChange(selected ? null : item.status)}
            className="flex min-h-11 shrink-0 items-center gap-2 border-r border-slate-200 px-3 text-sm text-slate-600 transition-colors hover:bg-slate-50 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 aria-pressed:bg-blue-50 aria-pressed:text-blue-700 sm:min-h-10"
          >
            {content}
          </button>
        ) : (
          <div key={item.field} className="flex min-h-11 shrink-0 items-center gap-2 px-3 text-sm text-slate-500 sm:min-h-10">
            {content}
          </div>
        )
      })}
    </section>
  )
}
