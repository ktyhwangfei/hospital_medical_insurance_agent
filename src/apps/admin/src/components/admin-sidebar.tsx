'use client'

import { useState } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  Home,
  Cpu,
  BookOpen,
  Brain,
  Wrench,
  ChevronLeft,
  ChevronRight,
  Shield,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface NavItem {
  id: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  href: string
}

interface NavSection {
  title: string
  items: NavItem[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: '平台管理',
    items: [
      { id: 'home', label: '首页', icon: Home, href: '/' },
      { id: 'mcp', label: 'MCP管理', icon: Cpu, href: '/mcp' },
      { id: 'knowledge', label: '知识管理', icon: BookOpen, href: '/knowledge' },
      { id: 'model', label: '模型管理', icon: Brain, href: '/model' },
      { id: 'skills', label: '技能管理', icon: Wrench, href: '/skills' },
    ],
  },
]

export default function AdminSidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const pathname = usePathname()

  return (
    <aside
      className={cn(
        'flex flex-col border-r border-slate-200 bg-white transition-all duration-300 shrink-0',
        collapsed ? 'w-14' : 'w-58'
      )}
    >
      {/* Logo area */}
      <div className="flex h-14 items-center border-b border-slate-100 px-3">
        {!collapsed ? (
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-blue-700 shadow-sm">
              <Shield className="size-3.5 text-white" />
            </div>
            <span className="truncate text-sm font-semibold text-slate-800">
              管理控制台
            </span>
          </div>
        ) : (
          <div className="flex w-full justify-center">
            <div className="flex size-7 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-blue-700 shadow-sm">
              <Shield className="size-3.5 text-white" />
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="mb-4">
            {!collapsed && (
              <p className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {section.title}
              </p>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const Icon = item.icon
                const isActive =
                  item.href === '/'
                    ? pathname === '/'
                    : pathname.startsWith(item.href)
                return (
                  <Link
                    key={item.id}
                    href={item.href}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-2 py-2 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                      collapsed && 'justify-center px-0'
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon className="size-4 shrink-0" />
                    {!collapsed && <span>{item.label}</span>}
                  </Link>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-slate-100 p-3">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className={cn(
            'flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors',
            collapsed ? 'w-full py-2' : 'w-full gap-2 py-2'
          )}
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
        >
          {collapsed ? (
            <ChevronRight className="size-4" />
          ) : (
            <>
              <ChevronLeft className="size-4" />
              <span className="text-xs">收起</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
