import { RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { SkillGovernancePriority } from '@/lib/types'

interface SkillWorkbenchHeaderProps {
  environment: 'dev' | 'test'
  priority: SkillGovernancePriority | null
  prioritySuspended: boolean
  onEnvironmentChange: (environment: 'dev' | 'test') => void
  onPriorityChange: (priority: SkillGovernancePriority | null) => void
  onOpenRouteTest: () => void
  onRefresh: () => void
}

export default function SkillWorkbenchHeader({
  environment,
  priority,
  prioritySuspended,
  onEnvironmentChange,
  onPriorityChange,
  onOpenRouteTest,
  onRefresh,
}: SkillWorkbenchHeaderProps) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-950 md:text-2xl">Skill 日常治理</h1>
        <p className="mt-1 text-sm text-slate-500">按优先级处理评测、复审与发布待办</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center sm:justify-end">
        <label htmlFor="skill-environment" className="sr-only">Skill 环境</label>
        <select
          id="skill-environment"
          value={environment}
          onChange={(event) => onEnvironmentChange(event.target.value as 'dev' | 'test')}
          className="h-11 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 sm:h-9"
        >
          <option value="test">test</option>
          <option value="dev">dev（只读）</option>
        </select>
        <label htmlFor="skill-priority" className="sr-only">待办优先级</label>
        <select
          id="skill-priority"
          value={priority ?? ''}
          disabled={prioritySuspended}
          onChange={(event) => onPriorityChange((event.target.value || null) as SkillGovernancePriority | null)}
          className="h-11 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 sm:h-9"
        >
          <option value="">全部优先级</option>
          <option value="blocked">阻断</option>
          <option value="high">高</option>
          <option value="normal">普通</option>
        </select>
        <Button variant="outline" className="h-11 sm:h-9" onClick={onOpenRouteTest}>路由调试</Button>
        <Button variant="ghost" size="icon" className="size-11 sm:size-9" aria-label="同步状态" onClick={onRefresh}>
          <RefreshCw className="h-4 w-4" />
        </Button>
        {prioritySuspended && (
          <p role="status" className="col-span-2 text-xs text-amber-700 sm:basis-full sm:text-right">
            目录降级未应用治理优先级
          </p>
        )}
      </div>
    </header>
  )
}
