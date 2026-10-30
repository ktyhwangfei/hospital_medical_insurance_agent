// 费用分解公开结果解析测试 — Issue #78 Phase 2。
// 覆盖 toFeeDecomposition 白名单转换、稀疏字段容忍（Milvus dynamic key 同类陷阱：
// 键缺失而非空串），以及 SSE result / 轨迹回放链路的挂接不丢失。
import { describe, expect, it } from 'vitest'

import { toFeeDecomposition, toPolicyQAResult } from '@/lib/policy-qa-stream'
import { restoreSessionState, type TrajectoryResponseDTO } from '@/lib/policy-qa-session'

const FULL_RAW = {
  schema_version: '1.0',
  algorithm_version: 'fee-decomp-v1',
  execution_status: 'complete',
  reconciliation_status: 'matched',
  summary_text: '本笔门诊费用分解核对完成。',
  summary_source: 'template',
  may_claim_full_explanation: true,
  fields: [
    {
      field_code: 'fund_pay',
      label: '统筹基金支付',
      check_type: 'independent_recalculation',
      check_status: 'matched',
      observed_amount: '113.66',
      calculated_amount: '113.66',
      difference: '0.00',
      explanation_level: 'causally_explained',
    },
  ],
  uncertainties: [{ code: 'CIVIL_CAP_PRIOR_UNVERIFIABLE', message: '交易前累计无法独立核实' }],
  coverage: {
    target_field_count: 4,
    independently_explained_count: 3,
    amount_reconciled_count: 1,
    observed_only_count: 0,
  },
}

