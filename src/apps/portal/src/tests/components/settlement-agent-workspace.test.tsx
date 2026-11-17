import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SettlementAgentWorkspace from '@/components/policy-qa/settlement-agent-workspace'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

const RAW_PATIENT = {
  card_no: '10319565700S',
  id_no_masked: '110***********1634',
  name: '王立全',
  gender: '男',
  birth_date: '1959-10-17',
  registration_id: '821',
}

const RAW_ITEMS = [
  {
    settlement_id: '803',
    settlement_date: '2024-11-03',
    person_type: '退休人员',
    insurance_type: '城镇职工',
    service_type: '普通住院',
    total_amount: 3155.66,
    coverage_status: 'complete',
  },
  {
    settlement_id: '821',
    settlement_date: '2024-11-29',
    person_type: '退休人员',
    insurance_type: '城镇职工',
    service_type: '普通住院',
    total_amount: 2030.0,
    coverage_status: 'complete',
  },
]

function makeExplanationPayload(settlementId: string, total: number) {
  return {
    answer: `结算单 ${settlementId} 的费用构成解释`,
    answer_status: 'complete',
    case_context: { total_amount: total, service_type: '普通住院' },
    calculation_steps: [],
    warnings: [],
    policy_evidence: [],
    citations: [],
    uncertainties: ['测试环境政策依据从略'],
    verification_summary: {
      settlement_checked: true,
      calculation_checked: true,
      policy_count: 0,
      message: '已核对',
    },
    is_broad: false,
  }
}

const COMPARE_PAYLOAD = {
  answer: '两张结算单逐项差异：费用总额 3155.66 → 2030.00，主要差异在统筹支付。',
  answer_status: 'partial',
  calculation_steps: [],
  warnings: [],
  policy_evidence: [],
  citations: [],
  uncertainties: ['部分差异未命中归因规则'],
  verification_summary: {
    settlement_checked: true,
    calculation_checked: false,
    policy_count: 0,
    message: '已核对结算金额，但政策依据不完整',
  },
  is_broad: false,
}

