'use client'

import { ReceiptText } from 'lucide-react'

import CalculationDisclosure from '@/components/policy-qa/calculation-disclosure'
import PolicySourcesDialog from '@/components/policy-qa/policy-sources-dialog'
import VerificationSummary from '@/components/policy-qa/verification-summary'
import { SERIES_COLORS } from '@/components/policy-qa/ops-answer-block'
import { formatAmount } from '@/lib/policy-qa-settlement-list'
import type { PolicyQAChatMessage } from '@/lib/policy-qa-session'
import type { PolicyQAResult } from '@/lib/policy-qa-stream'

/**
 * V4.0 结算解释智能体：单笔费用构成富块（设计 §4.2）。
 *
 * 总费用等宽大字 + 单色分段条（费用字段占比）+ 字段明细 + 完整解释
 * （answer / 计算依据 / 政策来源 / 核验摘要复用既有组件）。
 * 金额一律 --font-mono + tabular-nums（§6.1 金融数据质感）。
 */

interface SettlementResultBlockProps {
  settlementId: string
  result: PolicyQAResult
}

export default function SettlementResultBlock({
  settlementId,
  result,
}: SettlementResultBlockProps) {
  const total = result.caseContext?.totalAmount ?? null
  const segments = result.settlementFields.filter((field) => field.state === 'non_zero')

  // 以 message 视图复用计算依据展开（calculationSteps/caseContext/definition）
  const message: PolicyQAChatMessage = {
    role: 'assistant',
    content: result.answer,
    answerStatus: result.answerStatus,
    calculationSteps: result.calculationSteps,
    definition: result.definition,
    caseContext: result.caseContext,
    citations: result.citations,
    uncertainties: result.uncertainties,
    verificationSummary: result.verificationSummary,
  }

  return (
    <article
      data-testid="settlement-result-block"
      className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-100 pb-3">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <ReceiptText className="size-4 text-slate-400" aria-hidden />
          结算单 {settlementId} · 费用构成
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">总费用</p>
          <p className="tabular-amounts text-xl font-semibold text-slate-900">
            {formatAmount(total)}
            <span className="ml-0.5 text-xs font-normal text-slate-500">元</span>
          </p>
        </div>
      </header>

      {/* 单色分段条：费用字段占比（§6.2 accent 深浅阶，禁彩虹渐变） */}
      {segments.length > 0 && total && total > 0 ? (
        <div data-testid="settlement-composition-bar" className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
          {segments.map((field, index) => {
            const ratio = Math.max((field.value ?? 0) / total, 0)
            if (ratio <= 0) return null
            return (
              <span
                key={field.fieldName}
                title={`${field.fieldName} ${((ratio) * 100).toFixed(1)}%`}
                style={{
                  width: `${(ratio * 100).toFixed(2)}%`,
                  backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length],
                }}
              />
            )
          })}
        </div>
      ) : null}

      {/* 费用字段明细：等宽金额；reported_zero 显性展示 0.00，missing 显 '—' */}
      {result.settlementFields.length > 0 ? (
        <ul className="divide-y divide-slate-100 text-sm" data-testid="settlement-field-list">
          {result.settlementFields.map((field) => (
            <li key={field.fieldName} className="flex items-center justify-between gap-3 py-2">
              <span className="text-slate-600">
                {field.fieldName}
                {field.state === 'missing' ? (
                  <span className="ml-1 text-xs text-amber-600">（缺失）</span>
                ) : null}
              </span>
              <span
                className={[
                  'tabular-amounts',
                  field.state === 'missing' ? 'text-slate-400' : 'text-slate-900',
                ].join(' ')}
              >
                {field.state === 'missing' ? '—' : `${formatAmount(field.value)} 元`}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-900">{result.answer}</p>

      {result.verificationSummary ? (
        <div data-testid="policy-qa-verification" data-status={result.answerStatus}>
          <VerificationSummary summary={result.verificationSummary} answerStatus={result.answerStatus} />
        </div>
      ) : null}
      <CalculationDisclosure message={message} />
      <PolicySourcesDialog citations={result.citations} />
    </article>
  )
}
