// 居民门诊链路解释回归：大额支付取本字段公式、自付二构成、未执行比例不称“采用”、
// 结算时限价说明、个人支付构成、封顶条件给实际事实。
import { describe, expect, it } from 'vitest'
import { buildSummaryRows, feeItemExplanation, feeItemReason, ratioDetails } from '@/lib/fee-explanation'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'

const calc = (id: string, formula: string, result: string) => ({
  calculation_id: id, formula, display_name: id, formula_id: 'x', formula_version: '1',
  layout: 'generic', operands: [], unrounded_result: null, rounding_rule: null, result,
})

const RAW = {
  schema_version: '1.6',
  algorithm_version: 'resident_outpatient_v1',
  execution_status: 'complete',
  reconciliation_status: 'matched',
  summary_text: '',
  summary_source: 'template',
  may_claim_full_explanation: true,
  settlement_facts: {
    chain: 'outpatient', identifier: '011100030X240408000002', trade_date: '2024-04-08',
    medical_category: '11', insurance_type: '91', person_type: '15', hospital_level: '02',
    metadata_names: { medical_category: '普通门诊', insurance_type: '城乡居民', person_type: '无业', hospital_level: '三级甲等' },
    items: [
      { label: '费用总金额', value: '3435.00' },
      { label: '医保范围内金额', value: '3195.00' },
      { label: '医保范围外金额', value: '240.00' },
      { label: '自付一', value: '1597.50' },
      { label: '自付二', value: '180.00' },
      { label: '起付金额', value: '0.00' },
      { label: '大额支付', value: '1597.50' },
      { label: '大额个人自付', value: '1597.50' },
      { label: '基金合计', value: '1597.50' },
      { label: '大病保险支付', value: '0.00' },
      { label: '个人支付总金额', value: '1837.50' },
    ],
    payment_items: [{ label: '账户支付', value: '0.00' }, { label: '现金支付', value: '1837.50' }],
  },
  fields: [
    { field_code: 'T_BigPay', label: '大额支付', check_type: 'independent_recalculation', check_status: 'matched',
      observed_amount: '1597.50', calculated_amount: '1597.50', difference: '0.00',
      explanation_level: 'causally_explained', explainable: true,
      calculation_refs: ['calc.big_pay.capped', 'calc.big_pay.self_pay'] },
    { field_code: 'T_BigSelfPay', label: '大额个人自付', check_type: 'independent_recalculation', check_status: 'matched',
      observed_amount: '1597.50', calculated_amount: '1597.50', difference: '0.00',
      explanation_level: 'causally_explained', explainable: true,
      calculation_refs: ['calc.big_pay.self_pay'] },
    { field_code: 'T_SelfPay2', label: '自付二', check_type: 'independent_recalculation', check_status: 'matched',
      observed_amount: '180.00', calculated_amount: '180.00', difference: '0.00',
      explanation_level: 'causally_explained', explainable: true,
      calculation_refs: ['calc.catalog.total_self_pay_2'] },
    { field_code: 'T_BigillPay', label: '大病保险支付', check_type: 'independent_recalculation', check_status: 'not_applicable',
      observed_amount: '0.00', explanation_level: 'unexplained', explainable: false, reason_code: 'RESIDENT_BIGILL_NOT_APPLICABLE' },
    { field_code: 'T_SelfPayAll', label: '最终个人承担', check_type: 'identity_check', check_status: 'matched',
      observed_amount: '1837.50', calculated_amount: '1837.50', explanation_level: 'amount_reconciled', explainable: false,
      calculation_refs: ['calc.identity.self_pay_all'] },
  ],
  calculations: [
    calc('calc.deductible.copay_base', '报销基数＝医保内 3195.00－起付 0.00＝3195.00 元', '3195.00'),
    calc('calc.big_pay.capped', '居民大额支付＝医疗费用基数 3195.00 元×基金支付比例 50%＝1597.50 元', '1597.50'),
    calc('calc.big_pay.self_pay', '大额自付＝大额共付基数 3195.00－大额支付 1597.50＝1597.50 元', '1597.50'),
    calc('calc.catalog.total_self_pay_2', '先行自付合计＝人工晶体 100.00 元 ＋ 培美曲塞 80.00 元＝180.00 元', '180.00'),
    calc('calc.catalog.total_out_scope', '医保外费用合计＝人工晶体 100.00 元 ＋ 培美曲塞 80.00 元 ＋ 小换药 60.00 元＝240.00 元', '240.00'),
    calc('calc.identity.self_pay_all', '最终个人承担＝起付 0.00 ＋ 医保外 240.00 ＋ 大额自付 1597.50＝1837.50 元', '1837.50'),
  ],
  rule_choices: [
    { group_id: 'rules-ROP-RATE', title: '居民门诊基金支付比例', calculation_refs: ['calc.big_pay.capped'],
      input_refs: [], field_refs: [], candidates: [{ rule_id: 'ROP-RATE-002', name: '门诊基金支付比例-二级及以上',
        value: '50', unit: '%', version: 'V2018-01-01', effective_from: '2018-01-01', effective_to: null,
        source: 'mz.docx 城乡居民基本医疗保险-门诊', confirmation_status: '文档明确-待官方核证', status: 'selected', reason: '',
        checks: [{ name: '机构等级档', actual: '二级及以上（本单机构等级代码 02）', expected: '二级及以上', outcome: 'met' },
                 { name: '费用分段', actual: '本笔基数 3195.00 元', expected: '基础段', outcome: 'met' }] }] },
    { group_id: 'rules-ROP-CAP', title: '封顶线 · 不适用', calculation_refs: ['calc.big_pay.capped'],
      input_refs: [], field_refs: [], candidates: [{ rule_id: 'ROP-CAP-003', name: '门诊基金年度最高支付限额（2021 起）',
        value: '4500', unit: '元/保险年度', version: 'V2021-01-01', effective_from: '2021-01-01', effective_to: null,
        source: 'mz.docx 城乡居民基本医疗保险-门诊', confirmation_status: '文档明确-待官方核证', status: 'selected', reason: '',
        checks: [{ name: '年度封顶额度', actual: '交易前已支付 2304.50 元，剩余额度 2195.50 元；本次支付 1597.50 元，未触及上限',
                   expected: '4500 元', outcome: 'met' }] }] },
    { group_id: 'rules-ROP-BIGILL', title: '大病保险 · 大病支付', calculation_refs: [], input_refs: [], field_refs: [],
      candidates: [{ rule_id: 'ROP-BIGILL-001', name: '门诊大额封顶后大病保险支付', value: '75', unit: '%',
        version: 'V2021-01-01', effective_from: '2021-01-01', effective_to: null, source: '实证候选口径',
        confirmation_status: '文档明确-待官方核证', status: 'eligible', reason: '本单未进入该待遇分支，未产生本档计算记录',
        checks: [{ name: '费用分段', actual: '本笔基数 3195.00 元', expected: '基础段', outcome: 'met' }] }] },
  ],
  fee_items: [
    { line_id: '1', item_code: 'M1', item_name: '人工晶体', item_type: '耗材', fee_date: '2024-04-08',
      unit_price: '1935.00', quantity: '1', total_fee: '1935.00', observed_in_scope: '1835.00',
      observed_out_scope: '100.00', observed_self_pay_2: '100.00', status: 'calculated',
      division_method: 'limit', unit_price_limit: '1835.00', settlement_price_limit: '1835.00',
      limit_source: '明细结算时限价', classification_label: '乙类', explainable: true,
      conditions: [], formulas: [], notes: [] },
    { line_id: '2', item_code: 'D1', item_name: '注射用培美曲塞二钠', item_type: '药品', fee_date: '2024-04-08',
      unit_price: '100.00', quantity: '8', total_fee: '800.00', observed_in_scope: '720.00',
      observed_out_scope: '80.00', observed_self_pay_2: '80.00', status: 'calculated',
      division_method: 'ratio', self_pay_ratio: '0.1000', unit_price_limit: '809.0000',
      limit_source: '命中目录的单价限额', ratio_source: '明细结算时比例（正值优先）', a_xbbl: '0.2000',
      classification_label: '乙类西药', explainable: true, conditions: [], formulas: [], notes: [] },
    { line_id: '3', item_code: 'S3', item_name: '小换药', item_type: '诊疗项目', fee_date: '2024-04-08',
      unit_price: '60.00', quantity: '1', total_fee: '60.00', observed_in_scope: '0.00',
      observed_out_scope: '60.00', observed_self_pay_2: '0.00', status: 'calculated',
      division_method: 'full_out', explainable: true, conditions: [], formulas: [], notes: [] },
    { line_id: '4', item_code: 'D4', item_name: '甲类药品', item_type: '药品', fee_date: '2024-04-08',
      unit_price: '640.00', quantity: '1', total_fee: '640.00', observed_in_scope: '640.00',
      observed_out_scope: '0.00', observed_self_pay_2: '0.00', status: 'calculated',
      division_method: 'full_in', classification_label: '甲类', explainable: true,
      conditions: [], formulas: [], notes: [] },
  ],
  uncertainties: [], sources: [], conditions: [],
}

