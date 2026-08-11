'use client'

import { ArrowRight, Loader2, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { PrimaryAction } from './skill-primary-action'

interface SkillNextActionBarProps {
  action: PrimaryAction
  reason: string | null
  busy: boolean
  readOnly?: boolean
  error: string | null
  onRun: () => void
  onViewEvidence: () => void
}

export default function SkillNextActionBar({
  action,
  reason,
  busy,
  readOnly,
  error,
  onRun,
  onViewEvidence,
}: SkillNextActionBarProps) {
  const unavailable = action.kind === 'none'
  const writeDisabled = action.kind !== 'navigate' && readOnly

  return (
    <section
      aria-label="下一步治理动作"
      data-status={unavailable ? 'unavailable' : 'runnable'}
      className="sticky bottom-0 z-10 flex flex-col gap-3 border-t border-slate-200 bg-white px-4 py-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-900">{unavailable ? action.label : '建议下一步'}</p>
        <p className="mt-1 whitespace-normal break-words text-xs leading-5 text-slate-600">
          {reason ?? action.hint}
        </p>
        {error && <p role="alert" className="mt-1 whitespace-normal break-words text-xs leading-5 text-red-600">{error}</p>}
      </div>
      <div className="flex shrink-0 flex-col-reverse gap-2 sm:flex-row">
        <Button variant="outline" className="min-h-11 sm:min-h-9 2xl:hidden" onClick={onViewEvidence}>
          <Search aria-hidden /> 查看治理证据
        </Button>
        {!unavailable && (
          <Button
            className="min-h-11 sm:min-h-9"
            data-testid="skill-primary-action"
            disabled={busy || writeDisabled}
            onClick={onRun}
          >
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
            {action.label}
          </Button>
        )}
      </div>
    </section>
  )
}
