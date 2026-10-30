import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SettlementTimeBrowser from '@/components/policy-qa/settlement-time-browser'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const RAW_ITEMS = [
  {
    settlement_id: '1671213',
    settlement_date: '2026-09-14',
    person_type: '退休人员',
    insurance_type: '城镇职工',
    service_type: '普通住院',
    total_amount: 12386.4,
    coverage_status: 'complete',
  },
]

const RAW_PATIENT = {
  card_no: '10065478600S',
  id_no_masked: '110***********0937',
  name: '张三',
  gender: '男',
  birth_date: '1942-03-28',
  registration_id: '1671213',
}

/** 按路径分发：patient-lookup 与 settlements 两个端点；数值 payload = HTTP 状态码。 */
function stubFetch(routes: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: string | URL | RequestInfo) => {
    const url = String(input)
    for (const [fragment, payload] of Object.entries(routes)) {
      if (url.includes(fragment)) {
        const isError = typeof payload === 'number'
        const status = isError ? payload : 200
        return {
          ok: !isError,
          status,
          json: async () => (isError ? { detail: 'error' } : payload),
        } as Response
      }
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function locatePatient(key = '110103194203280937') {
  fireEvent.change(screen.getByRole('textbox', { name: '患者身份证号或卡号' }), {
    target: { value: key },
  })
  fireEvent.click(screen.getByRole('button', { name: '定位' }))
  await waitFor(() => {
    expect(screen.getByTestId('patient-card')).toBeInTheDocument()
  })
}

describe('SettlementTimeBrowser（患者定位 + 时间浏览）', () => {
  it('未定位患者时只显示定位表单与引导，不请求列表', () => {
    const fetchMock = stubFetch({ '/policy-qa/settlements': RAW_ITEMS })

    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)

    expect(screen.getByTestId('patient-locate-form')).toBeInTheDocument()
    expect(screen.getByText('先定位患者，再看 TA 的时段结算单。')).toBeInTheDocument()
    expect(screen.queryByTestId('settlement-list')).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
    // 时段预设禁用（防误触全院浏览）
    expect(screen.getByTestId('settlement-preset-this_week')).toBeDisabled()
  })

  it('定位成功显示患者卡（脱敏身份证）并自动按患者加载列表', async () => {
    const fetchMock = stubFetch({
      '/policy-qa/patient-lookup': RAW_PATIENT,
      '/policy-qa/settlements': RAW_ITEMS,
    })
    const onPatientChange = vi.fn()
    render(
      <SettlementTimeBrowser
        selectedId={null}
        onSelect={() => {}}
        onPatientChange={onPatientChange}
      />,
    )

    await locatePatient()

    // 患者卡：姓名 + 脱敏身份证 + 卡号
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.getByText(/110\*{11}0937/)).toBeInTheDocument()
    expect(screen.getByText(/卡号 10065478600S/)).toBeInTheDocument()
    expect(onPatientChange).toHaveBeenCalledWith(
      expect.objectContaining({ name: '张三', idNoMasked: '110***********0937' }),
    )

    // 自动加载列表：URL 带 patient_key
    await waitFor(() => {
      expect(screen.getByTestId('settlement-list')).toBeInTheDocument()
    })
    const listUrl = String(
      fetchMock.mock.calls.find((call) => String(call[0]).includes('/settlements'))?.[0],
    )
    expect(listUrl).toContain('patient_key=110103194203280937')
    expect(screen.getByText('1671213')).toBeInTheDocument()
    expect(screen.getByText('12,386.40')).toBeInTheDocument()
  })

  it('点击结算单行触发 onSelect(item)，住院单 decompositionChain 为 null', async () => {
    stubFetch({
      '/policy-qa/patient-lookup': RAW_PATIENT,
      '/policy-qa/settlements': RAW_ITEMS,
    })
    const onSelect = vi.fn()
    render(<SettlementTimeBrowser selectedId={null} onSelect={onSelect} />)

    await locatePatient()
    await waitFor(() => {
      expect(screen.getByTestId('settlement-item-1671213')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('settlement-item-1671213'))
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ settlementId: '1671213', decompositionChain: null }),
    )
  })

  it('门诊交易单带「门诊分解」徽标，onSelect 携带 decompositionChain=outpatient', async () => {
    stubFetch({
      '/policy-qa/patient-lookup': RAW_PATIENT,
      '/policy-qa/settlements': [
        {
          settlement_id: 'T123456789012345',
          settlement_date: '2026-09-14',
          person_type: '在职人员',
          insurance_type: '城镇职工',
          service_type: '普通门诊',
          total_amount: 6.5,
          coverage_status: 'complete',
          decomposition_chain: 'outpatient',
        },
        ...RAW_ITEMS,
      ],
    })
    const onSelect = vi.fn()
    render(<SettlementTimeBrowser selectedId={null} onSelect={onSelect} />)

    await locatePatient()
    await waitFor(() => {
      expect(screen.getByTestId('settlement-item-T123456789012345')).toBeInTheDocument()
    })
    // 门诊单有徽标，住院单无徽标
    expect(screen.getByTestId('settlement-chain-badge-T123456789012345')).toHaveTextContent(
      '门诊分解',
    )
    expect(screen.queryByTestId('settlement-chain-badge-1671213')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('settlement-item-T123456789012345'))
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        settlementId: 'T123456789012345',
        decompositionChain: 'outpatient',
      }),
    )
  })

  it('定位未命中显示错误提示，不进入患者卡', async () => {
    stubFetch({ '/policy-qa/patient-lookup': 404 })

    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)

    fireEvent.change(screen.getByRole('textbox', { name: '患者身份证号或卡号' }), {
      target: { value: 'NOT-EXIST' },
    })
    fireEvent.click(screen.getByRole('button', { name: '定位' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('未找到该患者')
    })
    expect(screen.queryByTestId('patient-card')).not.toBeInTheDocument()
  })

  it('列表接口失败展示内联错误', async () => {
    stubFetch({
      '/policy-qa/patient-lookup': RAW_PATIENT,
      '/policy-qa/settlements': 503,
    })

    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)

    await locatePatient()
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('结算单列表查询失败')
    })
  })

  it('空结果展示空状态提示', async () => {
    stubFetch({
      '/policy-qa/patient-lookup': RAW_PATIENT,
      '/policy-qa/settlements': [],
    })

    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)

    await locatePatient()
    await waitFor(() => {
      expect(screen.getByText('该时段暂无结算单，切换时段或刷新试试。')).toBeInTheDocument()
    })
  })

  it('换人清空患者与列表并回调 onPatientChange(null)', async () => {
    stubFetch({
      '/policy-qa/patient-lookup': RAW_PATIENT,
      '/policy-qa/settlements': RAW_ITEMS,
    })
    const onPatientChange = vi.fn()
    render(
      <SettlementTimeBrowser
        selectedId={null}
        onSelect={() => {}}
        onPatientChange={onPatientChange}
      />,
    )

    await locatePatient('10065478600S')
    fireEvent.click(screen.getByRole('button', { name: '换人' }))

    expect(screen.getByTestId('patient-locate-form')).toBeInTheDocument()
    expect(screen.queryByTestId('settlement-list')).not.toBeInTheDocument()
    expect(screen.getByText('先定位患者，再看 TA 的时段结算单。')).toBeInTheDocument()
    // 换人清空输入框，避免误用上一患者键
    expect(screen.getByRole('textbox', { name: '患者身份证号或卡号' })).toHaveValue('')
    expect(onPatientChange).toHaveBeenLastCalledWith(null)
  })

  it('空输入禁用定位按钮', () => {
    stubFetch({})
    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)

    expect(screen.getByRole('button', { name: '定位' })).toBeDisabled()
  })
})

