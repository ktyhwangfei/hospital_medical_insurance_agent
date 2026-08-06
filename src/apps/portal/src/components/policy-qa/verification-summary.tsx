import { BadgeCheck, Calculator, CircleAlert, FileCheck2, TriangleAlert } from 'lucide-react'

import type { PolicyQAResult, PolicyQAVerificationSummary } from '@/lib/policy-qa-stream'

interface VerificationSummaryProps {
  summary?: PolicyQAVerificationSummary
  answerStatus?: PolicyQAResult['answerStatus']
}

export default function VerificationSummary({
  summary,
  answerStatus,
}: VerificationSummaryProps) {
  if (!summary) return null
  const status = answerStatus ?? 'unavailable'
  const Icon =
    status === 'complete' ? BadgeCheck : status === 'partial' ? TriangleAlert : CircleAlert
  const tone =
    status === 'complete'
      ? 'border-emerald-200/70 bg-emerald-50/60 text-emerald-600'
      : status === 'partial'
        ? 'border-amber-200/70 bg-amber-50/60 text-amber-600'
        : 'border-slate-200 bg-slate-100/70 text-slate-500'

  return (
    <section
      aria-label="核验摘要"
      data-status={status}
      className={`rounded-xl border px-4 py-3 ${tone}`}
    >
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-medium leading-6 text-slate-800">{summary.message}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <FileCheck2 className="size-3.5" aria-hidden />
              {summary.settlementChecked ? '结算单已核对' : '结算单待核对'}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Calculator className="size-3.5" aria-hidden />
              {summary.calculationChecked ? '计算已核对' : '计算待核对'}
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
