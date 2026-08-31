import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DataSourcesPage from '../../app/data-governance/data-sources/page'
import {
  checkDataSourceCdc,
  createDataSource,
  downloadCdcScript,
  getPostgresTargetStatus,
  listDataSources,
  testDataSourceConnection,
  type DataSource,
} from '@/lib/data-governance-api'

vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  listDataSources: vi.fn(), createDataSource: vi.fn(), getPostgresTargetStatus: vi.fn(),
  testDataSourceConnection: vi.fn(), downloadCdcScript: vi.fn(), checkDataSourceCdc: vi.fn(),
  updateDataSource: vi.fn(), rotateDataSourceCredential: vi.fn(),
}))

const source: DataSource = {
  sourceId: 'bjybdb', hospitalCode: 'H001', hospitalName: '示例医院', name: '门诊医保库',
  host: '10.20.30.40', port: 1433, database: 'bjybdb', schemaName: 'dbo', username: 'readonly',
  credentialId: 'credential.bjybdb', credentialConfigured: true, credentialRevision: 1, connectionStatus: 'healthy',
  cdcStatus: 'waiting_dba', safeProbeMessage: '门诊 3 张源表及 117 个契约字段可读', lastProbedAt: null,
}

beforeEach(() => {
  sessionStorage.clear()
  vi.mocked(listDataSources).mockReset().mockResolvedValue([])
  vi.mocked(createDataSource).mockReset().mockResolvedValue(source)
  vi.mocked(getPostgresTargetStatus).mockReset().mockResolvedValue({
    connectionStatus: 'healthy', schemaReady: true, safeMessage: 'PostgreSQL 门诊结构及读写已就绪', checkedAt: '2026-08-31T00:00:00Z',
  })
  vi.mocked(testDataSourceConnection).mockReset().mockResolvedValue({ status: 'healthy', errorCode: null, safeMessage: '门诊 3 张源表及 117 个契约字段可读', checkedAt: '2026-08-31T00:00:00Z' })
  vi.mocked(downloadCdcScript).mockReset().mockResolvedValue()
  vi.mocked(checkDataSourceCdc).mockReset().mockResolvedValue({ status: 'ready', databaseEnabled: true, readyCaptures: ['dbo_o_Trade'], missingCaptures: [], retentionMinutes: 4320, safeMessage: 'CDC 已按受控模板开通', checkedAt: '2026-08-31T00:00:00Z' })
})

afterEach(cleanup)

describe('数据源配置', () => {
  it('密码只提交一次，保存后不再渲染', async () => {
    const user = userEvent.setup()
    render(<DataSourcesPage />)
    await screen.findByText('暂无数据源')
    await user.click(screen.getByRole('button', { name: '新增数据源' }))
    await user.type(screen.getByLabelText('数据源 ID'), 'bjybdb')
    await user.type(screen.getByLabelText('医院编码'), 'H001')
    await user.type(screen.getByLabelText('医院名称'), '示例医院')
    await user.type(screen.getByLabelText('数据源名称'), '门诊医保库')
    await user.type(screen.getByLabelText('主机'), '10.20.30.40')
    await user.type(screen.getByLabelText('数据库'), 'bjybdb')
    await user.type(screen.getByLabelText('用户名'), 'readonly')
    await user.type(screen.getByLabelText('凭据 ID'), 'credential.bjybdb')
    await user.type(screen.getByLabelText('密码'), 'secret-value')
    await user.click(screen.getByRole('button', { name: '保存数据源' }))

    expect(await screen.findByText('凭据已配置')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('secret-value')).not.toBeInTheDocument()
    expect(JSON.stringify(vi.mocked(createDataSource).mock.calls)).toContain('secret-value')
    expect(screen.getByText('10.20.*.*:1433 / bjybdb')).toBeInTheDocument()
  })

  it('下载脚本后显示等待 DBA，重新检测后显示 CDC 已就绪', async () => {
    vi.mocked(listDataSources).mockResolvedValue([source])
    const user = userEvent.setup()
    render(<DataSourcesPage />)

    await user.click(await screen.findByRole('button', { name: '下载 CDC 脚本' }))
    expect(await screen.findByText('等待 DBA 执行脚本')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重新检测 CDC' }))
    expect(await screen.findByText('CDC 已就绪')).toBeInTheDocument()
    expect(checkDataSourceCdc).toHaveBeenCalledWith('bjybdb')
  })

  it('分别展示门诊源表、PostgreSQL 读写和 CDC 状态', async () => {
    vi.mocked(listDataSources).mockResolvedValue([source])

    render(<DataSourcesPage />)

    expect(await screen.findByText('门诊 3 张源表及 117 个契约字段可读')).toBeInTheDocument()
    expect(screen.getByText('PostgreSQL 门诊结构及读写已就绪')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '门诊源表' })).toBeInTheDocument()
    expect(screen.getByText('等待 DBA')).toBeInTheDocument()
  })

  it('只读用户看得到状态但没有写操作', async () => {
    const payload = btoa(JSON.stringify({ permissions: ['data_governance:read'] }))
    sessionStorage.setItem('data-governance-token', `header.${payload}.signature`)
    vi.mocked(listDataSources).mockResolvedValue([source])

    render(<DataSourcesPage />)

    expect(await screen.findByText('凭据已配置')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '新增数据源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '测试连接' })).not.toBeInTheDocument()
  })
})
