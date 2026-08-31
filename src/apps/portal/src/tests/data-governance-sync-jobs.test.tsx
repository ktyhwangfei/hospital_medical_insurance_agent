import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SyncJobsPage from '../../app/data-governance/sync-jobs/page'
import {
  getSyncJob, listDataSources, listSyncRuns, runSyncJobOnce, saveSyncJob, startSyncJob,
  type DataSource, type SyncJob,
} from '@/lib/data-governance-api'

vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  listDataSources: vi.fn(), getSyncJob: vi.fn(), listSyncRuns: vi.fn(), saveSyncJob: vi.fn(),
  startSyncJob: vi.fn(), pauseSyncJob: vi.fn(), runSyncJobOnce: vi.fn(),
}))

const source: DataSource = {
  sourceId: 'bjybdb', hospitalCode: 'H001', hospitalName: '示例医院', name: '门诊医保库',
  host: 'db.example', port: 1433, database: 'bjybdb', schemaName: 'dbo', username: 'readonly',
  credentialId: 'credential.bjybdb', credentialConfigured: true, credentialRevision: 1, connectionStatus: 'healthy',
  cdcStatus: 'ready', safeProbeMessage: null, lastProbedAt: null,
}
const job: SyncJob = {
  sourceId: 'bjybdb', sourceMode: 'scheduled_sql', status: 'paused', cdcPollIntervalSeconds: 45,
  scheduleIntervalMinutes: 5, lookbackHours: 2, reconcileTime: '02:00:00', reconcileDays: 30, revision: 1,
  baselineRequired: true, nextRunAt: null, runOnceRequestedAt: null, lastStartedAt: null,
  lastSucceededAt: null, lastErrorCode: null,
}

beforeEach(() => {
  vi.mocked(listDataSources).mockReset().mockResolvedValue([source])
  vi.mocked(getSyncJob).mockReset().mockResolvedValue(null)
  vi.mocked(listSyncRuns).mockReset().mockResolvedValue([])
  vi.mocked(saveSyncJob).mockReset().mockResolvedValue(job)
  vi.mocked(startSyncJob).mockReset().mockResolvedValue({ ...job, status: 'ready' })
  vi.mocked(runSyncJobOnce).mockReset().mockResolvedValue({ ...job, status: 'running' })
})

afterEach(cleanup)

describe('同步任务配置', () => {
  it('定时 SQL 只提供受控参数并说明最终一致性', async () => {
    const user = userEvent.setup()
    render(<SyncJobsPage />)
    const mode = await screen.findByLabelText('同步方式')
    await user.selectOptions(mode, 'scheduled_sql')

    expect(screen.getByLabelText('执行周期（分钟）')).toHaveValue(5)
    expect(screen.getByLabelText('回看窗口（小时）')).toHaveValue(2)
    expect(screen.getByText(/最终一致/)).toBeInTheDocument()
    expect(screen.queryByLabelText('SQL')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '保存配置' }))
    await waitFor(() => expect(saveSyncJob).toHaveBeenCalledWith('bjybdb', expect.objectContaining({
      sourceMode: 'scheduled_sql', scheduleIntervalMinutes: 5, lookbackHours: 2,
    })))
  })

  it('CDC 未就绪时禁止启动，立即执行只显示已请求', async () => {
    vi.mocked(listDataSources).mockResolvedValue([{ ...source, cdcStatus: 'waiting_dba' }])
    vi.mocked(getSyncJob).mockResolvedValue({ ...job, sourceMode: 'cdc', status: 'paused' })
    render(<SyncJobsPage />)

    expect(await screen.findByRole('button', { name: '启动任务' })).toBeDisabled()
    expect(screen.getByText(/CDC 尚未就绪/)).toBeInTheDocument()
  })

  it('立即执行进入队列，不伪造同步成功', async () => {
    vi.mocked(getSyncJob).mockResolvedValue({ ...job, status: 'running' })
    const user = userEvent.setup()
    render(<SyncJobsPage />)
    await user.click(await screen.findByRole('button', { name: '立即执行' }))

    expect(await screen.findByText('已请求，worker 将按队列执行')).toBeInTheDocument()
    expect(screen.queryByText('同步成功')).not.toBeInTheDocument()
  })
})
