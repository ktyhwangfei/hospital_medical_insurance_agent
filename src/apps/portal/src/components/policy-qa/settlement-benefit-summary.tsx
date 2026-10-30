'use client'

import { Fragment, useState } from 'react'
import type { PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'
import { complementRatio, decimalUnits, percentOf, sumAmounts } from '@/lib/fee-explanation-numbers'
import { formatDecimal2 } from '@/lib/policy-qa-settlement-list'

const amount = (value: string | null | undefined) => value == null ? '未取得' : formatDecimal2(value)

function currentRates(data: PolicyQAFeeDecomposition) {
  return data.calculations.flatMap((calc) => {
    if (!calc.explainable) return []
    let ratio: string | null = null
    let base: string | null = calc.operands[0]?.value ?? null
    let logic = ''
    if (calc.formulaId === 'special_segment_self_ratio_v1') {
      ratio = complementRatio(calc.result)
      base = data.calculations.find((item) => item.calculationId === calc.calculationId.replace(/self_ratio$/, 'base'))?.result ?? null
      logic = `个人比例＝${percentOf(calc.operands[0]?.value) ?? '待补'}×${calc.operands[1]?.value ?? '待补'}${decimalUnits(calc.operands[2]?.value) ? `－${percentOf(calc.operands[2]?.value) ?? '待补'}` : ''}＝${percentOf(calc.result) ?? '待补'}；基金比例＝100%－个人比例`
    } else if (['ordinary_segment_pay_v1', 'big_pay_capped_v1', 'resident_big_pay_clamp_v1', 'resident_special_big_pay_clamp_v1'].includes(calc.formulaId)) {
      ratio = calc.operands[1]?.value ?? null
      logic = `${calc.formulaId === 'ordinary_segment_pay_v1' ? '' : '封顶前'}基金＝本段报销基数×${percentOf(ratio) ?? '待补'}；个人比例${percentOf(complementRatio(ratio)) ?? '待补'}（补助前）`
    } else if (calc.formulaId === 'special_large_fund_v1') {
      const parts = [calc.operands[1]?.value, calc.operands[2]?.value]
      ratio = sumAmounts(parts)
      logic = `基金比例＝基本比例 ${percentOf(parts[0]) ?? '待补'}＋降低自付 ${percentOf(parts[1]) ?? '待补'}`
    }
    if (!ratio || !percentOf(ratio) || (decimalUnits(base) ?? BigInt(0)) <= BigInt(0)) return []
    const inputRefs = calc.operands.map((op) => op.inputRef)
    const ruleIds = data.formulaInputs?.filter((input) => inputRefs.includes(input.inputId)).flatMap((input) => input.ruleId ? [input.ruleId] : []) ?? []
    const groups = data.ruleChoices?.filter((group) => group.calculationRefs.includes(calc.calculationId) || data.formulaInputs?.some((input) => inputRefs.includes(input.inputId) && input.ruleGroupRef === group.groupId)) ?? []
    const candidates = groups.flatMap((group) => group.candidates.filter((row) => ruleIds.length ? ruleIds.includes(row.ruleId) : row.status === 'selected' || row.status === 'eligible'))
    const checks = candidates.flatMap((row) => row.checks).filter((check, index, all) => all.findIndex((other) => other.name === check.name && other.actual === check.actual && other.expected === check.expected && other.outcome === check.outcome) === index)
    const name = candidates.find((row) => row.checks.some((check) => check.name === '费用分段'))?.checks.find((check) => check.name === '费用分段')?.expected ?? groups[0]?.title ?? calc.displayName
    return [{ calc, ratio, base, logic, checks, candidates, name }]
  })
}

export default function SettlementBenefitSummary({ data }: { data: PolicyQAFeeDecomposition }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const field = (...codes: string[]) => data.fields.find((item) => codes.includes(item.fieldCode))?.observedAmount ?? null
  const fact = (label: string) => data.settlementFacts?.items.find((item) => item.label === label)?.value ?? null
  const fixed = data.algorithmVersion === 'employee_special_fixed_kidney_v1'
  const total = field('T_FeeAll', 'ZJE') ?? fact('费用总金额') ?? fact('总费用')
  const special = data.settlementFacts?.chain === 'special' || data.algorithmVersion.includes('special')
  const fund = fixed ? null : field('T_FundPay') ?? (special ? sumAmounts(['统筹基金支付', '大额互助支付', '退休补助', '军残补助', '公疗补助', '大病保险支付', '民政救助支付'].map(fact)) : fact('基金合计'))
  const personal = field('T_SelfPayAll') ?? fact('个人支付总金额') ?? (special ? sumAmounts(data.settlementFacts?.paymentItems.map((item) => item.value) ?? []) : null)
  const rates = currentRates(data)
  const noBenefit = !!data.feeItems?.length && data.feeItems.every((item) => item.divisionMethod === 'settlement_override')
  const paid = sumAmounts([fund, personal])
  const difference = paid !== null && total !== null ? decimalUnits(paid)! - (decimalUnits(total) ?? decimalUnits(paid)!) : BigInt(0)
  const paymentConflict = difference > BigInt(10000) || difference < -BigInt(10000)
  const supplements = data.fields.filter((item) => ['T_BCPay', 'T_JCPay', 'T_OfficalPay', 'T_BigillPay', 'NT_CivilPay', 'BCZHF', 'JCZHF', 'GFYLBCHBX', 'BIG_ILL_PAY', 'CIVIL_IN'].includes(item.fieldCode) && (decimalUnits(item.observedAmount) ?? BigInt(0)) > BigInt(0))
  const baseCalc = data.calculations.find((calc) => calc.explainable && calc.calculationId === 'calc.deductible.copay_base')
  const deductibleCalc = data.calculations.find((calc) => calc.explainable && calc.calculationId === 'calc.deductible.split')
  const deductible = field('T_FirstPay', 'YBNQFJE')
  const inScope = baseCalc?.operands[0]?.value ?? deductibleCalc?.operands[0]?.value
  const calculatedDeductible = baseCalc?.operands[1]?.value ?? deductibleCalc?.result
  const noRateReason = noBenefit ? '本单全额个人承担；项目目录属性见费用明细。' : '本次未提供分段待遇解释。'
  return <section aria-label="本单待遇结论" className="min-w-0 space-y-4 border-y border-slate-200 bg-white p-4 sm:p-5" data-testid="settlement-benefit-summary">
    <h2 className="text-base font-semibold text-slate-900">待遇与支付核对</h2>
    {data.executionStatus === 'unavailable' ? <p className="text-sm leading-6 text-amber-800">暂无法分解：{data.uncertainties.find((gap) => !gap.code.includes('ROUNDING'))?.message || '结算依据尚不完整。'}</p> : null}
    <section aria-label="起付与基数">
      <dl className="divide-y divide-slate-100 text-xs leading-6">
        <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 py-2"><dt className="text-slate-600">起付（{special ? '周期' : '年度'}）</dt><dd className="flex flex-wrap items-baseline gap-x-4 tabular-nums text-slate-800"><span>标准 {amount(deductibleCalc?.operands[2]?.value)}{deductibleCalc?.operands[2]?.value != null ? ' 元' : ''}</span><span>{special ? '交易前已交' : '交易前累计'} {amount(deductibleCalc?.operands[1]?.value)}{deductibleCalc?.operands[1]?.value != null ? ' 元' : ''}</span><span>账面起付 {amount(deductible)}{deductible != null ? ' 元' : ''}</span></dd></div>
        <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 py-2"><dt className="text-slate-600">报销基数</dt><dd className="flex flex-wrap items-baseline gap-x-3 tabular-nums text-slate-800">{baseCalc?.result != null ? <span>医保范围内 {amount(inScope)} − 计算起付 {amount(calculatedDeductible)} ＝ <strong className="text-sm text-slate-900">{amount(baseCalc.result)} 元</strong></span> : '未取得'}</dd></div>
      </dl>
    </section>
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-900">分段待遇 <span className="font-normal text-slate-600">（补助前）</span></h3>
      {rates.length ? <div className="max-w-full overflow-x-auto" role="region" aria-label="分段待遇表，可横向滚动" tabIndex={0}>
        <table className="w-full min-w-[580px] text-left text-xs leading-6" aria-label="分段待遇（补助前）">
          <thead className="bg-slate-50 text-slate-600"><tr>{['费用段', '本段基数（元）', '基金比例', '个人比例', '依据'].map((label) => <th key={label} scope="col" className="px-2 py-1.5 font-medium">{label}</th>)}</tr></thead>
          <tbody className="divide-y divide-slate-100">{rates.map(({ calc, ratio, base, name, logic, checks, candidates }) => {
            const open = expanded === calc.calculationId
            const status = candidates.some((row) => row.status === 'conflict') ? 'conflict' : candidates.some((row) => row.status === 'unknown' || row.status === 'excluded') || checks.some((check) => check.outcome !== 'met') ? 'unverified' : calc.verificationStatus
            const label = name || '本次支付段'
            return <Fragment key={calc.calculationId}>
              <tr className="align-top"><th scope="row" className="px-2 py-2 font-medium text-slate-800">{label}</th><td className="px-2 py-2 font-semibold tabular-nums text-slate-900">{amount(base)}</td><td className="px-2 py-2 font-semibold tabular-nums text-slate-900">{percentOf(ratio)}</td><td className="px-2 py-2 tabular-nums text-slate-800">{percentOf(complementRatio(ratio))}</td><td className="px-2 py-2"><button type="button" aria-label={`${label}：条件与依据`} aria-expanded={open} aria-controls={`benefit-${calc.calculationId}`} onClick={() => setExpanded(open ? null : calc.calculationId)} className="whitespace-nowrap text-blue-800 underline underline-offset-4 hover:text-blue-900 focus-visible:outline-2">{open ? '收起' : '条件与依据'}</button></td></tr>
              {open ? <tr id={`benefit-${calc.calculationId}`}><td colSpan={5} className="bg-slate-50 px-3 py-3">
                <dl className="mb-2 flex flex-wrap gap-x-6 text-slate-600"><div className="flex gap-2"><dt>人员类别</dt><dd>{data.settlementFacts?.metadataNames?.person_type ?? '未取得'}</dd></div><div className="flex gap-2"><dt>结算日期</dt><dd>{data.settlementFacts?.tradeDate ?? '未取得'}</dd></div></dl>
                <p className="mb-2 text-slate-800">{logic}</p>
                {checks.length ? <table className="w-full text-left" aria-label={`${label}条件对照`}><thead className="text-slate-600"><tr>{['条件', '规则要求', '本单条件', '判定'].map((heading) => <th key={heading} scope="col" className="px-2 py-1 font-medium">{heading}</th>)}</tr></thead><tbody className="divide-y divide-slate-200">{checks.map((check, index) => <tr key={index} className="align-top"><th scope="row" className="px-2 py-1 font-normal">{check.name}</th><td className="px-2 py-1">{check.expected}</td><td className="px-2 py-1">{check.actual ?? '未取得'}</td><td className={`px-2 py-1 ${check.outcome === 'met' ? 'text-emerald-800' : 'text-amber-800'}`}>{({ met: '符合', unmet: '不符', unknown: '未确认' })[check.outcome]}</td></tr>)}</tbody></table> : <p className="text-amber-800">适用条件未取得。</p>}
                {candidates.length ? <table className="mt-2 w-full text-left" aria-label={`${label}规则来源`}><thead className="text-slate-600"><tr>{['规则', '版本', '确认状态', '来源'].map((heading) => <th key={heading} scope="col" className="px-2 py-1 font-medium">{heading}</th>)}</tr></thead><tbody>{candidates.map((candidate) => <tr key={candidate.ruleId} className="align-top"><th scope="row" className="px-2 py-1 font-normal">{candidate.name || candidate.ruleId}</th><td className="px-2 py-1">{candidate.version || '未取得'}</td><td className="px-2 py-1">{candidate.confirmationStatus || '未取得'}</td><td className="px-2 py-1">{candidate.source || '未取得'}</td></tr>)}</tbody></table> : null}
                {status !== 'verified' ? <p className="mt-2 text-amber-800">{calc.verificationReason || '计算输入或适用规则待核实；当前比例为本次计算采用值。'}</p> : null}
              </td></tr> : null}
            </Fragment>
          })}</tbody>
        </table>
      </div> : <p className="text-xs leading-6 text-amber-800">{noRateReason}</p>}
    </section>
    <section aria-label="本单实际支付" className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-900">实际支付</h3>
      <table className="w-full text-left text-xs leading-6" aria-label="实际支付"><thead className="bg-slate-50 text-slate-600"><tr><th scope="col" className="px-2 py-1.5 font-medium">项目</th><th scope="col" className="px-2 py-1.5 text-right font-medium">账面金额（元）</th><th scope="col" className="px-2 py-1.5 text-right font-medium">占总费用</th></tr></thead><tbody className="divide-y divide-slate-100">{[['总费用', total], ['基金及补助支付', fund], ['个人支付', personal]].map(([label, value]) => <tr key={label}><th scope="row" className="px-2 py-2 font-normal text-slate-800">{label}</th><td className="px-2 py-2 text-right text-sm font-semibold tabular-nums text-slate-900">{amount(value)}</td><td className="px-2 py-2 text-right tabular-nums text-slate-600">{label === '总费用' ? '—' : percentOf(value, total ?? '') ?? '未取得'}</td></tr>)}</tbody></table>
      <div className="flex flex-wrap justify-between gap-x-4 text-xs leading-6 text-slate-600"><p>个人支付含个人账户与现金。{fixed ? '医院定额基金另列。' : ''}</p>{supplements.length ? <details><summary className="cursor-pointer text-blue-800 underline underline-offset-4 focus-visible:outline-2">补助明细（{supplements.length}项，已计入支付）</summary><dl>{supplements.map((item) => <div key={item.fieldCode} className="flex justify-between gap-6"><dt>{item.label}</dt><dd className="tabular-nums">{amount(item.observedAmount)} 元</dd></div>)}</dl></details> : null}</div>
      {paymentConflict ? <p className="text-xs leading-6 text-amber-800">支付合计 {amount(paid)} 元与总费用不一致，支付范围待核实。</p> : null}
    </section>
  </section>
}
