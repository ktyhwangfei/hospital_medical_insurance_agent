// 结算解释工作区门诊展示链路测试 — Issue #78。
// 覆盖：门诊/门特单走会话共享分解端点 fetchSessionDecomposition（与聊天同一实例）
// 渲染结算单式样 SettlementBillView；住院单（chain=null）走原 settlement-explanation
// 路径渲染 SettlementResultBlock；分解契约校验失败 / 端点报错走既有 explanationError 条；
// 刷新恢复路径：轨迹消息中的 feeDecomposition 与实时面板载荷同源一致。
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/fee-decomposition-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/fee-decomposition-api')>()
  return { ...actual, fetchSessionDecomposition: vi.fn() }
})

const sendMock = vi.hoisted(() => vi.fn(async () => true))
const resetSessionMock = vi.hoisted(() => vi.fn(() => 'sess-reset-1'))
// 可按用例覆写的会话状态（恢复路径需要预置轨迹消息与锚点）
const hookState = vi.hoisted(() => ({
  messages: [] as Array<Record<string, unknown>>,
  anchorSettlementId: null as string | null,
}))

// 隔离会话流 hook 与患者定位/列表子组件，只验证工作区的路径分流
vi.mock('@/lib/use-policy-qa-stream', () => ({
  usePolicyQAStream: () => ({
    sessionId: 'test-session',
    mode: 'settlement_explain',
    anchor: {
      settlementId: hookState.anchorSettlementId,
      subjectChanged: false,
      subjectChangeMsg: null,
    },
    memories: [],
    messages: hookState.messages,
    lastContextNeed: null,
    steps: [],
    isStreaming: false,
    error: null,
    restoring: false,
    sessionStatus: 'unknown',
    statusReason: '',
    escalation: null,
    send: sendMock,
    resetSession: resetSessionMock,
    suspendSession: vi.fn(),
    resumeSession: vi.fn(),
    escalateSession: vi.fn(),
    resolveEscalation: vi.fn(),
    updateAnchor: vi.fn(),
    dismissSubjectChange: vi.fn(),
    appendLocalMessage: vi.fn(),
  }),
}))

vi.mock('@/components/policy-qa/settlement-time-browser', () => ({
  default: ({
    onSelect,
    onPatientChange,
    onCandidatesChange,
  }: {
    onSelect: (item: {
      settlementId: string
      settlementDate: string
      serviceType: string
      decompositionChain: 'outpatient' | 'special' | null
    }) => void
    onPatientChange?: (patient: null) => void
    onCandidatesChange?: (items: Array<{
      settlementId: string
      settlementDate: string
      serviceType: string
      decompositionChain: 'outpatient' | 'special' | null
    }>) => void
  }) => {
    const candidates = [
      {
        settlementId: 'T123456789012345',
        settlementDate: '2026-09-14 15:30:00',
        serviceType: '门诊',
        decompositionChain: 'outpatient' as const,
      },
      {
        settlementId: '1671213',
        settlementDate: '2026-09-14',
        serviceType: '普通住院',
        decompositionChain: null,
      },
    ]
    return (
      <div data-testid="browser-stub">
        <button type="button" data-testid="select-outpatient" onClick={() => onSelect(candidates[0])}>
          门诊单
        </button>
        <button type="button" data-testid="select-inpatient" onClick={() => onSelect(candidates[1])}>
          住院单
        </button>
        <button
          type="button"
          data-testid="load-candidates"
          onClick={() => onCandidatesChange?.(candidates)}
        >
          加载候选
        </button>
        <button type="button" data-testid="switch-patient" onClick={() => onPatientChange?.(null)}>
          换患者
        </button>
      </div>
    )
  },
}))

vi.mock('@/components/policy-qa/policy-composer', () => ({
  default: ({ value, onChange, onSend }: { value: string; onChange: (value: string) => void; onSend: () => void }) => (
    <div data-testid="policy-qa-composer">
      <input aria-label="结算追问" value={value} onChange={(event) => onChange(event.target.value)} />
      <button type="button" onClick={onSend}>发送</button>
    </div>
  ),
}))
vi.mock('@/components/policy-qa/policy-message-list', () => ({ default: () => null }))

