import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SkillDraftPreview from '../components/skills/skill-draft-preview'
import type { SkillAIGenerationProposal } from '../lib/types'

const PROPOSAL: SkillAIGenerationProposal = {
  generation_id: 'gen_abc_1',
  proposal_hash: 'a'.repeat(64),
  structured_config: {
    basic: { skill_id: 'ai_skill', skill_name: 'AI Skill', description: '解释结算', owner: '信息科' },
    business_mounting: { business_action: 'explain', business_object: 'settlement', include_keywords: ['结算'], excluded_intents: [] },
    inputs: [{ metric_code: 'Settlement.amount', alias: 'amount', required: true, purpose: '解释' }],
    schemas: { input: { type: 'object' }, output: { type: 'object' } },
  },
  raw_files: {
    'assembler.py': 'def assemble(data):\n    return data',
    'prompt_template.yaml': 'system: explain settlement',
    'ignored.txt': 'must not render',
  },
  validation_preview: { issues: [], has_blocking: false, blocking_ok: true },
  provenance: {
    model_type: 'test-model', scene: 'skill_authoring', prompt_version: 'v1',
    metric_versions: [{ metric_code: 'Settlement.amount', object_code: 'Settlement', object_version: 2, status: 'published' }],
    generated_at: '2026-08-10T00:00:00Z', content_hash: 'b'.repeat(64),
  },
  citations: [{ source_type: 'metric_registry', source_id: 'Settlement.amount@2', summary: 'published snapshot' }],
  uncertainties: ['人工确认政策范围'],
}

describe('SkillDraftPreview', () => {
  afterEach(cleanup)

  it('renders only the proposal whitelist, evidence and safety summary', () => {
    render(<SkillDraftPreview proposal={PROPOSAL} onAccept={vi.fn()} onBack={vi.fn()} accepting={false} />)

    expect(screen.getByText('尚未进入运行时')).toBeInTheDocument()
    expect(screen.getByText('assembler.py')).toBeInTheDocument()
    expect(screen.getByText('输入 Schema')).toBeInTheDocument()
    expect(screen.getByText('prompt_template.yaml')).toBeInTheDocument()
    expect(screen.getByText(/安全扫描通过/)).toBeInTheDocument()
    expect(screen.getByText(/Settlement.amount@v2/)).toBeInTheDocument()
    expect(screen.getByText(/published snapshot/)).toBeInTheDocument()
    expect(screen.getByText(/人工确认政策范围/)).toBeInTheDocument()
    expect(screen.queryByText('must not render')).not.toBeInTheDocument()
  })

  it('invokes typed callbacks and disables accept while loading', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn()
    const onBack = vi.fn()
    const { rerender } = render(
      <SkillDraftPreview proposal={PROPOSAL} onAccept={onAccept} onBack={onBack} accepting={false} />,
    )
    await user.click(screen.getByRole('button', { name: '返回修改' }))
    await user.click(screen.getByRole('button', { name: '接受为草稿' }))
    expect(onBack).toHaveBeenCalledOnce()
    expect(onAccept).toHaveBeenCalledOnce()

    rerender(<SkillDraftPreview proposal={PROPOSAL} onAccept={onAccept} onBack={onBack} accepting />)
    expect(screen.getByRole('button', { name: '正在接受' })).toBeDisabled()
  })
})
