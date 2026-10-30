import { Fragment } from 'react'

import { describeFeeField, feeFieldDisplayLabel, type FeeFieldAlgorithm } from '@/lib/fee-field-algorithms'
import type {
  PolicyQAFeeDecomposition,
  PolicyQAFeeDecompositionCalculation,
  PolicyQAFeeDecompositionCondition,
  PolicyQAFeeDecompositionField,
  PolicyQAFeeDecompositionSource,
  PolicyQAFeeDecompositionUncertainty,
} from '@/lib/policy-qa-stream'

/**
 * 费用分解公开结果块（Issue #78，解释投影 1.1）——/fee-decomposition 工作台核对视图。
 *
 * policy-qa 面向患者的展示改用结算单式样的 settlement-bill-view（不暴露核对/重算措辞）；
 * 本组件仅保留给工作台做账实核对。金额为十进制字符串，原样展示，禁止数值化运算。
 * feeDecomposition 为 undefined 时不渲染任何区块。
 * 字段行下方 <details> 就地展开五层解释（是什么/怎么来/为什么这样算/依据在哪里/解释到哪里），
 * 只渲染有数据的层；引用悬空时该层降级提示，不影响行与金额展示。

 */

interface FeeDecompositionBlockProps {
  feeDecomposition?: PolicyQAFeeDecomposition
  showAlgorithms?: boolean
}

const EXECUTION_BADGE: Record<
  PolicyQAFeeDecomposition['executionStatus'],
  { label: string; className: string }
