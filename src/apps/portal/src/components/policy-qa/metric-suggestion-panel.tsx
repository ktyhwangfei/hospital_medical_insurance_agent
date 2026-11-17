'use client'

import { BarChart3 } from 'lucide-react'

/**
 * V4.0 运营问数智能体：空状态指标 chip 建议（设计 §4.3）。
 *
 * 自然语言问数为主，指标 chip 仅在空状态作建议（辅助，非强制）。
 */

const METRIC_SUGGESTIONS = [
  '本月门诊次均费用是多少？',
  '各科室药品费用排名',
  '近三个月住院人次趋势',
  '医保目录内费用占比',
] as const

/** 筛查结果问法。只提问，不提供上传、批准或关闭规则。 */
const SCREENING_SUGGESTIONS = [
  '本月待核实疑点有多少条，涉及金额多少？',
  '按规则分别是多少？',
  '按科室分别是多少？',
  '列出金额最高的几条',
  '材料不足的有哪些？',
] as const

interface MetricSuggestionPanelProps {
  onSelectQuestion: (question: string) => void
}

export default function MetricSuggestionPanel({ onSelectQuestion }: MetricSuggestionPanelProps) {
  return (
    <section
      data-testid="ops-metric-suggestions"
      className="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-6 py-10 text-center"
    >
      <BarChart3 className="mx-auto size-8 text-slate-400" aria-hidden />
      <h2 className="mt-4 text-base font-semibold text-slate-900">用自然语言问运营数据</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
        可以问已跑出的筛查疑点，也可以问运营指标。回答带口径。上传、批准和关闭规则在规则管理，不在这里。
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2" data-testid="ops-screening-suggestions">
        {SCREENING_SUGGESTIONS.map((question) => (
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
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        {METRIC_SUGGESTIONS.map((question) => (
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
