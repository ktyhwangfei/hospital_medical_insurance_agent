// SettlementBillView 组件测试 — policy-qa 结算单式样费用构成（#78 展示重构）。
// 覆盖：病人基本信息块、双列金额只展示结算记录值、派生核对行（fieldCode 含 "."）过滤、
// 不暴露重算/核对/候选口径/未决事项措辞、点字段发起提问、费用明细页签懒加载、
// patient 缺省不渲染患者块、无字段（不可用）整体不渲染。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import SettlementBillView from '@/components/policy-qa/settlement-bill-view'
import type { PatientSummaryDTO } from '@/lib/policy-qa-settlement-list'
import type { PolicyQAFeeDecomposition } from '@/lib/policy-qa-stream'

const PATIENT: PatientSummaryDTO = {
  cardNo: '10065478600S',
  idNoMasked: '110***********0937',
  name: '张三',
  gender: '男',
  birthDate: '1942-03-28',
  registrationId: '1671213',
}

const BASE: PolicyQAFeeDecomposition = {
  schemaVersion: '1.1',
  algorithmVersion: 'employee_outpatient_v1',
  executionStatus: 'complete',
  reconciliationStatus: 'matched',
  summaryText: '总费用：结算记录 400.00 元，按规则重算 400.0000 元，一致。',
  summarySource: 'template',
  mayClaimFullExplanation: true,
  fields: [
    {
      fieldCode: 'T_FeeAll',
      label: '总费用',
      checkType: 'detail_aggregation',
      checkStatus: 'matched',
      observedAmount: '400.00',
      calculatedAmount: '400.0000',
      difference: '0.0000',
      explanationLevel: 'amount_reconciled',
      reasonCode: null,
      calculationRefs: [],
      sourceRefs: [],
      gapRefs: [],
      brief: null,
    },
    // 派生核对行：不进用户结算单
    {
      fieldCode: 'T_FeeAll.identity',
      label: '总费用（账面恒等 In+Out）',
      checkType: 'identity_check',
      checkStatus: 'matched',
      observedAmount: '400.00',
      calculatedAmount: '400.00',
      difference: '0.00',
      explanationLevel: 'amount_reconciled',
      reasonCode: null,
      calculationRefs: [],
      sourceRefs: [],
      gapRefs: [],
      brief: null,
    },
    {
      fieldCode: 'T_SelfPay1',
      label: '自付一',
      checkType: 'identity_check',
      checkStatus: 'matched',
      observedAmount: '210.50',
      calculatedAmount: '210.50',
      difference: '0.00',
      explanationLevel: 'amount_reconciled',
      reasonCode: null,
      calculationRefs: ['calc.identity.self_pay_1'],
      sourceRefs: [],
      gapRefs: [],
      brief: '自付一 210.50 元（账面勾稽）。',
    },
    {
      fieldCode: 'T_AccPay',
      label: '账户支付',
      checkType: 'identity_check',
      checkStatus: 'not_verifiable',
      observedAmount: null,
      calculatedAmount: null,
      difference: null,
      explanationLevel: 'observed_only',
      reasonCode: null,
      calculationRefs: [],
      sourceRefs: [],
      gapRefs: [],
      brief: null,
    },
  ],
  uncertainties: [
    {
      code: 'ACCUMULATION_DERIVED_IN_HOSPITAL',
      message: '账面年度累计未维护，交易前累计按同人同年本院历史推导。',
      id: 'gap.accumulation',
      affectedFields: ['T_FirstPay'],
    },
  ],
  coverage: {
    targetFieldCount: 4,
    independentlyExplainedCount: 3,
    amountReconciledCount: 1,
    observedOnlyCount: 0,
  },
  calculations: [],
  sources: [],
  conditions: [],
}

