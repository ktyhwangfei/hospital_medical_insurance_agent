import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'
import { FormulaCalculation, formulaRegistry, orderedCalculations } from '@/components/policy-qa/formula-evidence-ledger'
import SettlementExplanationWorkspace from '@/components/policy-qa/settlement-explanation-workspace'
import userEvent from '@testing-library/user-event'
import FeeItemBreakdownList from '@/components/policy-qa/fee-item-breakdown-list'

const raw = {
  execution_status: 'partial',
  calculations: [
    { calculation_id: 'calc.base', display_name: '报销基数', formula: '报销基数＝费用10－起付0＝10 元', result: '10', verification_status: 'verified', operands: [{ display_name: '原始费用', value: '10', input_ref: 'input-fee' }] },
    { calculation_id: 'calc.pay', display_name: '基金支付', formula: '基金支付＝基数10×比例0.8＝8 元', result: '8', verification_status: 'unverified', verification_reason: '支付比例条件待核实', operands: [{ display_name: '报销基数', value: '10', input_ref: 'input-base', calculation_ref: 'calc.base' }, { display_name: '原始费用', value: '10', input_ref: 'input-fee' }, { display_name: '支付比例', value: '0.8', input_ref: 'input-rate' }] },
  ],
  formula_inputs: [
    { input_id: 'input-fee', name: '原始费用', value: '10', status: 'verified', source: '唯一的费用来源' },
    { input_id: 'input-base', name: '报销基数', value: '10', status: 'verified', source: '上游计算', calculation_ref: 'calc.base' },
    { input_id: 'input-rate', name: '支付比例', value: '0.8', status: 'unverified', source: '当前待遇参数', reason: '身份条件待核实', rule_group_ref: 'rules-rate' },
  ],
  rule_choices: [{ group_id: 'rules-rate', title: '基本基金支付比例', calculation_refs: ['calc.pay'], input_refs: [], candidates: [
    { rule_id: 'a', name: '在职档', value: '70', unit: '%', status: 'excluded', reason: '当前人员为退休', checks: [{ name: '身份', actual: '退休', expected: '在职', outcome: 'unmet' }] },
    { rule_id: 'b', name: '退休档', value: '80', unit: '%', status: 'unknown', reason: '机构条件缺失', checks: [{ name: '机构', actual: null, expected: '非社区', outcome: 'unknown' }] },
  ] }],
}
afterEach(cleanup)

function renderLedger() {
  const data = toFeeDecomposition(raw)!
  const calculations = orderedCalculations(data, ['calc.pay'])
  const registry = formulaRegistry(data, calculations)
  return render(<>{calculations.map((calculation) => <FormulaCalculation key={calculation.calculationId} calculation={calculation} data={data} registry={registry} />)}</>)
}

