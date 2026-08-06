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
  const hasContent = Boolean(context || steps.length || message.definition || warnings.length)
  if (!hasContent) return null

  const amounts = context
    ? [
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