describe('toFeeDecomposition', () => {
  it('1.3 中文名、逐行算法与条件引用使用白名单，数值金额不强制转换', () => {
    const result = toFeeDecomposition({ ...FULL_RAW, schema_version: '1.3',
      settlement_facts: { chain: 'special', metadata_names: { medical_category: '门诊特殊病', invalid: 2 } },
      fee_items: [{ line_id: '1', item_name: '药品', status: 'future', total_fee: '-10.00', unit_price: 10, formulas: ['原始算式', 3], patient_name: '不能泄漏' }],
      calculations: [{ calculation_id: 'c', formula: '实际公式＝0.00 元' }],
      path_steps: [{ step_id: 'path.fund', name: '统筹', condition_refs: ['s', 2] }],
    })!
    expect(result.settlementFacts?.metadataNames).toEqual({ medical_category: '门诊特殊病' })
    expect(result.feeItems?.[0]).toMatchObject({ totalFee: '-10.00', unitPrice: null, status: 'unknown', formulas: ['原始算式'] })
    expect(result.calculations[0].formula).toBe('实际公式＝0.00 元')
    expect(result.pathSteps?.[0].conditionRefs).toEqual(['s'])
    expect(JSON.stringify(result)).not.toContain('不能泄漏')
  })
  it('1.2 事实与路径白名单解析，零值和负值原样保留', () => {
    const result = toFeeDecomposition({
      ...FULL_RAW, schema_version: '1.2',
      settlement_facts: {
        chain: 'outpatient', identifier: 'T1', trade_date: '2024-06-01',
        items: [{ label: '总费用', value: '-10.00', secret: '不公开' }, { label: '起付', value: '0.00' }, { label: '缺失' }],
        payment_items: null, secret: '不公开',
      },
      path_steps: [{ step_id: 'path.deductible', name: '起付', status: 'zero_amount', amount: '0.00', calculation_refs: ['c1', 12], secret: '不公开' }],
    })
    expect(result?.settlementFacts).toMatchObject({ identifier: 'T1', tradeDate: '2024-06-01', insuranceType: null, paymentItems: [] })
    expect(result?.settlementFacts?.items).toEqual([{ label: '总费用', value: '-10.00' }, { label: '起付', value: '0.00' }, { label: '缺失', value: null }])
    expect(result?.pathSteps?.[0]).toEqual({ stepId: 'path.deductible', name: '起付', status: 'zero_amount', amount: '0.00', calculationRefs: ['c1'], fieldRefs: [], reason: null, conditionRefs: [] })
    expect(JSON.stringify(result)).not.toContain('不公开')
  })

  it('1.0/1.1 缺新块及非法稀疏数据安全降级，不将数字金额转成字符串', () => {
    expect(toFeeDecomposition(FULL_RAW)?.settlementFacts).toBeUndefined()
    expect(toFeeDecomposition(FULL_RAW)?.pathSteps).toBeUndefined()
    const result = toFeeDecomposition({ ...FULL_RAW, settlement_facts: { chain: 'other' }, path_steps: [null, {}, { step_id: 'x', name: '未知', status: 'future', amount: 12 }] })
    expect(result?.settlementFacts).toBeUndefined()
    expect(result?.pathSteps).toEqual([{ stepId: 'x', name: '未知', status: 'unknown', amount: null, calculationRefs: [], fieldRefs: [], reason: null, conditionRefs: [] }])
  })

  it('白名单转换 snake_case → camelCase，金额保持十进制字符串', () => {
    const result = toFeeDecomposition(FULL_RAW)
    expect(result).toBeDefined()
    expect(result?.executionStatus).toBe('complete')
    expect(result?.reconciliationStatus).toBe('matched')
    expect(result?.algorithmVersion).toBe('fee-decomp-v1')
    expect(result?.mayClaimFullExplanation).toBe(true)
    expect(result?.fields[0]).toMatchObject({
      fieldCode: 'fund_pay',
      checkType: 'independent_recalculation',
      checkStatus: 'matched',
      observedAmount: '113.66',
      calculatedAmount: '113.66',
      difference: '0.00',
      explanationLevel: 'causally_explained',
    })
    expect(typeof result?.fields[0]?.observedAmount).toBe('string')
    expect(result?.coverage).toEqual({
      targetFieldCount: 4,
      independentlyExplainedCount: 3,
      amountReconciledCount: 1,
      observedOnlyCount: 0,
    })
  })

  it('稀疏容忍：coverage 缺失、单项金额键缺失、枚举未知值均不抛错', () => {
    const sparse = {
      execution_status: 'partial',
      reconciliation_status: 'not_verifiable',
      fields: [
        { field_code: 'civil_aid', check_status: 'matched' },
        { field_code: 'other', check_status: 'some_future_value', explanation_level: 'x' },
      ],
    }
    const result = toFeeDecomposition(sparse)
    expect(result).toBeDefined()
    expect(result?.executionStatus).toBe('partial')
    expect(result?.coverage).toBeUndefined()
    expect(result?.fields[0]?.observedAmount).toBeNull()
    expect(result?.fields[0]?.label).toBe('')
    expect(result?.fields[1]?.checkStatus).toBe('not_verifiable')
    expect(result?.fields[1]?.explanationLevel).toBe('unexplained')
    expect(result?.uncertainties).toEqual([])
    expect(result?.summaryText).toBe('')
  })

  it('coverage 为 null 时归一为 undefined', () => {
    const result = toFeeDecomposition({ ...FULL_RAW, coverage: null })
    expect(result?.coverage).toBeUndefined()
  })

  it('非对象或 execution_status 非法时返回 undefined（不渲染）', () => {
    expect(toFeeDecomposition(undefined)).toBeUndefined()
    expect(toFeeDecomposition(null)).toBeUndefined()
    expect(toFeeDecomposition('fee')).toBeUndefined()
    expect(toFeeDecomposition({ execution_status: 'weird' })).toBeUndefined()
  })
})

