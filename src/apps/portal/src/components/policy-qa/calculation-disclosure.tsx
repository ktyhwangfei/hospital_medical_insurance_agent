import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'

interface CalculationDisclosureProps {
  message: PolicyQAChatMessage
}

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} 元`
}

export default function CalculationDisclosure({ message }: CalculationDisclosureProps) {
  const context = message.caseContext
  const steps = message.calculationSteps ?? []
  const warnings = message.warnings ?? []
  const settlementFields = (message.settlementFields ?? []).filter(
    (field) => field.state === 'non_zero' || field.state === 'reported_zero',
  )
  if (settlementFields.length > 0) {
    return (
      <section
        aria-label="结算单费用"
        className="rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-4"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-slate-800">结算单费用</h3>
          {message.verificationSummary?.settlementChecked ? (
            <span className="text-xs font-medium text-emerald-700">结算金额已核对</span>
          ) : null}
        </div>
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {settlementFields.map((field) => (
            <div key={field.fieldName} className="flex items-center justify-between gap-4">
              <dt className="text-sm text-slate-600">{field.fieldName}</dt>
              <dd className="font-medium tabular-nums text-slate-900">
                {formatMoney(field.value)}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-slate-500">以上金额均来自本次医保结算单原始字段。</p>
      </section>
    )
  }
  const hasContent = Boolean(context || steps.length || message.definition || warnings.length)
  if (!hasContent) return null

  const coverageComplete = !context?.coverageStatus || context.coverageStatus === 'complete'
  const amounts = context && coverageComplete
    ? [
        ['住院总费用', context.totalAmount],
        ['统筹支付', context.basicPoolingPayment],
        ['统筹自付', context.basicPoolingSelfPay],
        ['大额支付', context.largeAmountPayment],
        ['大额自付', context.largeAmountSelfPay],
        ['起付线', context.deductible],
        ['个人总支付', context.personalTotalPay],
      ] as const
    : []

  return (
    <details className="rounded-xl border border-slate-200 bg-slate-50/60">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-700">
        计算依据
      </summary>
      <div className="space-y-4 border-t border-slate-200 px-4 py-4 text-sm text-slate-600">
        {context?.queryScope ? (
          <div className="space-y-1 rounded-lg bg-white px-3 py-2 text-slate-700">
            <p>查询范围：{context.queryScope === 'whole_admission' ? '整次住院' : '指定分段'}</p>
            {context.stayStartDate && context.stayEndDate ? (
              <p>住院期间：{context.stayStartDate} 至 {context.stayEndDate}</p>
            ) : null}
            {context.segmentCount !== null && context.segmentCount !== undefined ? (
              <p>
                {context.coverageStatus === 'complete'
                  ? `结算分段：${context.segmentCount} 个，已完整汇总`
                  : `结算分段：${context.segmentCount} 个，目前仅匹配 ${context.matchedSegmentCount ?? 0} 个`}
              </p>
            ) : null}
          </div>
        ) : null}

        {amounts.length > 0 ? (
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {amounts.map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-4">
                <dt>{label}</dt>
                <dd className="font-medium tabular-nums text-slate-800">{formatMoney(value)}</dd>
              </div>
            ))}
          </dl>
        ) : null}

        {steps.length > 0 ? (
          <ol className="space-y-3">
            {steps.map((step, index) => (
              <li key={`${step.stepName}-${index}`} className="space-y-1">
                <p className="font-medium text-slate-800">{step.stepName}</p>
                <p className="leading-6">{step.description}</p>
              </li>
            ))}
          </ol>
        ) : null}

        {message.definition ? (
          <div className="space-y-1">
            <p className="font-medium text-slate-800">{message.definition.name}</p>
            <p className="leading-6">{message.definition.plainText}</p>
            {message.definition.excludes.length > 0 ? (
              <p className="text-xs text-slate-500">
                不包括：{message.definition.excludes.join('、')}
              </p>
            ) : null}
          </div>
        ) : null}

        {warnings.length > 0 ? (
          <ul className="space-y-1 text-amber-700">
            {warnings.map((warning) => (
              <li key={warning}>提醒：{warning}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </details>
  )
}
