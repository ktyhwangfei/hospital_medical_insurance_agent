'use client'

import { useEffect, useRef, useState, createContext, useContext, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import {
  FileText,
  Wand2,
  BookOpen,
  History,
  Brain,
  ChevronLeft,
  ChevronRight,
  Activity,
} from 'lucide-react'
import { ApiProvider, useApiContext } from '@/lib/api-context'
import RoleSwitcher from '@/components/role-switcher'
import type { RoleId } from '@/lib/types'
import './globals.css'

// --- Role Context ---

interface RoleContextValue {
  currentRole: RoleId
  setCurrentRole: (role: RoleId) => void
}

const RoleContext = createContext<RoleContextValue | null>(null)

export function useRoleContext(): RoleContextValue {
  const ctx = useContext(RoleContext)
  if (!ctx) throw new Error('useRoleContext must be used within LayoutShell')
  return ctx
}

// --- Nav items ---

interface NavItem {
  label: string
  href: string
  icon: ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { label: '政策问答', href: '/policy-qa', icon: <FileText className="size-4" /> },
  { label: '技能', href: '/skills', icon: <Wand2 className="size-4" /> },
  { label: '语义层', href: '/semantic-layer', icon: <Brain className="size-4" /> },
  { label: '政策知识', href: '/policy-knowledge', icon: <BookOpen className="size-4" /> },
  { label: '问答历史', href: '/qa-history', icon: <History className="size-4" /> },
]

// --- Connection Status Badge ---

function ConnectionBadge() {
  const { connectionStatus } = useApiContext()

  const config: Record<string, { dot: string; label: string; ring: string }> = {
    connected: { dot: 'bg-emerald-500', label: '已连接', ring: 'ring-emerald-500/20' },
    fallback: { dot: 'bg-amber-500', label: '离线模式', ring: 'ring-amber-500/20' },
    unknown: { dot: 'bg-slate-300', label: '未检测', ring: 'ring-slate-300/20' },
  }

  const { dot, label, ring } = config[connectionStatus]

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ${ring} ${
        connectionStatus === 'connected'
          ? 'bg-emerald-50 text-emerald-700'
          : connectionStatus === 'fallback'
            ? 'bg-amber-50 text-amber-700'
            : 'bg-slate-50 text-slate-500'
      }`}
    >
      <span className={`size-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  )
}

// --- Layout Shell ---

export function LayoutShell({ children }: { children: ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const hasSidebarPreference = useRef(false)
  const [currentRole, setCurrentRole] = useState<RoleId>('cashier')
  const pathname = usePathname()

  useEffect(() => {
    const mobileViewport = window.matchMedia('(max-width: 767px)')
    const syncMobileDefault = () => {
      if (!hasSidebarPreference.current) setSidebarCollapsed(mobileViewport.matches)
    }
    syncMobileDefault()
    mobileViewport.addEventListener('change', syncMobileDefault)
    return () => mobileViewport.removeEventListener('change', syncMobileDefault)
  }, [])

  const toggleSidebar = () => {
    hasSidebarPreference.current = true
    setSidebarCollapsed((value) => !value)
  }

  return (
    <RoleContext.Provider value={{ currentRole, setCurrentRole }}>
      <div className="flex h-screen overflow-hidden bg-slate-50">
        {/* Sidebar */}
        <aside
          className={`flex flex-col border-r border-slate-200 bg-white transition-all duration-300 ${
            sidebarCollapsed ? 'w-16' : 'w-56'
          }`}
        >
          {/* Sidebar header */}
          <div className="flex h-14 items-center justify-between border-b border-slate-100 px-3">
            {!sidebarCollapsed && (
              <span className="text-sm font-semibold tracking-tight text-slate-800">
                导航菜单
              </span>
            )}
            <button
              type="button"
              onClick={toggleSidebar}
              className="flex size-7 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
              aria-label={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
            >
              {sidebarCollapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 space-y-1 px-2 py-4">
            {NAV_ITEMS.map((item) => {
              const isActive =
                item.href === '/'
                  ? pathname === '/'
                  : pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  } ${sidebarCollapsed ? 'justify-center px-2' : ''}`}
                  aria-label={sidebarCollapsed ? item.label : undefined}
                  title={sidebarCollapsed ? item.label : undefined}
                >
                  <span className="shrink-0">{item.icon}</span>
                  {!sidebarCollapsed && <span>{item.label}</span>}
                </Link>
              )
            })}
          </nav>

          {/* Sidebar footer */}
          <div className="border-t border-slate-100 p-3">
            {!sidebarCollapsed && (
              <p className="text-[10px] text-slate-400 leading-relaxed">
                医保AI导办平台 v0.1
              </p>
            )}
          </div>
        </aside>

        {/* Main area */}
        <div className="flex flex-1 flex-col min-w-0">
          {/* Header */}
          <header className="flex h-14 items-center justify-between border-b border-slate-200 bg-white px-6">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <div className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-blue-700 shadow-sm">
                  <Activity className="size-4 text-white" />
                </div>
                <h1 className="text-base font-semibold text-slate-800">医保AI导办平台</h1>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <ConnectionBadge />
              <RoleSwitcher currentRole={currentRole} onRoleChange={setCurrentRole} />
            </div>
          </header>

          {/* Content */}
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </div>
      </div>
    </RoleContext.Provider>
  )
}

// --- Root Layout ---

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">
        <ApiProvider>
          <LayoutShell>{children}</LayoutShell>
        </ApiProvider>
      </body>
    </html>
  )
}
