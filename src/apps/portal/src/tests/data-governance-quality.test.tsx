// 质量与发布页：同步质量门 + Flow 发布证据（活跃版本/产物哈希/发布人）。
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DataQualityPage from '../../app/data-governance/(manage)/quality/page'
import { getDataGovernanceOverview } from '@/lib/data-governance-api'
import { listFlowRevisions, listFlows } from '@/lib/flow-api'

vi.mock('@/lib/data-governance-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/data-governance-api')>()),
  getDataGovernanceOverview: vi.fn(),
}))
vi.mock('@/lib/flow-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/flow-api')>()),
  listFlows: vi.fn(),
  listFlowRevisions: vi.fn(),
}))

const overview = {
  platformReady: true,
  postgresql: { connectionStatus: 'healthy', schemaReady: true, safeMessage: 'ok', checkedAt: 'x' },
  dataSourceCount: 1,
  runningJobCount: 1,
  issueCount: 0,
  latestLatencySeconds: 30,
  sources: [{
    sourceId: 'bjybdb', hospitalCode: 'H001', hospitalName: '示例医院', name: '门诊医保库',
    credentialConfigured: true, connectionStatus: 'healthy', cdcStatus: 'ready',
    syncStatus: 'running', sourceMode: 'scheduled_sql', nextRunAt: null,
    lastSucceededAt: '2026-09-15T01:00:00Z', qualityStatus: 'accepted', latestLatencySeconds: 30,
  }],
  issues: [],
  recentRuns: [],
}

describe('质量与发布页', () => {
  beforeEach(() => {
    vi.mocked(getDataGovernanceOverview).mockResolvedValue(overview as never)
    vi.mocked(listFlows).mockResolvedValue([
      { flow_id: 'flow_op', name: '门诊加工', status: 'published' },
      { flow_id: 'flow_draft', name: '草稿流', status: 'draft' },
    ] as never)
    vi.mocked(listFlowRevisions).mockResolvedValue([{
      revision: {
        revision_id: 'flow_op-rev3', flow_id: 'flow_op', flow_revision: 3,
        content_hash: 'c', semantic_revision: 's',
        artifact_hash: 'abc123def4567890', published_at: '2026-09-14T08:00:00Z', published_by: '苏杭',
        definition: {},
      },
      is_active: true,
    }] as never)
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('同步质量门展示数据源批次状态', async () => {
    render(<DataQualityPage />)
    const section = await screen.findByTestId('sync-quality')
    expect(section.textContent).toContain('示例医院')
    expect(section.textContent).toContain('通过')
    expect(section.textContent).toContain('30 秒')
  })

  it('Flow 发布证据只列已发布，含活跃版本与产物哈希', async () => {
    render(<DataQualityPage />)
    const section = await screen.findByTestId('flow-releases')
    await waitFor(() => expect(section.textContent).toContain('flow_op-rev3'))
    expect(section.textContent).toContain('abc123def456')
    expect(section.textContent).toContain('苏杭')
    expect(section.textContent).not.toContain('草稿流')
    expect(listFlowRevisions).toHaveBeenCalledTimes(1)
    expect(listFlowRevisions).toHaveBeenCalledWith('flow_op')
  })
})
