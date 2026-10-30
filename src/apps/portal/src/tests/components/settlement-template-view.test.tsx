import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import SettlementBillView from '@/components/policy-qa/settlement-bill-view'
import SettlementSummaryTable from '@/components/policy-qa/settlement-summary-table'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'

const field = (key: string, label: string, value: string | null, row: number, column: number, fieldCode: string | null = null) => ({
  key, label, value, section: 'transaction', row, column, span: 1, scope: 'patient_actual',
  field_code: fieldCode, source_kind: 'record', status: value === null ? 'missing' : 'available',
})
const RAW = {
  schema_version: '1.8', algorithm_version: 'employee_outpatient_v1', execution_status: 'complete',
  reconciliation_status: 'matched', fields: [{ field_code: 'T_FeeIn', label: '旧中文别名',
    observed_amount: '1812.37', calculated_amount: '999', check_type: 'independent_recalculation', check_status: 'mismatched',
    explainable: false, calculation_refs: [], source_refs: [], gap_refs: [] }],
  uncertainties: [], calculations: [], sources: [], conditions: [],
  fee_items: [{ line_id: 'one', total_fee: '999', observed_in_scope: '999' }],
  settlement_facts: { chain: 'outpatient', items: [{ label: '医保范围内金额', value: '888' }], payment_items: [],
    display_template: { template_id: 'employee_outpatient', version: '1.0.0', title: '医保门诊实时结算详细信息查询',
      layout_status: 'image_verified', fields: [
        field('fee_in', '医疗保险范围内金额', '1812.37', 2, 1, 'T_FeeIn'),
        field('fee_all', '费用总金额', '1916.72', 1, 1),
        field('personal_total', '个人支付总金额', '590.29', 1, 2),
        field('cash_pay', '当次个人现金支付金额', '0.00', 8, 1),
        field('beyond_cap', '大额超封顶金额', null, 5, 1),
      ] } },
}

afterEach(cleanup)

describe('配置化结算单共用展示', () => {
  it('费用分解页与解释右栏使用相同的标准名称、金额和布局顺序', () => {
    const data = toFeeDecomposition(RAW)!
    render(<><SettlementBillView feeDecomposition={data} /><SettlementSummaryTable decomposition={data} identifier="T1" /></>)
    const views = screen.getAllByTestId('settlement-template-view')
    expect(views).toHaveLength(2)
    for (const view of views) {
      expect(within(view).getByText('医疗保险范围内金额')).toBeTruthy()
      expect(within(view).getByText('1812.37')).toBeTruthy()
      expect(within(view).queryByText('888.00')).toBeNull()
      expect(within(view).queryByText('999.00')).toBeNull()
      const keys = Array.from(view.querySelectorAll('[data-template-key]')).map(node => node.getAttribute('data-template-key'))
      expect(keys).toEqual(['fee_all', 'personal_total', 'fee_in', 'beyond_cap', 'cash_pay'])
      expect(within(view).getByText('0.00')).toBeTruthy()
      expect(within(view).getByText('未返回')).toBeTruthy()
    }
  })
  it('结算解释侧栏关闭字段说明，工作台仍可展开', () => {
    const raw = { ...structuredClone(RAW), template_explanations: {
      fee_in: { meaning: '医保范围内金额含义', composition: null, basis_text: null, boundary: null },
    } }
    const data = toFeeDecomposition(raw)!
    const { rerender } = render(<SettlementBillView feeDecomposition={data} showFieldExplanations={false} />)
    expect(screen.queryByTestId('template-field-explanation-fee_in')).toBeNull()
    rerender(<SettlementBillView feeDecomposition={data} />)
    expect(screen.getByTestId('template-field-explanation-fee_in')).toBeTruthy()
  })
  it('算法不可用时仍展示已有的原单模板与金额', () => {
    render(<SettlementBillView feeDecomposition={toFeeDecomposition({ ...RAW, fields: [], execution_status: 'unavailable' })!} />)
    expect(screen.getByText('1812.37')).toBeTruthy()
  })
  it('公开解析不透传数据库列与任意配置内容', () => {
    const raw = structuredClone(RAW)
    Object.assign(raw.settlement_facts.display_template.fields[0], { source_table: 'private_table', sql: 'SELECT private' })
    const data = toFeeDecomposition(raw)!
    expect(JSON.stringify(data.settlementFacts?.displayTemplate)).not.toContain('private')
  })
  it('新版本缺少模板时明确提示，不回退到旧名称或明细金额猜测', () => {
    const raw = structuredClone(RAW)
    const data = toFeeDecomposition({ ...raw, schema_version: '1.9', settlement_facts: { ...raw.settlement_facts, display_template: undefined } })!
    render(<SettlementBillView feeDecomposition={data} />)
    expect(screen.getByRole('status').textContent).toContain('模板未配置或内容无效')
    expect(screen.queryByText('旧中文别名')).toBeNull()
  })
})
