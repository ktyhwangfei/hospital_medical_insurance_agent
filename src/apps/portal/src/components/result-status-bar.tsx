'use client'

import { Loader2, CheckCircle2, AlertTriangle, XCircle, Info } from 'lucide-react'

/* ============================================================
   ResultStatusBar — 问答结果状态栏
   展示答案可回答性状态：running / can_answer / partial_answer / cannot_answer
   ============================================================ */

export interface ResultStatusBarProps {
  runStatus: 'running' | 'success' | 'failed'
  canAnswer: boolean
  partialAnswer: boolean
  canAnswerReason?: string
  missingItems?: string[]
}

export default function ResultStatusBar({
  runStatus,
  canAnswer,
  partialAnswer,
  canAnswerReason,
  missingItems,
}: ResultStatusBarProps) {
  // ── 正在运行 ──
  if (runStatus === 'running') {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
          <span className="text-sm text-blue-700 font-medium">正在处理...</span>
        </div>
      </div>
    )
  }

  // ── 失败 ──
  if (runStatus === 'failed') {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <XCircle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-red-700">
              处理失败
            </div>
            {canAnswerReason && (
              <div className="text-sm text-red-600 mt-1 leading-relaxed">
                {canAnswerReason}
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── 成功 + 可以回答 ──
  if (runStatus === 'success' && canAnswer && !partialAnswer) {
    return (
      <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-emerald-700">
              可以回答：已获取真实结算字段和核心政策依据
            </div>
            {canAnswerReason && (
              <div className="text-sm text-emerald-600 mt-1 leading-relaxed">
                {canAnswerReason}
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── 成功 + 部分回答 ──
  if (runStatus === 'success' && canAnswer && partialAnswer) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-amber-700">
              可以做部分解释：已获取真实结算字段，但政策依据或分段明细不完整
            </div>
            {canAnswerReason && (
              <div className="text-sm text-amber-600 mt-1 leading-relaxed">
                {canAnswerReason}
              </div>
            )}
            {missingItems && missingItems.length > 0 && (
              <ul className="mt-2 space-y-1">
                {missingItems.map((item, i) => (
                  <li key={i} className="flex items-center gap-1.5 text-xs text-amber-600">
                    <Info className="w-3 h-3 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── 成功 + 不可回答 ──
  if (runStatus === 'success' && !canAnswer) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <XCircle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-red-700">
              暂不能回答：缺少必要结算字段或政策依据
            </div>
            {canAnswerReason && (
              <div className="text-sm text-red-600 mt-1 leading-relaxed">
                {canAnswerReason}
              </div>
            )}
            {missingItems && missingItems.length > 0 && (
              <ul className="mt-2 space-y-1">
                {missingItems.map((item, i) => (
                  <li key={i} className="flex items-center gap-1.5 text-xs text-red-600">
                    <Info className="w-3 h-3 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    )
  }

  // 默认空渲染
  return null
}
