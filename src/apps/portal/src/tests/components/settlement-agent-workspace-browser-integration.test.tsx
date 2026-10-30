// 结算解释工作区 × 真实 SettlementTimeBrowser 联合用例（R1/R6）。
// 只 mock 网络边界（患者定位/列表/分解）与会话 hook，父子组件均为真实实现，
// 避免父层 stub 主动重推候选掩盖「新会话丢候选」「旧患者列表覆盖」类缺陷。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/policy-qa-settlement-list', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-qa-settlement-list')>()
  return {
    ...actual,
    fetchPatientLookup: vi.fn(),
    fetchSettlementsByDateRange: vi.fn(),
  }
})

vi.mock('@/lib/fee-decomposition-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/fee-decomposition-api')>()
  return { ...actual, fetchSessionDecomposition: vi.fn() }
})

const sendMock = vi.hoisted(() => vi.fn(async () => true))
const resetSessionMock = vi.hoisted(() => {
  let seq = 0
  return vi.fn(() => `sess-${++seq}`)
})
const updateAnchorMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/use-policy-qa-stream', () => ({
  usePolicyQAStream: () => ({
    sessionId: 'sess-live',
    mode: 'settlement_explain',
    anchor: { settlementId: null, subjectChanged: false, subjectChangeMsg: null },
    memories: [],
    messages: [],
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
    updateAnchor: updateAnchorMock,
    dismissSubjectChange: vi.fn(),
    appendLocalMessage: vi.fn(),
  }),
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
  fetchPatientLookup,
  fetchSettlementsByDateRange,
  type PatientSummaryDTO,
  type SettlementListItemDTO,
} from '@/lib/policy-qa-settlement-list'
import {
  fetchSessionDecomposition,
  type FeeDecompositionResponseDto,
} from '@/lib/fee-decomposition-api'

const PATIENT: PatientSummaryDTO = {
  name: '张三',
  idNoMasked: '110***********0937',
  cardNo: '10065478600S',
  gender: '男',
  birthDate: '1942-03-28',
  registrationId: 'P1',
} as PatientSummaryDTO

const ITEM_OUTPATIENT: SettlementListItemDTO = {
  settlementId: '011100030X240408000002',
  settlementDate: '2024-04-08',
  personType: '居民',
  insuranceType: '居民',
  serviceType: '普通门诊',
  totalAmount: 3435,
  coverageStatus: 'complete',
  decompositionChain: 'outpatient',
} as SettlementListItemDTO

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
      field_code: 'T_FeeAll',
      label: '费用总金额',
      check_type: 'detail_aggregation',
      check_status: 'matched',
      observed_amount: '3435.00',
      calculated_amount: '3435.00',
      difference: '0.00',
      explanation_level: 'amount_reconciled',
    },
  ],
  fee_items: [],
  uncertainties: [],
  coverage: {
    target_field_count: 1,
    independently_explained_count: 0,
    amount_reconciled_count: 1,
    observed_only_count: 0,
  },
  settlement_facts: {
    chain: 'outpatient',
    identifier: '011100030X240408000002',
    trade_date: '2024-04-08',
    medical_category: '普通门诊',
    insurance_type: '居民',
    person_type: '居民',
    hospital_level: '二级',
    items: [{ label: '费用总金额', value: '3435.00' }],
    payment_items: [],
  },
  meta: {
    identifier: '011100030X240408000002',
    chain: 'outpatient',
    profile: 'resident_outpatient',
    algorithm_version: 'fee-decomp-v1',
  },
} as unknown as FeeDecompositionResponseDto

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function locatePatient(key = 'KEY-A') {
  fireEvent.change(screen.getByRole('textbox', { name: '患者身份证号或卡号' }), {
    target: { value: key },
  })
  fireEvent.click(screen.getByRole('button', { name: '定位' }))
  await screen.findByTestId('patient-card')
}

async function selectItem(item: SettlementListItemDTO = ITEM_OUTPATIENT) {
  await screen.findByTestId(`settlement-item-${item.settlementId}`)
  fireEvent.click(screen.getByTestId(`settlement-item-${item.settlementId}`))
}

