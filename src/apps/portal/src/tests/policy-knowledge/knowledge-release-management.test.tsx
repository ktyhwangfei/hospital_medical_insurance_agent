import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeReleasesPage from '../../../app/policy-knowledge/knowledge/releases/page'
import {
  buildRelease,
  createRelease,
  getActiveRelease,
  getActiveSnapshot,
  getLatestReleaseQuality,
  getReleaseGateStatus,
  listChangeSets,
  listPublishedSnapshots,
  listReleases,
  listTestCases,
  saveTestCase,
  PolicyKnowledgeApiError,
  promoteGovernedRelease,
  rollbackRelease,
  runQuality,
  type KnowledgeChangeSet,
  type PolicyTestCase,
  type KnowledgeRelease,
  type PublishedSnapshot,
  type QualityRunReport,
  type ReleaseGateStatus,
  QUALITY_CONFIG_HASH,
} from '@/lib/policy-knowledge-api'

const currentApiContext = vi.hoisted(() => ({ userId: 'release-actor' }))

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/policy-knowledge/knowledge/releases'),
}))

vi.mock('@/lib/api-context', () => ({
  useApiContext: vi.fn(() => currentApiContext),
}))

vi.mock('@/lib/policy-knowledge-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-knowledge-api')>()
  return {
    ...actual,
    buildRelease: vi.fn(),
    createRelease: vi.fn(),
    getActiveRelease: vi.fn(),
    getActiveSnapshot: vi.fn(),
    getLatestReleaseQuality: vi.fn(),
    getReleaseGateStatus: vi.fn(),
    listChangeSets: vi.fn(),
    listPublishedSnapshots: vi.fn(),
    listReleases: vi.fn(),
    listTestCases: vi.fn(),
    saveTestCase: vi.fn(),
    promoteGovernedRelease: vi.fn(),
    rollbackRelease: vi.fn(),
    runQuality: vi.fn(),
  }
})

const release = (
  release_id: string,
  status: KnowledgeRelease['status'],
  overrides: Partial<KnowledgeRelease> = {},
): KnowledgeRelease => ({
  release_id,
  status,
  facts_collection: `facts_${release_id}`,
  rules_collection: `rules_${release_id}`,
  contract_version: 'v2.3',
  case_set_version: 7,
  config_hash: QUALITY_CONFIG_HASH,
  source_change_set_id: `CS_${release_id}`,
  quality_score: status === 'passed' || status === 'active' || status === 'retired' ? 0.94 : null,
  consistency_score: status === 'passed' || status === 'active' || status === 'retired' ? 0.98 : null,
  created_at: '2026-07-01T00:00:00Z',
  promoted_at: status === 'active' || status === 'retired' ? '2026-08-06T02:03:04Z' : null,
  promoted_by: status === 'active' || status === 'retired' ? 'release-operator' : null,
  ...overrides,
})

const quality = (
  releaseId: string,
  overrides: Partial<QualityRunReport['run']> = {},
): QualityRunReport => ({
  run: {
    run_id: `RUN_${releaseId}`,
    release_id: releaseId,
    baseline_release_id: 'REL_ACTIVE',
    status: 'passed',
    candidate_score: 0.94,
    baseline_score: 0.9,
    consistency_score: 0.98,
    blocked_reasons: [],
    repeat_count: 3,
    case_set_version: 7,
    config_hash: QUALITY_CONFIG_HASH,
    ...overrides,
  },
  case_results: [],
})

const gate = (
  releaseId: string,
  canPromote: boolean,
  blockedReasons: string[] = [],
  overrides: Partial<ReleaseGateStatus> = {},
): ReleaseGateStatus => ({
  release_id: releaseId,
  can_promote: canPromote,
  current_case_set_version: 7,
  active_release_id: 'REL_ACTIVE',
  latest_run: canPromote ? quality(releaseId).run : null,
  blocked_reasons: blockedReasons,
  sync_pending: false,
  sync_pending_reasons: [],
  ...overrides,
})