import SettlementAgentWorkspace from '@/components/policy-qa/settlement-agent-workspace'
import {
  fetchSessionDecomposition,
  type FeeDecompositionResponseDto,
} from '@/lib/fee-decomposition-api'
import { toFeeDecomposition } from '@/lib/policy-qa-stream'

const DECOMPOSE_RESPONSE: FeeDecompositionResponseDto = {
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
  fee_items: [
    {
      line_id: '1',
      item_code: 'MED-1',
      item_name: '测试药品',
      item_type: '药品',
      fee_date: '2026-09-14',
      unit_price: '100.00',
      quantity: '1',
      total_fee: '100.00',
      observed_in_scope: '100.00',
      observed_out_scope: '0',
      observed_self_pay_2: '0',
      calculated_in_scope: '100.00',
      calculated_out_scope: '0',
      calculated_self_pay_2: '0',
      status: 'calculated',
      conditions: [],
      formulas: [],
      notes: [],
    },
  ],
  uncertainties: [],
  coverage: {
    target_field_count: 1,
    independently_explained_count: 1,
    amount_reconciled_count: 0,
    observed_only_count: 0,
  },
  settlement_facts: {
    chain: 'outpatient',
    identifier: 'T123456789012345',
    trade_date: '2026-09-14 15:30:00',
    medical_category: '普通门诊',
    insurance_type: '城镇职工',
    person_type: '在职',
    hospital_level: '三级',
    items: [{ label: '费用总金额', value: '100.00' }],
    payment_items: [],
  },
  meta: {
    identifier: 'T123456789012345',
    chain: 'outpatient',
    profile: 'employee_outpatient',
    algorithm_version: 'fee-decomp-v1',
  },
}

// 通过 toPolicyQAResult 严格校验的最小住院结算解释结果
const INPATIENT_RESULT = {
  answer: '住院费用构成解释。',
  answer_status: 'complete',
  verification_summary: {
    settlement_checked: true,
    calculation_checked: true,
    policy_count: 1,
    message: '已完成核验。',
  },
  citations: [{ title: '医保政策', excerpt: '政策条文摘录' }],
  uncertainties: [],
}

function stubExplanationFetch() {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => INPATIENT_RESULT,
  })) as unknown as typeof fetch
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock as unknown as ReturnType<typeof vi.fn>
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  window.sessionStorage.clear()
  hookState.messages = []
  hookState.anchorSettlementId = null
})

