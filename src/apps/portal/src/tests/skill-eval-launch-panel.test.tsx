import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillEvalLaunchPanel from '@/components/skills/skill-eval-launch-panel'
import type { SkillVersionResponse } from '@/lib/types'

const mocks = vi.hoisted(() => ({
  catalog: vi.fn(),
  versions: vi.fn(),
  run: vi.fn(),
}))

vi.mock('@/lib/api-client', () => ({
  listInfraSkillCatalog: (...a: unknown[]) => mocks.catalog(...a),
  listInfraSkillVersions: (...a: unknown[]) => mocks.versions(...a),
  createSkillEvalRun: (...a: unknown[]) => mocks.run(...a),
}))

afterEach(cleanup)

function makeVersion(overrides: Partial<SkillVersionResponse> = {}): SkillVersionResponse {
  return {
    version_id: 'v1',
    skill_id: 'sk1',
    semantic_version: '1.0.0',
    source_commit: 'abc',
    source_path: '/p',
    artifact_hash: 'h',
    manifest_snapshot: {},
    dependency_snapshot: {},
    file_count: 1,
    validation_status: 'passed',
    validation_issues: [],
    created_by: 'tester',
    created_at: '2026-08-10T00:00:00Z',
    ...overrides,
  }
}

describe('SkillEvalLaunchPanel — 发起评测', () => {
  beforeEach(() => {
    mocks.catalog.mockReset()
    mocks.versions.mockReset()
    mocks.run.mockReset()
  })

  it('未选 skill/version 时发起按钮禁用', async () => {
    mocks.catalog.mockResolvedValue({ items: [{ skill_id: 'sk1' }] })
    render(<SkillEvalLaunchPanel enabledCaseCount={0} onLaunched={() => {}} />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-launch-skill')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('eval-launch-button')).toBeDisabled()
  })

  it('选 skill → 选版本 → 发起评测调用 createSkillEvalRun', async () => {
    const user = userEvent.setup()
    const onLaunched = vi.fn()
    mocks.catalog.mockResolvedValue({ items: [{ skill_id: 'sk1' }] })
    mocks.versions.mockResolvedValue([makeVersion()])
    mocks.run.mockResolvedValue({ run_id: 'run-9', skill_id: 'sk1' })

    render(<SkillEvalLaunchPanel enabledCaseCount={5} onLaunched={onLaunched} />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-launch-skill')).toBeInTheDocument(),
    )

    await user.selectOptions(screen.getByTestId('eval-launch-skill'), 'sk1')
    await waitFor(() =>
      expect(mocks.versions).toHaveBeenCalledWith('sk1'),
    )
    await user.selectOptions(screen.getByTestId('eval-launch-version'), 'v1')
    await user.click(screen.getByTestId('eval-launch-button'))

    await waitFor(() =>
      expect(mocks.run).toHaveBeenCalledWith('sk1', { version_id: 'v1' }),
    )
    expect(onLaunched).toHaveBeenCalledWith({ run_id: 'run-9', skill_id: 'sk1' })
  })

  it('发起失败时显示错误', async () => {
    const user = userEvent.setup()
    mocks.catalog.mockResolvedValue({ items: [{ skill_id: 'sk1' }] })
    mocks.versions.mockResolvedValue([makeVersion()])
    mocks.run.mockRejectedValue(new Error('版本未校验'))

    render(<SkillEvalLaunchPanel enabledCaseCount={0} onLaunched={() => {}} />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-launch-skill')).toBeInTheDocument(),
    )
    await user.selectOptions(screen.getByTestId('eval-launch-skill'), 'sk1')
    await user.selectOptions(screen.getByTestId('eval-launch-version'), 'v1')
    await user.click(screen.getByTestId('eval-launch-button'))

    await waitFor(() => expect(screen.getByText('发起评测失败')).toBeInTheDocument())
  })
})
