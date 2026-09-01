import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import GovernanceOverviewPage from '../../../app/policy-knowledge/page'
import {
  getActiveRelease,
  getGovernanceDashboard,
  getPipelineSummary,
  getPolicyKnowledgeStats,
  getSemanticSummary,
  listKnowledgeBuildTasks,
  PolicyKnowledgeApiError,
  type GovernanceDashboard,
  type KnowledgeBuildTask,
  type KnowledgeRelease,
  type PipelineSummary,
  type SemanticSummary,
} from '@/lib/policy-knowledge-api'

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/policy-knowledge-api')>()),
  getActiveRelease: vi.fn(),
  getGovernanceDashboard: vi.fn(),
  getPipelineSummary: vi.fn(),
  getPolicyKnowledgeStats: vi.fn(),
  getSemanticSummary: vi.fn(),
  listKnowledgeBuildTasks: vi.fn(),
}))

const mocked = {
  getActiveRelease: vi.mocked(getActiveRelease),
  getGovernanceDashboard: vi.mocked(getGovernanceDashboard),
  getPipelineSummary: vi.mocked(getPipelineSummary),
  getPolicyKnowledgeStats: vi.mocked(getPolicyKnowledgeStats),
  getSemanticSummary: vi.mocked(getSemanticSummary),
  listKnowledgeBuildTasks: vi.mocked(listKnowledgeBuildTasks),
}

const summaryFixture: PipelineSummary = {
  documents_count: 5,
  documents_raw: 1,
  units_count: 20,
  units_audited: 13,
  units_pending: 6,
  extractions_count: 20,
  extractions_draft: 6,
  extractions_reviewed: 4,
  extractions_published: 9,
}

const dashboardFixture: GovernanceDashboard = {
  documents_total: 5,
  change_sets_total: 4,
  knowledge_total: 30,
  rules_total: 30,
  rules_pending_review: 6,
  rules_approved: 20,
  compilation_by_status: { PASS: 20, REVIEW: 6, FAIL: 0 },
  tasks_pending: 2,
  tasks_by_type: { VALUE_UNMAPPED: 1, LOW_CONFIDENCE: 1 },
  change_sets_by_status: { PENDING_REVIEW: 2, NEEDS_DECISION: 1, APPROVED: 1 },
  risk_summary: { LOW: 3, MEDIUM: 1, HIGH: 0, CRITICAL: 0 },
  avg_source_fidelity: 0.86,
  avg_completeness: 0.72,
}

const semanticFixture: SemanticSummary = {
  metrics_count: 12,
  mapped_count: 8,
  unmapped_count: 3,
  mapping_rate: 66.7,
}

const releaseFixture: KnowledgeRelease = {
  release_id: 'REL_2026_003',
  status: 'active',
  facts_collection: 'policy_facts',
  rules_collection: 'policy_rules_v2',
  contract_version: 'v2.1',
  case_set_version: 1,
  config_hash: 'abc',
  quality_score: 1,
  consistency_score: 0.99,
}

function makeTask(taskId: string, status: KnowledgeBuildTask['status']): KnowledgeBuildTask {
  return {
    task_id: taskId,
    name: taskId,
    status,
    build_mode: 'INITIAL',
    semantic_contract_version: 'v2.1',
    pipeline_version: 'p1',
    model_scene: 'm1',
    config_hash: 'h',
    rebuild_reason: null,
    created_by: 'tester',
    units: [],
    processed_units: 0,
    result_change_set_id: null,
    result_summary: {},
    issue_count: 0,
    created_at: '2026-08-06T00:00:00Z',
    updated_at: '2026-08-06T00:00:00Z',
    started_at: null,
    finished_at: null,
  }
}

function setupDefaults() {
  mocked.getPipelineSummary.mockResolvedValue(summaryFixture)
  mocked.getPolicyKnowledgeStats.mockResolvedValue({ total: 9 })
  mocked.getGovernanceDashboard.mockResolvedValue(dashboardFixture)
  mocked.listKnowledgeBuildTasks.mockResolvedValue([
    makeTask('T1', 'QUEUED'),
    makeTask('T2', 'RUNNING'),
    makeTask('T3', 'WAITING_REVIEW'),
    makeTask('T4', 'WAITING_REVIEW'),
    makeTask('T5', 'APPROVED_PENDING_RELEASE'),
  ])
  mocked.getActiveRelease.mockResolvedValue(releaseFixture)
  mocked.getSemanticSummary.mockResolvedValue(semanticFixture)
}

