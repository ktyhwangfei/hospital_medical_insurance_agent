import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import NewSkillWizardPage from '../../app/skills/new/page'

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('NewSkillWizardPage', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders step 1 with required fields', () => {
    render(<NewSkillWizardPage />)
    expect(screen.getByText('新建 Skill 向导')).toBeInTheDocument()
    expect(screen.getByText(/skill_id/)).toBeInTheDocument()
    expect(screen.getByText('第一步 · 基本信息')).toBeInTheDocument()
  })

  it('disables next button until skill_id and name are filled', async () => {
    const user = userEvent.setup()
    render(<NewSkillWizardPage />)

    const nextButton = screen.getByText('下一步')
    expect(nextButton).toBeDisabled()

    // Fill required fields
    await user.type(screen.getByPlaceholderText('如 settlement_explain_skill'), 'my_new_skill')
    await user.type(screen.getByPlaceholderText('如 结算费用解释 Skill'), 'My Skill')
    expect(nextButton).not.toBeDisabled()
  })

  it('navigates through all 4 steps', async () => {
    const user = userEvent.setup()
    render(<NewSkillWizardPage />)

    // Step 1
    await user.type(screen.getByPlaceholderText('如 settlement_explain_skill'), 'test_skill')
    await user.type(screen.getByPlaceholderText('如 结算费用解释 Skill'), 'Test')
    await user.click(screen.getByText('下一步'))

    // Step 2
    expect(screen.getByText('第二步 · 业务挂载')).toBeInTheDocument()
    await user.click(screen.getByText('下一步'))

    // Step 3
    expect(screen.getByText('第三步 · 输入输出契约')).toBeInTheDocument()
    await user.click(screen.getByText('下一步'))

    // Step 4 - preview
    expect(screen.getByText('第四步 · 生成预览')).toBeInTheDocument()
    expect(screen.getByText('创建草稿')).toBeInTheDocument()
  })

  it('creates draft on submit and shows success', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        draft_id: 'd-1',
        skill_id: 'test_skill',
        skill_name: 'Test',
        status: 'editing',
        source_type: 'template',
        structured_config: { business_mounting: { business_action: 'explain', business_object: 'settlement' } },
        validation_blocking_ok: false,
        revision: 1,
        etag: 'e-1',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        created_by: 'u',
      }, 201),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<NewSkillWizardPage />)

    // Navigate to step 4
    await user.type(screen.getByPlaceholderText('如 settlement_explain_skill'), 'test_skill')
    await user.type(screen.getByPlaceholderText('如 结算费用解释 Skill'), 'Test')
    await user.click(screen.getByText('下一步'))
    await user.click(screen.getByText('下一步'))
    await user.click(screen.getByText('下一步'))

    // Submit
    await user.click(screen.getByText('创建草稿'))

    expect(screen.getByText('草稿已创建')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledOnce()
  })
})
