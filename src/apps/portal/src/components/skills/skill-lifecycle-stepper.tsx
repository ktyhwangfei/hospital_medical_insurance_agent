import { Check, Circle } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { SkillGovernanceStage, SkillWorkbenchItem, SkillWorkbenchTab } from '@/lib/types'

export type LifecycleVisualState = 'completed' | 'current' | 'blocked' | 'pending'

export interface LifecycleStep {
  stage: Exclude<SkillGovernanceStage, 'healthy'>
  tab: SkillWorkbenchTab
  label: string
  state: LifecycleVisualState
  description: string
}

const stages: Array<Omit<LifecycleStep, 'state'>> = [
  { stage: 'evaluate', tab: 'evaluation', label: '评测', description: '运行固定评测' },
  { stage: 'diagnose', tab: 'evaluation', label: '定位问题', description: '查看差异证据' },
  { stage: 'modify', tab: 'development', label: '修改', description: '修复候选制品' },
  { stage: 'review', tab: 'release', label: '复审', description: '进入人工复审' },
  { stage: 'release', tab: 'release', label: '发布', description: '激活 Test Shadow' },
]

const stateLabels: Record<LifecycleVisualState, string> = {
  completed: '已完成',
  current: '当前阶段',
  blocked: '已阻断',
  pending: '待处理',
}

export function lifecycleSteps(item: SkillWorkbenchItem): LifecycleStep[] {
  const currentIndex = stages.findIndex((step) => step.stage === item.current_stage)
  return stages.map((step, index) => ({
    ...step,
    state: item.current_stage === 'healthy'
      ? 'completed'
      : currentIndex < 0
        ? 'pending'
        : index < currentIndex
          ? 'completed'
          : index === currentIndex ? 'current' : 'pending',
  }))
}

interface SkillLifecycleStepperProps {
  item: SkillWorkbenchItem
  onNavigate: (tab: SkillWorkbenchTab) => void
}

export default function SkillLifecycleStepper({ item, onNavigate }: SkillLifecycleStepperProps) {
  return (
    <ol aria-label="Skill 治理阶段" className="grid grid-cols-1 divide-y divide-slate-200 border-b border-slate-200 sm:grid-cols-5 sm:divide-x sm:divide-y-0">
      {lifecycleSteps(item).map((step) => (
        <li key={step.stage}>
          <button
            type="button"
            aria-current={step.state === 'current' ? 'step' : undefined}
            onClick={() => onNavigate(step.tab)}
            className="flex min-h-11 w-full items-center gap-2 px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
          >
            <span className={cn(
              'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
              step.state === 'completed' && 'border-emerald-600 bg-emerald-600 text-white',
              step.state === 'current' && 'border-blue-600 text-blue-600',
              step.state === 'pending' && 'border-slate-300 text-slate-400',
            )}>
              {step.state === 'completed' ? <Check className="h-3 w-3" aria-hidden /> : <Circle className="h-2.5 w-2.5" aria-hidden />}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-slate-900">{step.label}</span>
              <span className="block text-xs text-slate-500">{stateLabels[step.state]}</span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