const data = toFeeDecomposition(RAW)!

describe('居民门诊解释', () => {
  it('大额支付行一句话说明基数乘比例，不铺内部封顶公式', () => {
    const row = buildSummaryRows(data).rows.find((item) => item.label === '门诊大额基金支付金额')!
    expect(row.explanation).toBe('本笔共付段基数 3195.00 元 × 基金比例 50% ＝ 1597.50 元；年度封顶剩余额度 2195.50 元，本次未触及')
    expect(row.explanation).not.toContain('较小值')
    expect(row.explanation).not.toContain('大额自付＝')
  })

  it('大额个人自付说明为什么这么多：基数减基金支付，起付与分担比例', () => {
    const row = buildSummaryRows(data).rows.find((item) => item.label === '大额自付金额')!
    expect(row.explanation).toContain('大额个人自付＝共付段基数 3195.00 元 － 基金支付 1597.50 元＝1597.50 元')
    expect(row.explanation).toContain('本笔起付 0.00 元')
    expect(row.explanation).toContain('共付段基金与个人按 50%／50% 分担')
    expect(row.explanation).not.toContain('较小值')
  })

  it('自付二说明构成与被医保外包含，并区分全额自费', () => {
    const row = buildSummaryRows(data).rows.find((item) => item.label === '个人支付自付（二）金额')!
    expect(row.explanation).toContain('超限价自付 100.00 元 ＋ 按比例先行自付 80.00 元＝180.00 元')
    expect(row.explanation).toContain('已包含在医保外 240.00 元中')
    expect(row.explanation).toContain('另有 60.00 元为全额自费项目')
    expect(row.notes.join('')).toContain('人工晶体')
    expect(row.notes.join('')).not.toContain('0.00 元已包含')
  })

  it('个人支付先说医保内个人承担加医保外，账户现金只作支付方式', () => {
    const row = buildSummaryRows(data).rows.find((item) => item.label === '个人支付总金额')!
    expect(row.explanation).toBe('个人支付总金额＝医保内个人承担（自付一）1597.50 元 ＋ 医保范围外 240.00 元＝1837.50 元；账户与现金是支付方式，不重复相加')
    expect(row.notes.join('')).toContain('当次个人现金支付金额 1837.50 元')
  })

  it('未执行的大病 75% 不写作“采用”', () => {
    const row = buildSummaryRows(data).rows.find((item) => item.label === '大病支付')!
    expect(row.explanation ?? '').not.toContain('采用')
    const detail = row.ratios.find((ratio) => ratio.title.includes('大病'))!
    expect(detail.executed).toBe(false)
    expect(detail.chosen).toContain('未执行')
    expect(detail.chosen).toContain('75%')
  })

  it('人工晶体按结算时限价说明，超出 100 元计入自付二', () => {
    const text = feeItemExplanation(data.feeItems![0])!
    expect(text).toContain('按本行结算时限价 1835.00 元纳入医保内')
    expect(text).toContain('超出 100.00 元计入自付二')
    expect(text).not.toContain('门诊限价')
    expect(text).not.toContain('最终自付比例')
    expect(feeItemReason(data.feeItems![0])).toContain('结算时限价')
  })

  it('条件表给出实际事实：机构档/本笔基数/封顶剩余额度', () => {
    const fund = buildSummaryRows(data).rows.find((item) => item.label === '门诊大额基金支付金额')!
    const checks = fund.ratios[0].checks
    expect(checks.find((check) => check.name === '费用分段')!.actual).toBe('本笔基数 3195.00 元')
    expect(checks.find((check) => check.name === '机构等级档')!.actual).toContain('机构等级代码 02')
    const cap = buildSummaryRows(data).rows.find((item) => item.label === '基金支付金额')!
    const capDetail = ratioDetails((data.ruleChoices ?? []).filter((group) => group.groupId === 'rules-ROP-CAP'))[0]
    expect(capDetail.checks[0].actual).toContain('剩余额度 2195.50 元')
    expect(cap).toBeTruthy()
  })

  it('未采用的目录超限参数不与实际比例混写', () => {
    const reason = feeItemReason(data.feeItems![1])!
    expect(reason).toContain('按 10% 计自付二')
    expect(reason).not.toContain('20%')
  })
})

