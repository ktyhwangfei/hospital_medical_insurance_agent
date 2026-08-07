import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import GovernanceOverviewPage from '../../../app/policy-knowledge/page'
import {
  getActiveRelease,
  getGovernanceDashboard,
  getLatestReleaseQuality,
  getPipelineSummary,
  getPolicyKnowledgeStats,
  getSemanticSummary,
  listEligibleKnowledgeUnits,
  listKnowledgeBuildTasks,
  listPipelineExtractions,
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
  getLatestReleaseQuality: vi.fn(),
  getPipelineSummary: vi.fn(),
  getPolicyKnowledgeStats: vi.fn(),
  getSemanticSummary: vi.fn(),
  listEligibleKnowledgeUnits: vi.fn(),
  listKnowledgeBuildTasks: vi.fn(),
  listPipelineExtractions: vi.fn(),
}))

const mocked = {
  getActiveRelease: vi.mocked(getActiveRelease),
  getGovernanceDashboard: vi.mocked(getGovernanceDashboard),
  getLatestReleaseQuality: vi.mocked(getLatestReleaseQuality),
  getPipelineSummary: vi.mocked(getPipelineSummary),
  getPolicyKnowledgeStats: vi.mocked(getPolicyKnowledgeStats),
  getSemanticSummary: vi.mocked(getSemanticSummary),
  listEligibleKnowledgeUnits: vi.mocked(listEligibleKnowledgeUnits),
  listKnowledgeBuildTasks: vi.mocked(listKnowledgeBuildTasks),
  listPipelineExtractions: vi.mocked(listPipelineExtractions),
}

const summaryFixture: PipelineSummary = {
  documents_count: 5,
  documents_raw: 1,
  extractions_count: 20,
  extractions_draft: 6,
  extractions_reviewed: 4,
  extractions_published: 9,
}

