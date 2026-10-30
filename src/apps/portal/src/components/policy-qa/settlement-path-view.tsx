import { matchedFeeExplanation, type PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'
import FeeItemBreakdownList from './fee-item-breakdown-list'
import SettlementFieldExplanation from './settlement-field-explanation'
import { FormulaCalculation, formulaRegistry, orderedCalculations, RuleChoiceTable } from './formula-evidence-ledger'
import { plainDescription } from '@/lib/fee-explanation'

const STAGES = [
  { id: 'fees', title: '费用明细与医保内外划分', paths: ['path.fee_items', 'path.catalog_split'], fields: ['T_FeeAll', 'ZJE', 'T_FeeIn', 'T_FeeOut', 'T_SelfPay2', 'YBN', 'YBW', 'TSBYBN', 'TSBYBW', 'GRZIFTW'] },
  { id: 'deductible', title: '起付金额与进入报销的基数', paths: ['path.deductible'], fields: ['T_FirstPay', 'YBNQFJE'] },
  { id: 'fund', title: '统筹与大额支付', paths: ['path.fund'], fields: ['T_BigPay', 'T_BigSelfPay', 'TCZHF', 'TCZIF', 'DEGWYZHF', 'DEGWYZIF', 'GRZIF1'] },
  { id: 'supplements', title: '补助、大病保险与医疗救助', paths: ['path.supplements', 'path.secondary'], fields: ['T_BCPay', 'T_JCPay', 'T_OfficalPay', 'BCZHF', 'JCZHF', 'GFYLBCHBX', 'T_BigillPay', 'NT_CivilPay', 'BIG_ILL_PAY', 'CIVIL_IN', 'FEEIN_DB_PAY', 'FEEOUT_DB_PAY', 'FEEIN_MAF_PAY', 'FEEOUT_MAF_PAY'] },
  { id: 'personal', title: '个人最终承担', paths: ['path.personal_total'], fields: ['T_SelfPayAll', 'PERSON_PAYABLE', 'T_SelfPay1', 'SELF_PAY_1', 'T_FundPay'] },
  { id: 'payment', title: '账户与现金支付', paths: ['path.payment_method'], fields: ['T_PersonCountPay', 'T_CashPay', 'XJZF', 'ZHZF'] },
]
const HOSPITAL_FIELDS = ['QUOTA_AMOUNT', 'AGENCY_PAY', 'TCZHF', 'DEGWYZHF', 'QUOTA.balance']
const OUTCOME: Record<string, string> = { true: '命中', false: '未命中', unknown: '待核实', not_applicable: '不适用', not_evaluated: '未评估', blocked: '已阻断' }
const CATALOG_SUMS = ['calc.catalog.total_fee', 'calc.catalog.total_in_scope', 'calc.catalog.total_out_scope', 'calc.catalog.total_self_pay_2', 'calc.catalog.total_proportional_self_pay', 'calc.detail.total_in_scope']

export default function SettlementPathView({ decomposition }: { decomposition: PolicyQAFeeDecomposition }) {
  const data = matchedFeeExplanation(decomposition)
  const fixed = data.algorithmVersion === 'employee_special_fixed_kidney_v1'
  const steps = data.pathSteps ?? []
  const used = new Set<string>()
  const usedFields = new Set(STAGES.flatMap((stage) => stage.fields))
  if (fixed) HOSPITAL_FIELDS.forEach((code) => usedFields.add(code))
  const take = (refs: string[], fees = false) => orderedCalculations(data, refs).filter((calc) => {
    if (used.has(calc.calculationId) || (fees && !CATALOG_SUMS.includes(calc.calculationId))) return false
    used.add(calc.calculationId)
    return true
  })
  const stages = STAGES.map((stage) => {
    const stageSteps = steps.filter((step) => stage.paths.includes(step.stepId) && !(fixed && step.stepId === 'path.fund'))
    const fields = data.fields.filter((field) => stage.fields.includes(field.fieldCode) && !(fixed && HOSPITAL_FIELDS.includes(field.fieldCode)))
    const refs = [...new Set([...stageSteps.flatMap((step) => step.calculationRefs), ...fields.flatMap((field) => field.calculationRefs)])]
    const calculations = take(refs.filter((ref) => !(fixed && ref === 'calc.fixed.hospital_fund')), stage.id === 'fees')
    const conditionRefs = new Set(stageSteps.flatMap((step) => step.conditionRefs ?? []))
    const conditions = data.conditions.filter((condition) => conditionRefs.has(condition.stepId) || condition.calculationRefs.some((ref) => refs.includes(ref)))
    return { ...stage, fields, stageSteps, calculations, conditions, refs }
  }).filter((stage) => stage.fields.length || stage.stageSteps.length || (stage.id === 'fees' && data.feeItems?.length))
  const hospitalFields = fixed ? data.fields.filter((field) => HOSPITAL_FIELDS.includes(field.fieldCode)) : []
  const hospitalCalcs = take([...hospitalFields.flatMap((field) => field.calculationRefs), ...(fixed ? ['calc.fixed.hospital_fund'] : [])])
  const otherFields = data.fields.filter((field) => !usedFields.has(field.fieldCode) && (!field.fieldCode.includes('.') || !data.fields.some((parent) => field.fieldCode.startsWith(`${parent.fieldCode}.`))))
  const otherCalcs = take(otherFields.flatMap((field) => field.calculationRefs))
  const registry = formulaRegistry(data, [...stages.flatMap((stage) => stage.calculations), ...hospitalCalcs, ...otherCalcs], true)
  const remainingRules = data.ruleChoices?.filter((group) => !registry.firstRule.has(group.groupId)) ?? []
  return <section aria-label="结算路径" className="min-w-0 space-y-6" data-testid="settlement-path-view">
    <p className="text-xs leading-6 text-slate-600">按费用、起付、支付顺序展示本单采用的计算依据。</p>
    <ol className="divide-y divide-slate-200 border-y border-slate-200 bg-white px-4 sm:px-5">
      {stages.map((stage, index) => <li key={stage.id} className="min-w-0 py-5" data-testid={`settlement-stage-${stage.id}`}>
        <h3 className="mb-3 text-base font-semibold text-slate-900">{index + 1}. {stage.title}</h3>
        {stage.id === 'fees' ? <FeeItemBreakdownList items={data.feeItems ?? []} /> : null}
        {stage.calculations.map((calc) => <FormulaCalculation key={calc.calculationId} calculation={calc} data={data} registry={registry} />)}
        {stage.refs.some((ref) => !data.calculations.some((calc) => calc.calculationId === ref)) ? <p className="text-xs text-amber-800">部分计算记录未返回，不能完整展开。</p> : null}
        {stage.conditions.length ? <div className="my-2 max-w-full overflow-x-auto" role="region" aria-label={`${stage.title}结算条件`} tabIndex={0}><table className="w-full min-w-[420px] text-left text-xs leading-6"><thead className="text-slate-600"><tr><th className="px-2 py-1 font-normal">条件</th><th className="px-2 py-1 font-normal">本单判定</th></tr></thead><tbody className="divide-y divide-slate-100">{stage.conditions.map((condition) => <tr key={condition.stepId} className="align-top"><th scope="row" className="px-2 py-2 font-normal text-slate-700">{plainDescription(condition.description)}</th><td className={`px-2 py-2 ${['unknown', 'blocked'].includes(condition.outcome) ? 'text-amber-800' : 'text-slate-700'}`}>{OUTCOME[condition.outcome] ?? '待核实'}</td></tr>)}</tbody></table></div> : null}
        <div className="grid gap-x-6 sm:grid-cols-2">{stage.fields.map((field) => <SettlementFieldExplanation key={field.fieldCode} field={field} decomposition={data} showCalculations={false} />)}</div>
      </li>)}
    </ol>
    {fixed && (hospitalFields.length || hospitalCalcs.length) ? <section className="border-y border-slate-200 bg-white p-5 text-sm" aria-label="医院定额结算">
      <h3 className="text-base font-semibold text-slate-900">医院定额结算</h3>
      <p className="my-2 text-xs leading-6 text-slate-600">医院核定定额与患者实际费用分开。此处为医院基金结算，患者待遇见前面的费用分解。</p>
      {hospitalCalcs.map((calc) => <FormulaCalculation key={calc.calculationId} calculation={calc} data={data} registry={registry} />)}
      {data.conditions.filter((condition) => condition.calculationRefs.some((ref) => ref.startsWith('calc.fixed.'))).map((condition) => <p key={condition.stepId} className="my-2 text-xs leading-6 text-amber-800">{plainDescription(condition.description)} · {OUTCOME[condition.outcome] ?? '待核实'}</p>)}
      {hospitalFields.map((field) => <SettlementFieldExplanation key={field.fieldCode} field={field} decomposition={data} showCalculations={false} />)}
    </section> : null}
    {otherFields.length ? <section className="border-t border-slate-200 bg-white p-5 text-sm"><h3 className="font-semibold text-slate-900">其他结算字段</h3>{otherCalcs.map((calc) => <FormulaCalculation key={calc.calculationId} calculation={calc} data={data} registry={registry} />)}{otherFields.map((field) => <SettlementFieldExplanation key={field.fieldCode} field={field} decomposition={data} showCalculations={false} />)}</section> : null}
    {remainingRules.map((group) => <RuleChoiceTable key={group.groupId} group={group} data={data} registry={registry} />)}
  </section>
}
