'use client'

import { AlertTriangle, Sparkles } from 'lucide-react'

import CalculationDisclosure from '@/components/policy-qa/calculation-disclosure'
import FeedbackDrawer from '@/components/policy-qa/feedback-drawer'
import PolicySourcesDialog from '@/components/policy-qa/policy-sources-dialog'
import VerificationSummary from '@/components/policy-qa/verification-summary'
import { Button } from '@/components/ui/button'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'

interface PolicyAgentAnswerProps {
  message: PolicyQAChatMessage
  onFollowUp?: (question: string) => void
}

export default function PolicyAgentAnswer({ message, onFollowUp }: PolicyAgentAnswerProps) {
  if (!message.content) return null

  return (
    <article
      data-testid="policy-qa-answer"
      className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-900">{message.content}</p>

      {message.verificationSummary ? (
        <div
          data-testid="policy-qa-verification"
          data-status={message.answerStatus ?? 'unavailable'}
        >
          <VerificationSummary
            summary={message.verificationSummary}
            answerStatus={message.answerStatus}
          />
        </div>
      ) : null}
      <CalculationDisclosure message={message} />
      <PolicySourcesDialog citations={message.citations ?? []} />

      {message.uncertainties && message.uncertainties.length > 0 ? (
        <section aria-label="尚待核实" className="rounded-xl bg-amber-50 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
            <AlertTriangle className="size-4" aria-hidden />
            尚待核实
          </div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-amber-800">
            {message.uncertainties.map((uncertainty) => (
              <li key={uncertainty}>{uncertainty}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {message.qaTurnId ? (
        <FeedbackDrawer qaTurnId={message.qaTurnId} />
      ) : null}

      {onFollowUp ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
          <span className="text-xs text-slate-500">建议追问</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onFollowUp('请用更通俗的语言解释刚才的回答')}
          >
            <Sparkles aria-hidden />
            请用更通俗的话解释
          </Button>
        </div>
      ) : null}
    </article>
  )
}
