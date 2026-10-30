import { describeFeeField, feeFieldDisplayLabel } from '@/lib/fee-field-algorithms'
import type { PolicyQAFeeDecomposition, PolicyQAFeeDecompositionField } from '@/lib/policy-qa-stream'
import FieldExplanationBlock from './field-explanation-block'
import { FormulaCalculation, formulaRegistry, orderedCalculations, type FormulaRegistry } from './formula-evidence-ledger'
import { decimalUnits } from '@/lib/fee-explanation-numbers'

const LEVEL = { causally_explained: '已记录独立分解', amount_reconciled: '仅验证金额关系', observed_only: '仅账面金额', unexplained: '计算依据待补充' }

export default function SettlementFieldExplanation({ field, decomposition, showCalculations = true, registry, calculationIds }: {
  field: PolicyQAFeeDecompositionField
  decomposition: PolicyQAFeeDecomposition
  showCalculations?: boolean
  registry?: FormulaRegistry
  calculationIds?: string[]
}) {
  // 阶段 B：四要素固定说明对所有展示字段可用（含非 explainable 字段）；
  // 两者皆无时保持原行为不渲染。
  if (!field.explainable && !field.explanation) return null
  const algorithm = describeFeeField(field, decomposition)
  const calculations = calculationIds ? calculationIds.flatMap((ref) => decomposition.calculations.find((calc) => calc.calculationId === ref) ?? []) : orderedCalculations(decomposition, field.calculationRefs)
  const inputRegistry = registry ?? formulaRegistry(decomposition, calculations)
  const independentlyVerified = field.explainable === true
  const gaps = decomposition.uncertainties.filter((gap) => field.gapRefs.includes(gap.id) || gap.affectedFields.includes(field.fieldCode))
  const auxiliary = decomposition.fields.filter((item) => item.fieldCode.startsWith(`${field.fieldCode}.`))
  const difference = decimalUnits(field.difference)
  const materialDifference = difference === null || difference > BigInt(10000) || difference < -BigInt(10000)
  return (
    <article className="min-w-0 space-y-2 border-b border-slate-200 py-4 last:border-0" data-testid={`fee-field-${field.fieldCode}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-semibold text-slate-900">{feeFieldDisplayLabel(field)}</h4>
        <p className="tabular-nums text-slate-900">账面 {field.observedAmount ?? '—'} 元{field.calculatedAmount !== null ? independentlyVerified ? ` · 独立计算 ${field.calculatedAmount} 元` : ' · 独立计算待核实' : ''}</p>
      </div>
      {showCalculations && algorithm.formula ? <p className="break-words leading-6 text-slate-700">计算公式：{algorithm.formula}</p> : null}
      {field.explanation ? (
        <FieldExplanationBlock explanation={field.explanation} testId={`field-explanation-${field.fieldCode}`} />
      ) : null}
      {showCalculations ? calculations.map((calc) => <FormulaCalculation key={calc.calculationId} calculation={calc} data={decomposition} registry={inputRegistry} />) : null}
      {field.checkStatus === 'not_applicable' || field.checkType === 'identity_check' ? <p className="text-xs leading-6 text-slate-600">{field.checkStatus === 'not_applicable' ? '本单不适用' : '账面金额关系，仅作辅助核对'}</p> : null}
      {field.checkStatus === 'mismatched' && materialDifference ? <p className="font-medium text-red-700">计算与账面不符，差额 {field.difference ?? '未返回'} 元。</p> : null}
      {gaps.map((gap) => <p key={gap.id || gap.code} className="text-xs leading-6 text-slate-600">来源说明：{gap.message}</p>)}
      <details className="text-xs leading-6 text-slate-600">
        <summary className="cursor-pointer py-1 focus-visible:outline-2">字段代码、来源与金额关系</summary>
        <p>字段代码：{field.fieldCode}</p>
        <p>{algorithm.meaning} · {LEVEL[field.explanationLevel]}</p>
        {algorithm.note ? <p>{algorithm.note}</p> : null}
        {field.calculatedAmount !== null && !independentlyVerified ? <p>候选计算记录值：{field.calculatedAmount} 元，适用性仍需按输入证据核实。</p> : null}
        {field.brief ? <p>计算说明：{field.brief}</p> : null}
        {field.sourceRefs.length === 0 ? <p>本字段未返回关联来源。</p> : field.sourceRefs.map((ref) => {
          const source = decomposition.sources.find((item) => item.refId === ref)
          return <p key={ref}>{source ? `${source.title}${source.confirmationStatus ? `（${source.confirmationStatus}）` : ''}${source.value !== null ? `：${source.value}` : ''}${source.values.length ? `：${source.values.join('、')}` : ''}` : '关联来源未返回'}</p>
        })}
        {auxiliary.map((item) => <p key={item.fieldCode}>{feeFieldDisplayLabel(item)}：账面 {item.observedAmount ?? '—'} 元，关系计算 {item.calculatedAmount ?? '未确定'} 元{item.difference !== null ? `，差额 ${item.difference} 元` : ''}。</p>)}
      </details>
    </article>
  )
}
