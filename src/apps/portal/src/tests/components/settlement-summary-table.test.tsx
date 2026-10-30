import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import SettlementSummaryTable from '@/components/policy-qa/settlement-summary-table'
import { buildSummaryRows } from '@/lib/fee-explanation'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'

afterEach(cleanup)

const RAW = {
  schema_version: '1.6', algorithm_version: 'resident_outpatient_v1', execution_status: 'complete',
  reconciliation_status: 'matched', summary_text: '', summary_source: 'template',
  may_claim_full_explanation: false,
  settlement_facts: {
    chain: 'outpatient', identifier: 'T1', trade_date: '2024-04-08', medical_category: '11',
    insurance_type: '91', person_type: '15', hospital_level: '02',
    metadata_names: { hospital_level: '三级甲等' },
    items: [
      { label: '大额支付', value: '1597.50' },
      { label: '大病保险支付', value: '0.00' },
      { label: '个人支付总金额', value: '1837.50' },
    ],
    payment_items: [{ label: '现金支付', value: '1837.50' }],
  },
  fields: [
    { field_code: 'T_BigPay', label: '大额支付', check_type: 'independent_recalculation', check_status: 'matched',
      observed_amount: '1597.50', calculated_amount: '1597.50', explanation_level: 'causally_explained',
      explainable: true, calculation_refs: ['calc.big_pay.capped'] },
    { field_code: 'T_BigillPay', label: '大病保险支付', check_type: 'independent_recalculation',
      check_status: 'not_applicable', observed_amount: '0.00', explanation_level: 'unexplained', explainable: false },
  ],
  calculations: [
    { calculation_id: 'calc.big_pay.capped', formula: '居民大额支付＝医疗费用基数 3195.00 元×基金支付比例 50%＝1597.50 元',
      display_name: '居民大额支付', formula_id: 'resident_big_pay_clamp_v1', formula_version: '1',
      layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '1597.50' },
  ],
  rule_choices: [
    { group_id: 'rules-ROP-RATE', title: '居民门诊基金支付比例', calculation_refs: ['calc.big_pay.capped'],
      input_refs: [], field_refs: [], candidates: [{ rule_id: 'ROP-RATE-002', name: '门诊基金支付比例-二级及以上',
        value: '50', unit: '%', version: 'V2018-01-01', source: '政策文件', confirmation_status: '待官方核证',
        status: 'selected', reason: '', checks: [
          { name: '机构等级档', actual: '二级及以上（本单机构等级代码 02）', expected: '二级及以上', outcome: 'met' },
        ] }] },
    { group_id: 'rules-ROP-BIGILL', title: '大病保险 · 大病支付', calculation_refs: [], input_refs: [], field_refs: [],
      candidates: [{ rule_id: 'ROP-BIGILL-001', name: '门诊大额封顶后大病保险支付', value: '75', unit: '%',
        version: 'V2021-01-01', source: '实证候选口径', confirmation_status: '待签核', status: 'eligible',
        reason: '本单未进入该待遇分支，未产生本档计算记录', checks: [] }] },
  ],
  fee_items: [],
  uncertainties: [], sources: [], conditions: [],
}

describe('SettlementSummaryTable 条件与未执行档位', () => {
  it('机构等级档把医院名称与档位一起展示', () => {
    render(<SettlementSummaryTable decomposition={toFeeDecomposition(RAW)!} identifier="T1" />)
    fireEvent.click(screen.getByTestId('summary-ratio-fact.大额支付'))
    expect(screen.getByText('三级甲等（二级及以上（本单机构等级代码 02））')).toBeTruthy()
    expect(screen.getAllByText('符合').length).toBeGreaterThan(0)
  })

  it('未执行的大病档位展开后标为未执行而非采用', () => {
    render(<SettlementSummaryTable decomposition={toFeeDecomposition(RAW)!} identifier="T1" />)
    const row = screen.getByTestId('summary-row-fact.大病保险支付')
    expect(row.textContent).not.toContain('采用')
    fireEvent.click(within(row).getByRole('button'))
    expect(screen.getByText(/未执行「门诊大额封顶后大病保险支付」75%/)).toBeTruthy()
  })
})

