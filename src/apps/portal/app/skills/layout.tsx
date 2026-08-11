'use client'

import { usePathname, useRouter } from 'next/navigation'

interface NavTab {
  label: string
  href: string
  match: (pathname: string) => boolean
}

// 顶部保留子路径：不能被当成 Skill 详情页
const RESERVED_SEGS = new Set(['assets', 'drafts', 'evaluations', 'releases', 'new', 'import', 'eval-case-pool', 'eval-mining'])

// /skills/<skillId> 或 /skills/<skillId>/edit（排除保留路径，否则 /skills/drafts 等会被误判为 Skill 详情）
function isSkillDetailPath(pathname: string): boolean {
  if (!pathname.startsWith('/skills/')) return false
  const firstSeg = pathname.slice('/skills/'.length).split('/')[0]
  return !RESERVED_SEGS.has(firstSeg)
}

// /skills 页签：对齐语义层/政策知识的扁平骨架（设计 §3.1）
const NAV_TABS: NavTab[] = [
  { label: '治理待办', href: '/skills', match: (p) => p === '/skills' },
  { label: 'Skill 资产', href: '/skills/assets', match: (p) => p.startsWith('/skills/assets') || p.startsWith('/skills/new') || p.startsWith('/skills/import') || isSkillDetailPath(p) },
  { label: '草稿', href: '/skills/drafts', match: (p) => p.startsWith('/skills/drafts') },
  { label: '评测中心', href: '/skills/evaluations', match: (p) => p.startsWith('/skills/evaluations') || p.startsWith('/skills/eval-') },
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
    <section className="mx-auto w-full max-w-[1600px] px-4 md:px-6">
      <nav aria-label="Skill 工作台" className="overflow-x-auto border-b border-slate-200">
        <div className="flex min-w-full w-max items-center gap-1">
          {NAV_TABS.map((tab) => {
            const active = currentTab === tab.href
            return (
              <button
                key={tab.href}
                type="button"
                onClick={() => router.push(tab.href)}
                aria-current={active ? 'page' : undefined}
                className={
                  'min-h-11 shrink-0 whitespace-nowrap rounded-none px-4 py-2.5 text-sm font-medium transition-colors ' +
                  (active
                    ? 'border-b-2 border-blue-600 text-blue-600'
                    : 'text-slate-500 hover:text-slate-700')
                }
              >
                {tab.label}
              </button>
            )
          })}
        </div>
      </nav>
      {children}
    </section>
  )
}
