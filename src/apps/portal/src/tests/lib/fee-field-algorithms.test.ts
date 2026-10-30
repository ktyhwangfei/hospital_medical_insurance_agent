import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { describeFeeField, feeFieldDisplayLabel } from '@/lib/fee-field-algorithms'
import { toFeeDecomposition, type PolicyQAFeeDecomposition, type PolicyQAFeeDecompositionField } from '@/lib/policy-qa-stream'

const FIELD: PolicyQAFeeDecompositionField = {
  fieldCode: 'T_SelfPayAll', label: '最终个人承担',
  observedAmount: '400.00', calculatedAmount: '400.00', difference: '0.00',
  checkType: 'identity_check', checkStatus: 'matched', explanationLevel: 'amount_reconciled',
  reasonCode: null, calculationRefs: [], sourceRefs: [], gapRefs: [], brief: null,
}
const RESULT: PolicyQAFeeDecomposition = {
  schemaVersion: '1.1', algorithmVersion: 'employee_outpatient_v1',
  executionStatus: 'partial', reconciliationStatus: 'not_verifiable',
  summaryText: '', summarySource: 'template', mayClaimFullExplanation: false,
  fields: [FIELD], calculations: [], conditions: [], sources: [], uncertainties: [],
}

describe('费用字段算法译文', () => {
  it('职工和居民普通门诊返回的基本费用字段都有算法译文', () => {
    const codes = ['T_FeeAll', 'T_FeeIn', 'T_FeeOut', 'T_SelfPay2', 'T_FirstPay', 'T_BigPay',
      'T_BigSelfPay', 'T_BCPay', 'T_JCPay', 'T_OfficalPay', 'T_SelfPay1', 'T_FundPay',
      'T_SelfPayAll', 'T_PersonCountPay', 'T_CashPay', 'T_FeeAll.identity', 'T_FeeIn.detail',
      'T_FeeOut.detail', 'T_SelfPay2.detail', 'T_SelfPayAll.vs_fee_all_minus_fund']
    for (const algorithmVersion of ['employee_outpatient_v1', 'resident_outpatient_v1']) {
      for (const fieldCode of codes) {
        expect(describeFeeField({ ...FIELD, fieldCode }, { ...RESULT, algorithmVersion }).meaning, fieldCode).not.toContain('尚未补充')
      }
    }
  })

  it('辅助核对行使用中文名，避免英文代码混进公式', () => {
    expect(feeFieldDisplayLabel({ ...FIELD, fieldCode: 'T_SelfPayAll.vs_fee_all_minus_fund', label: '最终个人承担（对照 FeeAll-FundPay）' })).toBe('最终个人承担（总费用减基金核对）')
    expect(feeFieldDisplayLabel({ ...FIELD, fieldCode: 'TSBYBN.detail', label: '特殊病医保内（明细账面汇总 Σybnje）' })).toBe('特殊病医保内（明细汇总核对）')
  })

  it('个人承担从明细开始，医保外已含自付二，公式不重复相加', () => {
    const algorithm = describeFeeField(FIELD, RESULT)
    expect(algorithm.steps[0]).toContain('费用明细')
    expect(algorithm.formula).toBe('最终个人承担＝本次起付承担＋医保外费用＋大额个人自付－退休补助－军残补助－公疗补助')
    expect(algorithm.formula).not.toContain('自付二')
    expect(algorithm.note).toContain('不重复相加')
  })

  it('使用结算单当前中文名，明细汇总和独立目录计算分别说明', () => {
    const inside = { ...FIELD, fieldCode: 'YBN', label: '本院医保内费用' }
    const employee = describeFeeField(inside, { ...RESULT, algorithmVersion: 'employee_outpatient_special_v1' })
    const resident = describeFeeField({ ...inside, fieldCode: 'TSBYBN' }, { ...RESULT, algorithmVersion: 'resident_outpatient_special_v1' })
    expect(employee.formula).toContain('本院医保内费用＝')
    expect(employee.steps.join('')).toContain('不重新判断')
    expect(resident.steps.join('')).toContain('匹配药品、诊疗或材料目录')
    const aggregation = describeFeeField({ ...inside, fieldCode: 'TSBYBN.detail' }, RESULT)
    expect(aggregation.note).toContain('不证明每条明细')
  })

  it('定额患者自付不用医院基金相减，核定定额明确是条件输入', () => {
    const context = { ...RESULT, algorithmVersion: 'employee_special_fixed_kidney_v1' }
    const self = describeFeeField({ ...FIELD, fieldCode: 'DEGWYZIF', label: '大额自付' }, context)
    expect(self.formula).toContain('患者实际大额段费用×降低后的个人自付比例')
    expect(self.formula).not.toContain('－大额互助支付')
    const payable = describeFeeField({ ...FIELD, fieldCode: 'PERSON_PAYABLE', checkType: 'independent_recalculation' }, context)
    expect(payable.note).toContain('不能用实际总费用减医院定额垫付额')
    const quota = describeFeeField({ ...FIELD, fieldCode: 'QUOTA_AMOUNT' }, context)
    expect(quota.formula).toBeNull()
    expect(quota.steps.join('')).toContain('不独立重算定额')
  })

  it('大病说明跨起付分段和分桶分配，救助说明剩余额度', () => {
    const context = { ...RESULT, algorithmVersion: 'employee_outpatient_special_v1' }
    const db = describeFeeField({ ...FIELD, fieldCode: 'FEEIN_DB_PAY', label: '自付一的大病支付' }, context)
    expect(db.formula).toContain('÷本笔大病合规费用基数')
    expect(db.steps.join('')).toContain('不能整笔乘一个固定比例')
    const aid = describeFeeField({ ...FIELD, fieldCode: 'CIVIL_IN' }, context)
    expect(aid.steps.join('')).toContain('年度限额')
    expect(aid.note).toContain('不')
  })

  it('不能因零金额推断全额个人承担，必须有后端记录的分支证据', () => {
    const field = { ...FIELD, fieldCode: 'T_FeeIn', observedAmount: '0.00' }
    expect(describeFeeField(field, RESULT).steps.join('')).toContain('匹配药品')
    const context = { ...RESULT, uncertainties: [{
      code: 'NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED', message: '标记待确认', id: 'gap', affectedFields: [],
    }] }
    const algorithm = describeFeeField(field, context)
    expect(algorithm.formula).toContain('＝0 元')
    expect(algorithm.note).toContain('不能据此断言')
    const personal = describeFeeField(FIELD, context)
    expect(personal.steps.join('')).toContain('全额个人承担')
    expect(personal.steps.join('')).not.toContain('按费用发生日期匹配')
  })

  it('账户、现金和未知字段不编造推算公式', () => {
    for (const fieldCode of ['T_PersonCountPay', 'T_CashPay', 'XJZF', 'ZHZF']) {
      const algorithm = describeFeeField({ ...FIELD, fieldCode, observedAmount: null }, RESULT)
      expect(algorithm.formula).toBeNull()
      expect(algorithm.steps.join('')).toContain('直接读取结算记录')
    }
    expect(describeFeeField({ ...FIELD, fieldCode: 'future_field' }, RESULT).formula).toBeNull()
    expect(describeFeeField(FIELD, { ...RESULT, algorithmVersion: 'future_v2' }).meaning).toContain('尚未补充')
  })

  it('居民普通门诊大病通道按该通道解释，不套用门诊大额公式', () => {
    const context: PolicyQAFeeDecomposition = {
      ...RESULT, algorithmVersion: 'resident_outpatient_v1', calculations: [{
        calculationId: 'pay', displayName: '大病保险支付', formulaId: 'resident_bigill_pay_v1',
        formulaVersion: 'v1', layout: 'product', operands: [], unroundedResult: null,
        roundingRule: null, result: '60.00',
      }],
    }
    expect(describeFeeField({ ...FIELD, fieldCode: 'T_FirstPay' }, context).formula).toContain('＝0 元')
    expect(describeFeeField({ ...FIELD, fieldCode: 'T_SelfPay1' }, context).formula).toContain('－大病保险支付－医保外费用')
    expect(describeFeeField(FIELD, context).formula).toBe('最终个人承担＝总费用－基金合计')
    expect(describeFeeField({ ...FIELD, fieldCode: 'T_BigillPay' }, context).note).toContain('不能混用')
  })

  it.each([
    'issue79_special_mz_batch_traces.json',
    'issue81_resident_special_batch_traces.json',
    'issue82_fixed_kidney_batch_traces.json',
  ])('真实回放 %s 的每个费用字段都有译文', (filename) => {
    const cases: unknown = JSON.parse(readFileSync(resolve(process.cwd(), '../../../scripts/eval', filename), 'utf8'))
    let count = 0
    function visit(value: unknown) {
      if (!value || typeof value !== 'object') return
      if ('algorithm_version' in value && 'fields' in value) {
        const result = toFeeDecomposition(value)
        expect(result).toBeDefined()
        if (!result) return
        for (const field of result.fields) {
          expect(describeFeeField(field, result).meaning, field.fieldCode).not.toContain('尚未补充')
          count++
        }
        return
      }
      for (const item of Object.values(value)) visit(item)
    }
    visit(cases)
    expect(count).toBeGreaterThan(10)
  })
})