describe('公式与输入证据', () => {
  it('费用分解页面不展示内部金额资格状态词', async () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [{ field_code: 'T_FirstPay', observed_amount: '10', calculated_amount: '9', check_status: 'mismatched', explanation_reason: '金额不符，算法待补全' }] })!
    const { container } = render(<SettlementExplanationWorkspace decomposition={data} />)
    expect(container.textContent).not.toMatch(/已算平|算法待补全/)
    await userEvent.click(screen.getByText(/金额核对记录/))
    await userEvent.click(screen.getByText('完整计算依据：结算路径与字段解释'))
    expect(container.textContent).not.toMatch(/已算平|算法待补全/)
  })
  it('同一政策跨比例表只出现一次全文来源，复用链接保留各表有效期', () => {
    const candidate = { ...raw.rule_choices[0].candidates[0], source: '唯一的政策文件§支付', version: 'v1', effective_from: '2024-01-01', effective_to: '2025-12-31', confirmation_status: '待签核' }
    const data = toFeeDecomposition({ ...raw, rule_choices: [
      { ...raw.rule_choices[0], candidates: [candidate], calculation_refs: ['calc.pay'] },
      { ...raw.rule_choices[0], group_id: 'rules-factor', calculation_refs: ['calc.base'], candidates: [{ ...candidate, version: 'v2' }] },
    ] })!
    const calculations = orderedCalculations(data, ['calc.pay'])
    const registry = formulaRegistry(data, calculations)
    const { container } = render(<>{calculations.map((calculation) => <FormulaCalculation key={calculation.calculationId} calculation={calculation} data={data} registry={registry} />)}</>)
    expect(screen.getAllByText(/唯一的政策文件§支付/)).toHaveLength(1)
    const link = screen.getByRole('link', { name: /沿用来源 S1/ })
    expect(container.querySelector(link.getAttribute('href')!)).not.toBeNull()
    expect(container.querySelector('#rules-factor')?.textContent).toContain('v2')
    expect(container.querySelector('#rules-rate')?.textContent).toContain('v1')
  })
  it('默认突出分类、集采、限价与实际比例，展开后按本行执行顺序查看', async () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fee_items: [{ explainable: true, line_id: '1', item_name: '药品', classification_label: '乙类', centralized_procurement: true, unit_price: '100', unit_price_limit: '50', status: 'calculated', division_method: 'ratio', self_pay_ratio: '0.2', ratio_basis: '本行费用金额', calculated_in_scope: '80', calculated_out_scope: '20', decision_path: [{ code: 'ncp', label: '集采单价≤限价', actual: '100', expected: '50', outcome: 'false' }], formulas: ['详细代入算式'] }] })!
    render(<FeeItemBreakdownList items={data.feeItems!} />)
    expect(screen.getByText('乙类')).toBeVisible()
    expect(screen.getByText('集采：是')).toBeVisible()
    expect(screen.getByText('采用限价 50.00 元')).toBeVisible()
    expect(screen.getByText('本行费用金额先行自付 20%')).toBeVisible()
    expect(screen.queryByText('详细代入算式')).toBeNull()
    await userEvent.click(screen.getByText('查看本行判定路径'))
    expect(screen.getByText('详细代入算式')).toBeVisible()
    expect(screen.getByRole('row', { name: /集采单价≤限价 100 50 不成立/ })).toBeVisible()
  })
  it('默认明细使用统一的金额格式、范围名称和缺值用语', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fee_items: [{ explainable: true, line_id: 'a', item_name: '药品', item_type: '药品', total_fee: '100.0000', status: 'calculated', division_method: 'full_in', calculated_in_scope: '100.0000', calculated_out_scope: '0', calculated_self_pay_2: '0', conditions: [], formulas: [], notes: [] }] })!
    render(<FeeItemBreakdownList items={data.feeItems!} />)
    expect(screen.getByRole('columnheader', { name: '分解金额（元）' })).toBeVisible()
    expect(screen.getByText('全额纳入医保范围内')).toBeVisible()
    expect(screen.getByText('医保范围内 100.00')).toBeVisible()
    expect(screen.getByText(/集采：未取得/)).toBeVisible()
  })
  it('依赖按上游顺序展示，来源只有首次完整展示，后续引用可定位', () => {
    const { container } = renderLedger()
    expect(screen.getByText('唯一的费用来源')).toBeVisible()
    expect(screen.getAllByText('唯一的费用来源')).toHaveLength(1)
    expect(container.querySelectorAll('#input-fee')).toHaveLength(1)
    expect(screen.getByRole('link', { name: /沿用 I1 的来源/ })).toHaveAttribute('href', '#input-fee')
    expect(screen.getByRole('link', { name: /见 #1 报销基数/ })).toHaveAttribute('href', '#formula-calc-base')
  })
  it('未核实的比例阻断主公式结果，候选运算结果保留在补充记录中', () => {
    renderLedger()
    const payment = within(screen.getByTestId('formula-calc.pay'))
    expect(payment.getByText('基金支付＝基数10×比例0.8＝待核实')).toBeVisible()
    expect(payment.getByText('基金支付＝基数10×比例0.8＝8 元')).not.toBeVisible()
    expect(payment.getByText('支付比例条件待核实')).toBeVisible()
  })
  it('候选档及每档排除、缺证原因默认可见', () => {
    renderLedger()
    expect(screen.getByRole('rowheader', { name: /在职档/ })).toBeVisible()
    expect(screen.getByText('当前人员为退休')).toBeVisible()
    expect(screen.getByText('机构条件缺失')).toBeVisible()
    expect(screen.getByText('无法判断')).toBeVisible()
    expect(screen.getByRole('region', { name: '基本基金支付比例候选档表' })).toHaveAttribute('tabindex', '0')
  })
  it('缺失数值和非法状态不能变成已核实输入，解析器不接收内部字段', () => {
    const result = toFeeDecomposition({ ...raw, formula_inputs: [{ input_id: 'x', value: 10, status: 'verified', source: '记录', sql: 'secret' }, { input_id: 'y', value: '0', status: 'approved', source: '记录' }] })!
    expect(result.formulaInputs?.[0].value).toBeNull()
    expect(result.formulaInputs?.[0].status).toBe('missing')
    expect(result.formulaInputs?.[1].status).toBe('unverified')
    expect(result.formulaInputs?.[0]).not.toHaveProperty('sql')
  })
  it('尚未独立算平的字段仅列核对诊断，候选条件不能拼成解释', async () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [{ field_code: 'T_FirstPay', label: '本次起付', observed_amount: '10' }], rule_choices: [{ ...raw.rule_choices[0], group_id: 'rules-deductible', title: '起付标准', calculation_refs: [], field_refs: ['T_FirstPay'] }] })!
    render(<SettlementExplanationWorkspace decomposition={data} />)
    await userEvent.click(screen.getByText('完整计算依据：结算路径与字段解释'))
    await userEvent.click(screen.getByRole('tab', { name: '字段解释' }))
    expect(screen.queryByText('起付标准：候选档判定')).toBeNull()
    expect(screen.queryByText('机构条件缺失')).toBeNull()
    expect(screen.getByText(/金额核对记录/)).toBeVisible()
  })
})