> = {
  complete: { label: '完整', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  partial: { label: '部分', className: 'bg-amber-50 text-amber-700 ring-amber-200' },
  unavailable: { label: '不可用', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
}

const RECONCILIATION_BADGE: Record<string, { label: string; className: string }> = {
  matched: { label: '账实相符', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  mismatched: { label: '账实不符', className: 'bg-red-50 text-red-700 ring-red-200' },
  not_verifiable: { label: '无法核对', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
}

const CHECK_STATUS_BADGE: Record<
  PolicyQAFeeDecompositionField['checkStatus'],
  { label: string; className: string }
> = {
  matched: { label: '相符', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  mismatched: { label: '不符', className: 'bg-red-50 text-red-700 ring-red-200' },
  not_verifiable: { label: '无法核对', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
  not_applicable: { label: '不适用', className: 'bg-slate-50 text-slate-400 ring-slate-200' },
}

const EXPLANATION_LEVEL_LABEL: Record<PolicyQAFeeDecompositionField['explanationLevel'], string> = {
  causally_explained: '因果解释',
  amount_reconciled: '金额勾稽',
  observed_only: '仅账面',
  unexplained: '未解释',
}

function Badge({ label, className }: { label: string; className: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${className}`}
    >
      {label}
    </span>
  )
}

/** 十进制字符串金额原样展示；null → '—'。 */
function amountText(value: string | null): string {
  return value ?? '—'
}

/** 操作数展示：负号提为连接符，绝对值原样字符串（禁止数值化）。 */
function operandDisplay(operand: PolicyQAFeeDecompositionCalculation['operands'][number]): {
  negative: boolean
  text: string
} {
  const negative = operand.value.startsWith('-')
  const absolute = negative ? operand.value.slice(1) : operand.value
  const intermediate = operand.isIntermediate ? '（计算中间量）' : ''
  return { negative, text: `${operand.displayName} ${absolute} 元${intermediate}` }
}

/** 单条计算记录：brief 先行，再按 layout 渲染算式，附取整说明。 */
export function CalculationDetail({ calculation, inputsOnly = false }: {
  calculation: PolicyQAFeeDecompositionCalculation
  inputsOnly?: boolean
}) {
  const layout = inputsOnly ? 'generic' : calculation.layout
  const target =
    calculation.result !== null
      ? `${calculation.displayName} ${calculation.result} 元`
      : calculation.displayName
  return (
    <div className="space-y-1" data-testid={`fee-calc-${calculation.calculationId}`}>
      {!calculation.formula || inputsOnly ? <p className="font-medium text-slate-800">{calculation.displayName}</p> : null}
      {calculation.formula && !inputsOnly ? (
        <p className="break-words leading-7 text-slate-800">{calculation.formula}</p>
      ) : layout === 'sum' ? (
        <p className="leading-6 text-slate-700">
          {target} ＝{' '}
          {calculation.operands
            .map((operand, index) => {
              const { negative, text } = operandDisplay(operand)
              const sign = negative ? '－ ' : index === 0 ? '' : '＋ '
              return `${sign}${text}`
            })
            .join(' ')}
        </p>
      ) : layout === 'subtract_rest' ? (
        // 首项减其余各项：操作数按无符号存储值展示，减号由布局给出
        <p className="leading-6 text-slate-700">
          {target} ＝{' '}
          {calculation.operands
            .map((operand, index) => {
              const intermediate = operand.isIntermediate ? '（计算中间量）' : ''
              const text = `${operand.displayName} ${operand.value} 元${intermediate}`
              return index === 0 ? text : `－ ${text}`
            })
            .join(' ')}
        </p>
      ) : layout === 'product' ? (
        <p className="leading-6 text-slate-700">
          {target} ＝{' '}
          {calculation.operands
            .map((operand) => {
              const intermediate = operand.isIntermediate ? '（计算中间量）' : ''
              return `${operand.displayName} ${operand.value}${intermediate}`
            })
            .join(' × ')}
        </p>
      ) : (
        <ul className="list-inside list-disc space-y-0.5 text-slate-700">
          {calculation.operands.map((operand, index) => (
            <li key={`${operand.displayName}-${index}`}>
              {operand.displayName}：{operand.value}
              {operand.isIntermediate ? '（计算中间量）' : ''}
            </li>
          ))}
        </ul>
      )}
      {(!calculation.formula || inputsOnly) && (inputsOnly || layout === 'generic') && calculation.result !== null ? (
        <p className="text-slate-700">计算记录结果：{calculation.result} 元</p>
      ) : null}
      {calculation.roundingRule ? (
        <p className="text-slate-500">取整：{calculation.roundingRule}</p>
      ) : null}
    </div>
  )
}

/** 条件项：module_label + description + 实际/期望 + outcome（原样展示）。 */
function ConditionDetail({ condition }: { condition: PolicyQAFeeDecompositionCondition }) {
  return (
    <li className="space-y-0.5" data-testid={`fee-condition-${condition.stepId}`}>
      <p className="text-slate-700">
        <span className="font-medium">{condition.moduleLabel}</span>：{condition.description}
      </p>
      {condition.actualDisplay !== null || condition.expectedDisplay !== null ? (
        <p className="text-slate-500">
          {condition.actualDisplay !== null ? `实际 ${condition.actualDisplay}` : ''}
          {condition.actualDisplay !== null && condition.expectedDisplay !== null ? ' / ' : ''}
          {condition.expectedDisplay !== null ? `期望 ${condition.expectedDisplay}` : ''}
        </p>
      ) : null}
      <p className="text-slate-500">结果：{condition.outcome}</p>
    </li>
  )
}

/** 来源项：title + confirmation_status + value + 可选外链。 */
function SourceDetail({ source }: { source: PolicyQAFeeDecompositionSource }) {
  return (
    <li className="space-y-0.5" data-testid={`fee-source-${source.refId}`}>
      <p className="text-slate-700">
        {source.title}
        {source.confirmationStatus ? (
          <span className="ml-1 text-slate-500">（{source.confirmationStatus}）</span>
        ) : null}
      </p>
      {source.value !== null ? <p className="text-slate-500">{source.value}</p> : null}
      {source.link ? (
        <a
          href={source.link}
          target="_blank"
          rel="noreferrer"
          className="text-blue-600 underline hover:text-blue-800"
        >
          {source.link}
        </a>
      ) : null}
    </li>
  )
}

interface FieldExplanationProps {
  field: PolicyQAFeeDecompositionField
  calculations: PolicyQAFeeDecompositionCalculation[]
  sources: PolicyQAFeeDecompositionSource[]
  conditions: PolicyQAFeeDecompositionCondition[]
  uncertainties: PolicyQAFeeDecompositionUncertainty[]
  inputsOnly?: boolean
}

/** 字段行下方五层解释展开体；只渲染有数据的层，悬空引用降级提示。 */
function FieldExplanation({
  field,
  calculations,
  sources,
  conditions,
  uncertainties,
  inputsOnly,
}: FieldExplanationProps) {
  const calculationById = new Map(calculations.map((item) => [item.calculationId, item]))
  const sourceById = new Map(sources.map((item) => [item.refId, item]))
  const gapById = new Map(uncertainties.map((item) => [item.id, item]))
  const relatedConditions = conditions.filter((condition) =>
    condition.calculationRefs.some((ref) => field.calculationRefs.includes(ref)),
  )

  return (
    <div className="mt-2 space-y-3 rounded-lg bg-white px-3 py-3 text-xs leading-5 text-slate-600">
      {/* a. 是什么：状态码原样展示，不美化 */}
      <div className="space-y-0.5">
        <p className="font-medium text-slate-800">是什么</p>
        <p className="text-slate-700">
          {field.label}，账面 {amountText(field.observedAmount)} 元
        </p>
        <p className="font-mono text-slate-500">
          {field.explanationLevel}
          {field.reasonCode ? ` / ${field.reasonCode}` : ''}
        </p>
      </div>

      {/* b. 怎么来：brief 先行 + 引用的计算逐条列出；悬空引用降级 */}
      {field.calculationRefs.length > 0 || (!inputsOnly && field.brief) ? (
        <div className="space-y-1.5">
          <p className="font-medium text-slate-800">{inputsOnly ? '本单计算输入' : '怎么来'}</p>
          {!inputsOnly && field.brief ? <p className="leading-6 text-slate-700">{field.brief}</p> : null}
          {field.calculationRefs.map((ref) => {
            const calculation = calculationById.get(ref)
            return calculation ? (
              <CalculationDetail key={ref} calculation={calculation} inputsOnly={inputsOnly} />
            ) : (
              <p key={ref} className="text-slate-400">
                未记录本步计算
              </p>
            )
          })}
        </div>
      ) : null}

      {/* c. 为什么这样算：与本字段计算有交集的采用条件 */}
      {relatedConditions.length > 0 ? (
        <div className="space-y-1">
          <p className="font-medium text-slate-800">为什么这样算</p>
          <ul className="space-y-1.5">
            {relatedConditions.map((condition) => (
              <ConditionDetail key={condition.stepId} condition={condition} />
            ))}
          </ul>
        </div>
      ) : null}

      {/* d. 依据在哪里：引用的来源；悬空引用降级 */}
      {field.sourceRefs.length > 0 ? (
        <div className="space-y-1">
          <p className="font-medium text-slate-800">依据在哪里</p>
          <ul className="space-y-1.5">
            {field.sourceRefs.map((ref) => {
              const source = sourceById.get(ref)
              return source ? (
                <SourceDetail key={ref} source={source} />
              ) : (
                <li key={ref} className="text-slate-400">
                  依据尚未关联
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}

      {/* e. 解释到哪里：引用的缺口 message；悬空引用降级 */}
      {field.gapRefs.length > 0 ? (
        <div className="space-y-1">
          <p className="font-medium text-slate-800">解释到哪里</p>
          <ul className="list-inside list-disc space-y-0.5 text-amber-800">
            {field.gapRefs.map((ref) => {
              const gap = gapById.get(ref)
              return (
                <li key={ref}>{gap ? gap.message : '依据尚未关联'}</li>
              )
            })}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function FieldAlgorithm({ field, algorithm }: {
  field: PolicyQAFeeDecompositionField
  algorithm: FeeFieldAlgorithm
}) {
  return (
    <div className="space-y-3 py-3 text-sm leading-6 text-slate-700" data-testid={`fee-field-algorithm-${field.fieldCode}`}>
      {algorithm.formula ? (
        <p className="break-words font-medium text-slate-900">{algorithm.formula}</p>
      ) : null}
      {algorithm.steps.length > 0 ? (
        <div>
          <p className="mb-1 font-medium text-slate-900">从费用明细开始</p>
          <ol className="list-decimal space-y-1 pl-5">
            {algorithm.steps.map((step) => <li key={step}>{step}</li>)}
          </ol>
        </div>
      ) : null}
      {algorithm.note ? <p className="text-slate-600">{algorithm.note}</p> : null}
      {field.checkStatus === 'not_verifiable' ? (
        <p className="text-amber-800">本单尚不能独立核对。以上是现有算法的说明，不代表本单已经算出或核对一致。</p>
      ) : field.checkStatus === 'mismatched' ? (
        <p className="text-amber-800">本单计算金额与结算记录存在差异，差额按上方原值保留。</p>
      ) : field.checkStatus === 'not_applicable' ? (
        <p className="text-slate-600">本单该项不适用，不按零金额参与独立核算。</p>
      ) : null}
    </div>
  )
}

export default function FeeDecompositionBlock({ feeDecomposition, showAlgorithms = false }: FeeDecompositionBlockProps) {
  if (!feeDecomposition) return null
  // 只在费用分解工作台启用译文，问答页继续使用原有公开展示。
  const display = showAlgorithms ? {
    ...feeDecomposition,
    fields: feeDecomposition.fields.map((field) => ({ ...field, label: feeFieldDisplayLabel(field) })),
  } : feeDecomposition
  const execution = EXECUTION_BADGE[feeDecomposition.executionStatus]
  const reconciliation =
    RECONCILIATION_BADGE[feeDecomposition.reconciliationStatus] ??
    RECONCILIATION_BADGE.not_verifiable
  const coverage = feeDecomposition.coverage
  const auxiliaryColumn = showAlgorithms ? 'hidden sm:table-cell' : ''

  return (
    <section
      aria-label="费用分解核对"
      data-testid="fee-decomposition-block"
      className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-800">{showAlgorithms ? '逐字段核对' : '费用分解核对'}</h3>
        <Badge label={`分解${execution.label}`} className={execution.className} />
        <Badge label={reconciliation.label} className={reconciliation.className} />
        <span className="ml-auto rounded bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 ring-1 ring-amber-200">
          候选口径·待业务签核
        </span>
      </div>

      {feeDecomposition.summaryText ? (
        showAlgorithms ? <details className="text-sm text-slate-600">
          <summary className="cursor-pointer">查看本单核对汇总</summary>
          <p className="mt-2 whitespace-pre-wrap leading-6">{feeDecomposition.summaryText}</p>
        </details> : <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">
          {feeDecomposition.summaryText}
          {feeDecomposition.summarySource === 'model' ? (
            <span className="ml-1 text-xs text-slate-400">（模型生成摘要）</span>
          ) : null}
        </p>
      ) : null}

      {feeDecomposition.fields.length > 0 ? (
        <div className="overflow-x-auto" data-testid="fee-decomposition-fields">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-1.5 pr-3 font-medium">字段</th>
                <th className="py-1.5 pr-3 text-right font-medium">账面金额</th>
                <th className="py-1.5 pr-3 text-right font-medium">计算金额</th>
                <th className={`py-1.5 pr-3 text-right font-medium ${auxiliaryColumn}`}>差异</th>
                <th className={`py-1.5 pr-3 font-medium ${auxiliaryColumn}`}>解释层级</th>
                <th className={`py-1.5 font-medium ${auxiliaryColumn}`}>核对状态</th>
              </tr>
            </thead>
            <tbody>
              {display.fields.map((field) => {
                const status = CHECK_STATUS_BADGE[field.checkStatus]
                const algorithm = showAlgorithms ? describeFeeField(field, display) : null
                return (
                  <Fragment key={field.fieldCode}>
                    <tr className="border-b border-slate-100">
                      <td className={`py-1.5 pr-3 text-slate-700 ${showAlgorithms ? 'w-1/2 sm:w-auto' : ''}`}>
                        <span>{field.label}</span>
                        {algorithm ? <p className="mt-1 max-w-prose text-slate-600">{algorithm.meaning}</p> : null}
                        {showAlgorithms ? <span className="mt-1 inline-block sm:hidden">
                          <Badge label={status.label} className={status.className} />
                          {field.checkStatus === 'mismatched' ? (
                            <span className="ml-1">差异 {amountText(field.difference)} 元</span>
                          ) : null}
                        </span> : null}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-900">
                        {amountText(field.observedAmount)}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-900">
                        {amountText(field.calculatedAmount)}
                      </td>
                      <td className={`py-1.5 pr-3 text-right font-mono tabular-nums text-slate-900 ${auxiliaryColumn}`}>
                        {amountText(field.difference)}
                      </td>
                      <td className={`py-1.5 pr-3 text-slate-500 ${auxiliaryColumn}`}>
                        {EXPLANATION_LEVEL_LABEL[field.explanationLevel]}
                      </td>
                      <td className={`py-1.5 ${auxiliaryColumn}`}>
                        <Badge label={status.label} className={status.className} />
                      </td>
                    </tr>
                    <tr className="border-b border-slate-100">
                      <td colSpan={6} className="py-1.5">
                        <details data-testid={`fee-field-detail-${field.fieldCode}`}>
                          <summary className="cursor-pointer select-none text-slate-500">
                            查看「{field.label}」的{showAlgorithms ? '算法与中文解释' : '构成解释'}
                          </summary>
                          {algorithm ? <FieldAlgorithm field={field} algorithm={algorithm} /> : null}
                          {algorithm ? <details className="pb-3">
                            <summary className="cursor-pointer text-slate-600">查看本单计算输入和核对依据</summary>
                            <FieldExplanation
                              field={field}
                              calculations={feeDecomposition.calculations}
                              sources={feeDecomposition.sources}
                              conditions={feeDecomposition.conditions}
                              uncertainties={feeDecomposition.uncertainties}
                              inputsOnly
                            />
                          </details> : <FieldExplanation
                            field={field}
                            calculations={feeDecomposition.calculations}
                            sources={feeDecomposition.sources}
                            conditions={feeDecomposition.conditions}
                            uncertainties={feeDecomposition.uncertainties}
                          />}
                        </details>
                      </td>
                    </tr>
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {feeDecomposition.uncertainties.length > 0 ? (
        <ul
          className="list-inside list-disc space-y-1 text-xs text-amber-800"
          data-testid="fee-decomposition-uncertainties"
        >
          {feeDecomposition.uncertainties.map((uncertainty) => (
            <li key={uncertainty.code || uncertainty.id || uncertainty.message}>
              <span className="font-mono">{uncertainty.code}</span>
              {uncertainty.code ? '：' : ''}
              {uncertainty.message}
            </li>
          ))}
        </ul>
      ) : null}

      {coverage ? (
        <div
          className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-200 pt-2 text-[11px] text-slate-500"
          data-testid="fee-decomposition-coverage"
        >
          <span>目标字段 {coverage.targetFieldCount}</span>
          <span>因果解释 {coverage.independentlyExplainedCount}</span>
          <span>金额勾稽 {coverage.amountReconciledCount}</span>
          <span>仅账面 {coverage.observedOnlyCount}</span>
        </div>
      ) : null}
    </section>
  )
}
