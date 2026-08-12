import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

import { usePolicyQAFeedback } from '@/hooks/use-policy-qa-feedback'

vi.mock('@/lib/policy-qa-feedback', () => ({
  submitPolicyQAFeedback: vi.fn(),
}))

import { submitPolicyQAFeedback } from '@/lib/policy-qa-feedback'

describe('usePolicyQAFeedback', () => {
  beforeEach(() => {
    vi.mocked(submitPolicyQAFeedback).mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('transitions to submitted on success and reports poolId', async () => {
    vi.mocked(submitPolicyQAFeedback).mockResolvedValue({
      poolId: 'pool_1',
      status: 'pending_triage',
      errorDimension: 'calculation',
      sourceSelectedSkillId: 'deductible',
    })
    const onSubmitted = vi.fn()

    const { result } = renderHook(() => usePolicyQAFeedback('qat_1', onSubmitted))

    await act(async () => {
      await result.current.submit('wrong_calculation', '口径不对')
    })

    expect(result.current.feedbackState).toBe('submitted')
    expect(onSubmitted).toHaveBeenCalledWith('pool_1', 'deductible')
    expect(submitPolicyQAFeedback).toHaveBeenCalledWith({
      qaTurnId: 'qat_1',
      reasonCode: 'wrong_calculation',
      comment: '口径不对',
    })
  })

  it('transitions to error on failure without throwing', async () => {
    vi.mocked(submitPolicyQAFeedback).mockRejectedValue(new Error('404'))
    const onSubmitted = vi.fn()

    const { result } = renderHook(() => usePolicyQAFeedback('qat_2', onSubmitted))

    await act(async () => {
      await result.current.submit('wrong_routing', null)
    })

    await waitFor(() => expect(result.current.feedbackState).toBe('error'))
    expect(onSubmitted).not.toHaveBeenCalled()
    expect(result.current.error).toBeTruthy()
  })

  it('is a no-op when qaTurnId is missing', async () => {
    const onSubmitted = vi.fn()
    const { result } = renderHook(() => usePolicyQAFeedback(undefined, onSubmitted))

    await act(async () => {
      await result.current.submit('wrong_calculation', null)
    })

    expect(submitPolicyQAFeedback).not.toHaveBeenCalled()
    expect(result.current.feedbackState).toBe('idle')
  })
})
