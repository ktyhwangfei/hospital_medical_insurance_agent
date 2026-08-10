import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import NewSkillWizardPage from '../../app/skills/new/page'

// Mock next/navigation
const routerPush = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush }),
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const AI_PROPOSAL = {
  generation_id: 'gen_abc_1',
  proposal_hash: 'a'.repeat(64),
  structured_config: {
    basic: { skill_id: 'ai_skill', skill_name: 'AI Skill', description: '解释结算', owner: '信息科' },
    business_mounting: { business_action: 'explain', business_object: 'settlement', include_keywords: ['结算'], excluded_intents: [] },
    inputs: [{ metric_code: 'Settlement.amount', alias: 'amount', required: true, purpose: '解释' }],
    schemas: { input: { type: 'object' }, output: { type: 'object' } },
  },
  raw_files: { 'assembler.py': 'def assemble(data): return data', 'prompt_template.yaml': 'system: explain' },
  validation_preview: { issues: [], has_blocking: false, blocking_ok: true },
  provenance: {
    model_type: 'test-model', scene: 'skill_authoring', prompt_version: 'v1',
    metric_versions: [{ metric_code: 'Settlement.amount', object_code: 'Settlement', object_version: 2, status: 'published' }],
    generated_at: '2026-08-10T00:00:00Z', content_hash: 'b'.repeat(64),
  },
  citations: [{ source_type: 'metric_registry', source_id: 'Settlement.amount@2', summary: 'published snapshot' }],
  uncertainties: ['人工确认政策范围'],
}

describe('NewSkillWizardPage', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    routerPush.mockReset()
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

  it('generates, previews and accepts an AI proposal before navigating to edit', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AI_PROPOSAL))
      .mockResolvedValueOnce(jsonResponse({
        draft_id: 'd-ai', skill_id: 'ai_skill', skill_name: 'AI Skill', status: 'editing',
        source_type: 'ai_generated', structured_config: AI_PROPOSAL.structured_config,
        revision: 1, created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z', created_by: 'u',
      }, 201))
    vi.stubGlobal('fetch', fetchMock)
    render(<NewSkillWizardPage />)

    await user.click(screen.getByRole('button', { name: 'AI 创建' }))
    await user.type(screen.getByPlaceholderText('描述你希望 Skill 完成的能力'), '解释医保结算金额')
    await user.type(screen.getByPlaceholderText('输入已发布 metric_code，逗号分隔'), 'Settlement.amount')
    await user.click(screen.getByRole('button', { name: '生成候选' }))

    expect(await screen.findByText('尚未进入运行时')).toBeInTheDocument()
    expect(screen.getByText('assembler.py')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '接受为草稿' }))

    expect(routerPush).toHaveBeenCalledWith('/skills/ai_skill/edit?draft=d-ai')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('keeps AI input after generation failure and can fall back to manual creation', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      jsonResponse({ detail: { error_code: 'SKILL_AI_MODEL_FAILED', message: '模型暂不可用', audit_event: {} } }, 503),
    ))
    render(<NewSkillWizardPage />)

    await user.click(screen.getByRole('button', { name: 'AI 创建' }))
    const description = screen.getByPlaceholderText('描述你希望 Skill 完成的能力')
    await user.type(description, '解释医保结算金额')
    await user.type(screen.getByPlaceholderText('输入已发布 metric_code，逗号分隔'), 'Settlement.amount')
    await user.click(screen.getByRole('button', { name: '生成候选' }))

    expect(await screen.findByText('模型暂不可用')).toBeInTheDocument()
    expect(description).toHaveValue('解释医保结算金额')
    await user.click(screen.getByRole('button', { name: '切换到手工创建' }))
    expect(screen.getByText('第一步 · 基本信息')).toBeInTheDocument()
  })

  it('disables duplicate AI generation while loading', async () => {
    const user = userEvent.setup()
    let resolveFetch: ((value: Response) => void) | undefined
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { resolveFetch = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    render(<NewSkillWizardPage />)

    await user.click(screen.getByRole('button', { name: 'AI 创建' }))
    await user.type(screen.getByPlaceholderText('描述你希望 Skill 完成的能力'), '解释医保结算金额')
    await user.type(screen.getByPlaceholderText('输入已发布 metric_code，逗号分隔'), 'Settlement.amount')
    const generate = screen.getByRole('button', { name: '生成候选' })
    await user.click(generate)
    expect(screen.getByRole('button', { name: '正在生成' })).toBeDisabled()
    expect(fetchMock).toHaveBeenCalledOnce()
    resolveFetch?.(jsonResponse(AI_PROPOSAL))
  })
})
