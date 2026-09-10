// 健康运营 /ops 页测试 — #45（空态/巡检触发/过滤徽标/错误态）
// + #50（状态筛选与徽标、行点开详情抽屉）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/ops',
}))

vi.mock('@/lib/ops-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/ops-api')>()
  return {
    ...actual,
    hasOpsPermission: vi.fn(() => true),
    listOpsFindings: vi.fn(),
    runOpsInspection: vi.fn(),
    getOpsFinding: vi.fn(),
    listOpsRemediationActions: vi.fn(),
  }
})

import OpsPage from '../../app/ops/page'
import { getOpsFinding, listOpsFindings, listOpsRemediationActions, runOpsInspection } from '@/lib/ops-api'
import type { OpsFindingDetailDto, OpsFindingDto, OpsFindingPageDto } from '@/lib/ops-api'

function finding(overrides: Partial<OpsFindingDto> = {}): OpsFindingDto {
  return {
    finding_id: 'f1',
    asset_type: 'data',
    asset_id: 'bjybdb',
    check_id: 'data_sync_failed',
    severity: 'warning',
    status: 'open',
    fingerprint: 'data:bjybdb:data_sync_failed',
    payload: { problem: 'sync_job_degraded', last_error_code: 'SOURCE_TIMEOUT' },
    first_seen_at: '2026-09-09T04:00:00+00:00',
    last_seen_at: '2026-09-09T04:10:00+00:00',
    occurrence_count: 3,
    diagnosis: null,
    revision: 3,
    ...overrides,
  }
}

function page(items: OpsFindingDto[], total = items.length): OpsFindingPageDto {
  return { items, total, page: 1, page_size: 20 }
}

describe('OpsPage 健康运营页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listOpsFindings).mockResolvedValue(page([]))
  })
  afterEach(() => cleanup())

  it('无问题时展示「全部健康」空态（默认查全部状态）', async () => {
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-empty')).toBeTruthy())
    expect(screen.getByText('全部健康')).toBeTruthy()
    // 默认不带 status 过滤（#50 起列表展示全部状态，徽标区分）
    expect(vi.mocked(listOpsFindings).mock.calls[0]?.[0]?.status).toBeUndefined()
  })

  it('渲染问题列表：severity 徽标、资产、检查项与发生次数', async () => {
    vi.mocked(listOpsFindings).mockResolvedValue(page([
      finding(),
      finding({
        finding_id: 'f2', check_id: 'data_source_down', severity: 'critical',
        payload: { safe_probe_message: '连接超时' }, occurrence_count: 1,
      }),
    ]))
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-table')).toBeTruthy())
    expect(screen.getAllByText('警告').length).toBeGreaterThan(0)
    expect(screen.getAllByText('严重').length).toBeGreaterThan(0)
    expect(screen.getAllByText('bjybdb').length).toBe(2)
    expect(screen.getByText('门诊同步异常')).toBeTruthy()
    expect(screen.getByText('数据源连接失败')).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('连接超时')).toBeTruthy()
    expect(screen.getByTestId('ops-total').textContent).toContain('2 条')
  })

  it('点击「立即巡检」触发 POST 并刷新列表', async () => {
    vi.mocked(runOpsInspection).mockResolvedValue({
      checked_at: '2026-09-09T04:20:00+00:00',
      check_count: 2,
      finding_count: 1,
      findings: [finding()],
      checker_errors: [],
    })
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-empty')).toBeTruthy())
    fireEvent.click(screen.getByTestId('ops-inspect-button'))
    await waitFor(() => expect(runOpsInspection).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByTestId('ops-inspection-note')).toBeTruthy())
    expect(screen.getByTestId('ops-inspection-note').textContent).toContain('本次发现 1 个问题')
    // 巡检后回到第一页重查
    expect(listOpsFindings).toHaveBeenCalledTimes(2)
  })

  it('巡检带检查器错误时提示失败数量', async () => {
    vi.mocked(runOpsInspection).mockResolvedValue({
      checked_at: '2026-09-09T04:20:00+00:00',
      check_count: 2,
      finding_count: 0,
      findings: [],
      checker_errors: [{ check_id: 'data_sync_failed', message: '治理控制面不可用' }],
    })
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-empty')).toBeTruthy())
    fireEvent.click(screen.getByTestId('ops-inspect-button'))
    await waitFor(() =>
      expect(screen.getByTestId('ops-inspection-note').textContent).toContain('1 个检查器执行失败'),
    )
  })

  it('过滤条件变化后按新条件查询并回到第一页', async () => {
    vi.mocked(listOpsFindings).mockResolvedValue(page([finding({ severity: 'critical' })]))
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-table')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('按严重度过滤'), { target: { value: 'critical' } })
    await waitFor(() =>
      expect(listOpsFindings).toHaveBeenLastCalledWith(expect.objectContaining({
        severity: 'critical', page: 1,
      })),
    )
  })

  it('列表加载失败展示错误条', async () => {
    vi.mocked(listOpsFindings).mockRejectedValue(new Error('无法连接健康运营服务'))
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-error')).toBeTruthy())
    expect(screen.getByTestId('ops-error').textContent).toContain('无法连接健康运营服务')
  })

  it('渲染状态徽标并支持状态过滤', async () => {
    vi.mocked(listOpsFindings).mockResolvedValue(page([
      finding(),
      finding({ finding_id: 'f2', status: 'ignored' }),
    ]))
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-table')).toBeTruthy())
    expect(screen.getAllByText('开放').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已忽略').length).toBeGreaterThan(0)

    fireEvent.change(screen.getByLabelText('按状态过滤'), { target: { value: 'ignored' } })
    await waitFor(() =>
      expect(listOpsFindings).toHaveBeenLastCalledWith(expect.objectContaining({
        status: 'ignored', page: 1,
      })),
    )
  })

  it('点击行打开详情抽屉并加载证据', async () => {
    vi.mocked(listOpsFindings).mockResolvedValue(page([finding()]))
    const detailDto: OpsFindingDetailDto = {
      finding: finding(),
      events: [{
        event_id: 'e1',
        finding_id: 'f1',
        event_type: 'ignored',
        actor: 'portal-dev-ops',
        reason: '排期维护',
        created_at: '2026-09-09T04:05:00+00:00',
      }],
      remediations: [],
    }
    vi.mocked(getOpsFinding).mockResolvedValue(detailDto)
    vi.mocked(listOpsRemediationActions).mockResolvedValue([])
    render(<OpsPage />)
    await waitFor(() => expect(screen.getByTestId('ops-finding-row')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-finding-row'))
    await waitFor(() => expect(getOpsFinding).toHaveBeenCalledWith('f1'))
    await waitFor(() => expect(screen.getByTestId('ops-detail-drawer')).toBeTruthy())
    expect(screen.getByText('证据快照')).toBeTruthy()
    expect(screen.getByText(/由 portal-dev-ops 忽略/)).toBeTruthy()
  })
})