// 解释投影 1.1 全量载荷：新增字段级引用、calculations/sources/conditions 顶层数组。
const FULL_RAW_11 = {
  schema_version: '1.1',
  algorithm_version: 'fee-decomp-v2',
  execution_status: 'complete',
  reconciliation_status: 'matched',
  summary_text: '本笔门诊费用分解核对完成。',
  summary_source: 'template',
  may_claim_full_explanation: true,
  fields: [
    {
      field_code: 'fund_pay',
      label: '统筹基金支付',
      check_type: 'independent_recalculation',
      check_status: 'matched',
      observed_amount: '113.66',
      calculated_amount: '113.66',
      difference: '0.00',
      explanation_level: 'causally_explained',
      reason_code: null,
      calculation_refs: ['calc-fund'],
      source_refs: ['src-settle'],
      gap_refs: ['gap-1'],
      brief: '统筹基金支付由甲类费用统筹额与乙类费用统筹额构成。',
    },
  ],
  uncertainties: [
    {
      code: 'CIVIL_CAP_PRIOR_UNVERIFIABLE',
      message: '交易前累计无法独立核实',
      id: 'gap-1',
      affected_fields: ['fund_pay'],
    },
  ],
  coverage: {
    target_field_count: 4,
    independently_explained_count: 3,
    amount_reconciled_count: 1,
    observed_only_count: 0,
  },
  calculations: [
    {
      calculation_id: 'calc-fund',
      display_name: '统筹基金支付',
      formula_id: 'F-FUND-01',
      formula_version: '1.0',
      layout: 'sum',
      operands: [
        { display_name: '甲类统筹', value: '100.00', is_intermediate: false },
        { display_name: '乙类统筹', value: '13.66', is_intermediate: true },
      ],
      unrounded_result: '113.66',
      rounding_rule: '四舍五入到分',
      result: '113.66',
    },
  ],
  sources: [
    {
      ref_id: 'src-settle',
      title: '门诊结算单',
      category: 'settlement_record',
      confirmation_status: '已确认',
      value: '113.66',
      values: ['113.66'],
      link: 'https://example.com/policy/1',
    },
  ],
  conditions: [
    {
      step_id: 'cond-deductible',
      module_label: '起付线模块',
      description: '累计费用已超过起付线',
      actual_display: '500.00',
      expected_display: null,
      outcome: 'pass',
      calculation_refs: ['calc-fund'],
    },
  ],
}

describe('toFeeDecomposition 解释投影 1.1', () => {
  it('1.1 全量载荷：字段引用与 calculations/sources/conditions 完整解析', () => {
    const result = toFeeDecomposition(FULL_RAW_11)
    expect(result?.schemaVersion).toBe('1.1')
    expect(result?.fields[0]).toMatchObject({
      reasonCode: null,
      calculationRefs: ['calc-fund'],
      sourceRefs: ['src-settle'],
      gapRefs: ['gap-1'],
      brief: '统筹基金支付由甲类费用统筹额与乙类费用统筹额构成。',
    })
    expect(result?.uncertainties[0]).toMatchObject({
      id: 'gap-1',
      affectedFields: ['fund_pay'],
    })
    expect(result?.calculations[0]).toMatchObject({
      calculationId: 'calc-fund',
      layout: 'sum',
      unroundedResult: '113.66',
      roundingRule: '四舍五入到分',
      result: '113.66',
    })
    expect(result?.calculations[0]?.operands).toEqual([
      { displayName: '甲类统筹', value: '100.00', isIntermediate: false },
      { displayName: '乙类统筹', value: '13.66', isIntermediate: true },
    ])
    expect(result?.sources[0]).toMatchObject({
      refId: 'src-settle',
      category: 'settlement_record',
      confirmationStatus: '已确认',
      value: '113.66',
      values: ['113.66'],
      link: 'https://example.com/policy/1',
    })
    expect(result?.conditions[0]).toMatchObject({
      stepId: 'cond-deductible',
      moduleLabel: '起付线模块',
      actualDisplay: '500.00',
      expectedDisplay: null,
      outcome: 'pass',
      calculationRefs: ['calc-fund'],
    })
  })

  it('1.0 旧载荷兼容：无新键时金额字段照常解析，新数组为空、字段新键归一为默认值', () => {
    const result = toFeeDecomposition(FULL_RAW)
    expect(result?.schemaVersion).toBe('1.0')
    expect(result?.fields[0]?.observedAmount).toBe('113.66')
    expect(result?.fields[0]?.difference).toBe('0.00')
    expect(result?.fields[0]?.reasonCode).toBeNull()
    expect(result?.fields[0]?.calculationRefs).toEqual([])
    expect(result?.fields[0]?.sourceRefs).toEqual([])
    expect(result?.fields[0]?.gapRefs).toEqual([])
    expect(result?.fields[0]?.brief).toBeNull()
    expect(result?.uncertainties[0]?.id).toBe('')
    expect(result?.uncertainties[0]?.affectedFields).toEqual([])
    expect(result?.calculations).toEqual([])
    expect(result?.sources).toEqual([])
    expect(result?.conditions).toEqual([])
  })

  it('坏数据降级：未知 layout → generic，未知 category 来源整项丢弃', () => {
    const result = toFeeDecomposition({
      execution_status: 'complete',
      calculations: [
        { calculation_id: 'c1', display_name: 'X', layout: 'divide', operands: [] },
        { calculation_id: 'c2', display_name: 'Y', layout: 'product', operands: [] },
      ],
      sources: [
        { ref_id: 's1', title: '结算单', category: 'settlement_record' },
        { ref_id: 's2', title: '内部轨迹', category: 'internal_trace' },
      ],
    })
    expect(result?.calculations[0]?.layout).toBe('generic')
    expect(result?.calculations[1]?.layout).toBe('product')
    expect(result?.sources).toHaveLength(1)
    expect(result?.sources[0]?.refId).toBe('s1')
  })

  it('稀疏降级：null/缺键数组 → 空数组，is_intermediate 非布尔 → false，可空字符串缺失 → null', () => {
    const result = toFeeDecomposition({
      execution_status: 'partial',
      fields: [{ field_code: 'f1', calculation_refs: null, source_refs: 'x', gap_refs: [1] }],
      calculations: null,
      sources: undefined,
      conditions: [
        {
          step_id: 'c1',
          module_label: '模块',
          description: '描述',
          outcome: 'pass',
          // calculation_refs 键整体缺失
        },
      ],
    })
    expect(result?.fields[0]?.calculationRefs).toEqual([])
    expect(result?.fields[0]?.sourceRefs).toEqual([])
    expect(result?.fields[0]?.gapRefs).toEqual([])
    expect(result?.calculations).toEqual([])
    expect(result?.sources).toEqual([])
    expect(result?.conditions[0]?.calculationRefs).toEqual([])

    const withBadOperand = toFeeDecomposition({
      execution_status: 'complete',
      calculations: [
        {
          calculation_id: 'c1',
          layout: 'sum',
          operands: [
            { display_name: 'A', value: '1.00', is_intermediate: 'yes' },
            { display_name: 'B', value: '-2.00' },
          ],
          // unrounded_result / rounding_rule / result 键整体缺失
        },
      ],
    })
    expect(withBadOperand?.calculations[0]?.operands[0]?.isIntermediate).toBe(false)
    expect(withBadOperand?.calculations[0]?.operands[1]?.isIntermediate).toBe(false)
    expect(withBadOperand?.calculations[0]?.result).toBeNull()
    expect(withBadOperand?.calculations[0]?.roundingRule).toBeNull()
  })
})

