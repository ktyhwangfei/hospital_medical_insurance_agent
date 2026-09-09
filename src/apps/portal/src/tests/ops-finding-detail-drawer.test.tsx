// 问题详情抽屉测试 — issue #50（证据快照 / 忽略与重开流转 / 时间线 / 冲突错误）。
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
    getOpsFinding: vi.fn(),
    ignoreOpsFinding: vi.fn(),
    reopenOpsFinding: vi.fn(),
  }
})

import FindingDetailDrawer from '../../app/ops/finding-detail-drawer'
import {
  getOpsFinding,
  ignoreOpsFinding,
  reopenOpsFinding,
  type OpsFindingDetailDto,
  type OpsFindingDto,
  type OpsFindingEventDto,
} from '@/lib/ops-api'
import { ApiClientError } from '@/lib/types'

function finding(overrides: Partial<OpsFindingDto> = {}): OpsFindingDto {
  return {
    finding_id: 'f1',
    asset_type: 'data',
    asset_id: 'bjybdb',
    check_id: 'data_sync_failed',
    severity: 'warning',
    status: 'open',
    fingerprint: 'data:bjybdb:data_sync_failed',
    payload: {
      problem: 'sync_job_degraded',
      last_error_code: 'SOURCE_TIMEOUT',
      safe_probe_message: '连接超时',
      last_probed_at: '2026-09-09T04:10:00+00:00',
    },
    first_seen_at: '2026-09-09T04:00:00+00:00',
    last_seen_at: '2026-09-09T04:10:00+00:00',
    occurrence_count: 3,
    diagnosis: null,
    revision: 3,
    ...overrides,
  }
}

function event(overrides: Partial<OpsFindingEventDto> = {}): OpsFindingEventDto {
  return {
    event_id: 'e1',
    finding_id: 'f1',
    event_type: 'ignored',
    actor: 'portal-dev-ops',
    reason: 'DBA 排期维护',
    created_at: '2026-09-09T04:05:00+00:00',
    ...overrides,
  }
}

function detail(overrides: Partial<OpsFindingDetailDto> = {}): OpsFindingDetailDto {
  return { finding: finding(), events: [], ...overrides }
}

function renderDrawer(findingId: string | null = 'f1', canWrite = true) {
  const onClose = vi.fn()
  const onMutated = vi.fn()
  render(
    <FindingDetailDrawer findingId={findingId} canWrite={canWrite} onClose={onClose} onMutated={onMutated} />,
  )
  return { onClose, onMutated }
}

describe('FindingDetailDrawer 详情抽屉', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getOpsFinding).mockResolvedValue(detail())
  })
  afterEach(() => cleanup())

  it('渲染证据快照、诊断占位与基础时间线', async () => {
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-drawer')).toBeTruthy())
    // 证据快照：已知键显示中文标签，问题码带翻译
    expect(screen.getByText('问题码')).toBeTruthy()
    expect(screen.getByText('同步任务降级（sync_job_degraded）')).toBeTruthy()
    expect(screen.getByText('错误码')).toBeTruthy()
    expect(screen.getByText('SOURCE_TIMEOUT')).toBeTruthy()
    expect(screen.getByText('连接探测')).toBeTruthy()
    // 诊断占位
    expect(screen.getByTestId('ops-detail-diagnosis').textContent).toContain('诊断报告未生成')
    // 时间线：首见 + 最近巡检确认（无流转事件）；「首次发现」在基础信息区也出现，用 getAll
    expect(screen.getAllByText('首次发现').length).toBeGreaterThan(0)
    expect(screen.getByText('最近巡检确认')).toBeTruthy()
    expect(screen.getByText('3 次')).toBeTruthy()
  })

  it('忽略流程：必填原因校验、提交带乐观锁版本、成功后回填详情并通知列表', async () => {
    const ignoredDetail = detail({
      finding: finding({ status: 'ignored', revision: 4 }),
      events: [event()],
    })
    vi.mocked(ignoreOpsFinding).mockResolvedValue(ignoredDetail)
    const { onMutated } = renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-ignore'))
    expect(screen.getByTestId('ops-detail-ignore-form')).toBeTruthy()
    // 空原因禁用确认
    expect(screen.getByTestId('ops-detail-ignore-confirm')).toHaveProperty('disabled', true)

    fireEvent.change(screen.getByTestId('ops-detail-ignore-reason'), {
      target: { value: 'DBA 排期维护' },
    })
    fireEvent.click(screen.getByTestId('ops-detail-ignore-confirm'))
    await waitFor(() =>
      expect(ignoreOpsFinding).toHaveBeenCalledWith('f1', 3, 'DBA 排期维护'),
    )
    // 详情以响应回填：状态徽标已忽略、重开按钮出现、时间线含忽略事件与原因
    await waitFor(() => expect(screen.getByTestId('ops-detail-reopen')).toBeTruthy())
    expect(screen.getByText('已忽略')).toBeTruthy()
    expect(screen.getByText(/由 portal-dev-ops 忽略/)).toBeTruthy()
    expect(screen.getByText(/原因：DBA 排期维护/)).toBeTruthy()
    expect(onMutated).toHaveBeenCalledTimes(1)
  })

  it('重开流程：对已忽略问题重开成功后回到开放状态', async () => {
    vi.mocked(getOpsFinding).mockResolvedValue(
      detail({ finding: finding({ status: 'ignored', revision: 4 }), events: [event()] }),
    )
    vi.mocked(reopenOpsFinding).mockResolvedValue(detail({ finding: finding({ revision: 5 }) }))
    const { onMutated } = renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-reopen')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-reopen'))
    await waitFor(() => expect(reopenOpsFinding).toHaveBeenCalledWith('f1', 4))
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())
    expect(screen.getByText('开放')).toBeTruthy()
    expect(onMutated).toHaveBeenCalledTimes(1)
  })

  it('版本冲突（409）时展示错误条且状态不变', async () => {
    vi.mocked(ignoreOpsFinding).mockRejectedValue(new ApiClientError(409, {
      error_code: 'FINDING_REVISION_CONFLICT',
      message: '问题 f1 版本冲突：期望 revision 3，实际 4',
    }))
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-ignore')).toBeTruthy())

    fireEvent.click(screen.getByTestId('ops-detail-ignore'))
    fireEvent.change(screen.getByTestId('ops-detail-ignore-reason'), {
      target: { value: '尝试忽略' },
    })
    fireEvent.click(screen.getByTestId('ops-detail-ignore-confirm'))
    await waitFor(() => expect(screen.getByTestId('ops-detail-action-error')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-action-error').textContent).toContain('FINDING_REVISION_CONFLICT')
    // 仍处于开放态，可再次展开忽略表单
    expect(screen.getByText('开放')).toBeTruthy()
  })

  it('详情加载失败展示错误信息', async () => {
    vi.mocked(getOpsFinding).mockRejectedValue(new Error('无法连接健康运营服务'))
    renderDrawer()
    await waitFor(() => expect(screen.getByTestId('ops-detail-error')).toBeTruthy())
    expect(screen.getByTestId('ops-detail-error').textContent).toContain('无法连接健康运营服务')
  })

  it('findingId 为空时不渲染抽屉', () => {
    renderDrawer(null)
    expect(screen.queryByTestId('ops-detail-overlay')).toBeNull()
  })

  it('无写权限时不渲染状态操作', async () => {
    renderDrawer('f1', false)
    await waitFor(() => expect(screen.getByTestId('ops-detail-drawer')).toBeTruthy())
    expect(screen.queryByTestId('ops-detail-ignore')).toBeNull()
  })
})
