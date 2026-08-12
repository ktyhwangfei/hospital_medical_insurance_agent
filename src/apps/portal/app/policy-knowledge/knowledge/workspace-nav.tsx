'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const WORKSPACES = [
  { label: '知识构建', href: '/policy-knowledge/knowledge/build' },
  { label: '知识审核', href: '/policy-knowledge/knowledge/review' },
  { label: '发布管理', href: '/policy-knowledge/knowledge/releases' },
  { label: '语义发现', href: '/policy-knowledge/knowledge/semantic-discovery' },
] as const

export function WorkspaceNav() {
  const pathname = usePathname()

  return (
    <nav aria-label="知识治理工作区" className="border-b border-slate-200">
      <div className="flex items-center gap-6 overflow-x-auto">
        {WORKSPACES.map(({ label, href }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`)

          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? 'page' : undefined}
              className={`whitespace-nowrap border-b-2 pb-2.5 pt-1 text-sm tracking-tight transition-colors ${
                active
                  ? 'border-emerald-600 font-semibold text-emerald-700'
                  : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800'
              }`}
            >
              {label}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}

export function riskColor(level: string): string {
  switch (level) {
    case 'CRITICAL': return 'bg-red-50 text-red-700'
    case 'HIGH': return 'bg-red-50 text-red-600'
    case 'MEDIUM': return 'bg-amber-50 text-amber-700'
    default: return 'bg-slate-100 text-slate-600'
  }
}

export function riskLabel(level: string): string {
  switch (level) {
    case 'CRITICAL': return '重大'
    case 'HIGH': return '高'
    case 'MEDIUM': return '中'
    default: return '低'
  }
}
