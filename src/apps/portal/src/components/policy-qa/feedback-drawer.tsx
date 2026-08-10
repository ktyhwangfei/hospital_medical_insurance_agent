'use client'

import { Flag } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  POLICY_QA_FEEDBACK_REASONS,
  type PolicyQAFeedbackReasonCode,
} from '@/lib/policy-qa-feedback'
import { usePolicyQAFeedback } from '@/hooks/use-policy-qa-feedback'

interface FeedbackDrawerProps {
  qaTurnId: string | undefined
  onSubmitted?: (poolId: string, sourceSelectedSkillId: string | null) => void
}

const REASON_LABELS: Record<PolicyQAFeedbackReasonCode, string> = {
  wrong_calculation: '计算错误',
  wrong_policy_content: '政策内容错误',
  wrong_citation: '来源引用错误',
  wrong_routing: '技能路由错误',
  unhelpful: '没有帮助',
  other: '其他',
}

/** 「回答有误」反馈抽屉：仅依据 qaTurnId 提交，客户端不伪造正文。 */
export default function FeedbackDrawer({ qaTurnId, onSubmitted }: FeedbackDrawerProps) {
  const { feedbackState, error, submit } = usePolicyQAFeedback(qaTurnId, onSubmitted)

  if (feedbackState === 'submitted') {
    return (
      <p data-testid="policy-qa-feedback-submitted" className="text-xs text-emerald-600">
        已记录，感谢反馈。该案例将进入评测回归池。
      </p>
    )
  }

  if (!qaTurnId) {
    return null
  }

  return (
    <div
      data-testid="policy-qa-feedback-drawer"
      className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3"
    >
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
        <Flag className="size-4" aria-hidden />
        这条回答有误？
      </div>
      <div className="flex flex-wrap gap-2">
        {POLICY_QA_FEEDBACK_REASONS.map((reason) => (
          <Button
            key={reason}
            type="button"
            variant="outline"
            size="sm"
            disabled={feedbackState === 'submitting'}
            data-testid={`policy-qa-feedback-reason-${reason}`}
            onClick={() => submit(reason, null)}
          >
            {REASON_LABELS[reason]}
          </Button>
        ))}
      </div>
      {feedbackState === 'error' ? (
        <p
          data-testid="policy-qa-feedback-error"
          className="mt-2 text-xs text-rose-600"
        >
          {error ?? '提交失败，请稍后重试'}
        </p>
      ) : null}
    </div>
  )
}