/** 路由桩：patient-lookup / settlements / settlement-explanation（含 compare_with）。 */
function stubFetch() {
  const fetchMock = vi.fn(async (input: string | URL | RequestInfo) => {
    const url = String(input)
    const respond = (payload: unknown, status = 200) =>
      ({
        ok: status >= 200 && status < 300,
        status,
        json: async () => payload,
      }) as Response
    if (url.includes('/policy-qa/patient-lookup')) return respond(RAW_PATIENT)
    if (url.includes('/policy-qa/settlements')) return respond(RAW_ITEMS)
    if (url.includes('/policy-qa/settlement-explanation')) {
      if (url.includes('compare_with=')) return respond(COMPARE_PAYLOAD)
      if (url.includes('settlement_id=803')) return respond(makeExplanationPayload('803', 3155.66))
      if (url.includes('settlement_id=821')) return respond(makeExplanationPayload('821', 2030.0))
      return respond({ detail: 'not found' }, 404)
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function locatePatient() {
  fireEvent.change(screen.getByRole('textbox', { name: '患者身份证号或卡号' }), {
    target: { value: '110104195910171634' },
  })
  fireEvent.click(screen.getByRole('button', { name: '定位' }))
  await waitFor(() => {
    expect(screen.getByTestId('patient-card')).toBeInTheDocument()
  })
  await waitFor(() => {
    expect(screen.getByTestId('settlement-item-803')).toBeInTheDocument()
  })
}

describe('SettlementAgentWorkspace（Issue #87 两单选择与对比）', () => {
  it('选中两张后按时间生成两个 tab，默认展示最新一张，可切换', async () => {
    stubFetch()
    render(<SettlementAgentWorkspace />)
    await locatePatient()

    fireEvent.click(screen.getByTestId('settlement-item-803'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-result-block')).toBeInTheDocument()
    })
    // 单选阶段没有 tab
    expect(screen.queryByTestId('settlement-compare-tabs')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('settlement-item-821'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-compare-tabs')).toBeInTheDocument()
    })

    // 两个 tab：按时间排列，默认激活最新（2024-11-29 · 821）
    const tab803 = screen.getByTestId('settlement-tab-803')
    const tab821 = screen.getByTestId('settlement-tab-821')
    expect(tab803).toHaveAttribute('aria-selected', 'false')
    expect(tab821).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('settlement-result-block')).toHaveTextContent('结算单 821')

    // 切换到较早一张
    fireEvent.click(tab803)
    await waitFor(() => {
      expect(screen.getByTestId('settlement-result-block')).toHaveTextContent('结算单 803')
    })
    expect(tab803).toHaveAttribute('aria-selected', 'true')
    expect(tab821).toHaveAttribute('aria-selected', 'false')
  })

  it('选中两张后提问按两张对比作答（较早一张为基准），问答落入对话流', async () => {
    const fetchMock = stubFetch()
    render(<SettlementAgentWorkspace />)
    await locatePatient()

    fireEvent.click(screen.getByTestId('settlement-item-803'))
    fireEvent.click(screen.getByTestId('settlement-item-821'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-compare-tabs')).toBeInTheDocument()
    })
    expect(screen.getByTestId('settlement-compare-hint')).toHaveTextContent('以较早一张')

    fireEvent.change(screen.getByRole('textbox', { name: '政策问题' }), {
      target: { value: '为什么两次结算的金额不一样' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByText('为什么两次结算的金额不一样')).toBeInTheDocument()
      expect(screen.getByText(/两张结算单逐项差异/)).toBeInTheDocument()
    })

    const compareCall = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes('compare_with='),
    )
    expect(compareCall).toBeDefined()
    const compareUrl = String(compareCall?.[0])
    // 基准 = 较早一张（803 / 2024-11-03）
    expect(compareUrl).toContain('settlement_id=803')
    expect(compareUrl).toContain('compare_with=821')
    expect(compareUrl).toContain(encodeURIComponent('为什么两次结算的金额不一样'))
  })

  it('取消一张后回到单笔解释，tab 消失', async () => {
    stubFetch()
    render(<SettlementAgentWorkspace />)
    await locatePatient()

    fireEvent.click(screen.getByTestId('settlement-item-803'))
    fireEvent.click(screen.getByTestId('settlement-item-821'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-compare-tabs')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('settlement-item-821'))
    await waitFor(() => {
      expect(screen.queryByTestId('settlement-compare-tabs')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('settlement-result-block')).toHaveTextContent('结算单 803')
  })

  it('解释区固定在右侧栏：一张或两张选中时均展示在同一右侧 aside', async () => {
    stubFetch()
    render(<SettlementAgentWorkspace />)
    await locatePatient()

    // 未选单：无右侧解释栏
    expect(screen.queryByTestId('settlement-explanation-aside')).not.toBeInTheDocument()

    // 选一张：解释进右侧栏，无 tab
    fireEvent.click(screen.getByTestId('settlement-item-803'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-explanation-aside')).toBeInTheDocument()
    })
    expect(screen.getByTestId('settlement-explanation-aside')).toContainElement(
      screen.getByTestId('settlement-result-block'),
    )

    // 选两张：tab 与激活单解释都在同一右侧栏内
    fireEvent.click(screen.getByTestId('settlement-item-821'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-compare-tabs')).toBeInTheDocument()
    })
    expect(screen.getByTestId('settlement-explanation-aside')).toContainElement(
      screen.getByTestId('settlement-compare-tabs'),
    )
    expect(screen.getByTestId('settlement-explanation-aside')).toContainElement(
      screen.getByTestId('settlement-result-block'),
    )
  })

  it('换人清空上一患者的选中单与解释（禁止跨患者锚定）', async () => {
    stubFetch()
    render(<SettlementAgentWorkspace />)
    await locatePatient()

    fireEvent.click(screen.getByTestId('settlement-item-803'))
    fireEvent.click(screen.getByTestId('settlement-item-821'))
    await waitFor(() => {
      expect(screen.getByTestId('settlement-compare-tabs')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: '换人' }))
    await waitFor(() => {
      expect(screen.queryByTestId('settlement-compare-tabs')).not.toBeInTheDocument()
      expect(screen.queryByTestId('settlement-result-block')).not.toBeInTheDocument()
    })
    expect(screen.getByTestId('patient-locate-form')).toBeInTheDocument()
  })
})
