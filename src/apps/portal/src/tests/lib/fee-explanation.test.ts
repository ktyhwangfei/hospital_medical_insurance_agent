// 结算解释投影：交易信息分组/解释门控/比例依据/包含关系，交易明细逐行解释。
import { describe, expect, it } from 'vitest'
import { buildSummaryRows, feeItemExplanation, feeItemReason, formatMoney, plainDescription } from '@/lib/fee-explanation'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'

const field = (label: string, code: string, refs: string[], extra: Record<string, unknown> = {}) => ({
  field_code: code, label, check_type: 'independent_recalculation', check_status: 'matched',
  observed_amount: null, calculated_amount: null, difference: null, explanation_level: 'causally_explained',
  calculation_refs: refs, explainable: true, ...extra,
})

const RAW = {
  schema_version: '1.6',
  algorithm_version: 'employee_outpatient_special_v1',
  execution_status: 'complete',
  reconciliation_status: 'not_verifiable',
  summary_text: '',
  summary_source: 'template',
  may_claim_full_explanation: false,
  settlement_facts: {
    chain: 'special', identifier: '567', trade_date: '2024-04-30',
    medical_category: '12', insurance_type: '3', person_type: '21', hospital_level: '02',
    metadata_names: { medical_category: '门诊特殊病', person_type: '退休', hospital_level: '三级甲等' },
    items: [
      { label: '费用总金额', value: '6000.00' },
      { label: '医保范围内金额', value: '6000.00' },
      { label: '医保范围外金额', value: '0.00' },
      { label: '自付二', value: '0.00' },
      { label: '本次起付金额', value: '1300.00' },
      { label: '统筹基金支付', value: '4277.00' },
      { label: '军残补助', value: '1511.50' },
      { label: '大病保险支付', value: '0.00' },
      { label: '个人支付总金额', value: '0.00' },
    ],
    payment_items: [{ label: '账户支付', value: '0.00' }, { label: '现金支付', value: '0.00' }],
  },
  fields: [
    field('本次起付金额', 'YBNQFJE', ['calc.deductible.split', 'calc.deductible.copay_base']),
    field('统筹基金支付', 'TCZHF', ['calc.pool.segment.ESP-RATE-101.base', 'calc.pool.segment.ESP-RATE-101.self_ratio', 'calc.pool.segmented']),
    field('军残补助', 'JCZHF', ['calc.dvet.amount'], { explainable: false }),
    field('大病保险支付（二次保障）', 'BIG_ILL_PAY', ['calc.secondary.feein_db_pay', 'calc.secondary.big_ill_pay'], { explainable: false }),
    field('最终个人承担', 'T_SelfPayAll', ['calc.identity.self_pay_all'], { explainable: false, check_type: 'identity_check' }),
  ],
  calculations: [
    { calculation_id: 'calc.deductible.split', formula: '门特起付线拆分＝较小值（医保内费用 6000.0000 元，最大值（起付标准 1300 元－交易前已累计 0.0000 元，0））＝1300.0000 元', display_name: '门特起付线拆分', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [{ display_name: '医保内费用合计', value: '6000.0000', is_intermediate: false }, { display_name: '交易前周期医保内累计', value: '0.0000', is_intermediate: false }, { display_name: '门特起付标准', value: '1300', is_intermediate: false }], unrounded_result: null, rounding_rule: null, result: '1300.0000' },
    { calculation_id: 'calc.deductible.copay_base', formula: '报销基数（扣减后）＝明细医保内费用合计 6000.0000 － 门特起付线拆分 1300.0000＝4700.0000 元', display_name: '报销基数（扣减后）', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [{ display_name: '明细医保内费用合计', value: '6000.0000', is_intermediate: false }, { display_name: '门特起付线拆分', value: '1300.0000', is_intermediate: false }], unrounded_result: null, rounding_rule: null, result: '4700.0000' },
    { calculation_id: 'calc.pool.segment.ESP-RATE-101.base', formula: '本段报销基数＝…＝4700.0000 元', display_name: '本段报销基数', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '4700.0000' },
    { calculation_id: 'calc.pool.segment.ESP-RATE-101.self_ratio', formula: '本段实际自付比例＝最大值（在职自付比例 0.15×身份折算系数 0.6－减点 0，0）＝0.090', display_name: '本段实际自付比例', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '0.090' },
    { calculation_id: 'calc.pool.segmented', formula: '统筹基金分段支付＝取整（本段费用 4700.0000 元×（1－本段实际自付比例 0.090））＝4277.00 元', display_name: '统筹基金分段支付', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '4277.00' },
    { calculation_id: 'calc.dvet.amount', formula: '军残补助＝取整（起付自付 1300.0000 元×补助比例 1）＝1511.50 元', display_name: '军残补助', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '1511.50' },
    { calculation_id: 'calc.secondary.feein_db_pay', formula: '大病支付（医保内）＝合规基数为零，不发生本桶大病支付＝0.00 元', display_name: '大病支付（医保内）', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '0.00' },
    { calculation_id: 'calc.secondary.big_ill_pay', formula: '大病保险支付合计＝大病支付（医保内） 0.00 ＋ 大病支付（医保外） 0.00＝0.00 元', display_name: '大病保险支付合计', formula_id: 'x', formula_version: '1', layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result: '0.00' },
    { calculation_id: 'calc.identity.self_pay_all', formula: '最终个人承担账面勾稽＝本次起付承担 1300.00 ＋ 医保外费用 0.00 ＋ 大额个人自付 0.00 ＋ 退休补充保险补助 211.50 ＋ 军残支付 1511.50 ＋ 公疗补充支付 0.00＝3023.00 元', display_name: '最终个人承担账面勾稽', formula_id: 'x', formula_version: '1', layout: 'sum', operands: [], unrounded_result: null, rounding_rule: null, result: '3023.00' },
  ],
  conditions: [{ step_id: 'large.enter', module_label: '大额基金', description: '存在封顶以上费用进入大额互助', actual_display: '0', expected_display: '0', outcome: 'false', calculation_refs: [] }],
  rule_choices: [
    {
      group_id: 'rules-ESP-RATE', title: '统筹分段 · 在职自付基础比例（退休另行折算）', calculation_refs: ['calc.pool.segment.ESP-RATE-101.base'], input_refs: [], field_refs: [],
      candidates: [{ rule_id: 'ESP-RATE-101', name: '统筹分段-三级-起付至1万段-在职', value: '15', unit: '%', version: '2024-04-30', effective_from: '2024-04-30', effective_to: null, source: 'ESP-RATE 参数表', confirmation_status: '候选口径', status: 'selected', reason: '', checks: [{ name: '比例基础档', actual: '在职', expected: '在职', outcome: 'met', input_ref: null }, { name: '住院口径机构档', actual: '三级档', expected: '三级档', outcome: 'met', input_ref: null }] }],
    },
    {
      group_id: 'rules-ESP-RATE-factor', title: '退休自付折算系数', calculation_refs: ['calc.pool.segmented'], input_refs: [], field_refs: [],
      candidates: [{ rule_id: 'ESP-RATE-113', name: '退休人员个人支付比例折算规则', value: '60', unit: '%', version: '2024-04-30', effective_from: null, effective_to: null, source: 'ESP-RATE 参数表', confirmation_status: '候选口径', status: 'selected', reason: '', checks: [{ name: '人员身份', actual: '退休', expected: '退休', outcome: 'met', input_ref: null }] }],
    },
    {
      group_id: 'rules-secondary-db', title: '二次大病保险比例', calculation_refs: [], input_refs: [], field_refs: [],
      candidates: [{ rule_id: 'SDB-1', name: '救助对象 · 第1段', value: '65.00', unit: '%', version: 'v1', effective_from: null, effective_to: null, source: '政策', confirmation_status: '候选口径', status: 'selected', reason: '', checks: [{ name: '救助身份', actual: '救助对象', expected: '救助对象', outcome: 'met', input_ref: null }] }],
    },
  ],
  path_steps: [{ step_id: 'path.supplements', name: '补助', status: 'applied', amount: null, calculation_refs: [], field_refs: ['JCZHF'] }],
  fee_items: [{ line_id: '1', item_code: 'X1', item_name: '他克莫司胶囊', item_type: '药品', total_fee: '6000.0000', observed_in_scope: '6000.0000', observed_out_scope: '0.0000', observed_self_pay_2: '0.00', status: 'calculated', division_method: 'ratio', explainable: true }],
  uncertainties: [], sources: [],
}

