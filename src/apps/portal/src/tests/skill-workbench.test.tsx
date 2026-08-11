import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillGovernanceWorkbench, { readWorkbenchUrl } from '@/components/skills/skill-governance-workbench'
import type { SkillWorkbenchResponse } from '@/lib/types'

const mockGetSkillGovernanceWorkbench = vi.fn()
const mockListInfraSkillCatalog = vi.fn()
const mockGetInfraSkillDetail = vi.fn()
const mockListInfraSkillVersions = vi.fn()
const mockListSkillEvalRuns = vi.fn()
const mockListSkillReleases = vi.fn()
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
  createSkillEvalRun: vi.fn(),
  createSkillRelease: vi.fn(),
  requestSkillReleaseApproval: vi.fn(),
  approveSkillRelease: (...args: unknown[]) => mockApproveSkillRelease(...args),
  activateSkillRelease: (...args: unknown[]) => mockActivateSkillRelease(...args),
  testInfraSkillRouting: (...args: unknown[]) => mockTestInfraSkillRouting(...args),
  testInfraSkillExecution: (...args: unknown[]) => mockTestInfraSkillExecution(...args),
}))

// 意见4 方案A：工作区点击评测/发布 lifecycle 步骤会 router.push 到顶层列表页（带 skill 筛选）
const { mockRouterPush } = vi.hoisted(() => ({ mockRouterPush: vi.fn() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockRouterPush, replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

function releasePage(status: 'approval_pending' | 'approved' | 'active') {
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
      approval: status === 'approval_pending' ? null : {
        approved_by: 'information-admin',
        approver_role: 'information_department',
        approved_at: '2026-08-05T06:20:00Z',
      },
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
    latest_eval_status: null,
    test_release_status: null,
    test_active_version: null,
    governance_status: 'needs_evaluation',
    attention_reason: 'passed_evaluation_required',
    current_stage: 'evaluate',
    priority: 'normal',
    latest_eval_run_id: null,
    candidate_version: null,
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

describe('Skill governance workbench', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/skills')
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
    })

    vi.stubGlobal('window', browserWindow)
  })

  it('renders one title, actionable summary and compact catalog', async () => {
    render(<SkillGovernanceWorkbench />)

    expect(await screen.findByRole('heading', { name: 'Skill 管理' })).toBeVisible()
    expect(screen.getAllByRole('heading', { name: 'Skill 管理' })).toHaveLength(1)
    expect(screen.getByText('待评测')).toBeVisible()
    expect(await screen.findByTestId('skill-catalog-item-settlement_explain_skill')).toBeVisible()
    expect(screen.queryByText('包含关键词')).not.toBeInTheDocument()
    expect(screen.queryByText('artifact hash')).not.toBeInTheDocument()
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

    expect(await screen.findByText('版本登记')).toBeVisible()
    expect(screen.getByText('批量评测')).toBeVisible()
    expect(screen.getByText('人工审批')).toBeVisible()
    expect(screen.getByText('Test 激活')).toBeVisible()
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

    await user.click(await screen.findByRole('button', { name: /批量评测/ }))

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
    expect(screen.getByText('治理聚合暂不可用，仅展示资产信息')).toBeVisible()
    expect(screen.queryByText('Test Shadow 已激活')).not.toBeInTheDocument()
    expect(screen.queryByTestId('skill-primary-action')).not.toBeInTheDocument()
  })

  it('refreshes catalog and lifecycle after activation', async () => {
    let releaseStatus: 'approved' | 'active' = 'approved'
    mockListSkillReleases.mockImplementation(async () => releasePage(releaseStatus))
    mockGetSkillGovernanceWorkbench.mockImplementation(async () => ({
      ...workbenchResponse,
      summary: { ...workbenchResponse.summary, test_active: releaseStatus === 'active' ? 1 : 0 },
      items: [{
        ...workbenchResponse.items[0],
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
    expect((await screen.findAllByText('Test Shadow 已激活'))[0]).toBeVisible()
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
