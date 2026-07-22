'use client'

import { usePathname, useRouter } from 'next/navigation'
import {
  LayoutDashboard, Building2, Box, BarChart3, Link2, Search,
} from 'lucide-react'

interface NavTab {
  label: string
  href: string
}

const NAV_TABS: NavTab[] = [
  { label: '概览', href: '/semantic-layer' },
  { label: '业务域', href: '/semantic-layer/domain' },
  { label: '业务对象', href: '/semantic-layer/object' },
  { label: '业务指标', href: '/semantic-layer/metrics' },
  { label: '映射', href: '/semantic-layer/mapping' },
  { label: '发现', href: '/semantic-layer/discovery' },
]

interface TabHeader {
  badge: string
  breadcrumb: string
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const TAB_HEADERS: Record<string, TabHeader> = {
  '/semantic-layer': {
    badge: '语义层',
    breadcrumb: '数据模型 / 概览',
    title: '首页概览',
    description: '一站式管理业务域、语义对象、业务指标与字段映射，快速了解数据资产建设进度。',
    icon: LayoutDashboard,
  },
  '/semantic-layer/domain': {
    badge: '语义层',
    breadcrumb: '数据模型 / 业务域',
    title: '业务域管理',
    description: '按业务场景划分并管理域（结算域、质控域等），组织对象与指标。支持新增、编辑、删除域。',
    icon: Building2,
  },
  '/semantic-layer/object': {
    badge: '语义层',
    breadcrumb: '数据模型 / 业务对象',
    title: '业务对象管理',
    description: '管理所有业务对象及其关联指标。点击对象进入详情可进行指标映射。',
    icon: Box,
  },
  '/semantic-layer/metrics': {
    badge: '语义层',
    breadcrumb: '数据模型 / 业务指标',
    title: '业务指标管理',
    description: '全局浏览所有指标，按对象、语义类型、映射状态筛选，追踪映射质量。',
    icon: BarChart3,
  },
  '/semantic-layer/mapping': {
    badge: '语义层',
    breadcrumb: '数据模型 / 映射',
    title: '映射中心',
    description: '追踪数据源字段到语义指标的映射关系，发现并处理未映射字段和值域标准化待办。',
    icon: Link2,
  },
  '/semantic-layer/discovery': {
    badge: '语义层',
    breadcrumb: '数据模型 / 发现',
    title: '发现中心',
    description: '扫描已接入数据表，自动发现未映射字段并快速创建指标。支持 Excel 批量导入字段释义。',
    icon: Search,
  },
}

function getActiveTab(pathname: string): string {
  for (const tab of NAV_TABS) {
    if (tab.href === '/semantic-layer') {
      if (pathname === '/semantic-layer') return tab.href
    } else if (pathname.startsWith(tab.href)) {
      return tab.href
    }
  }
  return NAV_TABS[0].href
}

export default function SemanticLayerLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()

  const currentTab = getActiveTab(pathname)

  return (
    <div className="relative min-h-screen">
      {/* 背景氛围：柔和渐变 + 细网格（保持"医疗控制台"气质） */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.12),transparent_55%),radial-gradient(ellipse_at_bottom,rgba(14,165,233,0.08),transparent_50%)]" />
        <div className="absolute inset-0 opacity-[0.35] [background-image:linear-gradient(to_right,rgba(15,23,42,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.05)_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="absolute -left-24 -top-24 size-[340px] rounded-full bg-blue-500/10 blur-3xl" />
        <div className="absolute -bottom-32 -right-24 size-[420px] rounded-full bg-sky-400/10 blur-3xl" />
      </div>

      <main className="mx-auto w-full max-w-[1200px] p-6">
        <nav className="flex w-full items-center gap-1 border-b border-slate-200">
          {NAV_TABS.map((tab) => {
            const active = currentTab === tab.href
            return (
              <button
                key={tab.href}
                type="button"
                onClick={() => router.push(tab.href)}
                className={
                  "rounded-none px-4 py-2.5 text-sm font-medium transition-colors " +
                  (active
                    ? "border-b-2 border-blue-600 text-blue-600"
                    : "text-slate-500 hover:text-slate-700")
                }
              >
                {tab.label}
              </button>
            )
          })}
        </nav>
        {TAB_HEADERS[currentTab] && (
          <header className="mb-4 space-y-1">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
                {TAB_HEADERS[currentTab].badge}
              </span>
              <span className="text-xs text-slate-500">
                {TAB_HEADERS[currentTab].breadcrumb}
              </span>
            </div>
            <h2 className="text-xl font-semibold tracking-tight text-slate-900">
              {TAB_HEADERS[currentTab].title}
            </h2>
            <p className="text-sm text-slate-600">
              {TAB_HEADERS[currentTab].description}
            </p>
          </header>
        )}
        {children}
      </main>
    </div>
  )
}
