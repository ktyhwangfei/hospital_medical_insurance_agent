// 数据探查页（自包含版）：扫描控制条 + 表清单（选表同步）+ 展开字段画像（纳入建模）。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DataProfilingPage from '../../app/data-governance/(manage)/profiling/page'
import {
  listDataSources,
  listSyncTables,
  selectSyncTable,
  getTimeCandidates,
} from '@/lib/data-governance-api'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  listDataSources: vi.fn(),
  listSyncTables: vi.fn(),
  selectSyncTable: vi.fn(),
  getTimeCandidates: vi.fn(),
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

  it('已映射字段不显示纳入建模，未映射字段提供治理内跳转', async () => {
    render(<DataProfilingPage />)
    await waitFor(() => screen.getByTestId('table-o_Trade'))
    fireEvent.click(screen.getByText('o_Trade'))
    const tradeFields = await screen.findByTestId('fields-o_Trade')
    // o_Trade 两个字段均已映射：不显示纳入建模入口
    expect(tradeFields.textContent).toContain('已在模型中')
    expect(tradeFields.querySelector('a')).toBeNull()
    // yb_mzjyxx.zje 未映射：显示纳入建模链接
    fireEvent.click(screen.getByText('yb_mzjyxx'))
    await screen.findByTestId('fields-yb_mzjyxx')
    const link = screen.getByRole('link', { name: /纳入建模/ })
    expect(link.getAttribute('href')).toContain('/data-governance/modeling')
    expect(link.getAttribute('href')).toContain('field=zje')
  })

  it('加入同步：弹窗配置时间字段后确认才调 API', async () => {
    vi.mocked(selectSyncTable).mockResolvedValue({} as never)
    vi.mocked(getTimeCandidates).mockResolvedValue(['T_TradeDate', 'SETL_DATE'] as never)
    render(<DataProfilingPage />)
    await waitFor(() => screen.getByTestId('select-sync-o_Trade'))
    fireEvent.click(screen.getByTestId('select-sync-o_Trade'))
    // 弹窗出现且未调 API
    const dialog = await screen.findByTestId('select-sync-dialog')
    expect(dialog.textContent).toContain('加入同步：o_Trade')
    expect(selectSyncTable).not.toHaveBeenCalled()
    // 选择增量时间字段后确认
    fireEvent.change(dialog.querySelector('select')!, { target: { value: 'T_TradeDate' } })
    fireEvent.click(screen.getByRole('button', { name: /确认加入/ }))
    await waitFor(() => expect(selectSyncTable).toHaveBeenCalledWith('bjybdb', 'o_Trade', {
      time_column: 'T_TradeDate', sync_mode: 'incremental', lookback_minutes: 5,
    }))
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
