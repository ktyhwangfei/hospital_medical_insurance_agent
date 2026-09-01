'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const tabs = [
  { href: '/data-governance', label: '运行概览' },
  { href: '/data-governance/data-sources', label: '数据源' },
  { href: '/data-governance/sync-jobs', label: '同步任务' },
]

export default function DataGovernanceLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  return <section className="mx-auto flex min-w-0 max-w-7xl flex-col gap-5">
    <header>
      <h1 className="text-xl font-semibold tracking-tight text-slate-900">数据治理中心</h1>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
        管理医院门诊数据接入、CDC 或定时 SQL 同步，并查看数据质量与运行状态。
      </p>
    </header>
    <nav aria-label="数据治理导航" className="flex gap-1 border-b border-slate-200">
      {tabs.map((tab) => {
        const active = tab.href === '/data-governance'
          ? pathname === tab.href
          : pathname.startsWith(tab.href)
        return <Link
          key={tab.href}
          href={tab.href}
          aria-current={active ? 'page' : undefined}
          className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            active
              ? 'border-blue-600 text-blue-700'
              : 'border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900'
          }`}
        >{tab.label}</Link>
      })}
    </nav>
    {children}
  </section>
}
