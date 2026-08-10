import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SkillCandidateEvaluationPanel } from '@/components/skills/skill-candidate-evaluation-panel'
import {
  evaluateSkillCandidateBehavior,
  evaluateSkillCandidateRoutes,
} from '@/lib/skill-draft-api'

vi.mock('@/lib/skill-draft-api', () => ({
  evaluateSkillCandidateRoutes: vi.fn(),
  evaluateSkillCandidateBehavior: vi.fn(),
}))

describe('SkillCandidateEvaluationPanel', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('shows route completion and fail-closed behavior status', async () => {
    vi.mocked(evaluateSkillCandidateRoutes).mockResolvedValue({
      artifact_hash: 'a'.repeat(64),
      case_snapshot_hash: 'b'.repeat(64),
      status: 'completed',
      metrics: {
        total: 1,
        passed: 1,
        required_total: 1,
        required_passed: 1,
        top1_accuracy: 1,
        baseline_top1_accuracy: 0,
        regression_count: 0,
        new_false_takeover_count: 0,
        gate_passed: true,
      },
      results: [],
      blocked_reason: null,
    })
    vi.mocked(evaluateSkillCandidateBehavior).mockResolvedValue({
      artifact_hash: 'a'.repeat(64),
      case_snapshot_hash: 'c'.repeat(64),
      status: 'blocked_by_evaluator',
      results: [],
      blocked_reason: 'sandbox_unavailable',
    })
    const user = userEvent.setup()
    render(<SkillCandidateEvaluationPanel draftId="d-1" disabled={false} />)

    await user.click(screen.getByRole('button', { name: '运行候选路由评测' }))
    await user.click(screen.getByRole('button', { name: '运行候选行为评测' }))

    expect(evaluateSkillCandidateRoutes).toHaveBeenCalledWith('d-1')
    expect(evaluateSkillCandidateBehavior).toHaveBeenCalledWith('d-1')
    expect(screen.getByText('路由评测：已完成')).toBeInTheDocument()
    expect(screen.getByText(/行为评测：评测器阻断/)).toHaveTextContent(
      'sandbox_unavailable',
    )
  })
})
