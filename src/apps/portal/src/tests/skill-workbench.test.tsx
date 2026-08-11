import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillsLayout from '../../app/skills/layout'
import SkillGovernanceWorkbench, * as workbenchModule from '@/components/skills/skill-governance-workbench'
import { shortHash } from '@/components/skills/skill-evidence-rail'
import { lifecycleSteps } from '@/components/skills/skill-lifecycle-stepper'
import type { InfraSkillCatalogResponse, SkillWorkbenchResponse } from '@/lib/types'

const { readWorkbenchUrl } = workbenchModule

const mockGetSkillGovernanceWorkbench = vi.fn()
const mockListInfraSkillCatalog = vi.fn()
const mockGetInfraSkillDetail = vi.fn()
const mockListInfraSkillVersions = vi.fn()
const mockListSkillEvalRuns = vi.fn()
const mockListSkillReleases = vi.fn()
const mockCreateSkillEvalRun = vi.fn()
const mockCreateSkillRelease = vi.fn()
const mockRequestSkillReleaseApproval = vi.fn()
const mockApproveSkillRelease = vi.fn()
const mockActivateSkillRelease = vi.fn()
const mockTestInfraSkillRouting = vi.fn()
const mockTestInfraSkillExecution = vi.fn()

vi.mock('@/lib/api-client', () => ({
  getSkillGovernanceWorkbench: (...args: unknown[]) => mockGetSkillGovernanceWorkbench(...args),
  listInfraSkillCatalog: (...args: unknown[]) => mockListInfraSkillCatalog(...args),
  getInfraSkillDetail: (...args: unknown[]) => mockGetInfraSkillDetail(...args),
  listInfraSkillVersions: (...args: unknown[]) => mockListInfraSkillVersions(...args),
  listSkillEvalRuns: (...args: unknown[]) => mockListSkillEvalRuns(...args),
  listSkillReleases: (...args: unknown[]) => mockListSkillReleases(...args),
  syncInfraSkillVersion: vi.fn(),
  listSkillEvalCases: vi.fn().mockResolvedValue({ items: [], total: 0, suite_version: 1 }),
  createSkillEvalCase: vi.fn(),
  createSkillEvalRun: (...args: unknown[]) => mockCreateSkillEvalRun(...args),
  createSkillRelease: (...args: unknown[]) => mockCreateSkillRelease(...args),
  requestSkillReleaseApproval: (...args: unknown[]) => mockRequestSkillReleaseApproval(...args),
  approveSkillRelease: (...args: unknown[]) => mockApproveSkillRelease(...args),
  activateSkillRelease: (...args: unknown[]) => mockActivateSkillRelease(...args),
  testInfraSkillRouting: (...args: unknown[]) => mockTestInfraSkillRouting(...args),
  testInfraSkillExecution: (...args: unknown[]) => mockTestInfraSkillExecution(...args),
}))

// 意见4 方案A：工作区点击评测/发布 lifecycle 步骤会 router.push 到顶层列表页（带 skill 筛选）
const { mockRouterPush, navigationState } = vi.hoisted(() => ({
  mockRouterPush: vi.fn(),
  navigationState: { pathname: '/skills' },
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => navigationState.pathname,
  useSearchParams: () => new URLSearchParams(),
}))

function releasePage(status: 'candidate' | 'approval_pending' | 'approved' | 'active') {
  return {
    items: [{
      release_id: 'release-1',
      skill_id: 'settlement_explain_skill',
      version_id: 'version-1',
      environment: 'test',
      status,
      baseline_release_id: null,
      eval_run_id: 'run-1',
      artifact_hash: 'a'.repeat(64),
      config_hash: 'b'.repeat(64),
      rollout_percent: 0,
      runtime_mode: 'shadow',
      revision: status === 'active' ? 4 : 3,
      created_by: 'portal-user',
      created_at: '2026-08-05T06:00:00Z',
      activated_at: status === 'active' ? '2026-08-05T06:30:00Z' : null,
      retired_at: null,
      approval: status === 'approved' || status === 'active' ? {
        approved_by: 'information-admin',
        approver_role: 'information_department',
        approved_at: '2026-08-05T06:20:00Z',
      } : null,
    }],
    total: 1,
  }
}

const workbenchResponse: SkillWorkbenchResponse = {
  summary: {
    total: 1,
    healthy: 0,
    needs_evaluation: 1,
    pending_approval: 0,
    test_active: 0,
    updated_at: '2026-08-05T06:00:00Z',
  },
  items: [{
    skill_id: 'settlement_explain_skill',
    skill_name: '结算费用解释',
    business_action: 'explain',
    business_object: 'settlement',
    semantic_version: '1.0.0',
    artifact_status: 'registered',
    validation_status: 'passed',
    latest_eval_status: 'failed',
    test_release_status: null,
    test_active_version: null,
    governance_status: 'needs_evaluation',
    attention_reason: 'passed_evaluation_required',
    current_stage: 'evaluate',
    priority: 'normal',
    latest_eval_run_id: 'run-1',
    candidate_version: '1.1.0',
    baseline_version: null,
    regression_count: 0,
    required_failure_count: 0,
    linked_draft_id: null,
    linked_draft_status: null,
    waiting_since: '2026-08-05T06:00:00Z',
    next_action: 'run_evaluation',
    next_action_reason: '当前版本尚未完成评测',
  }],
  total: 1,
  page: 1,
  page_size: 50,
}

const version = {
  version_id: 'version-1',
  skill_id: 'settlement_explain_skill',
  semantic_version: '1.1.0',
  source_commit: 'short-hash',
  source_path: 'skills/settlement_explain_skill',
  artifact_hash: 'abcdef123456uvwxyz',
  manifest_snapshot: {},
  dependency_snapshot: {},
  file_count: 5,
  validation_status: 'passed',
  validation_issues: [],
  created_by: 'portal-user',
  created_at: '2026-08-05T06:00:00Z',
}