const snapshot = (
  snapshot_id: string,
  overrides: Partial<PublishedSnapshot> = {},
): PublishedSnapshot => ({
  snapshot_id,
  doc_id: null,
  policy_scope: {},
  semantic_contract_version: 'v2.3',
  rules_collection: `rules_${snapshot_id}`,
  facts_collection: `facts_${snapshot_id}`,
  source_change_set_id: `CS_${snapshot_id}`,
  immutable: true,
  published_at: '2026-08-05T01:02:03Z',
  published_by: 'publisher-01',
  rollback_of: null,
  replaced_by: null,
  ...overrides,
})

const approvedChangeSet: KnowledgeChangeSet = {
  change_set_id: 'CS_APPROVED',
  source_document_version_id: 'REV_001',
  doc_id: 'DOC_001',
  doc_title: '职工基本医疗保险办法',
  build_task_id: 'TASK_001',
  source_units: [],
  semantic_contract_version: 'v2.3',
  supersedes_candidate_id: null,
  status: 'APPROVED',
  summary: { additions: 2, modifications: 1, replacements: 0, expirations: 0, unchanged: 4 },
  items: [],
  quality_report: {
    source_fidelity: 1,
    structural_completeness: 0.96,
    semantic_consistency: 0.93,
    rule_consistency: 0.95,
  },
  risk_summary: {},
  blockers: [],
  review_decision: null,
  created_at: '2026-08-04T00:00:00Z',
  updated_at: '2026-08-04T01:00:00Z',
}

const releases = [
  release('REL_ACTIVE', 'active'),
  release('REL_BUILDING', 'building'),
  release('REL_READY', 'ready', { source_change_set_id: null }),
  release('REL_FAILED', 'failed'),
  release('REL_PASSED', 'passed'),
  release('REL_RETIRED', 'retired'),
  release('REL_LEGACY', 'retired', { source_change_set_id: null }),
]
const snapshots = [
  snapshot('REL_ACTIVE', { published_by: 'active-publisher' }),
  snapshot('REL_RETIRED', {
    published_at: '2026-07-01T08:00:00Z',
    published_by: 'history-publisher',
  }),
  snapshot('REL_LEGACY', { source_change_set_id: null, published_by: 'legacy-publisher' }),
]

