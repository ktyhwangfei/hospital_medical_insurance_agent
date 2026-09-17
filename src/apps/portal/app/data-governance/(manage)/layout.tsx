'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const tabs = [
  { href: '/data-governance', label: '运行概览' },
  { href: '/data-governance/data-sources', label: '数据接入' },
  { href: '/data-governance/profiling', label: '数据探查' },
  { href: '/data-governance/sync-jobs', label: '数据同步' },
  { href: '/data-governance/modeling', label: '数据建模' },
  { href: '/data-governance/flows', label: '数据加工' },
  { href: '/data-governance/quality', label: '质量与发布' },
  { href: '/data-governance/assets', label: '数据资产' },
]

export default function DataGovernanceLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  return <section className="mx-auto flex min-w-0 max-w-7xl flex-col gap-5">
    <header>
      <h1 className="text-xl font-semibold tracking-tight text-slate-900">数据治理中心</h1>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
        数据资产生命周期：数据接入 → 数据探查 → 数据同步 → 数据建模 → 数据加工 → 质量与发布 → 数据资产；语义标准横向贯穿全流程。
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
