import { describe, expect, it } from 'vitest'
import { matchedFeeExplanation, toFeeDecomposition } from '@/lib/policy-qa-stream'

describe('已算平解释契约', () => {
  it('按后端资格筛选；旧载荷、字符串标志及仅金额状态不能放行', () => {
    const data = toFeeDecomposition({ execution_status: 'partial', fields: [{ field_code: 'good', explainable: true }, { field_code: 'legacy', check_status: 'matched' }],
      calculations: [{ calculation_id: 'good', explainable: true }, { calculation_id: 'bad', explainable: 'true', verification_status: 'verified' }],
      fee_items: [{ line_id: 'good', explainable: true }, { line_id: 'legacy', status: 'calculated' }],
    })!
    const explanation = matchedFeeExplanation(data)
    expect(explanation.fields.map((field) => field.fieldCode)).toEqual(['good'])
    expect(explanation.calculations.map((calc) => calc.calculationId)).toEqual(['good'])
    expect(explanation.feeItems?.map((item) => item.lineId)).toEqual(['good'])
    expect(data.fields).toHaveLength(2)
  })
  it('保留实际分支、参数来源、逐项差额和原始精度，过滤内部字段', () => {
    const row = toFeeDecomposition({ execution_status: 'partial', fee_items: [{ line_id: '1', centralized_procurement: null, classification_label: '乙类', ratio_basis: '限价内金额', ratio_source: '本次采用比例',
      decision_path: [{ code: 'price', label: '单价≤限价', operator: 'le', actual: '100.0000', expected: '50.0000', outcome: 'false', sql: 'secret' }],
      reconciliations: [{ label: '医保范围内', observed: '90.0000', calculated: '89.0000', difference: '-1.0000', check_status: 'mismatched', internal: 'secret' }],
    }] })!.feeItems![0]
    expect(row.centralizedProcurement).toBeNull()
    expect(row.decisionPath?.[0]).toMatchObject({ actual: '100.0000', expected: '50.0000', outcome: 'false' })
    expect(row.decisionPath?.[0]).not.toHaveProperty('sql')
    expect(row.reconciliations?.[0].difference).toBe('-1.0000')
    expect(row.reconciliations?.[0]).not.toHaveProperty('internal')
  })
})
