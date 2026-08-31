import type { ReactNode } from 'react'
import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DataGovernanceLayout from '../../app/data-governance/layout'
import DataGovernanceOverviewPage from '../../app/data-governance/page'
import { LayoutShell } from '../../app/layout'
import { getDataGovernanceOverview, type DataGovernanceOverview } from '@/lib/data-governance-api'

vi.mock('next/navigation', () => ({ usePathname: () => '/data-governance' }))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}))
vi.mock('@/lib/api-context', () => ({
  ApiProvider: ({ children }: { children: ReactNode }) => children,
  useApiContext: () => ({ connectionStatus: 'connected' }),
}))
vi.mock('@/components/role-switcher', () => ({ default: () => <button type="button">角色切换</button> }))
vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  getDataGovernanceOverview: vi.fn(),
}))

const overview: DataGovernanceOverview = {
  platformReady: true,
  postgresql: {
    connectionStatus: 'healthy', schemaReady: true,
    safeMessage: 'PostgreSQL 门诊结构及读写已就绪', checkedAt: '2026-08-31T00:00:00Z',
  },
  dataSourceCount: 1,
  runningJobCount: 1,
  issueCount: 0,
  latestLatencySeconds: 42,
  sources: [{
    sourceId: 'bjybdb', hospitalCode: 'H001', hospitalName: '示例医院门诊', name: '门诊医保库',
    credentialConfigured: true, connectionStatus: 'healthy', cdcStatus: 'waiting_dba',
    syncStatus: 'running', sourceMode: 'scheduled_sql', nextRunAt: '2026-08-31T08:00:00Z',
    lastSucceededAt: '2026-08-31T07:59:00Z', qualityStatus: 'accepted', latestLatencySeconds: 42,
  }],
  issues: [],
  recentRuns: [{
    attemptId: 'attempt-1', sourceId: 'bjybdb', sourceMode: 'cdc', runKind: 'incremental',
    status: 'succeeded', startedAt: '2026-08-31T07:59:00Z', finishedAt: '2026-08-31T07:59:02Z',
    safeErrorCode: null, safeMessage: null, rowCount: 16, batchId: 'batch-1',
  }],
}

beforeEach(() => {
  vi.mocked(getDataGovernanceOverview).mockReset().mockResolvedValue(overview)
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }),
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('数据治理运行概览', () => {
  it('展示真实同步状态、最近运行和三个页签', async () => {
    render(<DataGovernanceLayout><DataGovernanceOverviewPage /></DataGovernanceLayout>)

    expect(await screen.findByText('示例医院门诊')).toBeInTheDocument()
    expect(screen.getByText('数据底座')).toBeInTheDocument()
    expect(screen.getByText('可用')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL 门诊结构及读写已就绪')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '门诊源表' })).toBeInTheDocument()
    expect(screen.getByText('等待 DBA')).toBeInTheDocument()
    expect(screen.getAllByText('42 秒').length).toBeGreaterThan(0)
    expect(screen.getByText('batch-1')).toBeInTheDocument()
    expect(screen.queryByText('暂无数据源，请先新增')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link').map((link) => link.textContent)).toEqual([
      '运行概览', '数据源', '同步任务',
    ])
  })

  it('无数据源时显示明确入口，不伪造医院记录', async () => {
    vi.mocked(getDataGovernanceOverview).mockResolvedValue({
      ...overview, platformReady: false, dataSourceCount: 0, runningJobCount: 0, latestLatencySeconds: null,
      sources: [], recentRuns: [],
    })
    render(<DataGovernanceOverviewPage />)

    expect(await screen.findByText('暂无数据源，请先新增')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '新增数据源' })).toHaveAttribute(
      'href', '/data-governance/data-sources?create=1',
    )
    expect(screen.queryByText('示例医院门诊')).not.toBeInTheDocument()
  })

  it('错误时只显示安全提示并允许重试', async () => {
    vi.mocked(getDataGovernanceOverview)
      .mockRejectedValueOnce(new Error('数据治理服务暂不可用'))
      .mockResolvedValueOnce(overview)
    const user = userEvent.setup()
    render(<DataGovernanceOverviewPage />)

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('数据治理服务暂不可用')).toBeInTheDocument()
    await user.click(within(alert).getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('示例医院门诊')).toBeInTheDocument()
  })

  it('每 15 秒刷新且卸载后停止轮询', async () => {
    vi.useFakeTimers()
    const { unmount } = render(<DataGovernanceOverviewPage />)
    await act(async () => { await Promise.resolve() })
    expect(getDataGovernanceOverview).toHaveBeenCalledTimes(1)

    await act(async () => { vi.advanceTimersByTime(15_000); await Promise.resolve() })
    expect(getDataGovernanceOverview).toHaveBeenCalledTimes(2)
    unmount()
    await act(async () => { vi.advanceTimersByTime(30_000) })
    expect(getDataGovernanceOverview).toHaveBeenCalledTimes(2)
  })

  it('顶级侧栏提供数据治理入口', () => {
    render(<LayoutShell><h1>测试页</h1></LayoutShell>)
    expect(screen.getByRole('link', { name: '数据治理' })).toHaveAttribute('href', '/data-governance')
  })
})
