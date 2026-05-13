'use client'

import { useState } from 'react'
import { Noto_Sans_SC } from 'next/font/google'
import { ApiProvider, useApiContext } from '@/lib/api-context'
import AdminSidebar from '@/components/admin-sidebar'
import RoleSwitcher from '@/components/role-switcher'
import { Badge } from '@/components/ui/badge'
import type { RoleId } from '@/lib/types'
import './globals.css'

const notoSansSC = Noto_Sans_SC({
  subsets: ['latin'],
  variable: '--font-noto-sans-sc',
  weight: ['400', '500', '700'],
})

// ── Connection Status Badge ──

function ConnectionBadge() {
  const { connectionStatus } = useApiContext()

  const statusConfig: Record<string, { label: string; className: string }> = {
    unknown: { label: '未检测', className: 'bg-gray-100 text-gray-600' },
    connected: { label: '已连接', className: 'bg-green-100 text-green-800' },
    fallback: { label: '离线模式', className: 'bg-yellow-100 text-yellow-800' },
  }

  const config = statusConfig[connectionStatus] ?? statusConfig.unknown

  return <Badge className={config.className}>{config.label}</Badge>
}

// ── Layout Shell ──

function AdminShell({ children }: { children: React.ReactNode }) {
  const [currentRole, setCurrentRole] = useState<RoleId>('cashier')

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <AdminSidebar />
      <div className="flex flex-1 flex-col min-w-0">
        {/* Top header bar */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-blue-700 shadow-sm">
              <svg className="size-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-semibold text-gray-900 leading-tight">院端医保智能体</h1>
              <p className="text-[11px] text-gray-500 leading-tight">管理控制台</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ConnectionBadge />
            <RoleSwitcher currentRole={currentRole} onRoleChange={setCurrentRole} />
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-auto p-6">
          {children}
        </main>
      </div>
    </div>
  )
}

// ── Root Layout ──

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN" className={notoSansSC.variable}>
      <body style={{ fontFamily: 'var(--font-noto-sans-sc), sans-serif' }}>
        <ApiProvider>
          <AdminShell>{children}</AdminShell>
        </ApiProvider>
      </body>
    </html>
  )
}