beforeEach(() => {
  Object.values(mocked).forEach((mock) => mock.mockReset())
  setupDefaults()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('知识资产概览页', () => {
  it('首屏先展示五类资产台账并使用真实 Unit 口径', async () => {
    render(<GovernanceOverviewPage />)

    const ledger = await screen.findByRole('table', { name: '知识资产台账' })
    await waitFor(() => {
      expect(within(ledger).getByRole('row', { name: /政策文档.*5.*4 已完成解析.*1 待解析/ })).toBeInTheDocument()
    })
    expect(within(ledger).getByRole('row', { name: /政策单元.*20.*13 已审核.*6 待审核/ })).toBeInTheDocument()
    expect(within(ledger).getByRole('row', { name: /结构化知识.*30.*20 已批准.*2 个构建任务.*6 条待审核/ })).toBeInTheDocument()
    expect(within(ledger).getByRole('row', { name: /语义资产.*12.*8 已映射.*66.7%.*3 未映射/ })).toBeInTheDocument()
    expect(within(ledger).getByRole('row', { name: /发布快照.*1.*REL_2026_003.*1 待发布/ })).toBeInTheDocument()
    expect(screen.queryByText('影响分析')).not.toBeInTheDocument()
  })

  it('展开结构化知识的编译管线与四个真实工作域', async () => {
    render(<GovernanceOverviewPage />)

    const detail = await screen.findByRole('region', { name: '结构化知识详情' })
    expect(within(detail).getByText('INPUT_SNAPSHOT')).toBeInTheDocument()
    expect(within(detail).getByText('VALIDATE')).toBeInTheDocument()
    expect(within(detail).getByText('PASS 20')).toBeInTheDocument()
    expect(within(detail).getByText('REVIEW 6')).toBeInTheDocument()

    const workspaces = within(detail).getByRole('heading', { name: '知识工作域' }).parentElement
    expect(workspaces).not.toBeNull()
    expect(within(workspaces as HTMLElement).getByRole('link', { name: /知识构建/ })).toHaveAttribute('href', '/policy-knowledge/knowledge/build')
    expect(within(workspaces as HTMLElement).getByRole('link', { name: /知识审核/ })).toHaveAttribute('href', '/policy-knowledge/knowledge/review')
    expect(within(workspaces as HTMLElement).getByRole('link', { name: /发布管理/ })).toHaveAttribute('href', '/policy-knowledge/knowledge/releases')
    expect(within(workspaces as HTMLElement).getByRole('link', { name: /语义发现/ })).toHaveAttribute('href', '/policy-knowledge/knowledge/semantic-discovery')
  })

  it('治理进度只显示积压与当前优先待办', async () => {
    render(<GovernanceOverviewPage />)

    const governance = await screen.findByRole('region', { name: '治理进度' })
    expect(within(governance).getByText('1 待解析')).toBeInTheDocument()
    expect(within(governance).getByText('6 待审核')).toBeInTheDocument()
    expect(within(governance).getByText('2 构建中')).toBeInTheDocument()
    expect(within(governance).getByText('2 变更集')).toBeInTheDocument()
    expect(within(governance).getByText('活动版本正常')).toBeInTheDocument()

    const attention = screen.getByRole('region', { name: '当前需要处理' })
    expect(within(attention).getByText('编译结果需人工复核')).toBeInTheDocument()
    expect(within(attention).getByText('待审核知识变更集')).toBeInTheDocument()
    expect(within(attention).getByText('语义指标尚未映射')).toBeInTheDocument()
  })

  it('活动版本 404 时将发布快照显示为未发布', async () => {
    mocked.getActiveRelease.mockRejectedValue(
      new PolicyKnowledgeApiError('尚无活动版本', 404, 'POLICY_ACTIVE_RELEASE_NOT_FOUND', {}),
    )

    render(<GovernanceOverviewPage />)

    const ledger = await screen.findByRole('table', { name: '知识资产台账' })
    await waitFor(() => {
      expect(within(ledger).getByRole('row', { name: /发布快照.*尚未发布版本/ })).toBeInTheDocument()
    })
    expect(screen.queryByText('无法连接后端')).not.toBeInTheDocument()
  })

  it('单接口失败时只降级对应资产区块', async () => {
    mocked.getGovernanceDashboard.mockRejectedValue(new Error('pg down'))

    render(<GovernanceOverviewPage />)

    const ledger = await screen.findByRole('table', { name: '知识资产台账' })
    await waitFor(() => {
      expect(within(ledger).getByRole('row', { name: /结构化知识.*暂不可用/ })).toBeInTheDocument()
    })
    expect(within(ledger).getByRole('row', { name: /政策文档.*5/ })).toBeInTheDocument()
    expect(within(ledger).getByRole('row', { name: /语义资产.*12/ })).toBeInTheDocument()
  })
})