// ── R1：患者/查询上下文代次（旧响应不得覆盖新上下文）────────────────

const PATIENT_A = { ...RAW_PATIENT, name: '张三', id_no_masked: '110***********0937' }
const PATIENT_B = {
  ...RAW_PATIENT,
  name: '李四',
  id_no_masked: '110***********0001',
  registration_id: '900001',
}
const ITEM_A = {
  settlement_id: '011100030X240408000002',
  settlement_date: '2024-04-08',
  person_type: '居民',
  insurance_type: '居民',
  service_type: '普通门诊',
  total_amount: 3435,
  coverage_status: 'complete',
  decomposition_chain: 'outpatient' as const,
}
const ITEM_B = {
  settlement_id: '011100030X241118000008',
  settlement_date: '2024-11-18',
  person_type: '在职',
  insurance_type: '城镇职工',
  service_type: '普通门诊',
  total_amount: 3000,
  coverage_status: 'complete',
  decomposition_chain: 'outpatient' as const,
}
const ITEM_A2 = { ...ITEM_A, settlement_id: '011100030X240408000099' }

/** 手动控制每个 fetch 响应到达顺序（deferred），不依赖随机延时。 */
function deferredFetch() {
  const pending: Array<{
    url: string
    resolve: (payload: unknown) => void
    reject: (error: Error) => void
  }> = []
  const fetchMock = vi.fn(
    (input: string | URL | RequestInfo) =>
      new Promise<Response>((resolve, reject) => {
        pending.push({
          url: String(input),
          resolve: (payload) =>
            resolve({ ok: true, status: 200, json: async () => payload } as Response),
          reject,
        })
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, pending }
}

async function locateWithDeferred(
  key: string,
  pending: ReturnType<typeof deferredFetch>['pending'],
  patient: unknown,
) {
  fireEvent.change(screen.getByRole('textbox', { name: '患者身份证号或卡号' }), {
    target: { value: key },
  })
  fireEvent.click(screen.getByRole('button', { name: '定位' }))
  await waitFor(() => expect(pending.length).toBeGreaterThan(0))
  pending.shift()!.resolve(patient)
  await waitFor(() => expect(screen.getByTestId('patient-card')).toBeInTheDocument())
}

describe('SettlementTimeBrowser 患者/查询上下文代次（R1）', () => {
  it('A1 旧患者列表慢响应释放后不得覆盖新患者列表与候选', async () => {
    const { pending } = deferredFetch()
    const onCandidatesChange = vi.fn()
    render(
      <SettlementTimeBrowser
        selectedId={null}
        onSelect={() => {}}
        onCandidatesChange={onCandidatesChange}
      />,
    )
    await locateWithDeferred('KEY-A', pending, PATIENT_A)
    await waitFor(() => expect(pending.length).toBe(1))
    const slowListA = pending.shift()!

    fireEvent.click(screen.getByRole('button', { name: '换人' }))
    await locateWithDeferred('KEY-B', pending, PATIENT_B)
    await waitFor(() => expect(pending.length).toBe(1))
    pending.shift()!.resolve([ITEM_B])
    await waitFor(() => expect(screen.getByTestId('settlement-list')).toBeInTheDocument())
    expect(screen.getByTestId(`settlement-item-${ITEM_B.settlement_id}`)).toBeInTheDocument()

    // 旧患者 A 的列表此时才返回
    slowListA.resolve([ITEM_A])
    await waitFor(() => {
      expect(screen.queryByTestId(`settlement-item-${ITEM_A.settlement_id}`)).toBeNull()
    })
    expect(screen.getByTestId(`settlement-item-${ITEM_B.settlement_id}`)).toBeInTheDocument()
    const lastCandidates = onCandidatesChange.mock.calls.at(-1)?.[0] as Array<{ settlementId: string }>
    expect(lastCandidates.map((item) => item.settlementId)).toEqual([ITEM_B.settlement_id])
  })

  it('A2 同患者旧查询慢响应不得覆盖新查询结果，旧失败也不得展示', async () => {
    const { pending } = deferredFetch()
    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)
    await locateWithDeferred('KEY-A', pending, PATIENT_A)
    await waitFor(() => expect(pending.length).toBe(1))
    const slowToday = pending.shift()!

    // 切到本周：新查询先返回
    fireEvent.click(screen.getByTestId('settlement-preset-this_week'))
    await waitFor(() => expect(pending.length).toBe(1))
    const thisWeek = pending.shift()!
    thisWeek.resolve([ITEM_B])
    await waitFor(() =>
      expect(screen.getByTestId(`settlement-item-${ITEM_B.settlement_id}`)).toBeInTheDocument())

    // 旧的 today 查询后返回（成功或失败均不得影响）
    slowToday.reject(new Error('旧查询失败'))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(screen.getByTestId(`settlement-item-${ITEM_B.settlement_id}`)).toBeInTheDocument()
  })

  it('A3 患者 A→B→A 后，第一次 A 的响应仍必须过期', async () => {
    const { pending } = deferredFetch()
    render(<SettlementTimeBrowser selectedId={null} onSelect={() => {}} />)
    await locateWithDeferred('KEY-A', pending, PATIENT_A)
    await waitFor(() => expect(pending.length).toBe(1))
    const firstA = pending.shift()!

    fireEvent.click(screen.getByRole('button', { name: '换人' }))
    await locateWithDeferred('KEY-B', pending, PATIENT_B)
    await waitFor(() => expect(pending.length).toBe(1))
    pending.shift()!.resolve([ITEM_B])
    await waitFor(() =>
      expect(screen.getByTestId(`settlement-item-${ITEM_B.settlement_id}`)).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '换人' }))
    await locateWithDeferred('KEY-A', pending, PATIENT_A)
    await waitFor(() => expect(pending.length).toBe(1))
    pending.shift()!.resolve([ITEM_A2])
    await waitFor(() =>
      expect(screen.getByTestId(`settlement-item-${ITEM_A2.settlement_id}`)).toBeInTheDocument())

    firstA.resolve([ITEM_A])
    await waitFor(() => {
      expect(screen.queryByTestId(`settlement-item-${ITEM_A.settlement_id}`)).toBeNull()
    })
    expect(screen.getByTestId(`settlement-item-${ITEM_A2.settlement_id}`)).toBeInTheDocument()
  })

  it('A4 查询挂起时卸载：不得再发布候选', async () => {
    const { pending } = deferredFetch()
    const onCandidatesChange = vi.fn()
    const view = render(
      <SettlementTimeBrowser
        selectedId={null}
        onSelect={() => {}}
        onCandidatesChange={onCandidatesChange}
      />,
    )
    await locateWithDeferred('KEY-A', pending, PATIENT_A)
    await waitFor(() => expect(pending.length).toBe(1))
    const slowList = pending.shift()!
    const callsBeforeUnmount = onCandidatesChange.mock.calls.length

    view.unmount()
    slowList.resolve([ITEM_A])
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(onCandidatesChange.mock.calls.length).toBe(callsBeforeUnmount)
  })

  it('A4b 查询挂起时切换预设：旧列表与候选立即清空，不被旧响应恢复', async () => {
    const { pending } = deferredFetch()
    const onCandidatesChange = vi.fn()
    render(
      <SettlementTimeBrowser
        selectedId={null}
        onSelect={() => {}}
        onCandidatesChange={onCandidatesChange}
      />,
    )
    await locateWithDeferred('KEY-A', pending, PATIENT_A)
    await waitFor(() => expect(pending.length).toBe(1))
    const slowList = pending.shift()!

    fireEvent.click(screen.getByTestId('settlement-preset-this_week'))
    // 旧查询结果不得重新发布候选
    slowList.resolve([ITEM_A])
    await waitFor(() => {
      const last = onCandidatesChange.mock.calls.at(-1)?.[0] as Array<unknown>
      expect(last).toEqual([])
    })
    expect(screen.queryByTestId(`settlement-item-${ITEM_A.settlement_id}`)).toBeNull()
  })
})