function sendCommand(text: string) {
  fireEvent.change(screen.getByLabelText('结算追问'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '发送' }))
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('结算解释工作区（R1/R6：患者与会话生命周期）', () => {
  it('A5/R6 选单→新会话→同单命令：保留候选并复用同一链路与新 session', async () => {
    vi.mocked(fetchPatientLookup).mockResolvedValue(PATIENT)
    vi.mocked(fetchSettlementsByDateRange).mockResolvedValue([ITEM_OUTPATIENT])
    vi.mocked(fetchSessionDecomposition).mockResolvedValue(DECOMPOSE_RESPONSE)
    render(<SettlementAgentWorkspace />)

    await locatePatient()
    await selectItem()
    await waitFor(() => expect(fetchSessionDecomposition).toHaveBeenCalledTimes(1))
    const firstSession = vi.mocked(fetchSessionDecomposition).mock.calls[0][0]

    // 新会话：列表与患者仍在
    fireEvent.click(screen.getByRole('button', { name: '新会话' }))
    expect(screen.getByTestId(`settlement-item-${ITEM_OUTPATIENT.settlementId}`)).toBeInTheDocument()
    expect(screen.getByTestId('patient-card')).toBeInTheDocument()

    // 同一可见条目的命令必须命中（与非新会话时点击一致）
    sendCommand(`@换结算 ${ITEM_OUTPATIENT.settlementId}`)
    await waitFor(() => expect(fetchSessionDecomposition).toHaveBeenCalledTimes(2))
    const secondCall = vi.mocked(fetchSessionDecomposition).mock.calls[1]
    expect(secondCall[1]).toBe(ITEM_OUTPATIENT.settlementId)
    expect(secondCall[2]).toBe('outpatient')
    expect(secondCall[0]).not.toBe(firstSession)

    // 新会话后提问使用同一批 session/单号
    sendCommand('这笔门诊费用怎么算的？')
    await waitFor(() => expect(sendMock).toHaveBeenCalled())
    expect(resetSessionMock.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('A1 联合：旧患者列表晚到后，命令不能加载旧患者单据', async () => {
    const slowA = deferred<SettlementListItemDTO[]>()
    vi.mocked(fetchPatientLookup).mockResolvedValueOnce(PATIENT)
    vi.mocked(fetchPatientLookup).mockResolvedValueOnce({
      ...PATIENT,
      name: '李四',
    } as PatientSummaryDTO)
    vi.mocked(fetchSettlementsByDateRange)
      .mockReturnValueOnce(slowA.promise)
      .mockResolvedValueOnce([])
    vi.mocked(fetchSessionDecomposition).mockResolvedValue(DECOMPOSE_RESPONSE)
    render(<SettlementAgentWorkspace />)

    await locatePatient('KEY-A')
    // A 的列表挂起 → 换人并定位 B
    fireEvent.click(screen.getByRole('button', { name: '换人' }))
    await locatePatient('KEY-B')
    // A 的慢响应此刻才返回
    slowA.resolve([ITEM_OUTPATIENT])
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByTestId(`settlement-item-${ITEM_OUTPATIENT.settlementId}`)).toBeNull()

    sendCommand(`@换结算 ${ITEM_OUTPATIENT.settlementId}`)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('不在当前患者的候选结算单中'))
    expect(fetchSessionDecomposition).not.toHaveBeenCalled()
  })

  it('A6 新会话时解释请求挂起：旧解释不得回填新会话', async () => {
    const slowExplanation = deferred<FeeDecompositionResponseDto>()
    vi.mocked(fetchPatientLookup).mockResolvedValue(PATIENT)
    vi.mocked(fetchSettlementsByDateRange).mockResolvedValue([ITEM_OUTPATIENT])
    vi.mocked(fetchSessionDecomposition).mockReturnValueOnce(slowExplanation.promise)
    render(<SettlementAgentWorkspace />)

    await locatePatient()
    await selectItem()
    await waitFor(() => expect(fetchSessionDecomposition).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: '新会话' }))
    slowExplanation.resolve(DECOMPOSE_RESPONSE)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByTestId('settlement-bill-view')).toBeNull()
  })
})
