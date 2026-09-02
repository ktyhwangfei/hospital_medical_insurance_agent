'use client'

import { TriangleAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type {
  KnowledgeAnswerVerificationStatus,
  VerifyAnswerResponse,
} from '@/lib/policy-qa-feedback'

// 五维展示顺序与中文名（未知维度回退为 key 本身）
const DIMENSION_ORDER = [
  'citation_authenticity',
  'citation_support',
  'conclusion_consistency',
  'calculation_consistency',
  'coverage_completeness',
] as const

const DIMENSION_LABELS: Record<string, string> = {
  citation_authenticity: '引用真实性',
  citation_support: '引用支撑性',
  conclusion_consistency: '结论一致性',
  calculation_consistency: '计算一致性',
  coverage_completeness: '覆盖完整性',
}

const STATUS_LABELS: Record<KnowledgeAnswerVerificationStatus, string> = {
  passed: '通过',
  failed: '未通过',
  not_evaluable: '不可评估',
  blocked_by_evaluator: '评估器阻断',
  review_required: '需人工复核',
}

// 状态色语义：emerald=通过 / 红=失败 / amber=预警（阻断/复核）/ slate=不可用
export function statusTone(status: KnowledgeAnswerVerificationStatus): string {
  switch (status) {
    case 'passed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    case 'failed':
      return 'border-red-200 bg-red-50 text-red-700'
    case 'blocked_by_evaluator':
    case 'review_required':
      return 'border-amber-200 bg-amber-50 text-amber-700'
    case 'not_evaluable':
    default:
      return 'border-slate-200 bg-slate-100 text-slate-600'
  }
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as KnowledgeAnswerVerificationStatus] ?? status
}

/** 答案验证结果纯展示组件：整体状态 + 五维徽章 + 失败码 + degraded 提示。 */
export default function AnswerVerificationResult({
  result,
  className = '',
}: {
  result: VerifyAnswerResponse
  className?: string
}) {
  const verification = result.verification
  // 固定顺序展示，同时兼容未来新增维度 key
  const dimensionKeys = [
    ...DIMENSION_ORDER.filter((key) => key in verification.dimensions),
    ...Object.keys(verification.dimensions).filter(
      (key) => !(DIMENSION_ORDER as readonly string[]).includes(key),
    ),
  ]
  // 降级验证（无内部证据轨迹）且整体不可评估 → 结果无实质结论，给出明确解释而非无意义维度
  const meaninglessDegraded =
    verification.status === 'not_evaluable' && result.degraded

  return (
    <div className={`space-y-3 ${className}`}>
      <div
        className={`flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-xs ${statusTone(verification.status)}`}
      >
        <span className="font-semibold">整体状态：{statusLabel(verification.status)}</span>
        <span className="ml-auto text-[11px] text-slate-500">
          {result.trace_available ? '含验证轨迹' : '无验证轨迹'}
        </span>
      </div>
      {result.degraded && (
        <p className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <TriangleAlert className="size-3.5" />
          仅公开信息降级验证
        </p>
      )}
      {meaninglessDegraded ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-xs font-semibold text-slate-700">无法验证</p>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            该回答未生成完整验证所需的内部证据轨迹，无法进行引用真实性、结论/计算一致性、覆盖完整性核验。
            可能原因：该次回答本身未成功生成（如结算数据或模型服务不可用），或服务重启导致验证轨迹丢失。
            请在配置好结算数据与模型后重新发起问答，即可获得完整的五维验证结果。
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {dimensionKeys.map((key) => {
            const dim = verification.dimensions[key]
            const failures = dim.failures ?? []
            return (
              <li key={key} className="rounded-lg border border-slate-100 p-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-700">
                    {DIMENSION_LABELS[key] ?? key}
                  </span>
                  <Badge variant="outline" className={`ml-auto ${statusTone(dim.status)}`}>
                    {statusLabel(dim.status)}
                  </Badge>
                </div>
                {failures.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {failures.map((failure, index) => (
                      <div key={`${failure.code}-${index}`} className="flex items-start gap-2">
                        <Badge variant="destructive" className="shrink-0 font-mono">
                          {failure.code}
                        </Badge>
                        <span className="text-[11px] leading-5 text-slate-600">
                          {failure.message}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