const dashboardFixture: GovernanceDashboard = {
  documents_total: 5,
  change_sets_total: 4,
  rules_total: 30,
  rules_pending_review: 6,
  rules_approved: 20,
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
  quality_score: 1.0,
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

/** 全绿默认 mock：各接口按 fixture 返回，子测试可覆盖单个 */
function setupDefaults() {
  mocked.getPipelineSummary.mockResolvedValue(summaryFixture)
  mocked.getPolicyKnowledgeStats.mockResolvedValue({ total: 9 })
  mocked.listPipelineExtractions.mockResolvedValue({
    items: [{ confidence: 0.95 }, { confidence: 0.6 }, { confidence: null }],
    total: 3,
  })
  mocked.getGovernanceDashboard.mockResolvedValue(dashboardFixture)
  mocked.listKnowledgeBuildTasks.mockResolvedValue([
    makeTask('T1', 'QUEUED'),
    makeTask('T2', 'RUNNING'),
    makeTask('T3', 'WAITING_REVIEW'),
    makeTask('T4', 'WAITING_REVIEW'),
    makeTask('T5', 'APPROVED_PENDING_RELEASE'),
    makeTask('T6', 'PUBLISHED'),
  ])
  mocked.getActiveRelease.mockResolvedValue(releaseFixture)
  mocked.getLatestReleaseQuality.mockResolvedValue({
    run: {
      run_id: 'RUN1', release_id: 'REL_2026_003', baseline_release_id: null,
      status: 'passed', candidate_score: 1.0, baseline_score: null,
      consistency_score: 0.99, blocked_reasons: [], repeat_count: 3,
      case_set_version: 1, config_hash: 'abc',
    },
    case_results: [],
  })
  mocked.getSemanticSummary.mockResolvedValue(semanticFixture)
  mocked.listEligibleKnowledgeUnits.mockResolvedValue([
    { doc_id: 'D1', doc_title: 't', unit_id: 'U1', unit_revision_id: 'R1', path: [], source_preview: '', status: 'reviewed', knowledge_count: 0, availability: 'AVAILABLE', occupied_by: null, target_href: null },
    { doc_id: 'D1', doc_title: 't', unit_id: 'U2', unit_revision_id: 'R2', path: [], source_preview: '', status: 'published', knowledge_count: 1, availability: 'AVAILABLE', occupied_by: null, target_href: null },
    { doc_id: 'D2', doc_title: 't', unit_id: 'U3', unit_revision_id: 'R3', path: [], source_preview: '', status: 'reviewed', knowledge_count: 0, availability: 'AVAILABLE', occupied_by: null, target_href: null },
  ])
}

beforeEach(() => {
  vi.mocked(getPipelineSummary).mockReset()
  vi.mocked(getPolicyKnowledgeStats).mockReset()
  vi.mocked(listPipelineExtractions).mockReset()
  vi.mocked(getGovernanceDashboard).mockReset()
  vi.mocked(listKnowledgeBuildTasks).mockReset()
  vi.mocked(getActiveRelease).mockReset()
  vi.mocked(getLatestReleaseQuality).mockReset()
  vi.mocked(getSemanticSummary).mockReset()
  vi.mocked(listEligibleKnowledgeUnits).mockReset()
  setupDefaults()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('治理概览页', () => {
  it('流水线六步完整聚合（文档/单元/知识提取/知识审核/待发布/已生效）', async () => {
    render(<GovernanceOverviewPage />)
    const flow = await screen.findByRole('region', { name: '治理流水线' })
    // ① 文档 = summary.documents_count=5（fixture documents_raw=1 → 显示 "5 导入 · 1 待解析"）
    await waitFor(() => expect(within(flow).getByText(/^5 导入/)).toBeInTheDocument())
    expect(within(flow).getByText(/1 待解析/)).toBeInTheDocument()
    const docLink = within(flow).getByRole('link', { name: /文档/ })
    expect(docLink).toHaveAttribute('href', '/policy-knowledge/documents')
    // ② 单元 = eligible-units 长度 3
    await waitFor(() => expect(within(flow).getByText('3 可构建')).toBeInTheDocument())
    const unitLink = within(flow).getByRole('link', { name: /单元/ })
    expect(unitLink).toHaveAttribute('href', '/policy-knowledge/units')
    // ③ 知识提取 QUEUED+RUNNING=2（按步骤链接作用域断言，避免计数相同步骤歧义）
    const extractLink = within(flow).getByRole('link', { name: /知识提取/ })
    expect(extractLink).toHaveAttribute('href', '/policy-knowledge/knowledge/build')
    await waitFor(() => expect(within(extractLink).getByText('2 待处理')).toBeInTheDocument())
    // ④ 知识审核 WAITING_REVIEW=2
    const reviewLink = within(flow).getByRole('link', { name: /知识审核/ })
    expect(within(reviewLink).getByText('2 待处理')).toBeInTheDocument()
    expect(reviewLink).toHaveAttribute('href', '/policy-knowledge/knowledge/review')
    // ⑤ 待发布 APPROVED_PENDING_RELEASE=1
    const releaseLink = within(flow).getByRole('link', { name: /待发布/ })
    expect(within(releaseLink).getByText('1 待处理')).toBeInTheDocument()
    expect(releaseLink).toHaveAttribute('href', '/policy-knowledge/knowledge/releases')
    // ⑥ 已生效 = release_id
    expect(within(flow).getByText('REL_2026_003')).toBeInTheDocument()
  })

  it('待办队列四卡展示计数与类型分布', async () => {
    render(<GovernanceOverviewPage />)
    // 待审变更集 = PENDING_REVIEW 2 + NEEDS_DECISION 1 = 3
    const csCard = await screen.findByLabelText('待办-待审变更集')
    await waitFor(() => expect(within(csCard).getByText('3')).toBeInTheDocument())
    // 待发布 = build tasks APPROVED_PENDING_RELEASE 1
    const pendingCard = screen.getByLabelText('待办-待发布')
    expect(within(pendingCard).getByText('1')).toBeInTheDocument()
    // 决策任务：tasks_pending=2 + 类型分布
    const decisionCard = screen.getByLabelText('待办-决策任务待处理')
    expect(within(decisionCard).getByText('2')).toBeInTheDocument()
    expect(within(decisionCard).getByText(/VALUE_UNMAPPED 1/)).toBeInTheDocument()
    // 低置信：items 中 confidence<0.8 仅 1 条
    const lowConfCard = screen.getByLabelText('待办-低置信预警')
    expect(within(lowConfCard).getByText('1')).toBeInTheDocument()
  })

  it('全部待办清零时显示「暂无待办 · 流水线畅通」', async () => {
    mocked.getGovernanceDashboard.mockResolvedValue({
      ...dashboardFixture,
      tasks_pending: 0,
      tasks_by_type: {},
      change_sets_by_status: { APPROVED: 2 },
    })
    mocked.listKnowledgeBuildTasks.mockResolvedValue([makeTask('T9', 'PUBLISHED')])
    mocked.listPipelineExtractions.mockResolvedValue({ items: [{ confidence: 0.99 }], total: 1 })

    render(<GovernanceOverviewPage />)
    expect(await screen.findByText('暂无待办 · 流水线畅通')).toBeInTheDocument()
  })

  it('releases/active 404 时显示「未发布」而非报错', async () => {
    mocked.getActiveRelease.mockRejectedValue(
      new PolicyKnowledgeApiError('尚无活动版本', 404, 'POLICY_ACTIVE_RELEASE_NOT_FOUND', {}),
    )

    render(<GovernanceOverviewPage />)
    // 页头生效版本 chip
    const headerChip = await screen.findByText('未发布')
    expect(headerChip).toBeInTheDocument()
    // 流水线⑤「已生效」步骤也显示未发布（而非 暂不可用）
    const flow = screen.getByRole('region', { name: '治理流水线' })
    const activeStep = within(flow).getByRole('link', { name: /已生效/ })
    await waitFor(() => {
      expect(within(activeStep).getByText('未发布')).toBeInTheDocument()
    })
    // 不查质量门禁，且不出现整页错误
    expect(mocked.getLatestReleaseQuality).not.toHaveBeenCalled()
    expect(screen.queryByText('无法连接后端')).not.toBeInTheDocument()
  })

  it('单接口失败时对应区块降级为「暂不可用」，其他区块正常', async () => {
    mocked.getGovernanceDashboard.mockRejectedValue(new Error('pg down'))

    render(<GovernanceOverviewPage />)
    // 待办队列中 dashboard 相关卡降级
    const queue = await screen.findByRole('region', { name: '待办队列' })
    await waitFor(() => {
      expect(within(queue).getAllByText('暂不可用').length).toBeGreaterThanOrEqual(1)
    })
    // 统计卡带（summary/stats）仍正常渲染：文档统计卡（label+value 的 accessible name）
    const statLinks = await screen.findAllByRole('link', { name: /文档/ })
    const docStatCard = statLinks.find((l) => within(l).queryByText('5') !== null)
    expect(docStatCard).toBeTruthy()
    expect(within(docStatCard!).getByText('5')).toBeInTheDocument()
    // 标化四格仍正常
    expect(screen.getByLabelText('标化概览')).toBeInTheDocument()
  })

  it('标化四格渲染 semantic/summary 数据并链接语义层', async () => {
    render(<GovernanceOverviewPage />)
    // 先等数据渲染（loading 态也有同 aria-label，不能作为就绪信号）
    await screen.findByText('66.7%')
    const strip = screen.getByLabelText('标化概览')

    expect(within(strip).getByText('已映射')).toBeInTheDocument()
    expect(within(strip).getByText('8')).toBeInTheDocument()
    expect(within(strip).getByText('未映射')).toBeInTheDocument()
    expect(within(strip).getByText('3')).toBeInTheDocument()
    expect(within(strip).getByText('66.7%')).toBeInTheDocument()
    expect(within(strip).getByText('12')).toBeInTheDocument()
    expect(strip.closest('a')).toHaveAttribute('href', '/semantic-layer')
  })
})