describe('字段映射完整性（567 职工门特·项目口径）', () => {
  // 后端字段 label 取自 011100030X240408000002/567 真实投影（special mz 链）
  const SPECIAL_FIELD_LABELS = [
    ['ZJE', '总费用', '6000.00'],
    ['YBN', '医保内费用', '6000.00'],
    ['YBW', '医保外费用', '0'],
    ['GRZIFTW', '先行自付（明细汇总）', '0.00'],
    ['YBNQFJE', '本次起付金额', '1300.0000'],
    ['TCZHF', '统筹基金支付', '4277.00'],
    ['TCZIF', '统筹自付', '423.00'],
    ['DEGWYZHF', '大额互助支付', '0.00'],
    ['DEGWYZIF', '大额自付', '0.00'],
    ['BCZHF', '退休补助', '211.5000'],
    ['JCZHF', '军残补助', '1511.5000'],
    ['GFYLBCHBX', '公疗补助', '0.0000'],
    ['XJZF', '现金支付', '0.00'],
    ['ZHZF', '账户支付', '0.00'],
    ['BIG_ILL_PAY', '大病保险支付（二次保障）', '0.0000'],
    ['FEEIN_DB_PAY', '医保内个人自付一的大病支付', '0.0000'],
    ['FEEOUT_DB_PAY', '按比例先行自付的大病支付', '0.0000'],
    ['CIVIL_IN', '医疗救助支付', '0.0000'],
    ['FEEIN_MAF_PAY', '医保内剩余个人负担的救助', '0.0000'],
    ['FEEOUT_MAF_PAY', '按比例先行自付剩余负担的救助', '0.0000'],
    ['PERSON_PAYABLE', '个人应付（对照现金与账户合计）', '0.00'],
  ] as const

  function specialData() {
    // facts 条目取自 567 真实登记（yb_mzjyxx 门特口径）
    const facts = {
      ...RAW.settlement_facts, chain: 'special' as const, identifier: '567',
      items: [
        { label: '总费用', value: '6000.00' }, { label: '特殊病医保内', value: '6000.00' },
        { label: '特殊病医保外', value: '0.00' }, { label: '先行自付', value: '0.00' },
        { label: '本次起付金额', value: '1300.0000' }, { label: '统筹基金支付', value: '4277.00' },
        { label: '统筹自付', value: '423.00' }, { label: '大额互助支付', value: '0.00' },
        { label: '大额自付', value: '0.00' }, { label: '退休补助', value: '211.5000' },
        { label: '军残补助', value: '1511.5000' }, { label: '公疗补助', value: '0.0000' },
        { label: '大病保险支付', value: '0.0000' }, { label: '民政救助支付', value: '0.0000' },
        { label: '个人支付总金额', value: null },
      ],
    }
    return toFeeDecomposition({
      ...RAW, settlement_facts: facts,
      fields: SPECIAL_FIELD_LABELS.map(([code, label, value]) => ({
        field_code: code, label, check_type: 'independent_recalculation', check_status: 'matched',
        observed_amount: value, explanation_level: 'amount_reconciled', explainable: false,
      })),
    })!
  }

  it('每个后端字段都映射到页面行，不出现无法解释的缺失', async () => {
    const { buildFieldInventory } = await import('@/lib/fee-explanation')
    const data = specialData()
    const { rows, payments } = buildSummaryRows(data)
    const inventory = buildFieldInventory(data, [...rows, ...payments])
    const unmapped = inventory.filter((item) => !item.shownAsRow)
    expect(unmapped).toEqual([])
    // 抽查关键映射方向正确
    expect(inventory.find((item) => item.fieldCode === 'TCZHF')!.display).toBe('统筹基金支付金额')
    expect(inventory.find((item) => item.fieldCode === 'BCZHF')!.display).toBe('补充保险支付金额')
    expect(inventory.find((item) => item.fieldCode === 'FEEIN_DB_PAY')!.display).toBe('大病支付')
    expect(inventory.find((item) => item.fieldCode === 'PERSON_PAYABLE')!.display).toBe('个人支付总金额')
  })
})