const FEE_ITEMS = [
  {
    item_name: '注射用培美曲塞二钠',
    item_type: '药品',
    item_code: 'XL01BAP030B001010178396',
    quantity: '4.00',
    unit_price: '100.0000',
    total_fee: '400.0000',
    insurance_inner: '0.0000',
    insurance_outer: '400.0000',
    self_pay_2: '0.0000',
  },
]

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('SettlementBillView', () => {
  it('feeDecomposition 为 undefined 时不渲染任何区块', () => {
    const { container } = render(<SettlementBillView feeDecomposition={undefined} />)
    expect(container.innerHTML).toBe('')
    expect(screen.queryByTestId('settlement-bill-view')).toBeNull()
  })

  it('分解不可用（无字段）时整体不渲染，避免空卡片', () => {
    const { container } = render(
      <SettlementBillView
        feeDecomposition={{ ...BASE, fields: [], executionStatus: 'unavailable' }}
        patient={PATIENT}
      />,
    )
    expect(container.innerHTML).toBe('')
    expect(screen.queryByTestId('settlement-bill-view')).toBeNull()
  })

  it('结算单布局：病人基本信息 + 双列金额（结算记录值原样）', () => {
    render(
      <SettlementBillView
        feeDecomposition={BASE}
        patient={PATIENT}
        settlementId="011100030X240409000004"
        settlementDate="2024-04-09 10:23:45"
        serviceType="门诊"
      />,
    )
    const view = screen.getByTestId('settlement-bill-view')
    expect(view.textContent).toContain('结算单费用构成')
    expect(view.textContent).toContain('011100030X240409000004')
    expect(view.textContent).toContain('2024-04-09 10:23')
    // 病人基本信息
    const patient = screen.getByTestId('settlement-bill-patient')
    expect(patient.textContent).toContain('张三')
    expect(patient.textContent).toContain('男')
    expect(patient.textContent).toContain('110***********0937')
    expect(patient.textContent).toContain('10065478600S')
    expect(patient.textContent).toContain('门诊')
    // 交易相关信息：label + 结算记录金额原样；null → '—'
    const fields = screen.getByTestId('settlement-bill-fields')
    expect(fields.textContent).toContain('总费用')
    expect(fields.textContent).toContain('400.00')
    expect(fields.textContent).toContain('自付一')
    expect(fields.textContent).toContain('210.50')
    expect(fields.textContent).toContain('账户支付')
    expect(fields.textContent).toContain('—')
    // 派生核对行不展示
    expect(fields.textContent).not.toContain('账面恒等')
  })

  it('不暴露重算/核对/候选口径/未决事项等内部措辞', () => {
    render(<SettlementBillView feeDecomposition={BASE} patient={PATIENT} />)
    const view = screen.getByTestId('settlement-bill-view')
    expect(view.textContent).not.toContain('按规则重算')
    expect(view.textContent).not.toContain('核对')
    expect(view.textContent).not.toContain('差异')
    expect(view.textContent).not.toContain('候选口径')
    expect(view.textContent).not.toContain('待业务签核')
    expect(view.textContent).not.toContain('ACCUMULATION_DERIVED_IN_HOSPITAL')
    expect(view.textContent).not.toContain('账面年度累计未维护')
    // 后端 summary 与字段 brief 的勾稽措辞同样不进入账单视图
    expect(view.textContent).not.toContain('账面勾稽')
  })

  it('提供 onAskField 时字段可点击发起提问；缺省时不可点击', () => {
    const onAskField = vi.fn()
    render(<SettlementBillView feeDecomposition={BASE} onAskField={onAskField} />)

    fireEvent.click(screen.getByRole('button', { name: '提问：自付一' }))
    expect(onAskField).toHaveBeenCalledWith('自付一')

    cleanup()
    render(<SettlementBillView feeDecomposition={BASE} />)
    expect(screen.queryByRole('button', { name: '提问：自付一' })).toBeNull()
  })

  it('费用明细页签：点击才拉取（懒加载），渲染明细行', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => FEE_ITEMS,
    })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    render(
      <SettlementBillView
        feeDecomposition={BASE}
        settlementId="011100030X240409000004"
        feeItemsAvailable
      />,
    )

    // 默认交易信息页签，不拉取明细
    expect(fetchMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('bill-tab-items'))

    await waitFor(() => {
      expect(screen.getByTestId('settlement-bill-fee-items')).toBeInTheDocument()
    })
    const url = String((fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0]?.[0])
    expect(url).toContain('/policy-qa/settlements/011100030X240409000004/fee-items')
    const table = screen.getByTestId('settlement-bill-fee-items')
    expect(table.textContent).toContain('注射用培美曲塞二钠')
    expect(table.textContent).toContain('药品')
    expect(table.textContent).toContain('400.00')

    // 切回交易信息
    fireEvent.click(screen.getByTestId('bill-tab-info'))
    expect(screen.getByTestId('settlement-bill-fields')).toBeInTheDocument()
  })

  it('费用明细查询失败展示错误提示', async () => {
    const fetchMock = vi.fn(async () => ({ ok: false, status: 503 })) as unknown as typeof fetch
    vi.stubGlobal('fetch', fetchMock)

    render(
      <SettlementBillView
        feeDecomposition={BASE}
        settlementId="011100030X240409000004"
        feeItemsAvailable
      />,
    )
    fireEvent.click(screen.getByTestId('bill-tab-items'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('费用明细查询失败')
    })
  })

  it('feeItemsAvailable 关闭或无 settlementId 时不渲染页签', () => {
    render(<SettlementBillView feeDecomposition={BASE} settlementId="T123" />)
    expect(screen.queryByTestId('bill-tab-items')).toBeNull()
    cleanup()
    render(<SettlementBillView feeDecomposition={BASE} feeItemsAvailable />)
    expect(screen.queryByTestId('bill-tab-items')).toBeNull()
  })

  it('patient 缺省时不渲染病人基本信息块', () => {
    render(<SettlementBillView feeDecomposition={BASE} />)
    expect(screen.queryByTestId('settlement-bill-patient')).toBeNull()
    expect(screen.getByTestId('settlement-bill-fields')).toBeInTheDocument()
  })
})
