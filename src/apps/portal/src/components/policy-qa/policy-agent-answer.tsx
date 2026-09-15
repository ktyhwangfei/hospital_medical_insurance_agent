'use client'

import { AlertTriangle } from 'lucide-react'

import AnswerVerificationButton from '@/components/policy-qa/answer-verification-button'
import CalculationDisclosure from '@/components/policy-qa/calculation-disclosure'
import CitationCards from '@/components/policy-qa/citation-card'
import FeedbackDrawer from '@/components/policy-qa/feedback-drawer'
import OpsAnswerBlock from '@/components/policy-qa/ops-answer-block'
import PolicySourcesDialog from '@/components/policy-qa/policy-sources-dialog'
import VerificationSummary from '@/components/policy-qa/verification-summary'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'

interface PolicyAgentAnswerProps {
  message: PolicyQAChatMessage
}

export default function PolicyAgentAnswer({ message }: PolicyAgentAnswerProps) {
  if (!message.content) return null
  const isBroad = message.isBroad
  const hasDataQuery = !!message.dataQueryResult

  return (
    <article
      data-testid="policy-qa-answer"
      className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-900">{message.content}</p>

      {hasDataQuery && message.dataQueryResult ? (
        <OpsAnswerBlock result={message.dataQueryResult} />
      ) : null}

      {!isBroad && !hasDataQuery && message.verificationSummary ? (
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
      {!isBroad && !hasDataQuery && <CalculationDisclosure message={message} />}
      {/* V4.0 §4.1：宽泛政策问答（政策问答智能体）来源卡片常显；结算类答案保留来源对话框 */}
      {isBroad ? (
        <CitationCards citations={message.citations ?? []} />
      ) : (
        <PolicySourcesDialog citations={message.citations ?? []} />
      )}

      {!isBroad && message.uncertainties && message.uncertainties.length > 0 ? (
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

      {!isBroad && message.qaTurnId ? (
        <div className="flex flex-wrap items-center gap-3">
          <AnswerVerificationButton qaTurnId={message.qaTurnId} />
          <FeedbackDrawer qaTurnId={message.qaTurnId} />
        </div>
      ) : null}

      {isBroad ? (
        <p className="text-xs text-slate-400">
          政策可能动态调整，具体以当地医保经办机构解释为准。
        </p>
      ) : null}
    </article>
  )
}
