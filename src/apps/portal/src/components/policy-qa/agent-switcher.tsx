'use client'

import type { ReactNode } from 'react'
import { MessageSquare, ReceiptText, BarChart3 } from 'lucide-react'

/**
 * V4.0 智能体中心：智能体切换器。
 *
 * 三个智能体 chip（图标 + 名字 + 身份色描边），当前高亮；身份色只用于
 * 切换器与高亮态，不侵入工作区内部（设计 §6.2）。
 */

export type AgentId = 'policy' | 'settlement' | 'ops'

export interface AgentMeta {
  id: AgentId
  label: string
  icon: ReactNode
  /** 激活态完整静态类（Tailwind JIT 需完整类名，禁模板拼接） */
  activeClass: string
}

export const AGENTS: AgentMeta[] = [
  {
    id: 'policy',
    label: '政策问答',
    icon: <MessageSquare className="size-3.5" aria-hidden />,
    activeClass:
      'border-agent-policy/40 bg-white text-agent-policy ring-1 ring-agent-policy/20',
  },
  {
    id: 'settlement',
    label: '结算解释',
    icon: <ReceiptText className="size-3.5" aria-hidden />,
    activeClass:
      'border-agent-settlement/40 bg-white text-agent-settlement ring-1 ring-agent-settlement/20',
  },
  {
    id: 'ops',
    label: '运营问数',
    icon: <BarChart3 className="size-3.5" aria-hidden />,
    activeClass: 'border-agent-ops/40 bg-white text-agent-ops ring-1 ring-agent-ops/20',
  },
]

interface AgentSwitcherProps {
  agent: AgentId
  onChange: (agent: AgentId) => void
  /** 任一智能体流式回答中时锁定切换，避免中断在途回答 */
  disabled?: boolean
}

export default function AgentSwitcher({ agent, onChange, disabled = false }: AgentSwitcherProps) {
  return (
    <nav
      aria-label="智能体切换"
      data-testid="agent-switcher"
      className="mb-6 flex items-center justify-center gap-1 rounded-full border border-slate-200 bg-white p-1 shadow-sm"
    >
      {AGENTS.map((meta) => {
        const active = agent === meta.id
        return (
          <button
            key={meta.id}
            type="button"
            onClick={() => onChange(meta.id)}
            disabled={disabled}
            aria-pressed={active}
            data-testid={`agent-switcher-${meta.id}`}
            className={[
              'inline-flex items-center gap-1.5 rounded-full border px-4 py-1.5 text-sm font-medium transition-colors',
              active
                ? meta.activeClass
                : 'border-transparent text-slate-600 hover:bg-slate-100',
              disabled ? 'cursor-not-allowed opacity-50' : 'active:scale-[0.98]',
            ].join(' ')}
          >
            {meta.icon}
            {meta.label}
          </button>
        )
      })}
    </nav>
  )
}
