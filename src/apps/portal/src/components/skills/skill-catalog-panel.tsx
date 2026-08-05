import { useEffect, useState, type KeyboardEvent } from 'react'
import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { SkillGovernanceStatus, SkillWorkbenchItem } from '@/lib/types'

interface SkillCatalogPanelProps {
  items: SkillWorkbenchItem[]
  selectedSkillId: string | null
  query: string
  businessAction: string
  businessObject: string
  loading: boolean
  onQueryChange: (query: string) => void
  onBusinessActionChange: (action: string) => void
  onBusinessObjectChange: (object: string) => void
  onSelect: (skillId: string) => void
}

const statusLabels: Record<SkillGovernanceStatus, string> = {
  gate_failed: '门禁失败',
  pending_approval: '待审批',
  needs_evaluation: '需评测',
  artifact_changed: '制品变更',
  healthy: '健康',
}

function GovernanceStatusBadge({ status }: { status: SkillGovernanceStatus }) {
  const tone = status === 'healthy'
    ? 'bg-emerald-50 text-emerald-700'
    : status === 'gate_failed'
      ? 'bg-red-50 text-red-700'
      : status === 'pending_approval'
        ? 'bg-amber-50 text-amber-700'
        : 'bg-blue-50 text-blue-700'
  return <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium', tone)}>{statusLabels[status]}</span>
}

function statusHint(item: SkillWorkbenchItem): string {
  if (item.latest_eval_status === 'passed') return '评测通过'
  if (item.artifact_status !== 'registered') return '待登记'
  if (item.governance_status === 'needs_evaluation') return '尚未评测'
  return statusLabels[item.governance_status]
}

export default function SkillCatalogPanel({
  items,
  selectedSkillId,
  query,
  businessAction,
  businessObject,
  loading,
  onQueryChange,
  onBusinessActionChange,
  onBusinessObjectChange,
  onSelect,
}: SkillCatalogPanelProps) {
  const [search, setSearch] = useState(query)

  useEffect(() => {
    const nextQuery = search.trim()
    if (nextQuery === query) return
    const timeout = window.setTimeout(() => onQueryChange(nextQuery), 250)
    return () => window.clearTimeout(timeout)
  }, [onQueryChange, query, search])

  function moveFocus(event: KeyboardEvent<HTMLElement>): void {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-skill-catalog-button]'))
    const currentIndex = buttons.indexOf(document.activeElement as HTMLButtonElement)
    const delta = event.key === 'ArrowDown' ? 1 : -1
    const nextIndex = Math.min(Math.max(currentIndex + delta, 0), buttons.length - 1)
    if (buttons[nextIndex]) {
      event.preventDefault()
      buttons[nextIndex].focus()
    }
  }

  return (
    <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-white" aria-label="Skill 目录">
      <div className="space-y-3 border-b border-slate-200 p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
          <Input
            aria-label="搜索 Skill"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索名称或 ID"
            className="pl-8"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="sr-only" htmlFor="skill-action-filter">业务动作</label>
          <select
            id="skill-action-filter"
            value={businessAction}
            onChange={(event) => onBusinessActionChange(event.target.value)}
            className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600"
          >
            <option value="">全部动作</option>
            <option value="explain">解释</option>
            <option value="query">查询</option>
            <option value="guide">导办</option>
            <option value="verify">核验</option>
            <option value="compare">对比</option>
            <option value="evaluate">评估</option>
            <option value="analyze">分析</option>
          </select>
          <label className="sr-only" htmlFor="skill-object-filter">业务对象</label>
          <select
            id="skill-object-filter"
            value={businessObject}
            onChange={(event) => onBusinessObjectChange(event.target.value)}
            className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600"
          >
            <option value="">全部对象</option>
            <option value="settlement">结算</option>
            <option value="benefit">待遇</option>
            <option value="policy">政策</option>
            <option value="directory">目录</option>
          </select>
        </div>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto" onKeyDown={moveFocus}>
        {loading && items.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">正在加载 Skill…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">没有符合条件的 Skill</p>
        ) : items.map((item) => {
          const selected = item.skill_id === selectedSkillId
          return (
            <button
              key={item.skill_id}
              type="button"
              data-skill-catalog-button
              data-testid={`skill-catalog-item-${item.skill_id}`}
              aria-current={selected ? 'true' : undefined}
              onClick={() => onSelect(item.skill_id)}
              className={cn(
                'w-full border-l-2 px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                selected ? 'border-blue-600 bg-blue-50' : 'border-transparent hover:bg-slate-50',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="truncate text-sm font-medium text-slate-900">{item.skill_name}</span>
                <GovernanceStatusBadge status={item.governance_status} />
              </div>
              <div className="mt-1 truncate font-mono text-xs text-slate-500">{item.skill_id}</div>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                <span>v{item.semantic_version}</span>
                <span>{item.test_release_status === 'active' ? 'Test Active' : statusHint(item)}</span>
              </div>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
