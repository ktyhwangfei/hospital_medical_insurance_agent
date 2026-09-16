// 数据治理总览：语义标准横条 + 数据资产生命周期流程条。
// 各阶段状态聚合自既有只读接口；单接口失败独立降级为「—」。
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DataGovernancePipeline } from '../components/data-governance-pipeline'
import { getDataGovernanceOverview, listSyncTables } from '@/lib/data-governance-api'
import { listDataModels } from '@/lib/data-model-api'
import { getSemanticSummary } from '@/lib/policy-knowledge-api'
import { listFlows } from '@/lib/flow-api'

vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  getDataGovernanceOverview: vi.fn(),
  listSyncTables: vi.fn(),
}))
vi.mock('@/lib/data-model-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-model-api')>()),
  listDataModels: vi.fn(),
}))
vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  getSemanticSummary: vi.fn(),
}))
vi.mock('@/lib/flow-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/flow-api')>()),
  listFlows: vi.fn(),
}))

const overview = {
  platformReady: true,
  postgresql: { connectionStatus: 'healthy', schemaReady: true, safeMessage: 'ok', checkedAt: 'x' },
  dataSourceCount: 2,
  runningJobCount: 1,
  issueCount: 0,
  latestLatencySeconds: 12,
  sources: [{ sourceId: 'bjybdb' }],
  issues: [],
  recentRuns: [],
}

describe('DataGovernancePipeline', () => {
  beforeEach(() => {
    vi.mocked(getDataGovernanceOverview).mockResolvedValue(overview as never)
    vi.mocked(getSemanticSummary).mockResolvedValue({
      metrics_count: 166, mapped_count: 40, unmapped_count: 10, mapping_rate: 0.8,
      objects_count: 11, domains_count: 5,
    })
    vi.mocked(listFlows).mockResolvedValue([
      { status: 'published' }, { status: 'draft' }, { status: 'deprecated' },
    ] as never)
    vi.mocked(listDataModels).mockResolvedValue([{ model_code: 'dwd_mz_settlement' }] as never)
    vi.mocked(listSyncTables).mockResolvedValue([
      { table_name: 'yb_mzjyxx', last_row_count: 33 },
    ] as never)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        total_tables: 12, total_fields: 156, mapped_fields: 47, unmapped_fields: 109,
      }),
    }))
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('语义标准横条是横向纽带，链接语义层并聚合对象/指标/映射数', async () => {
    render(<DataGovernancePipeline />)
    const bar = screen.getByTestId('semantic-standard-bar')
    expect(bar.getAttribute('href')).toBe('/semantic-layer')
    await waitFor(() => expect(bar.textContent).toContain('业务对象 11'))
    expect(bar.textContent).toContain('指标 166')
    expect(bar.textContent).toContain('已确认 47 / 待确认 109')
  })

  it('生命周期六阶段一一链接到数据治理中心一级模块', async () => {
    render(<DataGovernancePipeline />)
    await waitFor(() => expect(screen.getByTestId('pipeline-stage-ingestion')).toBeTruthy())
    expect(screen.getByTestId('pipeline-stage-ingestion').getAttribute('href')).toBe('/data-governance/data-sources')
    expect(screen.getByTestId('pipeline-stage-profiling').getAttribute('href')).toBe('/data-governance/profiling')
    expect(screen.getByTestId('pipeline-stage-sync').getAttribute('href')).toBe('/data-governance/sync-jobs')
    expect(screen.getByTestId('pipeline-stage-modeling').getAttribute('href')).toBe('/data-governance/modeling')
    expect(screen.getByTestId('pipeline-stage-transformation').getAttribute('href')).toBe('/data-governance/flows')
    expect(screen.getByTestId('pipeline-stage-quality').getAttribute('href')).toBe('/data-governance/quality')
    expect(screen.getByTestId('pipeline-stage-asset').getAttribute('href')).toBe('/data-governance/assets')
  })

  it('聚合生命周期各阶段状态数值', async () => {
    render(<DataGovernancePipeline />)
    await waitFor(() => expect(screen.getByText('数据源 2 个')).toBeTruthy())
    expect(screen.getByText('表画像 12 / 字段 156')).toBeTruthy()
    expect(screen.getByText('数据模型 1 个')).toBeTruthy()
    expect(screen.getByText('选表 1 张 / 33 行')).toBeTruthy()
    expect(screen.getByText('治理 Flow 3 个')).toBeTruthy()
    expect(screen.getByText('已发布 1 个')).toBeTruthy()
  })

  it('单接口失败时该阶段降级为 —，其余阶段不受影响', async () => {
    vi.mocked(listFlows).mockRejectedValue(new Error('flow api down'))
    render(<DataGovernancePipeline />)
    await waitFor(() => expect(screen.getByText('治理 Flow — 个')).toBeTruthy())
    expect(screen.getByText('数据源 2 个')).toBeTruthy()
  })
})
