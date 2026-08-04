'use client'

/**
 * ReasoningChainCollapsible —— AI 回复下的推理链折叠组件
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §4.2/§5.2
 * - 消费 reasoning_step 累积 + result.reasoning_steps 定稿的推理链
 * - 按 kind 语义色区分：fact（事实）/ inference（推理）/ hypothesis（假设）/ verified（已验证）
 * - 默认折叠，点击展开
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { ReasoningStep } from '@/lib/policy-qa-session'

// ── Props ────────────────────────────────────────────────────

interface ReasoningChainCollapsibleProps {
  steps: ReasoningStep[]
  /** 默认展开状态（调试友好） */
  defaultOpen?: boolean
}

// ── kind 配置 ────────────────────────────────────────────────

const KIND_CONFIG: Record<string, { label: string; badge: string; dot: string }> = {
  fact: { label: '事实', badge: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500' },
  inference: { label: '推理', badge: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500' },
  hypothesis: { label: '假设', badge: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500' },
  verified: { label: '已验证', badge: 'bg-violet-100 text-violet-700', dot: 'bg-violet-500' },
}

function kindConfig(kind: string) {
  return (
    KIND_CONFIG[kind] ?? {
      label: kind,
      badge: 'bg-slate-100 text-slate-600',
      dot: 'bg-slate-400',
    }
  )
}

// ── Component ────────────────────────────────────────────────

export default function ReasoningChainCollapsible({
  steps,
  defaultOpen = false,
}: ReasoningChainCollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen)
  if (steps.length === 0) return null

  return (
    <div
      data-testid="reasoning-chain"
      className="w-full overflow-hidden rounded-xl border border-slate-200/70 bg-slate-50/70"
    >
      {/* 头部：折叠开关 + 步数 */}
      <button
        type="button"
        data-testid="reasoning-chain-toggle"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-[11px] font-normal text-slate-400 transition-colors hover:text-slate-600"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {open ? '收起依据' : '查看依据'}
      </button>

      {/* 步骤列表（垂直时间线） */}
      {open && (
        <div className="border-t border-slate-200/60 px-3 py-2" data-testid="reasoning-steps">
          {steps.map((step, idx) => {
            const cfg = kindConfig(step.kind)
            return (
              <div key={step.stepId || idx} className="flex gap-2.5 pb-2 last:pb-0" data-testid="reasoning-step">
                {/* 时间线 + 语义色圆点 */}
                <div className="flex flex-col items-center">
                  <span className={`mt-1 size-2 shrink-0 rounded-full ${cfg.dot}`} />
                  {idx < steps.length - 1 && <span className="w-px flex-1 bg-slate-200" />}
                </div>
                <div className="min-w-0 flex-1 pb-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${cfg.badge}`}>
                      {cfg.label}
                    </span>
                    {typeof step.confidence === 'number' && (
                      <span className="font-mono text-[10px] text-slate-400">
                        {Math.round(step.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs leading-relaxed text-slate-700">{step.claim}</div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
