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

  it('点击结算单行触发 onSelect(settlementId)', async () => {
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
    expect(onSelect).toHaveBeenCalledWith('1671213')
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
