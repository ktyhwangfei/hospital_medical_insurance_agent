import { MessageCircleQuestion } from 'lucide-react'

import MetricSuggestionPanel from '@/components/policy-qa/metric-suggestion-panel'
import type { PolicyQAMode } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 空状态按智能体建议（设计 §6.4 / §8.2）：
 * - 政策问答：纯政策问题建议（无结算单号要求）
 * - 运营问数：指标 chip 建议（MetricSuggestionPanel）
 * - 结算解释：时间快捷选择（U4 由 SettlementTimeBrowser 接管，此处兜底）
 */

const POLICY_EXAMPLE_QUESTIONS = [
  '门诊大额互助的报销比例是多少？',
  '退休人员的起付线标准是多少？',
  '异地就医备案流程是什么？',
] as const

const SETTLEMENT_EXAMPLE_QUESTIONS = [
  '查询住院费用，结算单 1671213',
  '统筹自付为什么这么多？',
  '起付线是怎么计算的？',
] as const

interface PolicyQAEmptyStateProps {
  onSelectQuestion: (question: string) => void
  /** 当前智能体绑定的工作模式；缺省按政策问答 */
  mode?: PolicyQAMode
}

export default function PolicyQAEmptyState({
  onSelectQuestion,
  mode = 'policy_chat',
}: PolicyQAEmptyStateProps) {
  if (mode === 'data_query') {
    return <MetricSuggestionPanel onSelectQuestion={onSelectQuestion} />
  }

  const questions =
    mode === 'settlement_explain' ? SETTLEMENT_EXAMPLE_QUESTIONS : POLICY_EXAMPLE_QUESTIONS
  const heading = mode === 'settlement_explain' ? '先问一个与当前结算相关的问题' : '直接问政策问题'
  const hint =
    mode === 'settlement_explain'
      ? '首次提问请带上结算单号，后续可直接连续追问。'
      : '回答附带可追溯的政策来源；连续追问无需结算单号。'

  return (
    <section className="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-6 py-10 text-center">
      <MessageCircleQuestion className="mx-auto size-8 text-slate-400" aria-hidden />
      <h2 className="mt-4 text-base font-semibold text-slate-900">{heading}</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">{hint}</p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {questions.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onSelectQuestion(question)}
            className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 transition-colors hover:border-slate-300 hover:text-slate-900"
          >
            {question}
          </button>
        ))}
      </div>
    </section>
  )
}