describe('居民门特模板行：自付一构成与二次保障阶段', () => {
  const field = (code: string, label: string, observed: string, extra: Record<string, unknown> = {}) => ({
    field_code: code, label, check_type: 'independent_recalculation', check_status: 'matched',
    observed_amount: observed, calculated_amount: observed, explanation_level: 'causally_explained',
    explainable: true, ...extra,
  })
  const calc = (id: string, formula: string, result: string) => ({
    calculation_id: id, formula, display_name: id, formula_id: 'x', formula_version: '1',
    layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result,
  })
  const RAW_688 = {
    schema_version: '1.6', algorithm_version: 'resident_outpatient_special_v1',
    execution_status: 'complete', reconciliation_status: 'matched', summary_text: '',
    summary_source: 'template', may_claim_full_explanation: false,
    settlement_facts: {
      chain: 'special', identifier: '688', trade_date: '2024-09-25', medical_category: '12',
      insurance_type: '93', person_type: '25', hospital_level: '03', metadata_names: {},
      items: [], payment_items: [],
      display_template: {
        template_id: 'resident_special', version: '1.0.0', title: '结算信息',
        layout_status: 'provisional',
        fields: [
          { key: 'self_pay_1', label: '个人支付自付（一）金额', section: 'transaction', row: 5, column: 2, span: 1, scope: 'patient_actual', source_kind: 'derived', status: 'available', field_code: 'GRZIF1', value: '279.27', semantic_label: '个人支付自付（一）金额' },
          { key: 'big_ill_pay', label: '大病支付', section: 'transaction', row: 9, column: 1, span: 1, scope: 'patient_actual', source_kind: 'record', status: 'available', field_code: 'BIG_ILL_PAY', value: '226.96', semantic_label: '大病支付' },
          { key: 'aid_pay', label: '救助支付', section: 'transaction', row: 9, column: 2, span: 1, scope: 'patient_actual', source_kind: 'record', status: 'available', field_code: 'CIVIL_IN', value: '122.21', semantic_label: '救助支付' },
        ],
      },
    },
    fields: [
      field('GRZIF1', '个人支付自付（一）金额', '279.27', { check_type: 'identity_check', explainable: false, calculation_refs: ['calc.self_pay_1.parts'] }),
      field('BIG_ILL_PAY', '大病支付', '226.96', { calculation_refs: ['calc.secondary.big_ill_pay'] }),
      field('CIVIL_IN', '救助支付', '122.21', { calculation_refs: ['calc.secondary.civil_in'] }),
      field('FEEIN_DB_PAY', '医保内个人自付一的大病支付', '181.53'),
      field('FEEOUT_DB_PAY', '按比例先行自付的大病支付', '45.43'),
      field('FEEIN_MAF_PAY', '医保内剩余个人负担的救助', '97.74'),
      field('FEEOUT_MAF_PAY', '按比例先行自付剩余负担的救助', '24.47'),
    ],
    calculations: [
      calc('calc.self_pay_1.parts', '个人支付自付（一）金额＝居民门特起付线 0.00 ＋ 大额自付 279.27＝279.27 元', '279.27'),
      calc('calc.secondary.big_ill_pay', '大病保险支付合计＝181.53＋45.43＝226.96 元', '226.96'),
      calc('calc.secondary.civil_in', '民政救助＝97.74＋24.47＝122.21 元', '122.21'),
      calc('calc.secondary.current_base', '本笔合规个人负担总基数＝279.27＋69.90＝349.17 元', '349.17'),
      calc('calc.secondary.remaining_base', '大病后合规剩余总基数＝97.74＋24.47＝122.21 元', '122.21'),
      calc('calc.secondary.person_payable', '二次保障后个人应付＝0.00 元', '0.00'),
    ],
    rule_choices: [], uncertainties: [], sources: [], conditions: [],
  }

  it('自付一标注计算构成，二次保障阶段与四个分项可见', () => {
    const data = toFeeDecomposition(RAW_688)!
    const { rows } = buildSummaryRows(data)
    const selfPay1 = rows.find((row) => row.key === 'self_pay_1')!
    expect(selfPay1.notes.join('')).toContain('计算构成（非原单记录）')
    expect(rows.find((row) => row.key === 'secondary_base')?.value).toBe('349.17')
    expect(rows.find((row) => row.key === 'secondary_after_db')?.value).toBe('122.21')
    expect(rows.find((row) => row.key === 'secondary_person')?.value).toBe('0.00')
    const bigIll = rows.find((row) => row.key === 'big_ill_pay')!
    expect(bigIll.notes.join('')).toContain('医保内个人自付一的大病支付 181.53 元')
    expect(bigIll.notes.join('')).toContain('按比例先行自付的大病支付 45.43 元')
    const aid = rows.find((row) => row.key === 'aid_pay')!
    expect(aid.notes.join('')).toContain('医保内剩余个人负担的救助 97.74 元')
  })
})
