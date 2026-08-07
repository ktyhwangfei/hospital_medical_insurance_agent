'use client'

import { usePathname, useRouter } from 'next/navigation'

interface NavTab {
  label: string
  href: string
  match: (pathname: string) => boolean
}

// 顶部保留子路径：不能被当成 Skill 详情页
const RESERVED_SEGS = new Set(['drafts', 'evaluations', 'releases', 'new', 'import'])

// /skills/<skillId> 或 /skills/<skillId>/edit（排除保留路径，否则 /skills/drafts 等会被误判为 Skill 详情）
function isSkillDetailPath(pathname: string): boolean {
  if (!pathname.startsWith('/skills/')) return false
  const firstSeg = pathname.slice('/skills/'.length).split('/')[0]
  return !RESERVED_SEGS.has(firstSeg)
}

// /skills 页签：对齐语义层/政策知识的扁平骨架（设计 §3.1）
const NAV_TABS: NavTab[] = [
  { label: 'Skill', href: '/skills', match: (p) => p === '/skills' || p.startsWith('/skills/new') || p.startsWith('/skills/import') || isSkillDetailPath(p) },
  { label: '草稿', href: '/skills/drafts', match: (p) => p.startsWith('/skills/drafts') },
  { label: '评测记录', href: '/skills/evaluations', match: (p) => p.startsWith('/skills/evaluations') },
  { label: '发布记录', href: '/skills/releases', match: (p) => p.startsWith('/skills/releases') },
]

function getActiveTab(pathname: string): string {
  for (const tab of NAV_TABS) {
    if (tab.match(pathname)) return tab.href
  }
  return NAV_TABS[0].href
}

export default function SkillsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const currentTab = getActiveTab(pathname)

  return (
    <div className="relative min-h-screen">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.12),transparent_55%),radial-gradient(ellipse_at_bottom,rgba(14,165,233,0.08),transparent_50%)]" />
        <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,rgba(15,23,42,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.05)_1px,transparent_1px)] [background-size:44px_44px]" />
      </div>

      <main className="mx-auto w-full max-w-[1600px] p-6">
        <nav className="flex w-full items-center gap-1 border-b border-slate-200">
          {NAV_TABS.map((tab) => {
            const active = currentTab === tab.href
            return (
              <button
                key={tab.href}
                type="button"
                onClick={() => router.push(tab.href)}
                className={
                  'rounded-none px-4 py-2.5 text-sm font-medium transition-colors ' +
                  (active
                    ? 'border-b-2 border-blue-600 text-blue-600'
                    : 'text-slate-500 hover:text-slate-700')
                }
              >
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