describe('门特模板行：个人支付自付（一）金额', () => {
  const tplField = (key: string, label: string, code: string, value: string, row: number, column: number) => ({
    key, label, section: 'transaction', row, column, span: 1, scope: 'patient_actual',
    source_kind: key === 'self_pay_1' ? 'derived' : 'record', status: 'available',
    field_code: code, value, semantic_label: label,
  })
  const data = toFeeDecomposition({
    ...RAW,
    fields: [
      { field_code: 'GRZIF1', label: '个人支付自付（一）金额', check_type: 'identity_check', check_status: 'matched',
        observed_amount: '1723.00', calculated_amount: '1723.00', explanation_level: 'amount_reconciled',
        explainable: false, calculation_refs: ['calc.self_pay_1.parts'] },
      { field_code: 'YBNQFJE', label: '本次起付金额', check_type: 'independent_recalculation', check_status: 'matched',
        observed_amount: '1300.00', calculated_amount: '1300.00', explanation_level: 'causally_explained', explainable: true },
      { field_code: 'TCZIF', label: '统筹自付', check_type: 'independent_recalculation', check_status: 'matched',
        observed_amount: '423.00', calculated_amount: '423.00', explanation_level: 'causally_explained', explainable: true },
      { field_code: 'DEGWYZIF', label: '大额自付', check_type: 'independent_recalculation', check_status: 'matched',
        observed_amount: '0.00', calculated_amount: '0.00', explanation_level: 'causally_explained', explainable: true },
    ],
    calculations: [
      { calculation_id: 'calc.self_pay_1.parts',
        formula: '个人支付自付（一）金额＝门特起付线拆分 1300.00 ＋ 统筹自付 423.00 ＋ 大额自付 0.00＝1723.00 元',
        display_name: '个人支付自付（一）金额', formula_id: 'self_pay_1_components_v1', formula_version: 'v1',
        layout: 'sum', operands: [], unrounded_result: null, rounding_rule: null, result: '1723.00' },
    ],
    settlement_facts: {
      ...RAW.settlement_facts, chain: 'special' as const, identifier: '567',
      items: [], payment_items: [],
      display_template: {
        template_id: 'employee_special', version: '1.0.0', title: '医保门诊实时结算详细信息查询',
        layout_status: 'provisional',
        fields: [
          tplField('first_pay', '起付金额', 'YBNQFJE', '1300.00', 5, 1),
          tplField('self_pay_1', '个人支付自付（一）金额', 'GRZIF1', '1723.00', 5, 2),
          tplField('pool_self', '统筹自付金额', 'TCZIF', '423.00', 7, 1),
          tplField('big_self_pay', '大额自付金额', 'DEGWYZIF', '0.00', 8, 1),
        ],
      },
    },
  })!

  it('模板行显示自付一并给出分量算式，不再退化成 0 或无解释', () => {
    const row = buildSummaryRows(data).rows.find((item) => item.key === 'self_pay_1')!
    expect(row.label).toBe('个人支付自付（一）金额')
    expect(row.value).toBe('1723.00')
    expect(row.explanation).toContain('个人支付自付（一）金额＝门特起付线拆分 1300.00')
    expect(row.explanation).toContain('统筹自付 423.00')
  })
})
