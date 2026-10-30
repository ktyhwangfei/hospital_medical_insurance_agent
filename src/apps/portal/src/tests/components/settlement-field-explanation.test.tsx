import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import SettlementFieldExplanation from '@/components/policy-qa/settlement-field-explanation'
import SettlementBillView from '@/components/policy-qa/settlement-bill-view'
import { toFeeDecomposition, type PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'

/** 最小分解载荷：只保留本组件用到的键。 */
function decomposition(field: Record<string, unknown>): PolicyQAFeeDecomposition {
  return {
    schemaVersion: '1.10', algorithmVersion: 'employee_outpatient_special_v1',
    executionStatus: 'partial', reconciliationStatus: 'matched',
    summaryText: '', summarySource: 'template', mayClaimFullExplanation: false,
    fields: [field as unknown as PolicyQAFeeDecomposition['fields'][number]],
    uncertainties: [], calculations: [], sources: [], conditions: [],
  }
}

const FIELD_BASE = {
  explainable: false,
  fieldCode: 'GRZIF1',
  label: '个人支付自付（一）金额',
  checkType: 'independent_recalculation' as const,
  checkStatus: 'not_verifiable' as const,
  observedAmount: null,
  calculatedAmount: '279.27',
  difference: null,
  explanationLevel: 'observed_only' as const,
  reasonCode: 'SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED',
  calculationRefs: [],
  sourceRefs: [],
  gapRefs: [],
  brief: null,
}

const EXPLANATION = {
  meaning: '医保范围内由个人承担的自付一部分，为补助或二次保障前的计算构成，属个人负担口径。',
  composition: '本次自付一按起付＋大额自付计算，得 279.27 元。',
  basisText: null,
  boundary: '该列在已核样本中未维护，当前金额由本单分量计算，不作账面核对。',
}

afterEach(cleanup)

describe('SettlementFieldExplanation 字段四要素固定说明', () => {
  it('非 explainable 字段也渲染四要素固定说明（阶段 B）', () => {
    const field = { ...FIELD_BASE, explanation: EXPLANATION }
    render(<SettlementFieldExplanation field={field} decomposition={decomposition(field)} />)
    const block = screen.getByTestId('field-explanation-GRZIF1')
    expect(block.textContent).toContain('金额含义')
    expect(block.textContent).toContain('补助或二次保障前的计算构成')
    expect(block.textContent).toContain('金额构成')
    expect(block.textContent).toContain('解释边界')
    expect(block.textContent).toContain('不作账面核对')
    // basisText 为 null 时不渲染该行
    expect(block.textContent).not.toContain('本单依据')
  })

  it('explainable 且无 explanation 时保持原渲染（无四要素块）', () => {
    const field = { ...FIELD_BASE, explainable: true, explanation: null }
    render(<SettlementFieldExplanation field={field} decomposition={decomposition(field)} />)
    expect(screen.queryByTestId('field-explanation-GRZIF1')).toBeNull()
  })

  it('既非 explainable 也无 explanation 时不渲染', () => {
    const field = { ...FIELD_BASE, explanation: null }
    const { container } = render(
      <SettlementFieldExplanation field={field} decomposition={decomposition(field)} />)
    expect(container.innerHTML).toBe('')
  })
})

describe('结算单模板字段四要素（template_explanations，与聊天同源）', () => {
  const raw = {
    schema_version: '1.10', algorithm_version: 'employee_outpatient_v1',
    execution_status: 'complete', reconciliation_status: 'matched',
    summary_text: '', summary_source: 'template', may_claim_full_explanation: false,
    fields: [], uncertainties: [], calculations: [], sources: [], conditions: [],
    settlement_facts: {
      chain: 'outpatient', items: [], payment_items: [],
      display_template: {
        template_id: 'employee_outpatient', version: '1.0.0', title: '结算单',
        layout_status: 'image_verified',
        fields: [
          { key: 'fee_all', label: '费用总金额', value: '100.00', section: 'transaction', row: 1, column: 1, span: 1, scope: 'patient_actual', field_code: 'T_FeeAll', source_kind: 'record', status: 'available' },
          { key: 'beyond_cap', label: '大额超封顶金额', value: null, section: 'transaction', row: 2, column: 1, span: 1, scope: 'patient_actual', field_code: null, source_kind: 'record', status: 'missing' },
        ],
      },
    },
    template_explanations: {
      fee_all: {
        meaning: '本笔结算的全部费用合计，属费用口径，不等于医保报销金额。',
        composition: null, basis_text: null,
        boundary: '本字段未记录关联政策依据来源。',
      },
      beyond_cap: {
        meaning: '超出大额基金封顶线的金额，属个人负担口径。',
        composition: null, basis_text: null,
        boundary: '模板未绑定计算目标（field_code 为空），内核未产出该字段的分解记录。',
      },
    },
  }

  it('模板字段就地渲染四要素说明；内核未产出字段展示具体缺项', () => {
    render(<SettlementBillView feeDecomposition={toFeeDecomposition(raw)!} />)
    expect(screen.getByTestId('template-field-explanation-fee_all').textContent).toContain('费用合计')
    const beyond = screen.getByTestId('template-field-explanation-beyond_cap')
    expect(beyond.textContent).toContain('封顶线')
    expect(beyond.textContent).toContain('未产出')
  })

  it('旧载荷无 template_explanations 时不渲染说明块', () => {
    const legacy = { ...raw, template_explanations: undefined }
    render(<SettlementBillView feeDecomposition={toFeeDecomposition(legacy)!} />)
    expect(screen.queryByTestId('template-field-explanation-fee_all')).toBeNull()
  })
})
