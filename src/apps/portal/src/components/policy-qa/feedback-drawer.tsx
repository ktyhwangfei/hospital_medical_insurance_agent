'use client'

import { useState } from 'react'
import { Flag } from 'lucide-react'

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

/**
 * 「回答有误」反馈：默认只占一行文字按钮，点击后弹出紧凑原因菜单，
 * 不再用整块卡片铺开 6 个按钮。
 */
export default function FeedbackDrawer({ qaTurnId, onSubmitted }: FeedbackDrawerProps) {
  const { feedbackState, error, submit } = usePolicyQAFeedback(qaTurnId, onSubmitted)
  const [open, setOpen] = useState(false)

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
    <div className="relative inline-block" data-testid="policy-qa-feedback-drawer">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 text-xs text-slate-400 underline-offset-4 hover:text-slate-600 hover:underline focus-visible:outline-2"
      >
        <Flag className="size-3" aria-hidden />
        反馈问题
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="反馈原因"
          className="absolute bottom-full left-0 z-20 mb-2 w-56 rounded-lg border border-slate-200 bg-white p-2 shadow-lg"
        >
          <p className="mb-1 px-1 text-xs text-slate-500">这条回答哪里有问题？</p>
          <div className="grid grid-cols-2 gap-1">
            {POLICY_QA_FEEDBACK_REASONS.map((reason) => (
              <button
                key={reason}
                type="button"
                role="menuitem"
                disabled={feedbackState === 'submitting'}
                data-testid={`policy-qa-feedback-reason-${reason}`}
                onClick={() => {
                  setOpen(false)
                  void submit(reason, null)
                }}
                className="rounded px-2 py-1 text-left text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-50"
              >
                {REASON_LABELS[reason]}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {feedbackState === 'error' ? (
        <p data-testid="policy-qa-feedback-error" className="mt-1 text-xs text-rose-600">
          {error ?? '提交失败，请稍后重试'}
        </p>
      ) : null}
    </div>
  )
}
