import { RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface SkillWorkbenchHeaderProps {
  environment: 'dev' | 'test'
  onEnvironmentChange: (environment: 'dev' | 'test') => void
  onOpenRouteTest: () => void
  onRefresh: () => void
}

export default function SkillWorkbenchHeader({
  environment,
  onEnvironmentChange,
  onOpenRouteTest,
  onRefresh,
}: SkillWorkbenchHeaderProps) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-950">Skill 管理</h1>
        <p className="mt-1 text-sm text-slate-500">版本证据、固定评测与 Test Shadow 发布治理</p>
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor="skill-environment" className="sr-only">Skill 环境</label>
        <select
          id="skill-environment"
          value={environment}
          onChange={(event) => onEnvironmentChange(event.target.value as 'dev' | 'test')}
          className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700"
        >
          <option value="test">test</option>
          <option value="dev">dev（只读）</option>
        </select>
        <Button variant="outline" onClick={onOpenRouteTest}>路由调试</Button>
        <Button variant="ghost" size="icon" aria-label="同步状态" onClick={onRefresh}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