describe('目录属性取自分解算法字段', () => {
  const item = (over: Record<string, unknown>) => ({ explainable: true, line_id: 'x', item_name: '项目', status: 'calculated',
    division_method: 'full_in', calculated_in_scope: '100', calculated_out_scope: '0', calculated_self_pay_2: '0',
    conditions: [], formulas: [], notes: [], ...over })
  const render1 = (over: Record<string, unknown>) => {
    const data = toFeeDecomposition({ execution_status: 'partial', fee_items: [item(over)] })!
    render(<FeeItemBreakdownList items={data.feeItems!} />)
  }

  it('耗材超结算时限价显示限内纳入、超限自担', () => {
    render1({ item_type: '耗材', division_method: 'limit',
      decision_path: [{ code: 'catalog_match', label: '医用材料目录匹配', operator: 'count_eq', actual: '1', expected: '有效目录条目', outcome: 'true' },
        { code: 'material_price_limit', label: '材料单价超结算时限价：限内纳入、超限自担', operator: 'gt', actual: '1935', expected: '1835', outcome: 'true' }] })
    expect(screen.getByText('耗材 · 限内纳入、超限自担')).toBeVisible()
    expect(screen.queryByText('目录分类未取得')).toBeNull()
  })

  it('耗材按纳入比例纳入时显示比例', () => {
    render1({ item_type: '耗材', included_ratio: '0.8',
      decision_path: [{ code: 'catalog_match', label: '医用材料目录匹配', operator: 'count_eq', actual: '1', expected: '有效目录条目', outcome: 'true' },
        { code: 'material_threshold', label: '材料单价低于纳入门槛', operator: 'lt', actual: '1000', expected: '1000', outcome: 'true' }] })
    expect(screen.getByText('耗材 · 按纳入比例 80% 纳入')).toBeVisible()
  })

  it('无分类时回落到后端命中的目录名称，不再显示未取得分类', () => {
    render1({ item_type: '诊疗项目', decision_path: [{ code: 'catalog_match', label: '诊疗/服务设施目录匹配', operator: 'count_eq', actual: '1', expected: '有效目录条目', outcome: 'true' }] })
    expect(screen.getByText('诊疗/服务设施目录')).toBeVisible()
    expect(screen.queryByText('未取得分类')).toBeNull()
  })

  it('药品无分类时显示药品目录', () => {
    render1({ item_type: '药品', decision_path: [{ code: 'catalog_match', label: '药品目录匹配', operator: 'count_eq', actual: '1', expected: '有效目录条目', outcome: 'true' }] })
    expect(screen.getByText('药品目录')).toBeVisible()
  })
})
