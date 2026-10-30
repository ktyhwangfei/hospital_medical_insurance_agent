// 费用分解工作台 /fee-decomposition 页测试 — Issue #78 Phase 3。
// 覆盖：happy path（meta 条 + 分解块）、稀疏字段/undefined coverage 不崩、
// 503 未配置原因展示、unavailable uncertainties 展示；
// 按人定位：身份证输入 → 候选列表（多候选/唯一/无候选/截断）、点击候选分解、422 IDENTIFIER_IS_ID_CARD。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/fee-decomposition-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/fee-decomposition-api')>()
  return { ...actual, decomposeFee: vi.fn(), resolvePerson: vi.fn() }
})

import FeeDecompositionPage from '../../app/fee-decomposition/page'
import {
  decomposeFee,
  resolvePerson,
  type FeeDecompositionResponseDto,
  type ResolvePersonResponseDto,
} from '@/lib/fee-decomposition-api'
import { ApiClientError } from '@/lib/types'

const FULL_RESPONSE: FeeDecompositionResponseDto = {
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
    {
      field_code: 'self_pay',
      label: '个人支付',
      check_type: 'detail_aggregation',
      check_status: 'mismatched',
      observed_amount: '6530.03',
      calculated_amount: '6527.53',
      difference: '2.50',
      explanation_level: 'amount_reconciled',
    },
  ],
  uncertainties: [],
  settlement_facts: {
    chain: 'outpatient', identifier: 'T123456789012345', trade_date: '2024-04-30',
    medical_category: null, insurance_type: null, person_type: null, hospital_level: null,
    items: [{ label: '本次起付金额', value: '20.00' }, { label: '统筹基金支付', value: '113.66' }],
    payment_items: [{ label: '账户支付', value: '0.00' }, { label: '现金支付', value: '6530.03' }],
  },
  fee_items: [
    {
      line_id: '1', item_code: 'XL04ADT002E001020304641', item_name: '他克莫司胶囊', item_type: '药品',
      fee_date: '2024-04-30', unit_price: '300.0000', quantity: '20.00', total_fee: '6000.0000',
      observed_in_scope: '6000.0000', observed_out_scope: '0.0000', observed_self_pay_2: '0.00',
      calculated_in_scope: '6000.0000', calculated_out_scope: '0.0000', calculated_self_pay_2: '0.00',
      status: 'calculated', division_method: 'ratio', self_pay_ratio: '0.0000', explainable: true,
      classification_code: '0102', classification_label: '乙类西药',
      effective_from: '2022-10-10', effective_to: '2024-05-31', a_ypbs: '否', a_mzxj: '0.0000', ypfl: '2',
      explanation: '乙类西药；个人自付2＝取整（费用金额 6000.0000 元×采用自付比例 0.0000）＝0.00 元',
      conditions: [], formulas: [], notes: [],
    },
    {
      line_id: '2', item_code: 'XL01BAP030B001010178396', item_name: '注射用培美曲塞二钠', item_type: '药品',
      fee_date: '2024-04-30', unit_price: '100.0000', quantity: '4.00', total_fee: '400.0000',
      observed_in_scope: '360.0000', observed_out_scope: '40.0000', observed_self_pay_2: '40.00',
      calculated_in_scope: '360.0000', calculated_out_scope: '40.0000', calculated_self_pay_2: '40.00',
      status: 'calculated', division_method: 'ratio', self_pay_ratio: '0.1000', unit_price_limit: '809.0000', explainable: true,
      centralized_procurement: true, classification_code: '0102', classification_label: '乙类西药',
      effective_from: '2023-03-01', effective_to: '2050-12-31', a_ypbs: '是', a_mzxj: '809.0000',
      explanation: '乙类西药；集采单价 100.0000 ≤ 门诊限价 809.0000；个人自付2＝取整（400.0000×10%）＝40.00 元',
      conditions: [], formulas: [], notes: [],
    },
  ],
  coverage: {
    target_field_count: 4,
    independently_explained_count: 3,
    amount_reconciled_count: 1,
    observed_only_count: 0,
  },
  meta: {
    identifier: 'T123456789012345',
    chain: 'outpatient',
    profile: 'employee_outpatient',
    algorithm_version: 'fee-decomp-v1',
  },
}

