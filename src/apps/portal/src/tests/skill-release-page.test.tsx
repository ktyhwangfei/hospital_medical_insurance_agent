import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillReleasesPage from '../../app/skills/releases/page'
import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchResponse,
} from '@/lib/types'

const mocks = vi.hoisted(() => ({
  activate: vi.fn(),
  approve: vi.fn(),
  create: vi.fn(),
  getWorkbench: vi.fn(),
  listRuns: vi.fn(),
  listReleases: vi.fn(),
  listVersions: vi.fn(),
  requestApproval: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('skill=settlement_explain_skill'),
}))

vi.mock('@/lib/api-client', () => ({
  activateSkillRelease: (...args: unknown[]) => mocks.activate(...args),
  approveSkillRelease: (...args: unknown[]) => mocks.approve(...args),
  createSkillRelease: (...args: unknown[]) => mocks.create(...args),
  getSkillGovernanceWorkbench: (...args: unknown[]) => mocks.getWorkbench(...args),
  listInfraSkillVersions: (...args: unknown[]) => mocks.listVersions(...args),
  listSkillEvalRuns: (...args: unknown[]) => mocks.listRuns(...args),
  listSkillReleases: (...args: unknown[]) => mocks.listReleases(...args),
  requestSkillReleaseApproval: (...args: unknown[]) => mocks.requestApproval(...args),
}))

const currentVersion: SkillVersionResponse = {
  version_id: 'version-current',
  skill_id: 'settlement_explain_skill',
  semantic_version: '2.0.0',
  source_commit: 'abc123',
  source_path: 'settlement_explain_skill',
  artifact_hash: 'a'.repeat(64),
  manifest_snapshot: {},
  dependency_snapshot: {},
  file_count: 1,
  validation_status: 'passed',
  validation_issues: [],
  created_by: 'portal-developer',
  created_at: '2026-08-11T06:00:00Z',
}

const currentRun: SkillEvalRunResponse = {
  run_id: 'run-current',
  skill_id: 'settlement_explain_skill',
  version_id: currentVersion.version_id,
  baseline_version_id: null,
  suite_version: 1,
  config_hash: 'b'.repeat(64),
  routing_manifest_hash: 'c'.repeat(64),
  status: 'passed',
  metrics: {
    total: 1,
    passed: 1,
    required_total: 1,
    required_passed: 1,
    top1_accuracy: 1,
    baseline_top1_accuracy: 1,
    regression_count: 0,
    new_false_takeover_count: 0,
    gate_passed: true,
  },
  results: [],
  case_snapshots: [],
  created_by: 'portal-developer',
  created_at: '2026-08-11T06:10:00Z',
  completed_at: '2026-08-11T06:11:00Z',
}

function release(
  releaseId: string,
  versionId: string,
  runId: string,
): SkillReleaseResponse {
  return {
    release_id: releaseId,
    skill_id: 'settlement_explain_skill',
    version_id: versionId,
    environment: 'test',
    status: 'approval_pending',
    baseline_release_id: null,
    eval_run_id: runId,
    artifact_hash: 'a'.repeat(64),
    config_hash: 'b'.repeat(64),
    rollout_percent: 0,
    runtime_mode: 'shadow',
    revision: 2,
    created_by: 'portal-developer',
    created_at: '2026-08-11T06:12:00Z',
    activated_at: null,
    retired_at: null,
    approval: null,
  }
}

const workbench: SkillWorkbenchResponse = {
  summary: {
    total: 1,
    healthy: 0,
    needs_evaluation: 0,
    pending_approval: 1,
    test_active: 0,
    draft_only: 0,
    updated_at: '2026-08-11T06:12:00Z',
  },
  items: [{
    skill_id: 'settlement_explain_skill',
    skill_name: '结算解释技能',
    business_action: 'explain',
    business_object: 'settlement',
    semantic_version: '2.0.0',
    artifact_status: 'registered',
    validation_status: 'passed',
    latest_eval_status: 'passed',
    test_release_status: 'approval_pending',
    test_active_version: null,
    governance_status: 'pending_approval',
    attention_reason: 'manual_review_required',
    current_stage: 'review',
    priority: 'high',
    latest_eval_run_id: currentRun.run_id,
    candidate_version: currentVersion.semantic_version,
    baseline_version: null,
    regression_count: 0,
    required_failure_count: 0,
    linked_draft_id: null,
    linked_draft_status: null,
    waiting_since: '2026-08-11T06:12:00Z',
    next_action: 'review_approval',
    next_action_reason: '需要不同身份的人工复审',
  }],
  total: 1,
  page: 1,
  page_size: 50,
}

describe('Skill release review page', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getWorkbench.mockResolvedValue(workbench)
    mocks.listVersions.mockResolvedValue([currentVersion])
    mocks.listRuns.mockResolvedValue({ items: [currentRun], total: 1 })
    mocks.listReleases.mockResolvedValue({
      items: [
        release('release-stale', 'version-stale', 'run-stale'),
        release('release-current', currentVersion.version_id, currentRun.run_id),
      ],
      total: 2,
    })
    mocks.approve.mockResolvedValue({
      ...release('release-current', currentVersion.version_id, currentRun.run_id),
      status: 'approved',
      revision: 3,
    })
  })

  it('approves only the release bound to the current candidate and evaluation facts', async () => {
    render(<SkillReleasesPage />)

    await userEvent.click(await screen.findByRole('button', { name: '人工审批通过' }))

    await waitFor(() => expect(mocks.approve).toHaveBeenCalledOnce())
    expect(mocks.approve).toHaveBeenCalledWith(
      'settlement_explain_skill',
      'release-current',
      expect.objectContaining({ expected_revision: 2 }),
      expect.any(String),
    )
  })

  it('uses the canonical run even when the legacy latest evaluation status disagrees', async () => {
    mocks.getWorkbench.mockResolvedValue({
      ...workbench,
      items: [{ ...workbench.items[0], latest_eval_status: 'failed' }],
    })

    render(<SkillReleasesPage />)

    await userEvent.click(await screen.findByRole('button', { name: '人工审批通过' }))
    await waitFor(() => expect(mocks.approve).toHaveBeenCalledWith(
      'settlement_explain_skill',
      'release-current',
      expect.objectContaining({ expected_revision: 2 }),
      expect.any(String),
    ))
  })

  it('chooses the version bound by the canonical run when semantic versions are duplicated', async () => {
    mocks.listVersions.mockResolvedValue([
      currentVersion,
      {
        ...currentVersion,
        version_id: 'version-duplicate',
        created_at: '2026-08-11T07:00:00Z',
      },
    ])

    render(<SkillReleasesPage />)

    await userEvent.click(await screen.findByRole('button', { name: '人工审批通过' }))
    await waitFor(() => expect(mocks.approve).toHaveBeenCalledWith(
      'settlement_explain_skill',
      'release-current',
      expect.objectContaining({ expected_revision: 2 }),
      expect.any(String),
    ))
  })

  it('fails closed when the workbench has no current evaluation fact', async () => {
    mocks.getWorkbench.mockResolvedValue({
      ...workbench,
      items: [{ ...workbench.items[0], latest_eval_run_id: null }],
    })

    render(<SkillReleasesPage />)

    expect(await screen.findByText('当前候选发布事实不完整，请返回治理待办刷新')).toBeVisible()
    expect(screen.queryByRole('button', { name: '人工审批通过' })).not.toBeInTheDocument()
  })
})
