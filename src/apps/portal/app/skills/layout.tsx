'use client'

import { usePathname, useRouter } from 'next/navigation'

interface NavTab {
  label: string
  href: string
  match: (pathname: string) => boolean
}

// 顶部保留子路径：不能被当成 Skill 详情页
const RESERVED_SEGS = new Set(['assets', 'drafts', 'evaluations', 'releases', 'eval-case-pool', 'eval-mining', 'new', 'import'])

// 草稿编辑器路径：/skills/<skillId>/edit（属于「草稿」页签，而非治理详情）
function isDraftEditPath(pathname: string): boolean {
  if (!pathname.startsWith('/skills/')) return false
  const segs = pathname.slice('/skills/'.length).split('/')
  return segs.length >= 2 && segs[1] === 'edit'
}

// /skills/<skillId>（排除保留路径与 /edit 子路径，否则草稿编辑器会被误判为治理详情）
function isSkillDetailPath(pathname: string): boolean {
  if (!pathname.startsWith('/skills/')) return false
  const segs = pathname.slice('/skills/'.length).split('/')
  const firstSeg = segs[0]
  return !RESERVED_SEGS.has(firstSeg) && !isDraftEditPath(pathname)
}

// /skills 页签：对齐语义层/政策知识的扁平骨架（设计 §3.1）
const NAV_TABS: NavTab[] = [
  { label: '概览', href: '/skills', match: (p) => p === '/skills' || isSkillDetailPath(p) },
  { label: '草稿', href: '/skills/drafts', match: (p) => p.startsWith('/skills/drafts') || p.startsWith('/skills/new') || p.startsWith('/skills/import') || isDraftEditPath(p) },
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
