import { Check, Circle, LockKeyhole } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { SkillWorkbenchItem, SkillWorkbenchTab } from '@/lib/types'

export type LifecycleVisualState = 'completed' | 'current' | 'blocked' | 'pending'

export interface LifecycleStep {
  tab: SkillWorkbenchTab
  label: string
  state: LifecycleVisualState
  description: string
}

function buildStep(
  tab: SkillWorkbenchTab,
  label: string,
  completed: boolean,
  current: boolean,
  blocked: boolean,
  description: string,
): LifecycleStep {
  return {
    tab,
    label,
    state: completed ? 'completed' : blocked ? 'blocked' : current ? 'current' : 'pending',
    description,
  }
}

const attentionLabels: Record<string, string> = {
  latest_evaluation_failed: '最近评测未通过，请检查回归证据',
  approval_required: '评测已通过，等待人工审批',
  passed_evaluation_required: '需要先通过当前版本的固定评测',
  artifact_not_registered: '当前制品已变化，需要重新登记',
}

const completedDescriptions: Record<string, string> = {
  '版本登记': '制品已登记并通过校验',
  '批量评测': '当前固定评测已通过',
  '人工审批': '人工审批证据已冻结',
  'Test 激活': 'Test Shadow 已激活',
}

export function lifecycleSteps(item: SkillWorkbenchItem): LifecycleStep[] {
  const registered = item.artifact_status === 'registered' && item.validation_status === 'passed'
  const evaluated = item.latest_eval_status === 'passed'
  const approved = item.test_release_status === 'approved' || item.test_release_status === 'active'
  const active = item.test_release_status === 'active'
  const blockedDescription = item.attention_reason
    ? attentionLabels[item.attention_reason] ?? '请查看评测证据'
    : '需要通过当前固定评测'
  return [
    buildStep('versions', '版本登记', registered, !registered, false, '需要登记并校验当前制品'),
    buildStep(
      'evaluation',
      '批量评测',
      evaluated,
      registered && !evaluated,
      item.governance_status === 'gate_failed',
      item.governance_status === 'gate_failed' ? blockedDescription : '需要通过当前固定评测',
    ),
    buildStep('release', '人工审批', approved, evaluated && !approved, false, '需要不同身份人工审批'),
    buildStep('release', 'Test 激活', active, approved && !active, false, '等待激活 Test Shadow'),
  ]
}

interface SkillLifecycleStepperProps {
  item: SkillWorkbenchItem
  onNavigate: (tab: SkillWorkbenchTab) => void
}

export default function SkillLifecycleStepper({ item, onNavigate }: SkillLifecycleStepperProps) {
  return (
    <ol aria-label="Skill 生命周期" className="grid gap-2 border-b border-slate-200 bg-slate-50/70 p-4 lg:grid-cols-4">
      {lifecycleSteps(item).map((step, index) => (
        <li key={`${step.label}-${index}`}>
          <button
            type="button"
            aria-current={step.state === 'current' ? 'step' : undefined}
            onClick={() => onNavigate(step.tab)}
            className={cn(
              'flex w-full items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
              step.state === 'completed' && 'border-emerald-200 bg-emerald-50/70',
              step.state === 'current' && 'border-blue-300 bg-blue-50',
              step.state === 'blocked' && 'border-red-200 bg-red-50',
              step.state === 'pending' && 'border-slate-200 bg-white/70',
            )}
          >
            <span className={cn(
              'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
              step.state === 'completed' ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-current',
              step.state === 'current' && 'text-blue-600',
              step.state === 'blocked' && 'text-red-600',
              step.state === 'pending' && 'text-slate-400',
            )}>
              {step.state === 'completed' ? <Check className="h-3 w-3" /> : step.state === 'blocked' ? <LockKeyhole className="h-3 w-3" /> : <Circle className="h-2.5 w-2.5" />}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-slate-900">{step.label}</span>
              <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                {step.state === 'completed' ? completedDescriptions[step.label] : step.description}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