describe('fee-explanation', () => {
  const data = toFeeDecomposition(RAW)!

  it('交易信息按结算单分组，金额行来自交易明细合计', () => {
    const { rows } = buildSummaryRows(data)
    expect(rows[0].label).toBe('费用总金额')
    expect(rows[0].group).toBe('费用构成')
    expect(rows[0].explanation).toBe('费用总金额＝他克莫司胶囊 6000.00 元＝6000.00 元')
    expect(rows.map((row) => row.group)).toContain('起付与基金支付')
    expect(rows.at(-1)?.label).toBe('个人支付总金额')
  })

  it('explainable=false 的金额不展开计算原因（恒等式构成的账面金额除外）', () => {
    const { rows } = buildSummaryRows(data)
    const jc = rows.find((row) => row.label === '残疾军人补助支付金额')!
    expect(jc.value).toBe('1511.50')
    expect(jc.explanation).toBeNull()
    expect(jc.expandLabel).toBeNull()
    expect(rows.find((row) => row.label === '个人支付总金额')!.explanation).toContain('最终个人承担账面勾稽')
  })

  it('零金额先回答"为什么是 0"，比例只留在展开里', () => {
    const { rows } = buildSummaryRows(data)
    const big = rows.find((row) => row.label === '大病支付')!
    expect(big.explanation).toBe('大病支付（医保内）＝合规基数为零，不发生本桶大病支付＝0.00 元')
    expect(big.explanation).not.toContain('65')
    expect(big.ratios.map((ratio) => ratio.chosen)).toEqual(['采用「救助对象 · 第1段」65.00%'])
    expect(big.expandLabel).toBe('比例依据')
  })

  it('起付金额默认两句话，完整函数算式进展开', () => {
    const { rows } = buildSummaryRows(data)
    const start = rows.find((row) => row.label === '起付金额')!
    expect(start.explanation).toBe('本结算周期起付标准 1300 元，交易前已承担起付 0.0000 元；本次承担起付 1300.00 元。 医保内 6000.00 元 － 起付 1300.00 元 ＝ 报销基数 4700.00 元。')
    expect(start.notes[0]).toContain('门特起付线拆分＝较小值')
    expect(start.expandLabel).toBe('起付标准依据')
    expect(start.ratios).toEqual([])
  })

  it('待遇比例讲清"在职基础档 × 退休折算系数 = 本段个人比例"', () => {
    const { rows } = buildSummaryRows(data)
    const fund = rows.find((row) => row.label === '统筹基金支付金额')!
    expect(fund.explanation).toContain('在职自付基础 15% × 退休折算系数 60% ＝ 9%')
    expect(fund.explanation).toContain('基金比例 91%')
    expect(fund.explanation).toContain('报销基数 4700.00 元×91%＝4277.00 元')
    expect(fund.ratios[0].checks.map((check) => check.name)).toEqual(['比例基础档', '住院口径机构档'])
    expect(fund.ratios[0].source).toBe('ESP-RATE 参数表')
  })

  it('包含关系经验算成立才展示', () => {
    const raw = { ...RAW, algorithm_version: 'employee_outpatient_v1', settlement_facts: { ...RAW.settlement_facts, chain: 'outpatient', items: [
      { label: '费用总金额', value: '3000.00' }, { label: '医保范围内金额', value: '2400.00' }, { label: '医保范围外金额', value: '600.00' },
      { label: '自付二', value: '600.00' }, { label: '起付金额', value: '1800.00' }, { label: '大额个人自付', value: '180.00' },
      { label: '自付一', value: '1980.00' }, { label: '个人支付总金额', value: '2580.00' },
    ] } }
    const { rows } = buildSummaryRows(toFeeDecomposition(raw)!)
    expect(rows.find((row) => row.label === '个人支付自付（一）金额')!.explanation).toBe('个人支付自付（一）金额＝起付金额 1800.00 元 ＋ 大额自付金额 180.00 元＝1980.00 元')
    expect(rows.find((row) => row.label === '个人支付总金额')!.explanation).toContain('2580.00 元')
  })

  it('去代码化只留中文', () => {
    expect(plainDescription('结算通道分流（T_CureType）')).toBe('结算通道分流')
  })

  it('退役医疗费展示原单事实，基金构成纳入该支付，不给本项待遇公式', () => {
    const raw = { ...RAW, algorithm_version: 'employee_outpatient_v1', fee_items: [], calculations: [],
      rule_choices: [], path_steps: [], fields: [field('退役医疗费支付', 'RETIRE_OFFICER_PAY', [], {
        observed_amount: '44.30', explainable: false, check_status: 'not_verifiable',
      })], settlement_facts: { ...RAW.settlement_facts, chain: 'outpatient', retire_officer_flag: '1', items: [
        { label: '大额支付', value: '155.05' }, { label: '退休补充保险补助', value: '0.00' },
        { label: '军残支付', value: '0.00' }, { label: '公疗补充支付', value: '0.00' },
        { label: '退役医疗费支付', value: '44.30' }, { label: '基金合计', value: '199.35' },
      ] } }
    const data = toFeeDecomposition(raw)!
    expect(data.settlementFacts?.retireOfficerFlag).toBe('1')
    const { rows } = buildSummaryRows(data)
    const payment = rows.find((row) => row.label === '退役医疗费')!
    expect(payment.value).toBe('44.30')
    expect(payment.explanation).toBe('按本单结算记录列示。')
    expect(payment.ratios).toEqual([])
    expect(rows.find((row) => row.label === '基金支付金额')!.explanation).toContain('退役医疗费支付 44.30 元')
    expect(rows.find((row) => row.label === '基金支付金额')!.explanation).toContain('＝199.35 元')
    const missing = toFeeDecomposition({ ...raw, settlement_facts: { ...raw.settlement_facts,
      retire_officer_flag: null,
      items: raw.settlement_facts.items.map((item) => item.label === '退役医疗费支付' ? { ...item, value: null } : item),
    } })!
    expect(missing.settlementFacts?.retireOfficerFlag).toBeNull()
    expect(buildSummaryRows(missing).rows.find((row) => row.label === '基金支付金额')!.explanation).toBeNull()
    expect(toFeeDecomposition({ ...raw, settlement_facts: { ...raw.settlement_facts, retire_officer_flag: '0' } })!.settlementFacts?.retireOfficerFlag).toBe('0')
  })

  it('个人支付的账面构成不一致时，不把候选算式作为解释', () => {
    const data = toFeeDecomposition({ ...RAW, fields: [
      field('最终个人承担', 'T_SelfPayAll', ['calc.identity.self_pay_all'], {
        explainable: false, check_type: 'identity_check', check_status: 'mismatched',
      }),
    ] })!
    expect(buildSummaryRows(data).rows.find((row) => row.label === '个人支付总金额')!.explanation).not.toContain('3023.00')
  })

  it('个人应付相同但上游不可解释时，不展示另一组候选金额', () => {
    const data = toFeeDecomposition({ ...RAW, fields: [
      field('个人应付（对照现金与账户合计）', 'PERSON_PAYABLE', ['calc.secondary.person_payable'], {
        explainable: false, observed_amount: '0.00',
      }),
    ], calculations: [{ calculation_id: 'calc.secondary.person_payable',
      formula: '个人应付＝279.27＋69.90－226.97－122.20＝0.00元', operands: [], result: '0.00' }] })!
    const text = buildSummaryRows(data).rows.find((row) => row.label === '个人支付总金额')!.explanation
    expect(text).not.toContain('226.97')
    expect(text).not.toContain('122.20')
  })

  it('居民门特基本医保字段的新名称可以关联到支付解释', () => {
    const data = toFeeDecomposition({ ...RAW, algorithm_version: 'resident_outpatient_special_v1',
      fee_items: [], rule_choices: [], path_steps: [], settlement_facts: { ...RAW.settlement_facts,
        items: [{ label: '大额互助支付', value: '837.83' }, { label: '大额自付', value: '279.27' }],
      }, fields: [field('基本医保基金支付', 'DEGWYZHF', ['calc.big_pay.capped']),
        field('基本医保基金支付后自付', 'DEGWYZIF', ['calc.big_pay.self_pay'])], calculations: [
        { calculation_id: 'calc.big_pay.capped', formula: '基本医保支付＝1117.10×75%＝837.83元', operands: [], result: '837.83' },
        { calculation_id: 'calc.big_pay.self_pay', formula: '基本医保支付后自付＝1117.10－837.83＝279.27元', operands: [], result: '279.27' },
      ] })!
    const { rows } = buildSummaryRows(data)
    expect(rows.find((row) => row.label === '门诊大额基金支付金额')!.explanation).toContain('75%')
    expect(rows.find((row) => row.label === '大额自付金额')!.explanation).toContain('279.27')
  })
})

