'use client'

import { useCallback, useState } from 'react'

import {
  submitPolicyQAFeedback,
  type PolicyQAFeedbackReasonCode,
} from '@/lib/policy-qa-feedback'

export type PolicyQAFeedbackState = 'idle' | 'submitting' | 'submitted' | 'error'

/**
 * 「回答有误」反馈钩子。
 *
 * 仅依据服务端下发的 qaTurnId 提交；缺失 ID 时为 no-op（避免提交伪造来源）。
 */
export function usePolicyQAFeedback(
  qaTurnId: string | undefined,
  onSubmitted?: (poolId: string, sourceSelectedSkillId: string | null) => void,
) {
  const [feedbackState, setFeedbackState] = useState<PolicyQAFeedbackState>('idle')
  const [error, setError] = useState<string | null>(null)

  const submit = useCallback(
    async (
      reasonCode: PolicyQAFeedbackReasonCode,
      comment: string | null,
    ): Promise<void> => {
      if (!qaTurnId) {
        return
      }
      setFeedbackState('submitting')
      setError(null)
      try {
        const result = await submitPolicyQAFeedback({ qaTurnId, reasonCode, comment })
        setFeedbackState('submitted')
        onSubmitted?.(result.poolId, result.sourceSelectedSkillId)
      } catch (err) {
        setFeedbackState('error')
        setError(err instanceof Error ? err.message : '反馈提交失败')
      }
    },
    [qaTurnId, onSubmitted],
  )

  const reset = useCallback(() => {
    setFeedbackState('idle')
    setError(null)
  }, [])

  return { feedbackState, error, submit, reset }
}
