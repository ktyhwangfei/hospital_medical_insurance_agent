'use client'

import { usePathname, useRouter } from 'next/navigation'
import { LayoutDashboard, FileText, Anchor, Lightbulb, FlaskConical } from 'lucide-react'

interface NavTab {
  label: string
  href: string
  icon: React.ComponentType<{ className?: string }>
}

// 政策知识治理平台 · 测试位于知识之后，门禁通过并人工发布后才对外生效。
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.1]
const NAV_TABS: NavTab[] = [
  { label: '概览', href: '/policy-knowledge', icon: LayoutDashboard },
  { label: '文档', href: '/policy-knowledge/documents', icon: FileText },
  { label: '单元', href: '/policy-knowledge/units', icon: Anchor },
  { label: '知识', href: '/policy-knowledge/knowledge', icon: Lightbulb },
  { label: '测试', href: '/policy-knowledge/test', icon: FlaskConical },
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

      <main className="mx-auto w-full max-w-[1440px] p-6">
        {/* 治理平台标题 + Tab Navigation */}
        <div className="mb-4 flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-3 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            政策知识治理
          </span>
          <span className="text-xs text-slate-400">质量 · 版本 · 审核 · 发布 · 追踪 · 影响分析</span>
        </div>
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
