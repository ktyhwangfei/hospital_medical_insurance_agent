import { useEffect, useState, type KeyboardEvent } from 'react'
import { Search } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { SkillGovernanceStage, SkillWorkbenchItem } from '@/lib/types'

interface SkillCatalogPanelProps {
  items: SkillWorkbenchItem[]
  selectedSkillId: string | null
  query: string
  businessAction: string
  businessObject: string
  loading: boolean
  hasActiveFilters: boolean
  hiddenOnMobile?: boolean
  onQueryChange: (query: string) => void
  onBusinessActionChange: (action: string) => void
  onBusinessObjectChange: (object: string) => void
  onClearFilters: () => void
  onSelect: (skillId: string) => void
}

const stageLabels: Record<SkillGovernanceStage, string> = {
  evaluate: '待评测',
  diagnose: '待定位',
  modify: '待修改',
  review: '待复审',
  release: '待发布',
  healthy: '健康',
}

export function waitingLabel(waitingSince: string, now = Date.now()): string {
  const parsed = Date.parse(waitingSince)
  if (Number.isNaN(parsed)) return '刚刚进入待办'
  const hours = Math.max(Math.floor((now - parsed) / 3_600_000), 0)
  if (hours < 1) return '刚刚进入待办'
  if (hours < 24) return `等待 ${hours} 小时`
  return `等待 ${Math.floor(hours / 24)} 天`
}

function StageBadge({ stage }: { stage: SkillGovernanceStage }) {
  const tone = stage === 'healthy'
    ? 'bg-emerald-50 text-emerald-700'
    : stage === 'diagnose'
      ? 'bg-red-50 text-red-700'
      : stage === 'review' || stage === 'release'
        ? 'bg-amber-50 text-amber-700'
        : 'bg-blue-50 text-blue-700'
  return <span className={cn('shrink-0 rounded px-2 py-0.5 text-[11px] font-medium', tone)}>{stageLabels[stage]}</span>
}

export default function SkillCatalogPanel({
  items,
  selectedSkillId,
  query,
  businessAction,
  businessObject,
  loading,
  hasActiveFilters,
  hiddenOnMobile = false,
  onQueryChange,
  onBusinessActionChange,
  onBusinessObjectChange,
  onClearFilters,
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
    <div data-skill-queue className={cn('min-h-0 flex-col border-r border-slate-200 bg-white md:flex', hiddenOnMobile ? 'hidden' : 'flex')}>
      <div className="space-y-3 border-b border-slate-200 p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
          <Input
            id="skill-queue-search"
            aria-label="搜索 Skill"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索名称或 ID"
            className="h-11 pl-8 sm:h-9"
          />
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label className="sr-only" htmlFor="skill-action-filter">业务动作</label>
          <select
            id="skill-action-filter"
            value={businessAction}
            onChange={(event) => onBusinessActionChange(event.target.value)}
            className="h-11 rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-600 sm:h-9 sm:text-xs"
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
            className="h-11 rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-600 sm:h-9 sm:text-xs"
          >
            <option value="">全部对象</option>
            <option value="settlement">结算</option>
            <option value="benefit">待遇</option>
            <option value="policy">政策</option>
            <option value="directory">目录</option>
          </select>
        </div>
      </div>
      <nav aria-label="治理待办" className="min-h-0 flex-1 overflow-y-auto" onKeyDown={moveFocus}>
        {loading && items.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">正在加载 Skill…</p>
        ) : items.length === 0 && hasActiveFilters ? (
          <div className="space-y-3 p-4 text-sm text-slate-500">
            <p>没有符合筛选条件的 Skill</p>
            <button
              type="button"
              onClick={() => {
                setSearch('')
                onClearFilters()
              }}
              className="min-h-11 font-medium text-blue-600 hover:text-blue-700"
            >
              清除筛选
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="space-y-3 p-4 text-sm text-slate-500">
            <p>当前没有需要处理的 Skill</p>
          </div>
        ) : items.map((item) => {
          const selected = item.skill_id === selectedSkillId
          return (
            <button
              key={item.skill_id}
              type="button"
              data-skill-catalog-button
              data-skill-id={item.skill_id}
              data-testid={`skill-catalog-item-${item.skill_id}`}
              aria-current={selected ? 'true' : undefined}
              onClick={() => onSelect(item.skill_id)}
              className={cn(
                'w-full border-l-2 px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
                selected ? 'border-blue-600 bg-blue-50' : 'border-transparent hover:bg-slate-50',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0 break-words text-sm font-medium text-slate-900">{item.skill_name}</span>
                <StageBadge stage={item.current_stage} />
              </div>
              {item.next_action_reason && (
                <p className="mt-2 line-clamp-2 break-words text-xs leading-5 text-slate-600">{item.next_action_reason}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-xs text-slate-500">
                {item.candidate_version ? (
                  <span>候选 v{item.candidate_version}</span>
                ) : item.linked_draft_status ? (
                  <span>草稿 {item.linked_draft_status}</span>
                ) : <span />}
                <span>{waitingLabel(item.waiting_since)}</span>
              </div>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
