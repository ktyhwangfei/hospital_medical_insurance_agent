import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SourceMappingModal } from '@/components/data-governance-source-tools'
import {
  exploreSourceTable,
  exploreSourceTables,
  getMappingSqlPreview,
  getSourceMapping,
  saveSourceMapping,
  type CaptureMapping,
  type SourceMapping,
} from '@/lib/data-governance-api'

vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  exploreSourceTables: vi.fn(),
  exploreSourceTable: vi.fn(),
  getSourceMapping: vi.fn(),
  saveSourceMapping: vi.fn(),
  getMappingSqlPreview: vi.fn(),
}))

const capture = (name: string, table: string, map: Record<string, string>): CaptureMapping => ({
  capture: name, table_schema: 'dbo', table_name: table,
  key_fields: Object.keys(map).slice(0, 1), column_map: map,
})

const mapping: SourceMapping = {
  source_id: 'bjybdb', revision: 1,
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  captures: {
    dbo_o_Trade: capture('dbo_o_Trade', 'o_Trade', { T_TradeNo: 'T_TradeNo', T_TradeDate: 'T_TradeDate', T_State: 'T_State' }),
    dbo_o_FeeItem: capture('dbo_o_FeeItem', 'o_FeeItem', { T_TradeNo: 'T_TradeNo', ItemId: 'ItemId' }),
    dbo_o_Diagnose: capture('dbo_o_Diagnose', 'o_Diagnose', { T_TradeNo: 'T_TradeNo', DiagnoseNo: 'DiagnoseNo' }),
  },
}

beforeEach(() => {
  vi.mocked(exploreSourceTables).mockReset().mockResolvedValue([
    { table_schema: 'dbo', table_name: 'o_Trade', row_count: 592 },
    { table_schema: 'his', table_name: 'MZ_JYLS', row_count: 1000 },
  ])
  vi.mocked(exploreSourceTable).mockReset().mockImplementation(async (_id, _schema, table) => {
    if (table === 'MZ_JYLS') return [
      { name: 'JYLSH', data_type: 'varchar', is_nullable: false, max_length: 32, is_primary_key: true },
      { name: 'JY_RQ', data_type: 'datetime', is_nullable: false, max_length: null, is_primary_key: false },
      { name: 'ZT', data_type: 'int', is_nullable: true, max_length: null, is_primary_key: false },
    ]
    return [
      { name: 'T_TradeNo', data_type: 'varchar', is_nullable: false, max_length: 32, is_primary_key: true },
      { name: 'T_TradeDate', data_type: 'datetime', is_nullable: false, max_length: null, is_primary_key: false },
    ]
  })
  vi.mocked(getSourceMapping).mockReset().mockResolvedValue(mapping)
  vi.mocked(saveSourceMapping).mockReset().mockResolvedValue(mapping)
  vi.mocked(getMappingSqlPreview).mockReset().mockResolvedValue({
    is_default: false, mapping_revision: 1,
    baseline_sql: ['SELECT [JYLSH] AS [T_TradeNo] FROM [his].[MZ_JYLS]'],
    incremental_window_sql: 'SELECT [JY_RQ] AS [T_TradeDate] FROM [his].[MZ_JYLS] WHERE [JY_RQ] >= ? AND [JY_RQ] < ?',
    incremental_children_sql: ['SELECT 1 FROM [his].[MZ_SFMX] WHERE [JYLSH] IN (?, ?, ?)'],
  })
})

afterEach(cleanup)

describe('字段映射弹窗', () => {
  it('加载默认映射并按表选择自动同名匹配', async () => {
    const user = userEvent.setup()
    render(<SourceMappingModal sourceId="bjybdb" onClose={() => {}} onSaved={() => {}} />)

    await screen.findByRole('button', { name: '保存映射' })
    // 默认契约表已选中
    expect(await screen.findByDisplayValue(/T_TradeNo · varchar/)).toBeTruthy()

    // 切换到 his.MZ_JYLS → 自动同名匹配（无同名契约字段，仅保留空映射列表）
    const tableSelect = screen.getAllByRole('combobox')[0]
    await user.selectOptions(tableSelect, 'his.MZ_JYLS')
    await waitFor(() => {
      expect(exploreSourceTable).toHaveBeenCalledWith('bjybdb', 'his', 'MZ_JYLS')
    })
  })

  it('SQL 预览展示实际执行 SQL', async () => {
    const user = userEvent.setup()
    render(<SourceMappingModal sourceId="bjybdb" onClose={() => {}} onSaved={() => {}} />)
    await screen.findByRole('button', { name: '保存映射' })

    await user.click(screen.getByRole('button', { name: 'SQL 预览' }))

    expect(await screen.findByText(/SELECT \[JYLSH\] AS \[T_TradeNo\]/)).toBeTruthy()
    expect(screen.getByText(/WHERE \[JY_RQ\] >= \? AND \[JY_RQ\] < \?/)).toBeTruthy()
  })

  it('保存提交完整三 capture 映射', async () => {
    const user = userEvent.setup()
    render(<SourceMappingModal sourceId="bjybdb" onClose={() => {}} onSaved={() => {}} />)
    await screen.findByRole('button', { name: '保存映射' })

    await user.click(screen.getByRole('button', { name: '保存映射' }))

    await waitFor(() => {
      expect(saveSourceMapping).toHaveBeenCalledWith('bjybdb', expect.anything(), 1)
      const captures = vi.mocked(saveSourceMapping).mock.calls[0][1]
      expect(captures).toHaveLength(3)
      expect(captures.map((item) => item.capture)).toEqual(
        expect.arrayContaining(['dbo_o_Trade', 'dbo_o_FeeItem', 'dbo_o_Diagnose']),
      )
    })
  })
})
