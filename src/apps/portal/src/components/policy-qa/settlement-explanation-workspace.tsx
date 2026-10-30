'use client'

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { matchedFeeExplanation, type PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'
import SettlementFieldExplanation from './settlement-field-explanation'
import SettlementPathView from './settlement-path-view'
import { calculationAnchor, formulaRegistry, orderedCalculations, RuleChoiceTable } from './formula-evidence-ledger'
import FeeItemBreakdownList from './fee-item-breakdown-list'
import SettlementBenefitSummary from './settlement-benefit-summary'

export default function SettlementExplanationWorkspace({ decomposition: original }: { decomposition: PolicyQAFeeDecomposition }) {
  const [query, setQuery] = useState('')
  const [view, setView] = useState('path')
  const [deep, setDeep] = useState(false)
  const decomposition = matchedFeeExplanation(original)
  const diagnostics = original.fields.filter((field) => !field.explainable && !field.fieldCode.includes('.') && field.checkStatus !== 'not_applicable')
  const fields = decomposition.fields.filter((field) => !field.fieldCode.includes('.') || !decomposition.fields.some((parent) => field.fieldCode.startsWith(`${parent.fieldCode}.`)))
  const matching = fields.filter((field) => `${field.label} ${field.fieldCode}`.toLowerCase().includes(query.trim().toLowerCase()))
  const seen = new Set<string>()
  const fieldBlocks = matching.map((field) => ({ field, calculations: orderedCalculations(decomposition, field.calculationRefs).filter((calc) => {
    if (seen.has(calc.calculationId)) return false
    seen.add(calc.calculationId)
    return true
  }) }))
  const fieldData = { ...decomposition, ruleChoices: decomposition.ruleChoices?.filter((group) => group.fieldRefs.some((ref) => matching.some((field) => field.fieldCode === ref)) || group.calculationRefs.some((ref) => seen.has(ref))) }
  const registry = formulaRegistry(fieldData, fieldBlocks.flatMap((block) => block.calculations), true, decomposition.ruleChoices)
  const pendingRules = fieldData.ruleChoices?.filter((group) => !registry.firstRule.has(group.groupId)) ?? []
  const targetCalc = decomposition.calculations.find((calc) => ['calc.big_pay.segmented', 'calc.big_pay.capped', 'calc.pool.segmented'].includes(calc.calculationId))
  return (
    <section className="space-y-4" data-testid="settlement-explanation-workspace">
      <SettlementBenefitSummary data={original} />
      {!deep ? <section className="min-w-0 space-y-3 bg-white p-4 sm:p-5" aria-label="简明费用明细"><h2 className="text-base font-semibold text-slate-900">费用明细</h2><FeeItemBreakdownList items={original.feeItems ?? []} /></section> : null}
      {diagnostics.length ? <details className="min-w-0 border-t border-slate-200 bg-white p-4 sm:p-5"><summary className="w-fit cursor-pointer text-sm text-slate-600 focus-visible:outline-2">金额核对记录（{diagnostics.length}项）</summary><div className="mt-3 max-w-full overflow-x-auto" role="region" aria-label="金额核对记录" tabIndex={0}><table className="w-full min-w-[560px] text-left text-xs leading-6"><thead><tr>{['金额项', '账面值', '计算值', '差额'].map((label) => <th key={label} scope="col" className="px-2 py-1 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{diagnostics.map((field) => <tr key={field.fieldCode}><th scope="row" className="px-2 py-2 font-normal">{field.label}</th><td className="px-2 py-2">{field.observedAmount ?? '未取得'}</td><td className="px-2 py-2">{field.calculatedAmount ?? '未取得'}</td><td className="px-2 py-2">{field.difference ?? '未取得'}</td></tr>)}</tbody></table></div></details> : null}
      <details onToggle={(event) => setDeep(event.currentTarget.open)} className="min-w-0 border-t border-slate-200 bg-white p-4 sm:p-5">
        <summary className="w-fit cursor-pointer text-sm font-medium text-blue-800 underline underline-offset-4 focus-visible:outline-2">完整计算依据：结算路径与字段解释</summary>
        {deep ? <div className="mt-4 space-y-4">
      <div className="space-y-2 border-y border-slate-200 bg-white p-4 sm:p-5">
        <h2 className="text-base font-semibold text-slate-900">结算解释</h2>
        {targetCalc && view === 'path' ? <div className="py-2"><p className="break-words text-base font-medium leading-7 text-slate-900">{targetCalc.explainable ? targetCalc.formula : targetCalc.formula?.replace(/＝[^＝]*$/, '＝待核实') || `${targetCalc.displayName}：输入待核实`}</p><div className="mt-2 flex flex-wrap gap-x-6 gap-y-2 text-xs leading-6">{targetCalc.operands.filter((op) => op.calculationRef).map((op, index) => <a key={index} className="text-blue-800 underline underline-offset-4" href={`#${calculationAnchor(op.calculationRef!)}`}>{op.displayName} · {op.value} · {decomposition.formulaInputs?.find((item) => item.inputId === op.inputRef)?.status === 'verified' ? '已核实' : '待核实'}</a>)}</div><p className="mt-1 text-xs leading-6 text-slate-600">输入及比例判定沿结算顺序列于下方。<a className="ml-2 text-blue-800 underline underline-offset-4" href={`#${calculationAnchor(targetCalc.calculationId)}`}>定位支付公式</a></p></div> : null}
        {decomposition.uncertainties.length ? <div data-testid="fee-decomposition-uncertainties" className="space-y-1 text-sm leading-6 text-amber-800">{decomposition.uncertainties.filter((gap) => !gap.affectedFields.some((code) => fields.some((field) => field.fieldCode === code))).map((gap) => <p key={gap.id || gap.code}>{gap.message}</p>)}</div> : null}
      </div>
      <Tabs value={view} onValueChange={setView}>
        <TabsList aria-label="结算解释视图" variant="line" className="mb-2 h-10">
          <TabsTrigger value="path" className="px-4">结算路径</TabsTrigger>
          <TabsTrigger value="fields" className="px-4">字段解释</TabsTrigger>
        </TabsList>
        <TabsContent value="path"><SettlementPathView decomposition={decomposition} /></TabsContent>
        <TabsContent value="fields">
          <div className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
            <label className="block text-sm text-slate-700">查找结算字段<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入中文名称或字段代码" className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-slate-600" /></label>
            <p className="mt-3 text-xs leading-6 text-slate-600">与结算路径共用输入、公式和候选判定；重复依赖只展示一次。</p>
            {fieldBlocks.some((block) => block.calculations.some((calc) => calc.calculationId.startsWith('calc.catalog.') || calc.calculationId === 'calc.detail.total_in_scope')) ? <div className="mt-4"><h3 className="mb-2 text-sm font-semibold">共用费用输入</h3><FeeItemBreakdownList items={decomposition.feeItems ?? []} /></div> : null}
            {fieldBlocks.map(({ field, calculations }) => <SettlementFieldExplanation key={field.fieldCode} field={field} decomposition={decomposition} registry={registry} calculationIds={calculations.map((calc) => calc.calculationId)} />)}
            {pendingRules.map((group) => <RuleChoiceTable key={group.groupId} group={group} data={fieldData} registry={registry} />)}
            {!matching.length ? <p className="py-6 text-sm text-slate-600">{fields.length ? '没有匹配的结算字段。' : '本次响应未返回可解释的结算字段。'}</p> : null}
          </div>
        </TabsContent>
      </Tabs>
        </div> : null}
      </details>
    </section>
  )
}
