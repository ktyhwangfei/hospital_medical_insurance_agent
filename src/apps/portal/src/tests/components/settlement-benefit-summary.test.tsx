import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'
import SettlementBenefitSummary from '@/components/policy-qa/settlement-benefit-summary'
import { complementRatio, percentOf, sumAmounts } from '@/lib/fee-explanation-numbers'
import userEvent from '@testing-library/user-event'

afterEach(cleanup)
describe('待遇结论优先', () => {
  it('起付压成两行，待遇和支付表突出金额，条件按段展开', async () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [
      { field_code: 'T_FeeAll', observed_amount: '3000.00' }, { field_code: 'T_FirstPay', observed_amount: '1800.00' },
      { field_code: 'T_FundPay', observed_amount: '420.00' }, { field_code: 'T_SelfPayAll', observed_amount: '2580.00' },
    ], calculations: [
      { explainable: true, calculation_id: 'calc.deductible.split', result: '1800.00', operands: [{ value: '2400.00' }, { value: '0.00' }, { value: '1800.00' }] },
      { explainable: true, calculation_id: 'calc.deductible.copay_base', result: '600.00' },
      { explainable: true, calculation_id: 'calc.big_pay.segment.base.pay', formula_id: 'ordinary_segment_pay_v1', result: '420.00', operands: [{ value: '600.00' }, { value: '0.7', input_ref: 'rate' }] },
    ], formula_inputs: [{ input_id: 'rate', rule_id: 'r', rule_group_ref: 'rate' }], rule_choices: [{ group_id: 'rate', candidates: [{ rule_id: 'r', status: 'unknown', confirmation_status: '待业务签核', checks: [
      { name: '人员身份', actual: '在职', expected: '在职', outcome: 'met' },
      { name: '机构类别', actual: '非社区', expected: '非社区', outcome: 'met' },
      { name: '费用分段', actual: '本笔与此段交集 600.00 元', expected: '基础段', outcome: 'met' },
      { name: '参数可用性', actual: '待业务签核', expected: '日期与确认状态满足计算门控', outcome: 'unknown' },
    ] }] }] })!
    render(<SettlementBenefitSummary data={data} />)
    const deductible = screen.getByRole('region', { name: '起付与基数' })
    expect(within(deductible).getAllByRole('term')).toHaveLength(2)
    expect(within(deductible).getByText('起付（年度）')).toBeVisible()
    expect(within(deductible).getByText(/标准 1800.00 元/)).toBeVisible()
    expect(within(deductible).getByText(/账面起付 1800.00 元/)).toBeVisible()
    expect(within(deductible).getByText(/交易前累计 0.00 元/)).toBeVisible()
    const rates = screen.getByRole('table', { name: '分段待遇（补助前）' })
    expect(within(rates).getByRole('row', { name: /基础段 600.00 70% 30% 已算平/ })).toBeVisible()
    expect(screen.queryByRole('table', { name: /基础段.*条件对照/ })).toBeNull()
    const expand = within(rates).getByRole('button', { name: '基础段：条件与依据' })
    expect(expand).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(expand)
    expect(expand).toHaveAttribute('aria-expanded', 'true')
    const table = screen.getByRole('table', { name: /基础段.*条件对照/ })
    expect(within(table).getByRole('columnheader', { name: '规则要求' })).toBeVisible()
    expect(within(table).getByRole('columnheader', { name: '本单条件' })).toBeVisible()
    expect(within(table).getByText('日期与确认状态满足计算门控')).toBeVisible()
    expect(within(table).getByText('未确认')).toBeVisible()
    const payments = screen.getByRole('table', { name: '实际支付' })
    expect(within(payments).getByRole('row', { name: /基金及补助支付 420.00 14%/ })).toBeVisible()
    expect(within(payments).getByRole('row', { name: /个人支付 2580.00 86%/ })).toBeVisible()
    expect(screen.queryByText(/以上为本次计算采用/)).toBeNull()
    await userEvent.click(expand)
    expect(screen.queryByRole('table', { name: /基础段.*条件对照/ })).toBeNull()
  })
  it.each(['big_pay_capped_v1', 'resident_big_pay_clamp_v1', 'resident_special_big_pay_clamp_v1'])('待遇比例来自计算输入，实际占比独立标注：%s', async (formulaId) => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [
      { field_code: 'T_FeeAll', observed_amount: '1000' }, { field_code: 'T_FundPay', observed_amount: '680' }, { field_code: 'T_SelfPayAll', observed_amount: '320' },
    ], calculations: [{ explainable: true, calculation_id: 'calc.big_pay.capped', formula_id: formulaId, display_name: '基金支付', result: '680', operands: [{ display_name: '起付后基数', value: '800' }, { display_name: '待遇比例', value: '0.85', input_ref: 'rate' }] }], formula_inputs: [{ input_id: 'rate', name: '待遇比例', value: '0.85', rule_group_ref: 'rules-rate', status: 'unverified' }], rule_choices: [{ group_id: 'rules-rate', candidates: [{ rule_id: 'r', status: 'selected', checks: [{ name: '人员身份', actual: '退休', expected: '退休', outcome: 'met' }] }] }] })!
    render(<SettlementBenefitSummary data={data} />)
    expect(within(screen.getByRole('table', { name: '实际支付' })).getByText('68%')).toBeVisible()
    expect(within(screen.getByRole('table', { name: '实际支付' })).getByText('32%')).toBeVisible()
    expect(within(screen.getByRole('table', { name: '分段待遇（补助前）' })).getByRole('row', { name: /800.00 85% 15%/ })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: /条件与依据/ }))
    expect(screen.getByRole('row', { name: /人员身份 退休 退休 符合/ })).toBeVisible()
    expect(screen.queryByText(/取整/)).toBeNull()
  })
  it('退休折算按需展开，定额医院基金不作患者实际支付占比', async () => {
    const data = toFeeDecomposition({ execution_status: 'partial', algorithm_version: 'employee_special_fixed_kidney_v1', fields: [ { field_code: 'ZJE', observed_amount: '100' }, { field_code: 'TCZHF', observed_amount: '1500' } ], calculations: [ { explainable: true, calculation_id: 'calc.pool.segment.x.base', result: '100' }, { explainable: true, calculation_id: 'calc.pool.segment.x.self_ratio', formula_id: 'special_segment_self_ratio_v1', result: '0.07', operands: [{ display_name: '在职自付', value: '0.15' }, { display_name: '退休系数', value: '0.6' }, { display_name: '减点', value: '0.02' }] } ] })!
    render(<SettlementBenefitSummary data={data} />)
    expect(screen.getByRole('row', { name: /100.00 93% 7%/ })).toBeVisible()
    expect(screen.queryByText(/15%×0.6－2%/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /条件与依据/ }))
    expect(screen.getByText(/15%×0.6－2%/)).toBeVisible()
    expect(screen.queryByText('1500%')).toBeNull()
    expect(screen.getByText(/医院定额/)).toBeVisible()
  })
  it('跨段分别显示金额和比例，不把各段合并成一个待遇比例', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', calculations: ['base', 'excess'].map((segment, index) => ({
      explainable: true, calculation_id: segment, formula_id: 'ordinary_segment_pay_v1', display_name: segment === 'base' ? '基础段' : '超限段',
      operands: [{ value: index ? '400.00' : '600.00' }, { value: index ? '0.6' : '0.7' }],
    })) })!
    render(<SettlementBenefitSummary data={data} />)
    const rates = screen.getByRole('table', { name: '分段待遇（补助前）' })
    expect(within(rates).getByRole('row', { name: /基础段 600.00 70% 30%/ })).toBeVisible()
    expect(within(rates).getByRole('row', { name: /超限段 400.00 60% 40%/ })).toBeVisible()
  })
  it('缺少起付计算时保留账面零值，不把零值认定为已经达到起付线', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [{ field_code: 'T_FirstPay', observed_amount: '0.00' }] })!
    render(<SettlementBenefitSummary data={data} />)
    const deductible = screen.getByRole('region', { name: '起付与基数' })
    expect(within(deductible).getByText(/账面起付 0.00 元/)).toBeVisible()
    expect(within(deductible).getByText('算法待补全')).toBeVisible()
    expect(within(deductible).getByText(/标准 未取得/)).toBeVisible()
    expect(within(deductible).getByText(/交易前累计 未取得/)).toBeVisible()
  })
  it('门特用周期起付口径，未提供分段记录时不伪造待遇', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', settlement_facts: { chain: 'special', trade_date: '2026-10-01', metadata_names: { person_type: '退休人员' } }, calculations: [{ explainable: true, calculation_id: 'calc.deductible.split', operands: [{ value: '600' }, { value: '100' }, { value: '1300' }] }] })!
    render(<SettlementBenefitSummary data={data} />)
    expect(screen.getByText('起付（周期）')).toBeVisible()
    expect(screen.getByText(/交易前已交 100.00 元/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /条件与依据/ })).toBeNull()
  })
  it('金额已算平与规则待签核分开表达，展开后保留来源和版本', async () => {
    const data = toFeeDecomposition({ execution_status: 'partial', calculations: [{ explainable: true, calculation_id: 'pay', formula_id: 'ordinary_segment_pay_v1', verification_status: 'verified', operands: [{ value: '600' }, { value: '0.7', input_ref: 'rate' }] }], formula_inputs: [{ input_id: 'rate', rule_id: 'r', rule_group_ref: 'rate' }], rule_choices: [{ group_id: 'rate', candidates: [{ rule_id: 'r', status: 'unknown', source: '比例依据§3', version: 'v2', confirmation_status: '待签核', checks: [] }] }] })!
    render(<SettlementBenefitSummary data={data} />)
    const row = within(screen.getByRole('table', { name: '分段待遇（补助前）' })).getByRole('row', { name: /600.00 70% 30%/ })
    expect(within(row).getByText('已算平')).toBeVisible()
    expect(screen.queryByText('比例依据§3')).toBeNull()
    await userEvent.click(within(row).getByRole('button'))
    expect(screen.getByText('比例依据§3')).toBeVisible()
    expect(screen.getByText('v2')).toBeVisible()
    expect(screen.getByText('待签核')).toBeVisible()
  })
  it('未算平起付只保留账面事实，不能展示下游报销基数解释', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [{ field_code: 'T_FirstPay', observed_amount: '10.00' }], calculations: [{ explainable: false, calculation_id: 'calc.deductible.split', result: '9.00', operands: [{ value: '100' }, { value: '1' }, { value: '10' }] }, { explainable: false, calculation_id: 'calc.deductible.copay_base', result: '91.00', operands: [{ value: '100' }, { value: '9' }] }] })!
    render(<SettlementBenefitSummary data={data} />)
    const deductible = screen.getByRole('region', { name: '起付与基数' })
    expect(within(deductible).getAllByRole('term')).toHaveLength(2)
    expect(within(deductible).getByText('账面起付 10.00 元')).toBeVisible()
    expect(within(deductible).queryByText(/计算起付 9.00/)).toBeNull()
    expect(within(deductible).queryByText('91.00 元')).toBeNull()
    expect(within(deductible).getByText('算法待补全')).toBeVisible()
  })
  it('金额缺失、负数及非法比例不补零，不使用浮点数计算账面占比', () => {
    expect(percentOf('0.1', '0.3')).toBe('33.33%')
    expect(percentOf('-1', '10')).toBeNull()
    expect(percentOf(null)).toBeNull()
    expect(complementRatio('1.1')).toBeNull()
    expect(sumAmounts(['0.1', '0.2'])).toBe('0.3')
    expect(sumAmounts(['0', null])).toBeNull()
  })
})
