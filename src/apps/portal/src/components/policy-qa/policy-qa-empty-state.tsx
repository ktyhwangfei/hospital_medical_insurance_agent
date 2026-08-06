import { MessageCircleQuestion } from 'lucide-react'

const EXAMPLE_QUESTIONS = [
  '查询住院费用，结算单 1671213',
  '统筹自付为什么这么多？',
  '起付线是怎么计算的？',
] as const

interface PolicyQAEmptyStateProps {
  onSelectQuestion: (question: string) => void
}

export default function PolicyQAEmptyState({ onSelectQuestion }: PolicyQAEmptyStateProps) {
  return (
    <section className="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-6 py-10 text-center">
      <MessageCircleQuestion className="mx-auto size-8 text-slate-400" aria-hidden />
      <h2 className="mt-4 text-base font-semibold text-slate-900">
        先问一个与当前结算相关的问题
      </h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
        首次提问请带上结算单号，后续可直接连续追问。
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {EXAMPLE_QUESTIONS.map((question) => (
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
