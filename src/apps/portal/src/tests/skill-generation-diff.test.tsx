import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SkillGenerationDiff } from '../components/skills/skill-generation-diff'
import type { SkillAIOptimizationProposal } from '../lib/types'

const PROPOSAL: SkillAIOptimizationProposal = {
  base_revision: 4,
  proposal_hash: 'e'.repeat(64),
  structured_config: {
    basic: { skill_id: 'demo_skill', skill_name: 'Demo', description: 'new', owner: 'it' },
    business_mounting: { business_action: 'explain', business_object: 'settlement', include_keywords: [], excluded_intents: [] },
    inputs: [{ metric_code: 'Settlement.amount', alias: 'amount', required: true, purpose: 'explain' }],
    schemas: { input: { type: 'object' }, output: { type: 'object' } },
  },
  raw_files: { 'assembler.py': 'def assemble(data): return data' },
  validation_preview: { issues: [], has_blocking: false, blocking_ok: true },
  provenance: {
    model_type: 'test-model', scene: 'skill_authoring', prompt_version: 'v1',
    metric_versions: [{ metric_code: 'Settlement.amount', object_code: 'Settlement', object_version: 2, status: 'published' }],
    generated_at: '2026-08-10T00:00:00Z', content_hash: 'b'.repeat(64),
  },
  diff: [
    { scope: 'field', change_type: 'changed', path: 'structured_config.basic.description', before: 'old', after: 'new' },
    { scope: 'file', change_type: 'added', path: 'raw_files.prompt_template.yaml', before: null, after: 'system: explain' },
    { scope: 'field', change_type: 'removed', path: 'structured_config.business_mounting.excluded_intents', before: '["legacy"]', after: null },
  ],
  citations: [],
  uncertainties: ['人工确认政策范围'],
}

describe('SkillGenerationDiff', () => {
  afterEach(cleanup)

  it('shows added, changed and removed entries in keyboard-accessible sections', async () => {
    const user = userEvent.setup()
    render(<SkillGenerationDiff proposal={PROPOSAL} onAccept={vi.fn()} onDismiss={vi.fn()} />)

    expect(screen.getByText('已更改')).toBeInTheDocument()
    expect(screen.getByText('已新增')).toBeInTheDocument()
    expect(screen.getByText('已移除')).toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /structured_config\.basic\.description/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('old')).toBeInTheDocument()
    expect(screen.getByText('new')).toBeInTheDocument()
  })

  it('does not accept or alter surrounding editor state until explicitly accepted', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn()
    render(
      <div>
        <input aria-label="current draft" defaultValue="unchanged" />
        <SkillGenerationDiff proposal={PROPOSAL} onAccept={onAccept} onDismiss={vi.fn()} />
      </div>,
    )

    expect(screen.getByLabelText('current draft')).toHaveValue('unchanged')
    expect(onAccept).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '接受优化' }))
    expect(onAccept).toHaveBeenCalledWith(PROPOSAL)
    expect(screen.getByLabelText('current draft')).toHaveValue('unchanged')
  })
})