beforeEach(() => {
  vi.mocked(listReleases).mockReset()
  vi.mocked(listChangeSets).mockReset()
  vi.mocked(listTestCases).mockReset()
  vi.mocked(listPublishedSnapshots).mockReset()
  vi.mocked(getActiveRelease).mockReset()
  vi.mocked(getActiveSnapshot).mockReset()
  vi.mocked(getLatestReleaseQuality).mockReset()
  vi.mocked(getReleaseGateStatus).mockReset()
  vi.mocked(createRelease).mockReset()
  vi.mocked(buildRelease).mockReset()
  vi.mocked(runQuality).mockReset()
  vi.mocked(promoteGovernedRelease).mockReset()
  vi.mocked(rollbackRelease).mockReset()
  currentApiContext.userId = 'release-actor'
  vi.mocked(listReleases).mockResolvedValue(releases)
  vi.mocked(listChangeSets).mockResolvedValue([approvedChangeSet])
  vi.mocked(listTestCases).mockResolvedValue([])
  vi.mocked(listPublishedSnapshots).mockResolvedValue(snapshots)
  vi.mocked(getActiveRelease).mockResolvedValue(releases[0])
  vi.mocked(getActiveSnapshot).mockResolvedValue(snapshots[0])
  vi.mocked(getLatestReleaseQuality).mockImplementation(async (releaseId) => {
    if (releaseId === 'REL_FAILED') return quality(releaseId, { status: 'failed', blocked_reasons: ['必测用例未全部通过'] })
    if (releaseId === 'REL_PASSED') return quality(releaseId)
    throw new Error('尚无质量记录')
  })
  vi.mocked(getReleaseGateStatus).mockImplementation(async (releaseId) => {
    if (releaseId === 'REL_PASSED') return gate(releaseId, true)
    return gate(releaseId, false, [`release 状态尚不可发布：${releaseId}`])
  })
  vi.mocked(createRelease).mockResolvedValue(release('REL_NEW', 'building', { source_change_set_id: 'CS_APPROVED' }))
  vi.mocked(buildRelease).mockResolvedValue(release('REL_BUILDING', 'ready'))
  vi.mocked(runQuality).mockImplementation(async (releaseId) => quality(releaseId).run)
  vi.mocked(promoteGovernedRelease).mockResolvedValue(release('REL_PASSED', 'active'))
  vi.mocked(rollbackRelease).mockResolvedValue(release('REL_RETIRED', 'active'))
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('发布管理页', () => {
  it('保持共享骨架顺序，展示当前、待发布和历史三段真实信息', async () => {
    render(<KnowledgeReleasesPage />)

    expect(await screen.findByRole('heading', { name: '当前正式版本' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '待发布版本' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '历史正式版本' })).toBeInTheDocument()
    const navigation = screen.getByRole('navigation', { name: '知识治理工作区' })
    const context = screen.getByRole('complementary', { name: '知识构建上下文' })
    const flow = screen.getByRole('list', { name: '知识治理流程' })
    const current = screen.getByRole('region', { name: '当前正式版本' })
    expect(navigation.compareDocumentPosition(context) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(context.compareDocumentPosition(flow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(flow.compareDocumentPosition(current) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    expect(within(current).getByText('REL_ACTIVE')).toBeInTheDocument()
    expect(within(current).getByText(/active-publisher/)).toBeInTheDocument()
    expect(within(current).getByText(/2026\/8\/5/)).toBeInTheDocument()
    expect(within(current).getByText(/当前启用时间：2026\/8\/6/)).toBeInTheDocument()
    expect(within(current).getByText(/本次启用操作人：release-operator/)).toBeInTheDocument()
    expect(within(current).getByText(/语义契约 v2\.3/)).toBeInTheDocument()
    expect(within(current).getByText(/质量 94%/)).toBeInTheDocument()
    expect(within(current).getByText(/血缘 CS_REL_ACTIVE/)).toBeInTheDocument()
    expect(within(current).getByText(/规则总数：暂无统计/)).toBeInTheDocument()

    const history = screen.getByRole('region', { name: '历史正式版本' })
    expect(within(history).getByText('REL_RETIRED')).toBeInTheDocument()
    expect(within(history).getByText(/history-publisher/)).toBeInTheDocument()
    expect(within(history).getByText(/血缘 CS_REL_RETIRED/)).toBeInTheDocument()
    expect(screen.getAllByText('1 个构建结果').length).toBeGreaterThan(0)
    const legacyCandidate = screen.getByText('REL_READY').closest('article')
    expect(legacyCandidate).toHaveTextContent('来源未记录（兼容版本）')
    expect(legacyCandidate).not.toHaveTextContent('1 个构建结果')
  })

  it('只允许从审核通过结果创建单来源发布候选', async () => {
    const user = userEvent.setup()
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '待发布版本' })

    await user.click(screen.getByRole('button', { name: /选择变更集 CS_APPROVED/ }))
    await user.type(screen.getByRole('textbox', { name: '发布候选标识' }), 'REL_NEW')
    await user.click(screen.getByRole('button', { name: '创建发布候选' }))

    await waitFor(() => expect(createRelease).toHaveBeenCalledWith({
      release_id: 'REL_NEW',
      contract_version: 'v2.3',
      config_hash: QUALITY_CONFIG_HASH,
      source_change_set_id: 'CS_APPROVED',
    }))
    expect(listReleases).toHaveBeenCalledTimes(2)
  })

  it('在候选卡片展示最近一次索引构建失败原因', async () => {
    vi.mocked(listReleases).mockResolvedValueOnce([
      release('REL_BUILDING', 'building', { build_error: '规则索引字段类型不兼容' }),
    ])

    render(<KnowledgeReleasesPage />)

    const card = (await screen.findByText('REL_BUILDING')).closest('article')
    expect(card).toHaveTextContent('索引构建失败')
    expect(card).toHaveTextContent('规则索引字段类型不兼容')
  })

  it('按 building、ready、failed 和有效 passed 状态暴露严格门禁动作', async () => {
    const user = userEvent.setup()
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '待发布版本' })

    expect(screen.getByRole('button', { name: '构建索引：REL_BUILDING' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '运行质量检查：REL_READY' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重新运行质量检查：REL_FAILED' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '发布正式版本：REL_PASSED' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '构建索引：REL_BUILDING' }))
    await waitFor(() => expect(buildRelease).toHaveBeenCalledWith('REL_BUILDING'))
    await user.click(screen.getByRole('button', { name: '运行质量检查：REL_READY' }))
    await waitFor(() => expect(runQuality).toHaveBeenCalledWith('REL_READY'))
    await user.click(screen.getByRole('button', { name: '重新运行质量检查：REL_FAILED' }))
    await waitFor(() => expect(runQuality).toHaveBeenCalledWith('REL_FAILED'))
    expect(listReleases).toHaveBeenCalledTimes(4)
    await user.click(screen.getByRole('button', { name: '发布正式版本：REL_PASSED' }))
    await waitFor(() => expect(promoteGovernedRelease).toHaveBeenCalledWith('REL_PASSED', 'release-actor'))
  })

  it('failed 候选重跑质量检查被服务端拒绝时保留当前状态', async () => {
    const user = userEvent.setup()
    vi.mocked(runQuality).mockRejectedValueOnce(new Error('质量重跑失败'))
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '待发布版本' })

    await user.click(screen.getByRole('button', { name: '重新运行质量检查：REL_FAILED' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('质量重跑失败')
    expect(screen.getByText('REL_FAILED').closest('article')).toHaveTextContent('质量未通过')
    expect(listReleases).toHaveBeenCalledTimes(1)
  })

  it('只服从服务端权威门禁结果，展示阻断原因', async () => {
    vi.mocked(getReleaseGateStatus).mockImplementation(async (releaseId) => gate(
      releaseId,
      false,
      releaseId === 'REL_PASSED' ? ['最新质量运行的活动基线已过期'] : [],
    ))
    render(<KnowledgeReleasesPage />)

    await screen.findByRole('heading', { name: '待发布版本' })
    expect(screen.queryByRole('button', { name: '发布正式版本：REL_PASSED' })).not.toBeInTheDocument()
    expect(screen.getByText('最新质量运行的活动基线已过期')).toBeInTheDocument()
  })

  it('服务端门禁不可用时禁止发布并显示独立错误', async () => {
    vi.mocked(getReleaseGateStatus).mockImplementation(async (releaseId) => {
      if (releaseId === 'REL_PASSED') throw new PolicyKnowledgeApiError('发布门禁暂不可用', 503, 'POLICY_RELEASE_GATE_UNAVAILABLE', { release_id: releaseId })
      return gate(releaseId, false)
    })
    render(<KnowledgeReleasesPage />)

    await screen.findByRole('heading', { name: '待发布版本' })
    expect(screen.queryByRole('button', { name: '发布正式版本：REL_PASSED' })).not.toBeInTheDocument()
    expect(screen.getByText('发布门禁暂不可用')).toBeInTheDocument()
  })

  it('发布失败时保留旧 active，展示真实错误且不乐观刷新', async () => {
    const user = userEvent.setup()
    vi.mocked(promoteGovernedRelease).mockRejectedValueOnce(new Error('快照同步失败，请幂等重试'))
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '待发布版本' })

    await user.click(screen.getByRole('button', { name: '发布正式版本：REL_PASSED' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('快照同步失败，请幂等重试')
    expect(screen.getByRole('region', { name: '当前正式版本' })).toHaveTextContent('REL_ACTIVE')
    expect(listReleases).toHaveBeenCalledTimes(1)
  })

  it('发布已生效但同步待收口时立即重拉新 active 并提示幂等重试', async () => {
    const user = userEvent.setup()
    const nextActive = release('REL_PASSED', 'active', {
      promoted_at: '2026-08-06T03:04:05Z',
      promoted_by: 'release-actor',
    })
    vi.mocked(promoteGovernedRelease).mockRejectedValueOnce(new PolicyKnowledgeApiError(
      '正式版本已切换，同步待收口',
      503,
      'POLICY_RELEASE_SYNC_PENDING',
      { release_id: 'REL_PASSED', source_change_set_id: 'CS_REL_PASSED' },
    ))
    vi.mocked(listReleases).mockResolvedValueOnce(releases).mockResolvedValueOnce([
      nextActive,
      ...releases.filter((item) => item.release_id !== 'REL_PASSED' && item.release_id !== 'REL_ACTIVE'),
      release('REL_ACTIVE', 'retired'),
    ])
    vi.mocked(getActiveRelease).mockResolvedValueOnce(releases[0]).mockResolvedValueOnce(nextActive)
    vi.mocked(getActiveSnapshot).mockResolvedValueOnce(snapshots[0]).mockResolvedValueOnce(snapshot('REL_PASSED', { published_by: 'release-actor' }))
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '待发布版本' })

    await user.click(screen.getByRole('button', { name: '发布正式版本：REL_PASSED' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('发布已生效，快照/血缘同步待重试')
    expect(screen.getByRole('alert')).toHaveTextContent('CS_REL_PASSED')
    await waitFor(() => expect(screen.getByRole('region', { name: '当前正式版本' })).toHaveTextContent('REL_PASSED'))
    expect(listReleases).toHaveBeenCalledTimes(2)
  })

  it('快照缺失时仍展示 release 的真实启用时间与操作人', async () => {
    vi.mocked(getActiveSnapshot).mockRejectedValueOnce(new PolicyKnowledgeApiError('快照不存在', 404, 'SNAPSHOT_NOT_FOUND', {}))
    render(<KnowledgeReleasesPage />)

    const current = await screen.findByRole('region', { name: '当前正式版本' })
    expect(current).toHaveTextContent('当前启用时间：2026/8/6')
    expect(current).toHaveTextContent('本次启用操作人：release-operator')
    expect(current).toHaveTextContent('原始快照：暂无记录')
  })

  it('活动快照加载失败不隐藏 active release', async () => {
    vi.mocked(getActiveSnapshot).mockRejectedValueOnce(new Error('活动快照服务不可用'))
    render(<KnowledgeReleasesPage />)

    const current = await screen.findByRole('region', { name: '当前正式版本' })
    expect(current).toHaveTextContent('REL_ACTIVE')
    expect(current).toHaveTextContent('活动快照服务不可用')
    expect(screen.getByRole('region', { name: '待发布版本' })).toHaveTextContent('REL_PASSED')
  })

  it('审核结果加载失败只锁定创建区，不影响现有版本', async () => {
    vi.mocked(listChangeSets).mockRejectedValueOnce(new Error('审核结果暂不可用'))
    render(<KnowledgeReleasesPage />)

    await screen.findByText('审核结果暂不可用')
    expect(screen.getByRole('button', { name: '创建发布候选' })).toBeDisabled()
    expect(screen.getByRole('region', { name: '当前正式版本' })).toHaveTextContent('REL_ACTIVE')
    expect(screen.getByRole('region', { name: '待发布版本' })).toHaveTextContent('REL_PASSED')
  })

  it('release 列表加载失败不抹掉独立加载的 active 与历史快照', async () => {
    vi.mocked(listReleases).mockRejectedValueOnce(new Error('release 列表暂不可用'))
    render(<KnowledgeReleasesPage />)

    expect(await screen.findByText('release 列表暂不可用')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '当前正式版本' })).toHaveTextContent('REL_ACTIVE')
    expect(screen.getByRole('region', { name: '历史正式版本' })).toHaveTextContent('REL_RETIRED')
  })

  it('活动版本刷新后仍可见同步待收口原因并可重试', async () => {
    const user = userEvent.setup()
    let activeGateCalls = 0
    vi.mocked(getReleaseGateStatus).mockImplementation(async (releaseId) => {
      if (releaseId === 'REL_ACTIVE') {
        activeGateCalls += 1
        return gate(releaseId, false, [], activeGateCalls === 1 ? {
          sync_pending: true,
          sync_pending_reasons: ['发布快照尚未落库'],
        } : {})
      }
      return gate(releaseId, releaseId === 'REL_PASSED')
    })
    vi.mocked(promoteGovernedRelease).mockResolvedValueOnce(releases[0])
    render(<KnowledgeReleasesPage />)

    expect(await screen.findByText('发布快照尚未落库')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '重试发布同步：REL_ACTIVE' }))
    await waitFor(() => expect(promoteGovernedRelease).toHaveBeenCalledWith('REL_ACTIVE', 'release-actor'))
    await waitFor(() => expect(screen.queryByRole('button', { name: '重试发布同步：REL_ACTIVE' })).not.toBeInTheDocument())
  })

  it('活动版本再次返回同步待收口时刷新并保留可重试状态', async () => {
    const user = userEvent.setup()
    vi.mocked(getReleaseGateStatus).mockImplementation(async (releaseId) => gate(
      releaseId,
      releaseId === 'REL_PASSED',
      [],
      releaseId === 'REL_ACTIVE' ? { sync_pending: true, sync_pending_reasons: ['变更集状态尚未收口'] } : {},
    ))
    vi.mocked(promoteGovernedRelease).mockRejectedValueOnce(new PolicyKnowledgeApiError(
      '同步待收口',
      503,
      'POLICY_RELEASE_SYNC_PENDING',
      { release_id: 'REL_ACTIVE', source_change_set_id: 'CS_REL_ACTIVE' },
    ))
    render(<KnowledgeReleasesPage />)
    await screen.findByText('变更集状态尚未收口')

    await user.click(screen.getByRole('button', { name: '重试发布同步：REL_ACTIVE' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('REL_ACTIVE')
    expect(screen.getByRole('alert')).toHaveTextContent('CS_REL_ACTIVE')
    expect(screen.getByRole('button', { name: '重试发布同步：REL_ACTIVE' })).toBeEnabled()
    expect(getActiveRelease).toHaveBeenCalledTimes(2)
  })

  it('active release 与 active snapshot ID 错位时不拼接也不把两者放入历史', async () => {
    vi.mocked(getActiveSnapshot).mockResolvedValueOnce(snapshot('REL_SNAPSHOT_OTHER', { published_by: 'other-publisher' }))
    vi.mocked(listPublishedSnapshots).mockResolvedValueOnce([
      ...snapshots,
      snapshot('REL_SNAPSHOT_OTHER', { published_by: 'other-publisher' }),
    ])
    render(<KnowledgeReleasesPage />)

    const current = await screen.findByRole('region', { name: '当前正式版本' })
    expect(current).toHaveTextContent('REL_ACTIVE')
    expect(current).toHaveTextContent('活动版本与快照同步中/不一致')
    expect(current).toHaveTextContent('原始快照：暂无记录')
    expect(current).not.toHaveTextContent('other-publisher')
    const history = screen.getByRole('region', { name: '历史正式版本' })
    expect(history).not.toHaveTextContent('REL_ACTIVE')
    expect(history).not.toHaveTextContent('REL_SNAPSHOT_OTHER')
  })

  it('发布状态未知时显示精确提示并立即刷新', async () => {
    const user = userEvent.setup()
    vi.mocked(promoteGovernedRelease).mockRejectedValueOnce(new PolicyKnowledgeApiError(
      '无法确定发布是否已生效',
      503,
      'POLICY_RELEASE_STATE_UNKNOWN',
      { release_id: 'REL_PASSED', source_change_set_id: 'CS_REL_PASSED' },
    ))
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '待发布版本' })

    await user.click(screen.getByRole('button', { name: '发布正式版本：REL_PASSED' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('发布状态未知，已刷新服务端状态')
    expect(listReleases).toHaveBeenCalledTimes(2)
  })

  it('无血缘兼容版本只读显示，不提供正式发布或回滚', async () => {
    render(<KnowledgeReleasesPage />)
    const history = await screen.findByRole('region', { name: '历史正式版本' })
    const legacy = within(history).getByText('REL_LEGACY').closest('article')

    expect(legacy).toHaveTextContent('来源未记录（兼容版本）')
    expect(within(legacy as HTMLElement).queryByRole('button', { name: '回滚到 REL_LEGACY' })).not.toBeInTheDocument()
  })

  it('回滚 retired 版本时使用共享 Dialog 显式确认当前操作人', async () => {
    const user = userEvent.setup()
    currentApiContext.userId = 'demo'
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '历史正式版本' })

    await user.click(screen.getByRole('button', { name: '回滚到 REL_RETIRED' }))
    const dialog = screen.getByRole('dialog', { name: '确认回滚正式版本' })
    expect(dialog).toHaveAttribute('data-slot', 'dialog-content')
    expect(within(dialog).getByText('确认人：demo（演示身份）')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '确认回滚' }))

    await waitFor(() => expect(rollbackRelease).toHaveBeenCalledWith('REL_RETIRED', 'demo'))
    expect(listPublishedSnapshots).toHaveBeenCalledTimes(2)
  })

  it('只保留最新刷新结果，并能在 StrictMode 重放后加载', async () => {
    const stale = deferred<KnowledgeRelease[]>()
    vi.mocked(listReleases)
      .mockImplementationOnce(() => stale.promise)
      .mockResolvedValueOnce([release('REL_NEWEST', 'active')])
      .mockResolvedValueOnce([release('REL_NEWEST', 'active')])
    vi.mocked(getActiveRelease).mockResolvedValue(release('REL_NEWEST', 'active'))
    vi.mocked(getActiveSnapshot).mockResolvedValue(snapshot('REL_NEWEST'))

    render(<StrictMode><KnowledgeReleasesPage /></StrictMode>)

    expect(await screen.findByText('REL_NEWEST')).toBeInTheDocument()
    await act(async () => {
      stale.resolve([release('REL_STALE', 'active')])
      await stale.promise
    })
    expect(screen.queryByText('REL_STALE')).not.toBeInTheDocument()
  })

  it('卸载后不写入延迟请求结果', async () => {
    const pending = deferred<KnowledgeRelease[]>()
    vi.mocked(listReleases).mockImplementationOnce(() => pending.promise)
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const view = render(<KnowledgeReleasesPage />)

    view.unmount()
    await act(async () => {
      pending.resolve([release('REL_AFTER_UNMOUNT', 'active')])
      await pending.promise
    })

    expect(screen.queryByText('REL_AFTER_UNMOUNT')).not.toBeInTheDocument()
    expect(consoleError).not.toHaveBeenCalled()
    consoleError.mockRestore()
  })
})

describe('质量测试用例', () => {
  it('展示内置与自定义质量测试用例', async () => {
    vi.mocked(listTestCases).mockResolvedValue([
      testCase({ case_id: 'TC_DEFAULT_001', name: '住院起付线', mode: 'semantic' }),
      testCase({ case_id: 'TC_CUSTOM_001', name: '门诊报销比例', mode: 'hybrid' }),
    ])
    const user = userEvent.setup()
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '质量测试用例' })
    expect(screen.getByText('住院起付线')).toBeInTheDocument()
    expect(screen.getByText('门诊报销比例')).toBeInTheDocument()
    expect(screen.getByText(/TC_DEFAULT_001/)).toBeInTheDocument()
  })

  it('新增质量测试用例并刷新列表', async () => {
    const user = userEvent.setup()
    render(<KnowledgeReleasesPage />)
    await screen.findByRole('heading', { name: '质量测试用例' })
    await user.type(screen.getByRole('textbox', { name: '用例名称' }), '大病保险报销')
    await user.type(screen.getByRole('textbox', { name: '用例查询' }), '大病医疗保险的报销范围是什么')
    await user.click(screen.getByRole('button', { name: '新增用例' }))
    await waitFor(() => expect(saveTestCase).toHaveBeenCalledWith(expect.objectContaining({
      name: '大病保险报销',
      query: '大病医疗保险的报销范围是什么',
      mode: 'semantic',
    })))
  })
})

function testCase(overrides: Partial<PolicyTestCase> = {}): PolicyTestCase {
  return {
    case_id: 'TC_DEFAULT_001',
    name: '默认用例',
    query: '默认政策查询',
    mode: 'semantic',
    expected_knowledge_ids: [],
    filters: {},
    required: true,
    active: true,
    case_set_version: 0,
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}
