import type { PolicyQAFieldExplanation } from '@/lib/policy-qa-stream'

const PARTS = [
  ['金额含义', 'meaning'],
  ['金额构成', 'composition'],
  ['本单依据', 'basisText'],
  ['解释边界', 'boundary'],
] as const

/**
 * 字段四要素固定说明（解释投影 1.10）：面板与聊天同源同文，
 * 只渲染后端确定性生成的文字，缺项由后端 boundary 显式声明。
 */
export default function FieldExplanationBlock({
  explanation,
  testId,
}: {
  explanation: PolicyQAFieldExplanation
  testId?: string
}) {
  const rows = PARTS.flatMap(([title, key]) => {
    const text = explanation[key]
    return text ? [{ title, text }] : []
  })
  if (rows.length === 0) return null
  return (
    <dl data-testid={testId} className="space-y-0.5 text-xs leading-5 text-slate-600">
      {rows.map((row) => (
        <div key={row.title} className="flex gap-2">
          <dt className="shrink-0 text-slate-400">{row.title}</dt>
          <dd className="min-w-0 break-words">{row.text}</dd>
        </div>
      ))}
    </dl>
  )
}