const VALID_RESULT_RAW = {
  answer: '本次门诊费用分解如下。',
  answer_status: 'complete',
  verification_summary: {
    settlement_checked: true,
    calculation_checked: true,
    policy_count: 1,
    message: '已核对',
  },
  citations: [{ title: '政策', excerpt: '摘要' }],
  uncertainties: [],
  fee_decomposition: FULL_RAW,
}

describe('PolicyQAResult.feeDecomposition 挂接', () => {
  it('toPolicyQAResult 从 result.fee_decomposition 解析并挂接', () => {
    const result = toPolicyQAResult(VALID_RESULT_RAW)
    expect(result.answerStatus).toBe('complete')
    expect(result.feeDecomposition?.executionStatus).toBe('complete')
    expect(result.feeDecomposition?.fields).toHaveLength(1)
  })

  it('result 无 fee_decomposition 时字段为 undefined', () => {
    const { fee_decomposition: _omit, ...raw } = VALID_RESULT_RAW
    const result = toPolicyQAResult(raw)
    expect(result.feeDecomposition).toBeUndefined()
  })

  it('轨迹回放恢复不丢 feeDecomposition', () => {
    const trajectory: TrajectoryResponseDTO = {
      session_id: 'sess-1',
      status: 'active',
      turns: [
        {
          qa_turn_id: 'turn-1',
          question: '这笔门诊费用怎么算的？',
          answer_status: 'complete',
          settlement_id: 'T123',
          payload: { result: VALID_RESULT_RAW },
        },
      ],
    }
    const restored = restoreSessionState(trajectory)
    const assistant = restored.messages.find((m) => m.role === 'assistant')
    expect(assistant?.feeDecomposition?.reconciliationStatus).toBe('matched')
    expect(assistant?.feeDecomposition?.uncertainties[0]?.code).toBe(
      'CIVIL_CAP_PRIOR_UNVERIFIABLE',
    )
  })
})
