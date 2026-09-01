import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillEvalSuitePanel from '@/components/skills/skill-eval-suite-panel'
import { createSkillEvalSuite, listSkillEvalSuites, updateSkillEvalSuite } from '@/lib/api-client'

vi.mock('@/lib/api-client', () => ({
  createSkillEvalSuite: vi.fn(),
  listSkillEvalSuites: vi.fn(),
  updateSkillEvalSuite: vi.fn(),
}))

const platformSuite = {
  suite_id: 'EVS_platform_routing',
  name: '平台默认路由测评集',
  scope: 'platform' as const,
  skill_id: null,
  purpose: '兼容历史路由评测与发布门禁',
  status: 'active' as const,
  revision: 1,
  created_by: 'system',
  updated_by: 'system',
  created_at: '2026-08-31T00:00:00Z',
  updated_at: '2026-08-31T00:00:00Z',
}

const skillSuite = {
  ...platformSuite,
  suite_id: 'EVS_skill',
  name: '门诊路由回归',
  scope: 'skill' as const,
  skill_id: 'mzsettlement_verify_skill',
}

describe('SkillEvalSuitePanel', () => {
  beforeEach(() => {
    vi.mocked(listSkillEvalSuites).mockResolvedValue({ items: [platformSuite], total: 1 })
    vi.mocked(createSkillEvalSuite).mockResolvedValue({
      ...platformSuite,
      suite_id: 'EVS_created',
      name: '门诊路由回归',
      scope: 'skill',
      skill_id: 'mzsettlement_verify_skill',
    })
    vi.mocked(updateSkillEvalSuite).mockResolvedValue({
      ...skillSuite,
      status: 'inactive',
      revision: 2,
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('列出、选择并新建当前 Skill 的测评集', async () => {
    const onSelect = vi.fn()
    render(
      <SkillEvalSuitePanel
        skillId="mzsettlement_verify_skill"
        selectedSuiteId={null}
        onSelect={onSelect}
      />,
    )

    expect(await screen.findByText('平台默认路由测评集')).toBeVisible()
    fireEvent.change(screen.getByLabelText('测评集名称'), {
      target: { value: '门诊路由回归' },
    })
    fireEvent.click(screen.getByRole('button', { name: '新建测评集' }))

    await waitFor(() => expect(createSkillEvalSuite).toHaveBeenCalledWith({
      name: '门诊路由回归',
      scope: 'skill',
      skill_id: 'mzsettlement_verify_skill',
      purpose: '',
    }))
    expect(onSelect).toHaveBeenCalledWith('EVS_created')
  })

  it('停用当前 Skill 的非默认测评集', async () => {
    vi.mocked(listSkillEvalSuites).mockResolvedValueOnce({
      items: [platformSuite, skillSuite],
      total: 2,
    })
    render(
      <SkillEvalSuitePanel
        skillId="mzsettlement_verify_skill"
        selectedSuiteId="EVS_skill"
        onSelect={vi.fn()}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: '停用测评集' }))
    await waitFor(() => expect(updateSkillEvalSuite).toHaveBeenCalledWith(
      'EVS_skill',
      {
        name: '门诊路由回归',
        purpose: '兼容历史路由评测与发布门禁',
        status: 'inactive',
        expected_revision: 1,
      },
    ))
  })

  it('停用测评集仍可选择并重新启用', async () => {
    vi.mocked(listSkillEvalSuites).mockResolvedValueOnce({
      items: [platformSuite, { ...skillSuite, status: 'inactive' }],
      total: 2,
    })
    vi.mocked(updateSkillEvalSuite).mockResolvedValueOnce({
      ...skillSuite,
      status: 'active',
      revision: 2,
    })
    render(
      <SkillEvalSuitePanel
        skillId="mzsettlement_verify_skill"
        selectedSuiteId="EVS_skill"
        onSelect={vi.fn()}
      />,
    )

    const select = await screen.findByLabelText('选择测评集')
    expect(select.querySelector('option[value="EVS_skill"]')).not.toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '启用测评集' }))
    await waitFor(() => expect(updateSkillEvalSuite).toHaveBeenCalledWith(
      'EVS_skill',
      expect.objectContaining({ status: 'active' }),
    ))
  })
})