const evaluationRun = {
  run_id: 'run-1',
  skill_id: 'settlement_explain_skill',
  version_id: 'version-1',
  baseline_version_id: 'baseline-1',
  suite_version: 7,
  config_hash: 'config1234567890hash',
  routing_manifest_hash: 'routing123456789hash',
  status: 'failed',
  metrics: {
    total: 10,
    passed: 8,
    required_total: 5,
    required_passed: 4,
    top1_accuracy: 0.8,
    baseline_top1_accuracy: 0.7,
    regression_count: 3,
    new_false_takeover_count: 1,
    gate_passed: false,
  },
  results: [
    {
      case_id: 'case-new-failure',
      expected_skill_id: 'settlement_explain_skill',
      candidate_skill_id: null,
      baseline_skill_id: 'settlement_explain_skill',
      candidate_confidence: 0.2,
      baseline_confidence: 0.9,
      candidate_passed: false,
      baseline_passed: true,
      required: true,
      diff: 'new_failure',
      candidate_keywords: [],
      baseline_keywords: [],
    },
    {
      case_id: 'case-route-changed',
      expected_skill_id: 'settlement_explain_skill',
      candidate_skill_id: 'other_skill',
      baseline_skill_id: 'settlement_explain_skill',
      candidate_confidence: 0.75,
      baseline_confidence: 0.8,
      candidate_passed: false,
      baseline_passed: true,
      required: false,
      diff: 'route_changed',
      candidate_keywords: [],
      baseline_keywords: [],
    },
    {
      case_id: 'case-unchanged-fail',
      expected_skill_id: 'settlement_explain_skill',
      candidate_skill_id: null,
      baseline_skill_id: null,
      candidate_confidence: 0,
      baseline_confidence: 0,
      candidate_passed: false,
      baseline_passed: false,
      required: false,
      diff: 'unchanged_fail',
      candidate_keywords: [],
      baseline_keywords: [],
    },
    {
      case_id: 'case-new-pass',
      expected_skill_id: 'settlement_explain_skill',
      candidate_skill_id: 'settlement_explain_skill',
      baseline_skill_id: null,
      candidate_confidence: 0.95,
      baseline_confidence: 0.1,
      candidate_passed: true,
      baseline_passed: false,
      required: false,
      diff: 'new_pass',
      candidate_keywords: [],
      baseline_keywords: [],
    },
  ],
  case_snapshots: [
    {
      case_id: 'case-new-failure',
      suite_version: 7,
      question_template: '患者 P001 的审批理由是绝密内容',
      expected_skill_id: 'settlement_explain_skill',
      required: true,
      risk_tags: ['HIGH'],
      business_tags: [],
      source_type: 'feedback',
      source_ref: 'sensitive-source',
      contains_sensitive_data: true,
      enabled: true,
      created_by: 'portal-user',
      created_at: '2026-08-05T06:00:00Z',
      updated_at: '2026-08-05T06:00:00Z',
    },
  ],
  created_by: 'portal-user',
  created_at: '2026-08-05T06:10:00Z',
  completed_at: '2026-08-05T06:11:00Z',
}

const historicalVersion = {
  ...version,
  version_id: 'version-historical',
  semantic_version: '0.9.0',
  artifact_hash: 'historical-artifact-hash',
}

const passedCurrentRun = {
  ...evaluationRun,
  status: 'passed' as const,
  metrics: { ...evaluationRun.metrics, gate_passed: true, passed: 10 },
}

