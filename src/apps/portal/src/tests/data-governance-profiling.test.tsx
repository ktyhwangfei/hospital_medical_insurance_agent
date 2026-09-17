// 数据探查页（自包含版）：扫描控制条 + 表清单（选表同步）+ 展开字段画像（纳入建模）。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DataProfilingPage from '../../app/data-governance/(manage)/profiling/page'
import {
  listDataSources,
  listSyncTables,
  selectSyncTable,
} from '@/lib/data-governance-api'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  listDataSources: vi.fn(),
  listSyncTables: vi.fn(),
  selectSyncTable: vi.fn(),
  runSyncTables: vi.fn(),
}))

const RESULTS = {
  tables_count: 2,
  fields_count: 3,
  fields: [
    { field_name: 'T_FundPay', table_name: 'o_Trade', data_type: 'numeric', non_null_rate: 99.8, non_null_row_count: 592, is_primary_key: false, mapped: true, sample_value: '113.66', description: '统筹支付' },
    { field_name: 'T_TradeNo', table_name: 'o_Trade', data_type: 'nvarchar', non_null_rate: 100, non_null_row_count: 592, is_primary_key: true, mapped: true, sample_value: '0111...', description: '交易号' },
    { field_name: 'zje', table_name: 'yb_mzjyxx', data_type: 'numeric', non_null_rate: 100, non_null_row_count: 33, is_primary_key: false, mapped: false, sample_value: '356770.97', description: null },
  ],
}

describe('数据探查页（自包含版）', () => {
  beforeEach(() => {
    vi.mocked(listDataSources).mockResolvedValue([
      { sourceId: 'bjybdb', hospitalName: '示例医院', name: '门诊医保库', credentialConfigured: true, connectionStatus: 'healthy' },
    ] as never)
    vi.mocked(listSyncTables).mockResolvedValue([
      { table_name: 'yb_mzjyxx', last_row_count: 33 },
    ] as never)
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.includes('/discovery/history')) {
        return Promise.resolve({ ok: true, json: async () => [{ scan_id: 's1', started_at: '2026-09-16T01:00:00Z', status: 'completed', duration_seconds: 90 }] })
      }
      return Promise.resolve({ ok: true, json: async () => RESULTS })
    }))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks() })

  it('控制条显示统计，探查结果按数据源取数', async () => {
    render(<DataProfilingPage />)
    await waitFor(() => screen.getByTestId('profiling-stats'))
    expect(screen.getByTestId('profiling-stats').textContent).toContain('2 表')
    expect(screen.getByTestId('profiling-stats').textContent).toContain('已选同步 1 张')
    // 请求必须带 datasource_id（按数据源隔离，不被小扫描覆盖）
    const fetchMock = vi.mocked(fetch)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('datasource_id=bjybdb'))).toBe(true)
  })

  it('表清单聚合画像：主键、映射数、同步状态', async () => {
    render(<DataProfilingPage />)
    const tradeRow = await screen.findByTestId('table-o_Trade')
    expect(tradeRow.textContent).toContain('2 字段')
    expect(tradeRow.textContent).toContain('已映射 2')
    expect(tradeRow.textContent).toContain('主键 T_TradeNo')
    expect(screen.getByTestId('table-yb_mzjyxx').textContent).toContain('已同步 33 行')
  })

  it('展开字段画像并提供「纳入建模」治理内跳转', async () => {
    render(<DataProfilingPage />)
    await waitFor(() => screen.getByTestId('table-o_Trade'))
    fireEvent.click(screen.getByText('o_Trade'))
    const fields = await screen.findByTestId('fields-o_Trade')
    expect(fields.textContent).toContain('99.8%')
    expect(fields.textContent).toContain('113.66')
    const link = screen.getAllByRole('link', { name: /纳入建模/ })[0]
    expect(link.getAttribute('href')).toContain('/data-governance/modeling')
    expect(link.getAttribute('href')).toContain('field=')
  })

  it('加入同步调用 API 并更新为待同步状态', async () => {
    vi.mocked(selectSyncTable).mockResolvedValue({} as never)
    render(<DataProfilingPage />)
    await waitFor(() => screen.getByTestId('select-sync-o_Trade'))
    fireEvent.click(screen.getByTestId('select-sync-o_Trade'))
    await waitFor(() => expect(selectSyncTable).toHaveBeenCalledWith('bjybdb', 'o_Trade'))
    await waitFor(() => expect(screen.getByTestId('table-o_Trade').textContent).toContain('待同步'))
  })

  it('筛选：已选同步 / 含未映射字段', async () => {
    render(<DataProfilingPage />)
    await waitFor(() => screen.getByTestId('table-o_Trade'))
    fireEvent.click(screen.getByRole('button', { name: '已选同步' }))
    expect(screen.queryByTestId('table-o_Trade')).toBeNull()
    expect(screen.getByTestId('table-yb_mzjyxx')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '含未映射字段' }))
    expect(screen.getByTestId('table-yb_mzjyxx')).toBeTruthy()
    expect(screen.queryByTestId('table-o_Trade')).toBeNull()
  })
})
