import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SettlementPathView from '@/components/policy-qa/settlement-path-view'
import { CalculationDetail } from '@/components/policy-qa/fee-decomposition-block'
import SettlementExplanationWorkspace from '@/components/policy-qa/settlement-explanation-workspace'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'

afterEach(cleanup)
const raw = {
  execution_status: 'partial', algorithm_version: 'employee_outpatient_v1',
  fields: [
    { explainable: true, field_code: 'T_FeeIn', label: '医保内费用', observed_amount: '90.00', calculated_amount: '90.00', calculation_refs: ['total'] },
    { field_code: 'T_FirstPay', label: '本次起付', observed_amount: '20.00', calculated_amount: '10.00', difference: '10.00', check_status: 'mismatched', calculation_refs: ['deductible'] },
  ],
  fee_items: [{ explainable: true, line_id: 'a', item_name: '测试药品', unit_price: '100.00', quantity: '1', total_fee: '100.00', status: 'calculated', calculated_in_scope: '90.00', calculated_out_scope: '10.00', calculated_self_pay_2: '10.00', conditions: ['本行采用乙类自付比例 0.1'], formulas: ['先行负担＝取整（100.00×0.1）＝10.00 元', '医保内金额＝100.00－10.00＝90.00 元'] }],
  path_steps: [
    { step_id: 'path.catalog_split', name: '目录划分', status: 'applied', field_refs: ['T_FeeIn'], calculation_refs: ['total'] },
    { step_id: 'path.deductible', name: '起付', status: 'unknown', field_refs: ['T_FirstPay'], calculation_refs: ['deductible'], condition_refs: ['condition'] },
  ],
  calculations: [
    { explainable: true, calculation_id: 'total', display_name: '医保内合计', layout: 'sum', result: '90.00', formula: '医保内合计＝本行医保内 90.00＝90.00 元' },
    { calculation_id: 'deductible', display_name: '起付金额', layout: 'generic', result: '10.00', formula: '起付金额＝较小值（90.00，10.00）＝10.00 元' },
  ],
  conditions: [{ step_id: 'condition', description: '累计口径确认', actual_display: '未确认', outcome: 'unknown' }],
  uncertainties: [{ id: 'gap', code: 'PENDING', message: '累计时点需要确认', affected_fields: ['T_FirstPay'] }],
}

describe('SettlementPathView', () => {
  it('任何未算平金额只进入诊断，不生成原因解释', async () => {
    const data = toFeeDecomposition({ ...raw, fields: [
      { field_code: 'T_FirstPay', label: '本次起付', observed_amount: '1.01', calculated_amount: '1', difference: '0.01', check_status: 'mismatched' },
      { field_code: 'T_BigPay', label: '基金支付', observed_amount: '1.02', calculated_amount: '1', difference: '0.02', check_status: 'mismatched' },
    ] })!
    render(<SettlementExplanationWorkspace decomposition={data} />)
    await userEvent.click(screen.getByText(/金额核对记录/))
    expect(screen.getByRole('cell', { name: '0.01' })).toBeVisible()
    expect(screen.getByRole('cell', { name: '0.02' })).toBeVisible()
    expect(screen.queryByTestId('fee-field-T_FirstPay')).toBeNull()
  })
  it('旧核对视图要求只展示输入时，新增公式不越过这一限制', () => {
    const calculation = toFeeDecomposition({ execution_status: 'partial', calculations: [{ calculation_id: 'c', display_name: '条件计算', formula: '尚未采用的完整公式', result: '5.00' }] })!.calculations[0]
    render(<CalculationDetail calculation={calculation} inputsOnly />)
    expect(screen.queryByText('尚未采用的完整公式')).toBeNull()
    expect(screen.getByText('计算记录结果：5.00 元')).toBeVisible()
  })
  it('费用结果默认可见，展开行后可查完整算式；深度路径仍按业务阶段排序', async () => {
    render(<SettlementPathView decomposition={toFeeDecomposition(raw)!} />)
    expect(screen.getAllByRole('heading', { level: 3 }).map((el) => el.textContent)).toEqual(['1. 费用明细与医保内外划分'])
    expect(screen.queryByText('先行负担＝取整（100.00×0.1）＝10.00 元')).toBeNull()
    await userEvent.click(screen.getByText('查看本行判定路径'))
    expect(screen.getByText('先行负担＝取整（100.00×0.1）＝10.00 元')).toBeVisible()
    expect(screen.queryByRole('rowheader', { name: '累计口径确认' })).toBeNull()
    expect(screen.queryByText(/起付金额＝较小值/)).toBeNull()
    expect(screen.queryByRole('heading', { name: '逐字段核对' })).toBeNull()
  })
  it('未知项目保留负数账面，不能伪造划分算式', () => {
    const data = toFeeDecomposition({ execution_status: 'unavailable', fee_items: [{ line_id: 'a', item_name: '退费项目', total_fee: '-10.00', observed_in_scope: '-10.00', status: 'unknown' }] })!
    render(<SettlementExplanationWorkspace decomposition={data} />)
    const item = screen.getByTestId('fee-item-0')
    expect(item.textContent).toContain('-10.00')
    expect(item.textContent).toContain('算法待补全')
    expect(item.textContent).not.toContain('＝')
  })
  it('字段视图复用同一公式，可用中文或字段码搜索', async () => {
    render(<SettlementExplanationWorkspace decomposition={toFeeDecomposition(raw)!} />)
    await userEvent.click(screen.getByText('完整计算依据：结算路径与字段解释'))
    await userEvent.click(screen.getByRole('tab', { name: '字段解释' }))
    expect(screen.queryByText(/起付金额＝较小值/)).toBeNull()
    await userEvent.type(screen.getByRole('textbox', { name: '查找结算字段' }), 'T_FeeIn')
    expect(screen.getByTestId('fee-field-T_FeeIn')).toBeVisible()
    expect(screen.queryByTestId('fee-field-T_FirstPay')).toBeNull()
  })
  it('定额医院基金与患者统筹自付分开，所有金额保持原值', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', algorithm_version: 'employee_special_fixed_kidney_v1', fields: [
      { field_code: 'TCZHF', label: '医院统筹基金', observed_amount: '210.60', calculated_amount: '210.60' },
      { explainable: true, field_code: 'TCZIF', label: '统筹自付', observed_amount: '5.00', calculated_amount: '5.00', calculation_refs: ['calc.pool.self_pay'] },
    ], calculations: [{ explainable: true, calculation_id: 'calc.pool.self_pay', display_name: '统筹自付', result: '5.00' }] })!
    render(<SettlementPathView decomposition={data} />)
    expect(within(screen.getByTestId('settlement-stage-fund')).queryByText(/210.60/)).toBeNull()
    expect(screen.queryByTestId('fee-field-TCZHF')).toBeNull()
    expect(data.fields[0].observedAmount).toBe('210.60')
  })
})