describe('交易明细逐行解释', () => {
  const item = (over: Record<string, unknown> = {}) => ({
    line_id: '1', item_code: 'X1', item_name: '注射用培美曲塞二钠', item_type: '药品',
    unit_price: '1000.0000', quantity: '3.00', total_fee: '3000.0000',
    observed_in_scope: '2400.0000', observed_out_scope: '600.00', observed_self_pay_2: '600.00',
    status: 'calculated', division_method: 'ratio', self_pay_ratio: '0.2000', unit_price_limit: '809.0000',
    classification_label: '乙类西药', centralized_procurement: true,
    ratio_source: '明细结算时比例（正值优先）', a_mzxj: '809.0000', explainable: true,
    conditions: [], formulas: [], notes: [], ...over,
  })
  const decompose = (items: unknown[]) => toFeeDecomposition({ ...RAW, fee_items: items, path_steps: [] })!

  it('关键原因把集采、限价、比例与结果串起来', () => {
    const data = decompose([item()])
    const reason = feeItemReason(data.feeItems![0])!
    expect(reason).toContain('集采药')
    expect(reason).toContain('单价 1000.0000 高于限价 809.0000')
    expect(reason).toContain('按 20% 计自付二')
    expect(reason).toContain('自付二 600.00 元、医保内 2400.00 元')
    const text = feeItemExplanation(data.feeItems![0])!
    expect(text).toContain('集采药品')
    expect(text).toContain('按本行限价 809.0000 元纳入医保内')
    expect(text).toContain('超出 573.00 元计入自付二')
    expect(text).toContain('采用明细结算时比例 20%，作用于整笔费用 3000.00 元')
  })

  it('不可解释的行不给原因', () => {
    const data = decompose([item({ explainable: false })])
    expect(feeItemReason(data.feeItems![0])).toBeNull()
    expect(feeItemExplanation(data.feeItems![0])).toBeNull()
  })

  it('未采用的目录参数不进入关键原因', () => {
    const data = decompose([item({ a_xbbl: '0.2000', self_pay_ratio: '0.1000' })])
    expect(feeItemReason(data.feeItems![0])).toContain('按 10% 计自付二')
    expect(feeItemReason(data.feeItems![0])).not.toContain('20%')
    expect(formatMoney('3000.0000')).toBe('3000.00 元')
  })
})
