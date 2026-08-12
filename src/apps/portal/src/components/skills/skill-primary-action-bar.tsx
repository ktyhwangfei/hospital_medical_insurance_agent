'use client'

import { ArrowRight, CheckCircle2, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { PrimaryAction } from './skill-primary-action'

interface SkillPrimaryActionBarProps {
  action: PrimaryAction
  busy: boolean
  /** dev 环境只读：禁用写操作按钮 */
  readOnly?: boolean
  error: string | null
  onRun: () => void
}

// 顶层主动作条：把"下一个治理动作"从 Tab 里提到工作台最上层，选中 Skill 即一键执行。
// 设计：单一强调色（蓝=可执行 / 琥珀=需查看 / 翠绿=已完成），不堆卡片，留白收紧层级。
export default function SkillPrimaryActionBar({
  action,
  busy,
  readOnly,
  error,
  onRun,
}: SkillPrimaryActionBarProps) {
  const done = action.kind === 'none'
  const navigate = action.kind === 'navigate'
  const tone = done ? 'emerald' : navigate ? 'amber' : 'blue'

  const toneWrap = {
    blue: 'bg-blue-50/60 border-blue-100',
    amber: 'bg-amber-50/60 border-amber-100',
    emerald: 'bg-emerald-50/60 border-emerald-100',
  }[tone]

  const toneIcon = {
    blue: 'text-blue-600',
    amber: 'text-amber-600',
    emerald: 'text-emerald-600',
  }[tone]

  // dev 环境工作台只读：写操作禁用（navigate/完成态不受影响）
  const writeDisabled = !done && !navigate && readOnly

  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4', toneWrap)}>
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          {done ? (
            <CheckCircle2 className={cn('h-4 w-4', toneIcon)} aria-hidden />
          ) : null}
          <span>{action.label}</span>
        </div>
        <p className="mt-0.5 truncate text-xs text-slate-500">{action.hint}</p>
        {error ? (
          <p role="alert" className="mt-1 text-xs text-red-600">
            {error}
          </p>
        ) : null}
      </div>

      {!done ? (
        <Button
          onClick={onRun}
          disabled={busy || writeDisabled}
          data-testid="skill-primary-action"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <ArrowRight className="h-4 w-4" aria-hidden />
          )}
          {navigate ? '前往查看' : action.label}
        </Button>
      ) : null}
    </div>
  )
}
