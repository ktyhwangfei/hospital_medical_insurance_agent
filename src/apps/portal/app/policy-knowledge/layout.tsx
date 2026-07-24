'use client'

import { usePathname, useRouter } from 'next/navigation'
import { LayoutDashboard, FileText, GitBranch, Database, Search } from 'lucide-react'

interface NavTab {
  label: string
  href: string
  icon: React.ComponentType<{ className?: string }>
}

const NAV_TABS: NavTab[] = [
  { label: '管线概览', href: '/policy-knowledge', icon: LayoutDashboard },
  { label: '政策原文', href: '/policy-knowledge/documents', icon: FileText },
  { label: '规则提取', href: '/policy-knowledge/extractions', icon: GitBranch },
  { label: '已入库规则', href: '/policy-knowledge/rules', icon: Database },
  { label: '知识检索', href: '/policy-knowledge/search', icon: Search },
]

function getActiveTab(pathname: string): string {
  if (pathname === '/policy-knowledge') return '/policy-knowledge'
  for (const tab of NAV_TABS) {
    if (tab.href !== '/policy-knowledge' && pathname.startsWith(tab.href)) return tab.href
  }
  return '/policy-knowledge'
}

export default function PolicyKnowledgeLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const currentTab = getActiveTab(pathname)

  return (
    <div className="relative min-h-screen">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.12),transparent_55%),radial-gradient(ellipse_at_bottom,rgba(14,165,233,0.08),transparent_50%)]" />
        <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,rgba(15,23,42,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.05)_1px,transparent_1px)] [background-size:44px_44px]" />
      </div>

      <main className="mx-auto w-full max-w-[1200px] p-6">
        {/* Tab Navigation */}
        <nav className="flex w-full items-center gap-1 border-b border-slate-200 mb-6">
          {NAV_TABS.map((tab) => {
            const Icon = tab.icon
            const active = currentTab === tab.href
            return (
              <button
                key={tab.href}
                type="button"
                onClick={() => router.push(tab.href)}
                className={
                  "flex items-center gap-2 rounded-none px-4 py-2.5 text-sm font-medium transition-colors " +
                  (active
                    ? "border-b-2 border-blue-600 text-blue-600"
                    : "text-slate-500 hover:text-slate-700")
                }
              >
                <Icon className="size-4" />
                {tab.label}
              </button>
            )
          })}
        </nav>

        {children}
      </main>
    </div>
  )
}