const historicalPassedRun = {
  ...passedCurrentRun,
  run_id: 'run-historical',
  version_id: historicalVersion.version_id,
  created_at: '2026-08-05T05:00:00Z',
  completed_at: '2026-08-05T05:01:00Z',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

describe('Skill governance workbench', () => {
  beforeEach(() => {
    ;[
      mockGetSkillGovernanceWorkbench,
      mockListInfraSkillCatalog,
      mockGetInfraSkillDetail,
      mockListInfraSkillVersions,
      mockListSkillEvalRuns,
      mockListSkillReleases,
      mockCreateSkillEvalRun,
      mockCreateSkillRelease,
      mockRequestSkillReleaseApproval,
      mockApproveSkillRelease,
      mockActivateSkillRelease,
      mockTestInfraSkillRouting,
      mockTestInfraSkillExecution,
    ].forEach((mock) => mock.mockReset())
    window.history.replaceState({}, '', '/skills')
    navigationState.pathname = '/skills'
    mockGetSkillGovernanceWorkbench.mockResolvedValue(workbenchResponse)
    mockListInfraSkillCatalog.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    mockGetInfraSkillDetail.mockResolvedValue({
      skill_id: 'settlement_explain_skill',
      skill_name: '结算费用解释',
      business_action: 'explain',
      business_object: 'settlement',
      include_keywords: [],
      excluded_intents: [],
      manifest: {},
      readme: '',
      files_structure: {},
      field_mapping: null,
    })
    mockListInfraSkillVersions.mockResolvedValue([])
    mockListSkillEvalRuns.mockResolvedValue({ items: [], total: 0 })
    mockListSkillReleases.mockResolvedValue({ items: [], total: 0 })
    mockCreateSkillEvalRun.mockResolvedValue(evaluationRun)
    mockCreateSkillRelease.mockResolvedValue(releasePage('candidate').items[0])
    mockRequestSkillReleaseApproval.mockResolvedValue(releasePage('approval_pending').items[0])
    mockApproveSkillRelease.mockResolvedValue({ status: 'approved' })
    mockActivateSkillRelease.mockResolvedValue({ status: 'active' })
    mockTestInfraSkillRouting.mockResolvedValue({ candidates: [] })
    mockTestInfraSkillExecution.mockResolvedValue({ status: 'completed' })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('uses safe defaults while the page is prerendered without window', () => {
    const browserWindow = window
    vi.stubGlobal('window', undefined)

    expect(readWorkbenchUrl()).toMatchObject({
      skillId: null,
      tab: 'overview',
      env: 'test',
      query: '',
      priority: null,
    })
    expect(readWorkbenchUrl('?priority=urgent').priority).toBeNull()
    expect(readWorkbenchUrl('?priority=blocked').priority).toBe('blocked')

    vi.stubGlobal('window', browserWindow)
  })

  it('renders one daily-governance title and the governance queue landmark', async () => {
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByRole('heading', { name: 'Skill 日常治理' })).toBeVisible()
    expect(screen.getAllByRole('heading', { name: 'Skill 日常治理' })).toHaveLength(1)
    expect(screen.getAllByRole('navigation', { name: '治理待办' })).toHaveLength(1)
    expect(screen.getAllByText('待评测')[0]).toBeVisible()
    expect(await screen.findByTestId('skill-catalog-item-settlement_explain_skill')).toBeVisible()
    expect(screen.queryByText('包含关键词')).not.toBeInTheDocument()
    expect(screen.queryByText('artifact hash')).not.toBeInTheDocument()
  })

  it('persists whitelisted priority and selected skill without sensitive detail', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    await user.selectOptions(await screen.findByLabelText('待办优先级'), 'blocked')
    await user.click(await screen.findByTestId('skill-catalog-item-settlement_explain_skill'))

    await waitFor(() => expect(window.location.search).toContain('priority=blocked'))
    expect(window.location.search).toContain('skill=settlement_explain_skill')
    expect(window.location.search).not.toMatch(/question_template|approval_reason|patient_id|evidence/i)
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenLastCalledWith(expect.objectContaining({ priority: 'blocked' }))
  })

  it('returns from mobile detail to the governance queue and restores item focus', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)
    const item = await screen.findByTestId('skill-catalog-item-settlement_explain_skill')

    await user.click(item)
    const backButton = await screen.findByRole('button', { name: '返回治理待办' })
    expect(backButton).toHaveFocus()
    let queueWasVisibleWhenFocusReturned = false
    item.addEventListener('focus', () => {
      queueWasVisibleWhenFocusReturned = !item.closest('[data-skill-queue]')?.classList.contains('hidden')
    })
    queueWasVisibleWhenFocusReturned = false
    await user.click(backButton)

    expect(screen.getByRole('navigation', { name: '治理待办' })).toBeVisible()
    await waitFor(() => expect(item).toHaveFocus())
    expect(queueWasVisibleWhenFocusReturned).toBe(true)
  })

  it('focuses queue search when the selected item disappears before mobile return', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)
    await user.click(await screen.findByTestId('skill-catalog-item-settlement_explain_skill'))
    const backButton = await screen.findByRole('button', { name: '返回治理待办' })
    mockGetSkillGovernanceWorkbench.mockResolvedValueOnce({
      ...workbenchResponse,
      items: [],
      total: 0,
    })

    await user.click(screen.getByRole('button', { name: '同步状态' }))
    await waitFor(() => expect(screen.queryByTestId('skill-catalog-item-settlement_explain_skill')).not.toBeInTheDocument())
    await user.click(backButton)

    await waitFor(() => expect(screen.getByLabelText('搜索 Skill')).toHaveFocus())
  })

  it('uses arrow keys for roving focus and Enter for explicit queue activation', async () => {
    const secondItem = {
      ...workbenchResponse.items[0],
      skill_id: 'benefit_query_skill',
      skill_name: '待遇查询',
    }
    mockGetSkillGovernanceWorkbench.mockResolvedValueOnce({
      ...workbenchResponse,
      items: [workbenchResponse.items[0], secondItem],
      total: 2,
    })
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)
    const first = await screen.findByTestId('skill-catalog-item-settlement_explain_skill')
    const second = screen.getByTestId('skill-catalog-item-benefit_query_skill')

    first.focus()
    await user.keyboard('{ArrowDown}')

    expect(second).toHaveFocus()
    expect(first).toHaveAttribute('aria-current', 'true')
    expect(second).not.toHaveAttribute('aria-current')
    expect(screen.queryByRole('button', { name: '返回治理待办' })).not.toBeInTheDocument()

    await user.keyboard('{ArrowUp}')
    expect(first).toHaveFocus()
    expect(screen.queryByRole('button', { name: '返回治理待办' })).not.toBeInTheDocument()
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('button', { name: '返回治理待办' })).toHaveFocus()
  })

  it('marks governance and asset routes as separate active tabs', () => {
    const { rerender } = render(<SkillsLayout><p>content</p></SkillsLayout>)

    expect(screen.getByRole('button', { name: '治理待办' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Skill 资产' })).not.toHaveAttribute('aria-current')

    navigationState.pathname = '/skills/assets'
    rerender(<SkillsLayout><p>content</p></SkillsLayout>)

    expect(screen.getByRole('button', { name: 'Skill 资产' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: '治理待办' })).not.toHaveAttribute('aria-current')
  })

  it('loads the formal asset list without governance write actions', async () => {
    mockListInfraSkillCatalog.mockResolvedValueOnce({
      items: [{
        skill_id: 'settlement_explain_skill',
        skill_name: '结算费用解释',
        business_action: 'explain',
        business_object: 'settlement',
        include_keywords: [],
        excluded_intents: [],
        semantic_version: '1.0.0',
        artifact_hash: 'a'.repeat(64),
        artifact_status: 'registered',
        file_count: 1,
        registered_version: null,
      }],
      total: 1,
      page: 1,
      page_size: 50,
    })
    const assetPagePath = '../../app/skills/assets/page'
    const { default: SkillAssetsPage } = await import(/* @vite-ignore */ assetPagePath)

    render(<SkillAssetsPage />)

    expect(await screen.findByRole('heading', { name: 'Skill 资产', level: 2 })).toBeVisible()
    expect(screen.getByRole('link', { name: /结算费用解释/ })).toHaveAttribute(
      'href',
      '/skills/settlement_explain_skill',
    )
    expect(screen.queryByRole('button', { name: /发布|审批|激活/ })).not.toBeInTheDocument()
  })

  it('loads additional asset pages without duplicating assets', async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => ({
      skill_id: `skill-${index + 1}`,
      skill_name: `Skill ${index + 1}`,
      business_action: 'explain',
      business_object: 'settlement',
      include_keywords: [],
      excluded_intents: [],
      semantic_version: '1.0.0',
      artifact_hash: 'a'.repeat(64),
      artifact_status: 'registered' as const,
      file_count: 1,
      registered_version: null,
    }))
    let resolveNextPage!: (value: InfraSkillCatalogResponse) => void
    const nextPage = new Promise<InfraSkillCatalogResponse>((resolve) => { resolveNextPage = resolve })
    mockListInfraSkillCatalog
      .mockResolvedValueOnce({ items: firstPage, total: 51, page: 1, page_size: 50 })
      .mockReturnValueOnce(nextPage)
    const assetPagePath = '../../app/skills/assets/page'
    const { default: SkillAssetsPage } = await import(/* @vite-ignore */ assetPagePath)
    const user = userEvent.setup()
    render(<SkillAssetsPage />)
    const loadMore = await screen.findByRole('button', { name: '加载更多' })

    await user.click(loadMore)
    expect(loadMore).toHaveAttribute('aria-disabled', 'true')
    expect(loadMore).toHaveTextContent('正在加载…')
    resolveNextPage({
      items: [firstPage[0], { ...firstPage[0], skill_id: 'skill-51', skill_name: 'Skill 51' }],
      total: 51,
      page: 2,
      page_size: 50,
    })

    expect(await screen.findByRole('link', { name: /Skill 51/ })).toBeVisible()
    expect(screen.getAllByRole('link').filter((link) => link.getAttribute('href') === '/skills/skill-1')).toHaveLength(1)
    const completed = screen.getByRole('button', { name: '已加载全部 Skill 资产' })
    expect(completed).toBe(loadMore)
    expect(completed).toHaveFocus()
    await user.click(completed)
    expect(mockListInfraSkillCatalog).toHaveBeenCalledTimes(2)
  })

  it('shows an asset request error without also showing the empty state', async () => {
    mockListInfraSkillCatalog.mockRejectedValueOnce(new Error('ASSET_LIST_FAILED'))
    const assetPagePath = '../../app/skills/assets/page'
    const { default: SkillAssetsPage } = await import(/* @vite-ignore */ assetPagePath)

    render(<SkillAssetsPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('ASSET_LIST_FAILED')
    expect(screen.queryByText('暂无 Skill 资产')).not.toBeInTheDocument()
    expect(screen.queryByText('正在加载 Skill 资产…')).not.toBeInTheDocument()
  })

  it('distinguishes filtered no-results and clears every queue filter coherently', async () => {
    window.history.replaceState({}, '', '/skills?q=missing&priority=blocked&status=needs_evaluation&action=explain&object=settlement')
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [],
      total: 0,
    })
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('没有符合筛选条件的 Skill')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '清除筛选' }))

    await waitFor(() => expect(window.location.search).not.toMatch(/q=|priority=|status=|action=|object=/))
    expect(screen.getByLabelText('待办优先级')).toHaveValue('')
    expect(screen.getByLabelText('搜索 Skill')).toHaveValue('')
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenLastCalledWith({ page: 1, page_size: 50 })
    expect(await screen.findByText('当前没有需要处理的 Skill')).toBeVisible()
    expect(screen.getByRole('link', { name: '查看全部资产' })).toHaveAttribute('href', '/skills/assets')
  })

  it('formats queue wait time at deterministic boundaries', () => {
    const waitingLabel = (workbenchModule as unknown as {
      waitingLabel: (waitingSince: string, now?: number) => string
    }).waitingLabel
    const now = Date.parse('2026-08-11T12:00:00Z')

    expect(waitingLabel('invalid', now)).toBe('刚刚进入待办')
    expect(waitingLabel('2026-08-11T11:00:01Z', now)).toBe('刚刚进入待办')
    expect(waitingLabel('2026-08-11T11:00:00Z', now)).toBe('等待 1 小时')
    expect(waitingLabel('2026-08-10T12:00:01Z', now)).toBe('等待 23 小时')
    expect(waitingLabel('2026-08-10T12:00:00Z', now)).toBe('等待 1 天')
    expect(waitingLabel('2026-08-09T12:00:00Z', now)).toBe('等待 2 天')
  })

  it('restores selected skill and tab from the URL', async () => {
    // 意见4 方案A：评测/发布 tab 已上移顶层页，工作区只剩 总览/版本/开发详情
    window.history.replaceState({}, '', '/skills?skill=settlement_explain_skill&tab=versions')

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByTestId('skill-workspace-settlement_explain_skill')).toBeVisible()
    expect(screen.getByRole('tab', { name: '版本' })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps the catalog visible when the selected detail fails', async () => {
    mockGetInfraSkillDetail.mockRejectedValueOnce(new Error('SKILL_DETAIL_FAILED'))

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByTestId('skill-catalog-item-settlement_explain_skill')).toBeVisible()
    expect(await screen.findByText('SKILL_DETAIL_FAILED')).toBeVisible()
  })

  it('shows server-backed lifecycle steps and three tabs', async () => {
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('评测')).toBeVisible()
    expect(screen.getByText('定位问题')).toBeVisible()
    expect(screen.getByText('修改')).toBeVisible()
    expect(screen.getByText('复审')).toBeVisible()
    expect(screen.getByText('发布')).toBeVisible()
    // 意见4 方案A：评测/发布 tab 上移顶层列表页，工作区只剩 总览/版本/开发详情
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      '总览',
      '版本',
      '开发详情',
    ])
    expect(screen.getByTestId('skill-workspace-tabs')).toHaveClass('flex-col')
  })

  it('navigates a blocked step to its top-level page', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    await user.click(await screen.findByRole('button', { name: /^评测/ }))

    // 意见4 方案A：评测 tab 已上移，lifecycle 评测步骤改为 router.push 到顶层评测页（带 skill 筛选）
    expect(mockRouterPush).toHaveBeenCalledWith(
      expect.stringMatching(/\/skills\/evaluations\?skill=settlement_explain_skill/),
    )
  })

  it('navigates to the release review surface without approving immediately', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        current_stage: 'review',
        priority: 'high',
        next_action: 'review_approval',
      }],
    })
    mockListSkillReleases.mockResolvedValue(releasePage('approval_pending'))
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('进入人工复审')).toBeVisible()
    await userEvent.click(screen.getByTestId('skill-primary-action'))

    expect(mockRouterPush).toHaveBeenCalledWith(
      expect.stringMatching(/\/skills\/releases\?skill=settlement_explain_skill/),
    )
    expect(mockApproveSkillRelease).not.toHaveBeenCalled()
  })

  it('shows the fixed evaluation metrics and regression comparison surface', async () => {
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [evaluationRun], total: 1 })

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('候选通过率')).toBeVisible()
    expect(screen.getByText('活动基线通过率')).toBeVisible()
    expect(screen.getByText('新增回归')).toBeVisible()
    expect(screen.getByText('必测通过数')).toBeVisible()
    expect(screen.getByRole('table', { name: '评测差异案例' })).toBeVisible()
  })

  it('binds current metrics, cases, and frozen evidence to the canonical evaluation run', async () => {
    const staleVersion = {
      ...version,
      version_id: 'version-stale',
      semantic_version: '0.9.0',
      artifact_hash: 'staleartifact123456hash',
      source_commit: 'stale-source-commit',
    }
    const staleRun = {
      ...evaluationRun,
      run_id: 'run-stale',
      version_id: staleVersion.version_id,
      status: 'passed' as const,
      metrics: {
        ...evaluationRun.metrics,
        passed: 10,
        regression_count: 0,
        gate_passed: true,
      },
      results: [{
        ...evaluationRun.results[0],
        case_id: 'case-stale',
        diff: 'new_failure' as const,
      }],
      case_snapshots: [],
      created_at: '2026-08-05T07:10:00Z',
      completed_at: '2026-08-05T07:11:00Z',
    }
    const currentRelease = releasePage('approved').items[0]
    const staleRelease = {
      ...currentRelease,
      release_id: 'release-stale',
      version_id: staleVersion.version_id,
      eval_run_id: staleRun.run_id,
      created_by: 'stale-release-operator',
      created_at: '2026-08-05T07:20:00Z',
    }
    mockListInfraSkillVersions.mockResolvedValue([staleVersion, version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [staleRun, evaluationRun], total: 2 })
    mockListSkillReleases.mockResolvedValue({ items: [staleRelease, currentRelease], total: 2 })

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('80%')).toBeVisible()
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
    expect(screen.getByText('case-new-failure')).toBeVisible()
    expect(screen.queryByText('case-stale')).not.toBeInTheDocument()
    const evidence = screen.getByRole('complementary', { name: '治理证据' })
    expect(evidence).toHaveTextContent('run-1')
    expect(evidence).toHaveTextContent('abcdef…uvwxyz')
    expect(evidence).not.toHaveTextContent('stale-release-operator')
  })

  it('shows evaluation loading before the evidence batch settles', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: null,
        latest_eval_status: null,
        candidate_version: null,
      }],
    })
    const pendingEvaluations = deferred<{ items: Array<typeof evaluationRun>; total: number }>()
    mockListSkillEvalRuns.mockReturnValue(pendingEvaluations.promise)

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByRole('status', { name: '正在加载评测证据' })).toBeVisible()
    expect(screen.getByRole('complementary', { name: '治理证据' })).toHaveTextContent('正在加载当前门禁证据')
    expect(screen.queryByText('当前视图没有差异案例')).not.toBeInTheDocument()

    await act(async () => pendingEvaluations.resolve({ items: [], total: 0 }))
    expect(await screen.findByText('当前视图没有差异案例')).toBeVisible()
    expect(screen.queryByRole('status', { name: '正在加载评测证据' })).not.toBeInTheDocument()
    const evidence = screen.getByRole('complementary', { name: '治理证据' })
    expect(evidence).toHaveTextContent('尚无评测结论')
    expect(evidence).not.toHaveTextContent('当前门禁证据不可用')
  })

  it('shows ready-empty for an unevaluated current version even when historical runs exist', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: null,
        latest_eval_status: null,
        candidate_version: version.semantic_version,
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([historicalVersion, version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [historicalPassedRun], total: 1 })

    render(<SkillGovernanceWorkbench />)

    const evidence = await screen.findByRole('complementary', { name: '治理证据' })
    await waitFor(() => expect(evidence).toHaveTextContent('尚无评测结论'))
    expect(evidence).toHaveTextContent(shortHash(historicalPassedRun.run_id))
    expect(evidence).not.toHaveTextContent('当前门禁证据不可用')
    expect(screen.getByText('当前视图没有差异案例')).toBeVisible()
  })

  it('shows evaluation evidence as unavailable after its request fails', async () => {
    mockListSkillEvalRuns.mockRejectedValue(new Error('evaluation unavailable'))

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('评测证据不可用，请刷新重试')).toBeVisible()
    expect(screen.queryByText('当前视图没有差异案例')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('evaluation unavailable')
    expect(screen.getByRole('complementary', { name: '治理证据' })).toHaveTextContent('当前门禁证据不可用')
  })

  it('keeps the queue and loaded evaluation evidence when releases fail', async () => {
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [evaluationRun], total: 1 })
    mockListSkillReleases.mockRejectedValue(new Error('release unavailable'))

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByTestId('skill-catalog-item-settlement_explain_skill')).toBeVisible()
    expect(await screen.findByText('80%')).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('release unavailable')
    expect(screen.getByRole('alert')).toHaveTextContent('刷新')
  })

  it('renders the service reason with one primary control and a read-only evidence control', async () => {
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [evaluationRun], total: 1 })

    render(<SkillGovernanceWorkbench />)

    expect((await screen.findAllByText('当前版本尚未完成评测'))[0]).toBeVisible()
    expect(screen.getAllByTestId('skill-primary-action')).toHaveLength(1)
    const evidence = screen.getByRole('button', { name: '查看治理证据' })
    expect(evidence).not.toHaveAttribute('data-testid', 'skill-primary-action')
    await userEvent.click(evidence)
    expect(screen.getByRole('dialog', { name: '治理证据' })).toBeVisible()
  })

  it('runs evaluation against the canonical candidate version rather than array order', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: null,
        latest_eval_status: null,
        candidate_version: version.semantic_version,
        next_action: 'run_evaluation',
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([historicalVersion, version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [historicalPassedRun], total: 1 })

    render(<SkillGovernanceWorkbench />)
    await userEvent.click(await screen.findByTestId('skill-primary-action'))

    await waitFor(() => expect(mockCreateSkillEvalRun).toHaveBeenCalledWith(
      'settlement_explain_skill',
      { version_id: version.version_id },
    ))
  })

  it('creates a candidate from the canonical current run rather than historical passed runs', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: passedCurrentRun.run_id,
        latest_eval_status: 'passed',
        candidate_version: version.semantic_version,
        next_action: 'create_candidate',
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([historicalVersion, version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [historicalPassedRun, passedCurrentRun], total: 2 })

    render(<SkillGovernanceWorkbench />)
    await userEvent.click(await screen.findByTestId('skill-primary-action'))

    await waitFor(() => expect(mockCreateSkillRelease).toHaveBeenCalledWith(
      'settlement_explain_skill',
      {
        version_id: version.version_id,
        eval_run_id: passedCurrentRun.run_id,
        environment: 'test',
      },
      expect.stringContaining('settlement_explain_skill:create_candidate:'),
    ))
  })

  it('requests approval for the current candidate relationship rather than the first release', async () => {
    const currentRelease = releasePage('candidate').items[0]
    const historicalRelease = {
      ...currentRelease,
      release_id: 'release-historical',
      version_id: historicalVersion.version_id,
      eval_run_id: historicalPassedRun.run_id,
      revision: 9,
    }
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: passedCurrentRun.run_id,
        latest_eval_status: 'passed',
        candidate_version: version.semantic_version,
        next_action: 'request_approval',
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([historicalVersion, version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [historicalPassedRun, passedCurrentRun], total: 2 })
    mockListSkillReleases.mockResolvedValue({ items: [historicalRelease, currentRelease], total: 2 })

    render(<SkillGovernanceWorkbench />)
    await userEvent.click(await screen.findByTestId('skill-primary-action'))

    await waitFor(() => expect(mockRequestSkillReleaseApproval).toHaveBeenCalledWith(
      'settlement_explain_skill',
      currentRelease.release_id,
      { expected_revision: currentRelease.revision },
      expect.stringContaining('settlement_explain_skill:request_approval:'),
    ))
  })

  it('activates the approved release bound to the current run rather than the first release', async () => {
    const currentRelease = releasePage('approved').items[0]
    const historicalRelease = {
      ...currentRelease,
      release_id: 'release-historical',
      version_id: historicalVersion.version_id,
      eval_run_id: historicalPassedRun.run_id,
      revision: 9,
    }
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: passedCurrentRun.run_id,
        latest_eval_status: 'passed',
        candidate_version: version.semantic_version,
        next_action: 'activate_test_shadow',
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([historicalVersion, version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [historicalPassedRun, passedCurrentRun], total: 2 })
    mockListSkillReleases.mockResolvedValue({ items: [historicalRelease, currentRelease], total: 2 })

    render(<SkillGovernanceWorkbench />)
    await userEvent.click(await screen.findByTestId('skill-primary-action'))

    await waitFor(() => expect(mockActivateSkillRelease).toHaveBeenCalledWith(
      'settlement_explain_skill',
      currentRelease.release_id,
      { expected_revision: currentRelease.revision },
      expect.stringContaining('settlement_explain_skill:activate:'),
    ))
  })

  it.each([
    ['run_evaluation', '2.0.0', null, '当前候选版本证据不一致，请刷新后重试'],
    ['create_candidate', version.semantic_version, 'missing-run', '当前评测证据不一致，请刷新或重新评测'],
    ['request_approval', version.semantic_version, passedCurrentRun.run_id, '当前候选发布证据不一致，请刷新后重试'],
    ['activate_test_shadow', version.semantic_version, passedCurrentRun.run_id, '当前已审批发布证据不一致，请刷新后重试'],
  ] as const)('fails closed when %s lacks a canonical write target', async (nextAction, candidateVersion, runId, error) => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_run_id: runId,
        latest_eval_status: runId ? 'passed' : null,
        candidate_version: candidateVersion,
        next_action: nextAction,
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [passedCurrentRun], total: 1 })
    mockListSkillReleases.mockResolvedValue({ items: [releasePage(nextAction === 'activate_test_shadow' ? 'candidate' : 'approved').items[0]], total: 1 })

    render(<SkillGovernanceWorkbench />)
    await userEvent.click(await screen.findByTestId('skill-primary-action'))

    expect(await screen.findByText(error)).toBeVisible()
    expect(mockCreateSkillEvalRun).not.toHaveBeenCalled()
    expect(mockCreateSkillRelease).not.toHaveBeenCalled()
    expect(mockRequestSkillReleaseApproval).not.toHaveBeenCalled()
    expect(mockActivateSkillRelease).not.toHaveBeenCalled()
  })

  it('maps the five governance stages and fails closed for an unknown stage', () => {
    expect(lifecycleSteps({ ...workbenchResponse.items[0], current_stage: 'diagnose' }).map((step) => [step.label, step.state])).toEqual([
      ['评测', 'completed'],
      ['定位问题', 'current'],
      ['修改', 'pending'],
      ['复审', 'pending'],
      ['发布', 'pending'],
    ])
    expect(lifecycleSteps({ ...workbenchResponse.items[0], current_stage: 'healthy' }).map((step) => step.state)).toEqual([
      'completed', 'completed', 'completed', 'completed', 'completed',
    ])
    expect(lifecycleSteps({
      ...workbenchResponse.items[0],
      current_stage: 'unexpected',
    } as unknown as SkillWorkbenchResponse['items'][number]).map((step) => step.state)).toEqual([
      'pending', 'pending', 'pending', 'pending', 'pending',
    ])
  })

  it('renders an accessible ordered lifecycle with visible state text', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{ ...workbenchResponse.items[0], current_stage: 'healthy', governance_status: 'healthy' }],
    })
    render(<SkillGovernanceWorkbench />)

    const lifecycle = await screen.findByRole('list', { name: 'Skill 治理阶段' })
    expect(lifecycle).toHaveTextContent('评测')
    expect(lifecycle).toHaveTextContent('定位问题')
    expect(lifecycle).toHaveTextContent('修改')
    expect(lifecycle).toHaveTextContent('复审')
    expect(lifecycle).toHaveTextContent('发布')
    expect(lifecycle).toHaveTextContent('已完成')
  })

  it('shows no active baseline instead of inventing zero percent', async () => {
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({
      items: [{ ...evaluationRun, baseline_version_id: null }],
      total: 1,
    })
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('无活动基线')).toBeVisible()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('filters regression cases and exposes only shortened, non-sensitive evidence', async () => {
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [evaluationRun], total: 1 })
    const releaseWithPrivateReason = {
      ...releasePage('approved').items[0],
      approval_reason: '包含患者 P002 的审批理由',
    }
    mockListSkillReleases.mockResolvedValue({ items: [releaseWithPrivateReason], total: 1 })
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('case-new-failure')).toBeVisible()
    expect(screen.getByText('case-route-changed')).toBeVisible()
    expect(screen.getByText('case-unchanged-fail')).toBeVisible()
    expect(screen.queryByText('case-new-pass')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '改善' }))
    expect(screen.getByText('case-new-pass')).toBeVisible()
    expect(screen.queryByText('case-new-failure')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '全部' }))
    expect(screen.getByText('case-new-failure')).toBeVisible()
    expect(screen.getByText('case-new-pass')).toBeVisible()
    expect(screen.getAllByText('失败码不可用')[0]).toBeVisible()
    expect(screen.getByText('abcdef…uvwxyz')).toBeVisible()
    expect(screen.getByText('short-hash')).toBeVisible()
    expect(screen.queryByText(version.artifact_hash)).not.toBeInTheDocument()
    expect(screen.queryByText(evaluationRun.config_hash)).not.toBeInTheDocument()
    expect(screen.queryByText(/P001|P002|绝密内容|审批理由/)).not.toBeInTheDocument()
  })

  it('uses the truthful global governance evidence action without case-specific claims', async () => {
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [evaluationRun], total: 1 })
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    const table = await screen.findByRole('table', { name: '评测差异案例' })
    expect(within(table).queryByRole('button', { name: '查看脱敏证据' })).not.toBeInTheDocument()
    expect(within(table).queryByRole('button', { name: '查看治理证据' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '查看治理证据' }))

    const dialog = screen.getByRole('dialog', { name: '治理证据' })
    expect(dialog).toHaveTextContent('当前 Skill 的门禁与冻结记录')
    expect(dialog).not.toHaveTextContent('案例 case-new-failure')
    expect(screen.queryByRole('button', { name: '查看脱敏证据' })).not.toBeInTheDocument()
  })

  it('keeps inline evidence at 2xl and lets the outer decision region own scrolling', async () => {
    render(<SkillGovernanceWorkbench />)

    const evidence = await screen.findByRole('complementary', { name: '治理证据' })
    expect(evidence).toHaveClass('hidden', '2xl:block')
    expect(evidence).not.toHaveClass('xl:block', 'min-[1120px]:block')
    const decisionRegion = screen.getByRole('region', { name: '治理决策区' })
    expect(decisionRegion).not.toHaveClass('overflow-y-auto')
    expect(decisionRegion.parentElement?.parentElement).toHaveClass('overflow-clip')
    expect(decisionRegion.parentElement?.parentElement).not.toHaveClass('overflow-hidden')
    expect(screen.getByLabelText('下一步治理动作')).toHaveClass('sticky', 'bottom-0')
  })

  it('offers an immediate drawer-header close action and restores evidence-trigger focus', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)
    const trigger = await screen.findByRole('button', { name: '查看治理证据' })

    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: '治理证据' })
    const header = dialog.querySelector('[data-slot="dialog-header"]')
    expect(header).not.toBeNull()
    const close = within(header as HTMLElement).getByRole('button', { name: '关闭治理证据' })
    expect(close).toBeVisible()

    await user.click(close)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '治理证据' })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('keeps evidence accessible and unavailable actions neutral', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        next_action: 'view_evidence',
        next_action_reason: '治理证据暂不可用',
        test_release_status: null,
      }],
    })
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByRole('complementary', { name: '治理证据' })).toBeInTheDocument()
    const nextAction = screen.getByLabelText('下一步治理动作')
    expect(nextAction).toHaveAttribute('data-status', 'unavailable')
    expect(nextAction).not.toHaveClass('bg-emerald-50')
    expect(screen.queryByTestId('skill-primary-action')).not.toBeInTheDocument()
  })

  it('fails closed when a passed run is stale for the current queue facts', async () => {
    const reason = '当前制品已变化，需要重新登记'
    mockGetSkillGovernanceWorkbench.mockResolvedValue({
      ...workbenchResponse,
      items: [{
        ...workbenchResponse.items[0],
        artifact_status: 'changed',
        latest_eval_status: 'passed',
        latest_eval_run_id: 'new-run',
        candidate_version: '1.2.0',
        next_action: 'register_version',
        next_action_reason: reason,
      }],
    })
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({
      items: [{
        ...evaluationRun,
        status: 'passed',
        metrics: { ...evaluationRun.metrics, gate_passed: true },
      }],
      total: 1,
    })

    render(<SkillGovernanceWorkbench />)

    const evidence = await screen.findByRole('complementary', { name: '治理证据' })
    expect(within(evidence).queryByText('固定评测门禁通过')).not.toBeInTheDocument()
    expect(evidence).toHaveTextContent('当前门禁证据不可用')
    expect(evidence).toHaveTextContent(reason)
    expect(evidence).toHaveTextContent('run-1')
  })

  it('shortens hashes only above the twelve-character boundary', () => {
    expect(shortHash(null)).toBe('—')
    expect(shortHash(undefined)).toBe('—')
    expect(shortHash('')).toBe('')
    expect(shortHash('123456789012')).toBe('123456789012')
    expect(shortHash('1234567890123')).toBe('123456…890123')
  })

  it('keeps catalog fallback read-only when governance aggregation fails', async () => {
    mockGetSkillGovernanceWorkbench.mockRejectedValueOnce(new Error('WORKBENCH_UNAVAILABLE'))
    mockListInfraSkillCatalog.mockResolvedValueOnce({
      items: [{
        skill_id: 'settlement_explain_skill',
        skill_name: '结算费用解释',
        business_action: 'explain',
        business_object: 'settlement',
        include_keywords: [],
        excluded_intents: [],
        semantic_version: '1.0.0',
        artifact_hash: 'a'.repeat(64),
        artifact_status: 'registered',
        file_count: 1,
        registered_version: null,
      }],
      total: 1,
      page: 1,
      page_size: 50,
    })

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByText('治理状态暂不可用')).toBeVisible()
    expect(screen.getAllByText('治理聚合暂不可用，仅展示资产信息')[0]).toBeVisible()
    expect(screen.queryByText('Test Shadow 已激活')).not.toBeInTheDocument()
    expect(screen.queryByTestId('skill-primary-action')).not.toBeInTheDocument()
  })

  it('suspends but preserves governance priority while catalog fallback is active', async () => {
    window.history.replaceState({}, '', '/skills?priority=blocked')
    mockGetSkillGovernanceWorkbench.mockRejectedValueOnce(new Error('WORKBENCH_UNAVAILABLE'))
    mockListInfraSkillCatalog.mockResolvedValue({
      items: [{
        skill_id: 'settlement_explain_skill',
        skill_name: '结算费用解释',
        business_action: 'explain',
        business_object: 'settlement',
        include_keywords: [],
        excluded_intents: [],
        semantic_version: '1.0.0',
        artifact_hash: 'a'.repeat(64),
        artifact_status: 'registered',
        file_count: 1,
        registered_version: null,
      }],
      total: 1,
      page: 1,
      page_size: 50,
    })

    render(<SkillGovernanceWorkbench />)

    await waitFor(() => expect(screen.getByLabelText('待办优先级')).toBeDisabled())
    expect(screen.getByLabelText('待办优先级')).toHaveValue('blocked')
    expect(window.location.search).toContain('priority=blocked')
    expect(screen.getByText('目录降级未应用治理优先级')).toBeVisible()
    expect(screen.getAllByText('治理聚合暂不可用，仅展示资产信息')[0]).toBeVisible()
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(1)
    expect(mockListInfraSkillCatalog).toHaveBeenCalledTimes(1)

    mockGetSkillGovernanceWorkbench.mockResolvedValueOnce(workbenchResponse)
    await userEvent.click(screen.getByRole('button', { name: '同步状态' }))

    await waitFor(() => expect(screen.getByLabelText('待办优先级')).toBeEnabled())
    expect(screen.queryByText('目录降级未应用治理优先级')).not.toBeInTheDocument()
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(2)
    expect(mockListInfraSkillCatalog).toHaveBeenCalledTimes(1)
  })

  it('keeps priority selected when governance and catalog fallback both fail', async () => {
    window.history.replaceState({}, '', '/skills?priority=blocked')
    mockGetSkillGovernanceWorkbench.mockRejectedValueOnce(new Error('WORKBENCH_UNAVAILABLE'))
    mockListInfraSkillCatalog.mockRejectedValueOnce(new Error('CATALOG_UNAVAILABLE'))

    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByRole('alert')).toHaveTextContent('WORKBENCH_UNAVAILABLE')
    expect(screen.getByLabelText('待办优先级')).toHaveValue('blocked')
    expect(screen.getByLabelText('待办优先级')).toBeEnabled()
    expect(window.location.search).toContain('priority=blocked')
    expect(screen.queryByText('目录降级未应用治理优先级')).not.toBeInTheDocument()
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(1)
    expect(mockListInfraSkillCatalog).toHaveBeenCalledTimes(1)
  })

  it('refreshes catalog and lifecycle after activation', async () => {
    let releaseStatus: 'approved' | 'active' = 'approved'
    mockListInfraSkillVersions.mockResolvedValue([version])
    mockListSkillEvalRuns.mockResolvedValue({ items: [passedCurrentRun], total: 1 })
    mockListSkillReleases.mockImplementation(async () => releasePage(releaseStatus))
    mockGetSkillGovernanceWorkbench.mockImplementation(async () => ({
      ...workbenchResponse,
      summary: { ...workbenchResponse.summary, test_active: releaseStatus === 'active' ? 1 : 0 },
      items: [{
        ...workbenchResponse.items[0],
        latest_eval_status: 'passed',
        test_release_status: releaseStatus === 'active' ? 'active' : null,
        next_action: releaseStatus === 'active' ? 'view_evidence' : 'activate_test_shadow',
      }],
    }))
    mockActivateSkillRelease.mockImplementation(async () => {
      releaseStatus = 'active'
      return releasePage('active').items[0]
    })
    render(<SkillGovernanceWorkbench />)

    // 直接点顶层主动作按钮，无需进入发布 Tab
    await userEvent.click(await screen.findByRole('button', { name: '激活 Test Shadow' }))

    await waitFor(() => expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(2))
    expect((await screen.findAllByText('Test Active'))[0]).toBeVisible()
  })

  it('keeps selected skill and tab after closing route diagnostics', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    await user.click(await screen.findByRole('button', { name: '路由调试' }))
    expect(screen.getByRole('dialog', { name: '路由调试' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '关闭路由调试' }))

    expect(screen.getByTestId('skill-workspace-settlement_explain_skill')).toBeVisible()
    expect(window.location.search).toContain('skill=settlement_explain_skill')
  })

  it('does not persist diagnostic questions in the URL', async () => {
    const user = userEvent.setup()
    render(<SkillGovernanceWorkbench />)

    await user.click(await screen.findByRole('button', { name: '路由调试' }))
    await user.type(screen.getByLabelText('路由问题'), '统筹自付为什么这么多')

    expect(window.location.href).not.toContain(encodeURIComponent('统筹自付为什么这么多'))
  })
})