function submitForm(identifier: string) {
  fireEvent.change(screen.getByTestId('fee-decomposition-identifier'), {
    target: { value: identifier },
  })
  fireEvent.click(screen.getByTestId('fee-decomposition-submit'))
}

const ID_CARD = '110101199001011234'

const MULTI_CANDIDATES: ResolvePersonResponseDto = {
  match_status: 'multiple_candidates',
  truncated: false,
  candidates: [
    {
      chain: 'outpatient',
      identifier: 'T123456789012345',
      chain_label: '普通门诊',
      profile_label: '职工门诊',
      service_date: '2025-11-02',
      total_amount: '6.50',
    },
    {
      chain: 'special',
      identifier: '604',
      chain_label: '门诊特殊病',
      profile_label: '居民门特',
      service_date: null,
      total_amount: null,
    },
  ],
}

beforeEach(() => {
  vi.mocked(decomposeFee).mockResolvedValue(FULL_RESPONSE)
  vi.mocked(resolvePerson).mockResolvedValue(MULTI_CANDIDATES)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('FeeDecompositionPage', () => {
  it('同一单据的事实区与解释区使用独立组件身份', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      render(<FeeDecompositionPage />)
      submitForm('T123456789012345')
      await screen.findByTestId('settlement-summary-table')
      expect(errors.mock.calls.some((args) => String(args[0]).includes('same key'))).toBe(false)
    } finally {
      errors.mockRestore()
    }
  })
  it('分解不可用时仍展示交易信息与未分解原因', async () => {
    vi.mocked(decomposeFee).mockResolvedValue({
      ...FULL_RESPONSE, schema_version: '1.6', execution_status: 'unavailable', fields: [], fee_items: [],
      uncertainties: [{ code: 'UNSUPPORTED_PROFILE', message: '该险种门诊费用分解暂未支持' }],
      settlement_facts: {
        chain: 'outpatient', identifier: 'T1', trade_date: null, medical_category: null,
        insurance_type: null, person_type: null, hospital_level: null,
        items: [{ label: '费用总金额', value: '400.00' }], payment_items: [],
      },
    })
    render(<FeeDecompositionPage />)
    submitForm('T1')
    const summary = await screen.findByTestId('settlement-summary-table')
    expect(summary.textContent).toContain('400.00')
    expect(screen.getByTestId('fee-decomposition-unavailable').textContent).toContain('该险种门诊费用分解暂未支持')
    expect(screen.queryByTestId('fee-detail-table')).toBeNull()
    expect(screen.queryByRole('tab', { name: '交易明细' })).toBeNull()
    expect(screen.queryByTestId('fee-decomposition-block')).toBeNull()
  })

  it('happy path：交易信息金额行带解释，交易明细切到 tab 后按需列出现', async () => {
    render(<FeeDecompositionPage />)
    submitForm('T123456789012345')

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-result')).toBeTruthy()
    })
    expect(decomposeFee).toHaveBeenCalledWith('T123456789012345', 'auto')

    const summary = screen.getByTestId('settlement-summary-table')
    expect(summary.textContent).toContain('T123456789012345')
    expect(screen.getByTestId('summary-row-sum.total').textContent).toContain('6400.00')
    expect(screen.getByTestId('summary-row-sum.in').textContent).toContain('6360.00')
    expect(screen.getByTestId('summary-row-sum.self2').textContent).toContain('40.00')
    expect(screen.getByTestId('summary-row-sum.personal_total').textContent).toContain('6530.03')
    expect(summary.textContent).not.toMatch(/T_|@\d{4}|ROP-|EOP-/)
    expect(screen.queryByTestId('fee-detail-table')).toBeNull()

    await userEvent.click(screen.getByRole('tab', { name: '交易明细' }))
    const detail = screen.getByTestId('fee-detail-table')
    expect(detail.textContent).toContain('他克莫司胶囊')
    expect(detail.textContent).toContain('注射用培美曲塞二钠')
    expect(detail.textContent).toContain('乙类西药')
    expect(detail.textContent).toContain('集采药')
    expect(detail.textContent).toContain('限价')
    // 单价、日期、编码与目录参数收进展开，默认列只保留金额、类别与关键原因
    expect(detail.querySelector('thead')?.textContent).not.toContain('集采标识')
    expect(detail.querySelector('thead')?.textContent).not.toContain('门诊限价')
    expect(detail.textContent).not.toContain('住院限价')
    expect(detail.textContent).not.toContain('自制剂标准价格')
    await userEvent.click(screen.getAllByRole('button', { name: '展开解释' })[1])
    expect(detail.textContent).toContain('集采')
    expect(detail.textContent).toContain('本次采用的限价')
    expect(detail.textContent).toContain('项目编码')
    expect(screen.queryByTestId('fee-decomposition-block')).toBeNull()
  })

  it('链路选择门诊特殊病时传 chain=special', async () => {
    render(<FeeDecompositionPage />)
    fireEvent.change(screen.getByTestId('fee-decomposition-chain'), {
      target: { value: 'special' },
    })
    submitForm('604')

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-result')).toBeTruthy()
    })
    expect(decomposeFee).toHaveBeenCalledWith('604', 'special')
  })

  it('稀疏字段：coverage 为 null、金额键缺失不崩，渲染 — 与不适用徽标', async () => {
    vi.mocked(decomposeFee).mockResolvedValue({
      ...FULL_RESPONSE,
      coverage: null,
      fields: [
        {
          field_code: 'civil_aid',
          label: '医疗救助',
          check_type: 'identity_check',
          check_status: 'not_applicable',
          observed_amount: null,
          calculated_amount: null,
          difference: null,
          explanation_level: 'observed_only',
        },
      ],
    })
    render(<FeeDecompositionPage />)
    submitForm('T123456789012345')

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-result')).toBeTruthy()
    })
    const summary = screen.getByTestId('settlement-summary-table')
    // not_applicable 字段不再独占一行，但保证可查：收进“未单列的结算字段”映射区
    expect(within(summary).getByTestId('summary-hidden-fields').textContent).toContain('医疗救助')
    expect(summary.textContent).toContain('—')
    expect(screen.queryByTestId('fee-field-NT_CivilPay')).toBeNull()
    expect(screen.queryByTestId('fee-decomposition-coverage')).toBeNull()
  })

  it('503 未配置：展示 FEE_DECOMPOSITION_NOT_CONFIGURED 与缺失项说明', async () => {
    vi.mocked(decomposeFee).mockRejectedValue(
      new ApiClientError(503, {
        error_code: 'FEE_DECOMPOSITION_NOT_CONFIGURED',
        message: '费用分解未配置：缺少 FEE_DECOMPOSITION_ROUNDING_MODE',
      }),
    )
    render(<FeeDecompositionPage />)
    submitForm('604')

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-error')).toBeTruthy()
    })
    const error = screen.getByTestId('fee-decomposition-error')
    expect(error.textContent).toContain('费用分解功能未配置')
    expect(error.textContent).toContain('FEE_DECOMPOSITION_NOT_CONFIGURED')
    expect(error.textContent).toContain('FEE_DECOMPOSITION_ROUNDING_MODE')
    expect(screen.queryByTestId('fee-decomposition-result')).toBeNull()
  })

  it('unavailable：展示 uncertainties（诚实降级，200 语义）', async () => {
    vi.mocked(decomposeFee).mockResolvedValue({
      ...FULL_RESPONSE,
      execution_status: 'unavailable',
      reconciliation_status: 'not_verifiable',
      fields: [],
      uncertainties: [
        { code: 'UNSUPPORTED_PROFILE', message: '该险种门诊费用分解暂未支持' },
      ],
      meta: { ...FULL_RESPONSE.meta, profile: null },
    })
    render(<FeeDecompositionPage />)
    submitForm('604')

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-result')).toBeTruthy()
    })
    expect(screen.getByTestId('fee-decomposition-unavailable').textContent).toContain('暂无法分解')
    expect(screen.getByTestId('fee-decomposition-unavailable').textContent).toContain('该险种门诊费用分解暂未支持')
    expect(screen.getByTestId('settlement-summary-table')).toBeVisible()
  })

  it('身份证号输入 → 走 resolvePerson，渲染多候选列表（不调用 decomposeFee）', async () => {
    render(<FeeDecompositionPage />)
    submitForm(ID_CARD)

    await waitFor(() => {
      expect(screen.getByTestId('person-candidates')).toBeTruthy()
    })
    expect(resolvePerson).toHaveBeenCalledWith(ID_CARD)
    expect(decomposeFee).not.toHaveBeenCalled()

    const list = screen.getByTestId('person-candidates')
    expect(list.textContent).toContain('普通门诊')
    expect(list.textContent).toContain('职工门诊')
    expect(list.textContent).toContain('2025-11-02')
    expect(list.textContent).toContain('6.50')
    expect(list.textContent).toContain('门诊特殊病')
    expect(list.textContent).toContain('居民门特')
    expect(screen.getByTestId('person-candidate-outpatient-T123456789012345')).toBeTruthy()
    expect(screen.getByTestId('person-candidate-special-604')).toBeTruthy()
  })

  it('唯一候选也列表展示（标注唯一匹配），不自动分解', async () => {
    vi.mocked(resolvePerson).mockResolvedValue({
      match_status: 'unique_match',
      truncated: false,
      candidates: [MULTI_CANDIDATES.candidates[0]],
    })
    render(<FeeDecompositionPage />)
    submitForm(ID_CARD)

    await waitFor(() => {
      expect(screen.getByTestId('person-candidates')).toBeTruthy()
    })
    expect(screen.getByTestId('person-candidates').textContent).toContain('唯一匹配')
    expect(screen.getByTestId('person-candidate-outpatient-T123456789012345')).toBeTruthy()
    expect(decomposeFee).not.toHaveBeenCalled()
  })

  it('no_match：展示「未找到该人员的门诊交易/门特登记」', async () => {
    vi.mocked(resolvePerson).mockResolvedValue({
      match_status: 'no_match',
      truncated: false,
      candidates: [],
    })
    render(<FeeDecompositionPage />)
    submitForm(ID_CARD)

    await waitFor(() => {
      expect(screen.getByTestId('person-candidates-empty')).toBeTruthy()
    })
    expect(screen.getByTestId('person-candidates-empty').textContent).toContain(
      '未找到该人员的门诊交易/门特登记',
    )
  })

  it('truncated=true：展示截断提示', async () => {
    vi.mocked(resolvePerson).mockResolvedValue({ ...MULTI_CANDIDATES, truncated: true })
    render(<FeeDecompositionPage />)
    submitForm(ID_CARD)

    await waitFor(() => {
      expect(screen.getByTestId('person-candidates-truncated')).toBeTruthy()
    })
    expect(screen.getByTestId('person-candidates-truncated').textContent).toContain(
      '结果过多已截断，请改用交易号/登记号精确查询',
    )
  })

  it('点击候选 → 用候选 identifier + chain 调 decomposeFee 并渲染结果，候选列表保留', async () => {
    render(<FeeDecompositionPage />)
    submitForm(ID_CARD)

    await waitFor(() => {
      expect(screen.getByTestId('person-candidates')).toBeTruthy()
    })
    fireEvent.click(screen.getByTestId('person-candidate-outpatient-T123456789012345'))

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-result')).toBeTruthy()
    })
    expect(decomposeFee).toHaveBeenCalledWith('T123456789012345', 'outpatient')
    expect(screen.getByTestId('settlement-summary-table').textContent).toContain('T123456789012345')
    expect(screen.getByTestId('person-candidates')).toBeTruthy()
  })

  it('decompose 返回 422 IDENTIFIER_IS_ID_CARD：错误条展示错误码与提示', async () => {
    vi.mocked(decomposeFee).mockRejectedValue(
      new ApiClientError(422, {
        error_code: 'IDENTIFIER_IS_ID_CARD',
        message: '该单号为身份证号格式，请改用按人定位查询',
      }),
    )
    render(<FeeDecompositionPage />)
    submitForm('T123456789012345')

    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-error')).toBeTruthy()
    })
    const error = screen.getByTestId('fee-decomposition-error')
    expect(error.textContent).toContain('IDENTIFIER_IS_ID_CARD')
    expect(error.textContent).toContain('按人定位')
    expect(screen.queryByTestId('fee-decomposition-result')).toBeNull()
    expect(screen.queryByTestId('person-candidates')).toBeNull()
  })

  it('新查询重置：交易号查询后候选列表与旧结果被清空', async () => {
    render(<FeeDecompositionPage />)
    submitForm(ID_CARD)
    await waitFor(() => {
      expect(screen.getByTestId('person-candidates')).toBeTruthy()
    })

    submitForm('T123456789012345')
    await waitFor(() => {
      expect(screen.getByTestId('fee-decomposition-result')).toBeTruthy()
    })
    expect(screen.queryByTestId('person-candidates')).toBeNull()
    expect(decomposeFee).toHaveBeenCalledWith('T123456789012345', 'auto')
  })
})