describe('SettlementAgentWorkspace 门诊/门特分解链路', () => {
  it('快速切换结算单时旧请求不能覆盖当前单据的回显', async () => {
    let finishOld!: (value: FeeDecompositionResponseDto) => void
    vi.mocked(fetchSessionDecomposition).mockReturnValue(new Promise((resolve) => { finishOld = resolve }))
    stubExplanationFetch()
    render(<SettlementAgentWorkspace />)
    fireEvent.click(screen.getByTestId('select-outpatient'))
    fireEvent.click(screen.getByTestId('select-inpatient'))
    await screen.findByTestId('settlement-result-block')
    await act(async () => finishOld(DECOMPOSE_RESPONSE))
    expect(screen.queryByTestId('settlement-decomposition-result')).toBeNull()
  })
  it('门诊交易单：右侧只读展示交易信息和费用明细，中间保留问答，不请求住院解释', async () => {
    vi.mocked(fetchSessionDecomposition).mockResolvedValue(DECOMPOSE_RESPONSE)
    const fetchMock = stubExplanationFetch()
    // 结果区在长列表下方：账单就绪后自动滚入视野
    const scrollSpy = vi.fn()
    window.HTMLElement.prototype.scrollIntoView = scrollSpy
    render(<SettlementAgentWorkspace />)

    fireEvent.click(screen.getByTestId('select-outpatient'))

    await waitFor(() => {
      expect(screen.getByTestId('settlement-bill-view')).toBeInTheDocument()
    })
    // 面板与聊天共用同一会话的共享分解实例（选单重置会话后取新 session id）
    expect(fetchSessionDecomposition).toHaveBeenCalledWith('sess-reset-1', 'T123456789012345', 'outpatient')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(sendMock).not.toHaveBeenCalled()
    const sidebar = screen.getByTestId('settlement-details-sidebar')
    expect(sidebar).toHaveClass('xl:sticky')
    expect(sidebar.textContent).toContain('交易相关信息（元）')
    expect(sidebar.textContent).toContain('T123456789012345')
    expect(sidebar.textContent).toContain('2026-09-14 15:30')
    expect(sidebar.textContent).toContain('测试药品')
    expect(within(sidebar).getByRole('region', { name: '逐项费用分解' })).toBeInTheDocument()
    expect(within(screen.getByTestId('settlement-chat-column')).getByTestId('policy-qa-composer')).toBeInTheDocument()
    expect(within(sidebar).queryByRole('button', { name: /为什么是这个比例/ })).not.toBeInTheDocument()
    expect(screen.queryByTestId('settlement-result-block')).not.toBeInTheDocument()
    // 选单不自动提问；用户主动追问时仍携带当前结算单锚点。
    fireEvent.change(screen.getByLabelText('结算追问'), { target: { value: '为什么本单按70%支付？' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => {
      expect(sendMock).toHaveBeenCalledWith(
        '为什么本单按70%支付？',
        { settlementId: 'T123456789012345', decompositionChain: 'outpatient' },
      )
    })
    // 数据就绪后仍定位到问答区，侧栏保持可见
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled())
  })

  it('住院单（chain=null）：走原 settlement-explanation 路径，不调用共享分解端点', async () => {
    window.sessionStorage.setItem('fee-decomposition-token', 'Bearer test-token')
    const fetchMock = stubExplanationFetch()
    render(<SettlementAgentWorkspace />)

    fireEvent.click(screen.getByTestId('select-inpatient'))

    await waitFor(() => {
      expect(screen.getByTestId('settlement-result-block')).toBeInTheDocument()
    })
    expect(fetchSessionDecomposition).not.toHaveBeenCalled()
    const url = String(fetchMock.mock.calls[0]?.[0])
    expect(url).toContain('/policy-qa/settlement-explanation')
    expect(url).toContain('settlement_id=1671213')
    expect(screen.queryByTestId('settlement-bill-view')).not.toBeInTheDocument()
    // 旧 GET 读取同样携带费用读取令牌（鉴权与费用分解同权）
    const init = fetchMock.mock.calls[0]?.[1] as { headers?: Record<string, string> } | undefined
    expect(init?.headers?.Authorization).toBe('Bearer test-token')
  })

  it('fetchSessionDecomposition 报错：复用 explanationError 条展示', async () => {
    vi.mocked(fetchSessionDecomposition).mockRejectedValue(new Error('费用分解功能未配置'))
    stubExplanationFetch()
    render(<SettlementAgentWorkspace />)

    fireEvent.click(screen.getByTestId('select-outpatient'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('费用分解功能未配置')
    })
    expect(screen.queryByTestId('settlement-bill-view')).not.toBeInTheDocument()
  })

  it('刷新恢复：轨迹消息中的 feeDecomposition 与实时面板同源一致渲染', async () => {    // 刷新后无选单动作：面板回落到会话轨迹里同单的分解载荷（与端点同一实例）
    hookState.anchorSettlementId = 'T123456789012345'
    hookState.messages = [
      { role: 'user', content: '这笔门诊费用怎么算的' },
      {
        role: 'assistant',
        content: '本笔门诊费用分解核对完成。',
        feeDecomposition: toFeeDecomposition(DECOMPOSE_RESPONSE),
      },
    ]
    render(<SettlementAgentWorkspace />)

    await waitFor(() => {
      expect(screen.getByTestId('settlement-bill-view')).toBeInTheDocument()
    })
    // 恢复路径不再请求端点，也不请求住院解释
    expect(fetchSessionDecomposition).not.toHaveBeenCalled()
    const sidebar = screen.getByTestId('settlement-details-sidebar')
    expect(sidebar.textContent).toContain('T123456789012345')
    expect(sidebar.textContent).toContain('测试药品')
    expect(within(sidebar).getByRole('region', { name: '逐项费用分解' })).toBeInTheDocument()
  })
})

describe('SettlementAgentWorkspace @换结算 命令链路', () => {
  // 命令换单必须复用列表点击入口：链路/日期/类型取当前患者候选，不退回住院查询。
  const sendCommand = (text: string) => {
    fireEvent.change(screen.getByLabelText('结算追问'), { target: { value: text } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
  }

  it('命令选门诊单与列表选单请求一致（同一分解端点与链路）', async () => {
    vi.mocked(fetchSessionDecomposition).mockResolvedValue(DECOMPOSE_RESPONSE)
    const fetchMock = stubExplanationFetch()
    render(<SettlementAgentWorkspace />)
    fireEvent.click(screen.getByTestId('load-candidates'))

    sendCommand('@换结算 T123456789012345')

    await waitFor(() => {
      expect(fetchSessionDecomposition).toHaveBeenCalledWith(
        'sess-reset-1', 'T123456789012345', 'outpatient')
    })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.getByTestId('settlement-bill-view')).toBeInTheDocument()
    // 命令不当作问题发送给聊天
    expect(sendMock).not.toHaveBeenCalled()
  })

  it('命令选住院条目保留住院分支（旧 GET，不调用共享分解端点）', async () => {
    const fetchMock = stubExplanationFetch()
    render(<SettlementAgentWorkspace />)
    fireEvent.click(screen.getByTestId('load-candidates'))

    sendCommand('@换结算 1671213')

    await waitFor(() => {
      expect(screen.getByTestId('settlement-result-block')).toBeInTheDocument()
    })
    expect(fetchSessionDecomposition).not.toHaveBeenCalled()
    const url = String(fetchMock.mock.calls[0]?.[0])
    expect(url).toContain('/policy-qa/settlement-explanation')
    expect(url).toContain('settlement_id=1671213')
  })

  it('候选外单号：提示调整时段并选单，不猜链路、不请求任何读取', async () => {
    const fetchMock = stubExplanationFetch()
    render(<SettlementAgentWorkspace />)
    fireEvent.click(screen.getByTestId('load-candidates'))

    sendCommand('@换结算 688')

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('不在当前患者的候选结算单中')
    })
    expect(fetchSessionDecomposition).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('换患者后候选清空：仍按候选外单号提示，不跨患者锚定', async () => {
    const fetchMock = stubExplanationFetch()
    render(<SettlementAgentWorkspace />)
    fireEvent.click(screen.getByTestId('load-candidates'))
    fireEvent.click(screen.getByTestId('switch-patient'))

    sendCommand('@换结算 T123456789012345')

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('不在当前患者的候选结算单中')
    })
    expect(fetchSessionDecomposition).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('命令换单后慢旧响应晚返回不覆盖新单', async () => {
    let finishOld!: (value: FeeDecompositionResponseDto) => void
    vi.mocked(fetchSessionDecomposition).mockReturnValueOnce(
      new Promise((resolve) => { finishOld = resolve }))
    stubExplanationFetch()
    render(<SettlementAgentWorkspace />)
    fireEvent.click(screen.getByTestId('load-candidates'))

    sendCommand('@换结算 T123456789012345')
    sendCommand('@换结算 1671213')
    await screen.findByTestId('settlement-result-block')
    await act(async () => finishOld(DECOMPOSE_RESPONSE))

    expect(screen.queryByTestId('settlement-decomposition-result')).toBeNull()
    expect(screen.getByTestId('settlement-result-block')).toBeInTheDocument()
  })
})
