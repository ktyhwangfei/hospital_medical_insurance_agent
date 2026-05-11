'use client'

import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  MessageSquare,
  AlertTriangle,
  ClipboardCheck,
  BarChart3,
  Server,
  BookOpen,
  FlaskConical,
  Building2,
  PanelLeftClose,
  PanelLeft,
  Sparkles,
} from 'lucide-react'
import SettlementChat from '@/components/settlement-chat'
import DischargeQC from '@/components/discharge-qc'
import Dashboard from '@/components/dashboard'
import RoleSwitcher from '@/components/role-switcher'
import McpManagement from '@/components/mcp-management'
import KnowledgeExplorer from '@/components/knowledge-explorer'
import ModelTest from '@/components/model-test'
import { useApiContext } from '@/lib/api-context'
import type { RoleId } from '@/lib/types'

type TabId = 'chat' | 'settlement' | 'qc' | 'dashboard' | 'mcp' | 'knowledge' | 'model'

interface NavItem {
  id: TabId
  label: string
  icon: React.ComponentType<{ className?: string }>
  badge?: string
}

interface NavSection {
  label: string
  items: NavItem[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    label: '业务应用',
    items: [
      { id: 'chat', label: 'AI导办对话', icon: MessageSquare },
      { id: 'settlement', label: '结算异常导办', icon: AlertTriangle, badge: '3' },
      { id: 'qc', label: '出院前联合质控', icon: ClipboardCheck },
      { id: 'dashboard', label: '运营驾驶舱', icon: BarChart3 },
    ],
  },
  {
    label: '平台管理',
    items: [
      { id: 'mcp', label: 'MCP管理', icon: Server },
      { id: 'knowledge', label: '知识浏览', icon: BookOpen },
      { id: 'model', label: '模型测试', icon: FlaskConical },
    ],
  },
]

const roleNames: Record<string, string> = {
  cashier: '收费员',
  medical_office: '医保办',
  information_department: '信息科',
  medical_record_staff: '病案室',
  clinician: '临床医生',
}

export default function Home() {
  const [currentRole, setCurrentRole] = useState<RoleId>('cashier')
  const [activeTab, setActiveTab] = useState<TabId>('chat')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [chatPrefill, setChatPrefill] = useState('')
  const { connectionStatus } = useApiContext()

  const connectionDot = {
    connected: 'bg-emerald-500',
    fallback: 'bg-amber-500',
    unknown: 'bg-slate-400',
  }[connectionStatus] ?? 'bg-slate-400'

  const connectionLabel = {
    connected: '已连接',
    fallback: '离线模式',
    unknown: '未检测',
  }[connectionStatus] ?? '未检测'

  const connectionTextColor = {
    connected: 'text-emerald-700',
    fallback: 'text-amber-700',
    unknown: 'text-slate-500',
  }[connectionStatus] ?? 'text-slate-500'

  const connectionRing = {
    connected: 'ring-emerald-300/60',
    fallback: 'ring-amber-300/60',
    unknown: 'ring-slate-300/60',
  }[connectionStatus] ?? 'ring-slate-300/60'

  return (
    <div className="min-h-screen bg-[#f6f8fc] bg-subtle-grid">
      {/* Header */}
      <header className="relative z-40 flex h-14 shrink-0 items-center border-b border-slate-200/80 bg-white/70 px-5 shadow-sm backdrop-blur-md sticky top-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#0a2540] to-[#1a4a7a] shadow-sm ring-1 ring-white/20">
            <Building2 className="h-4.5 w-4.5 text-white" />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-bold leading-tight text-slate-900 truncate">医保AI导办与运营协同平台</h1>
            <p className="text-[10px] leading-tight text-slate-400">v1.0 · 院内智能工作台</p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-3">
          {/* Connection status - pill badge */}
          <div className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-all duration-300 ${
            connectionStatus === 'connected'
              ? 'bg-emerald-50 border-emerald-200/60'
              : connectionStatus === 'fallback'
                ? 'bg-amber-50 border-amber-200/60'
                : 'bg-slate-50 border-slate-200/60'
          }`}>
            <span className="relative flex h-2 w-2">
              <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-40 ${
                connectionStatus === 'connected' ? 'bg-emerald-400' : connectionStatus === 'fallback' ? 'bg-amber-400' : 'bg-slate-400'
              }`} />
              <span className={`relative inline-flex h-2 w-2 rounded-full ${connectionDot} ring-2 ${connectionRing}`} />
            </span>
            <span className={`font-medium ${connectionTextColor}`}>{connectionLabel}</span>
          </div>

          <RoleSwitcher currentRole={currentRole} onRoleChange={setCurrentRole} />

          <Badge variant="secondary" className="font-normal text-xs px-2.5 py-0.5 hidden sm:inline-flex">
            {roleNames[currentRole]}
          </Badge>
        </div>
      </header>

      <div className="flex h-[calc(100vh-56px)]">
        {/* Sidebar */}
        <aside
          className={`relative flex shrink-0 flex-col overflow-hidden bg-[#0a1a2e] text-white transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] ${
            sidebarCollapsed ? 'w-14' : 'w-58'
          }`}
        >
          {/* Subtle gradient overlay at top */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-white/[0.04] to-transparent" />

          <nav className="flex-1 overflow-y-auto py-3 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
            {NAV_SECTIONS.map((section) => (
              <div key={section.label} className="mb-2">
                {!sidebarCollapsed && (
                  <div className="px-4 pb-1.5 pt-3 text-[10px] font-semibold tracking-[0.15em] text-slate-400/60 uppercase">
                    {section.label}
                  </div>
                )}
                {section.items.map((item) => {
                  const Icon = item.icon
                  const isActive = activeTab === item.id
                  return (
                    <button
                      key={item.id}
                      onClick={() => setActiveTab(item.id)}
                      className={`relative w-full flex items-center gap-3 text-sm transition-all duration-200 ${
                        isActive
                          ? 'text-white'
                          : 'text-slate-400/80 hover:text-slate-200'
                      } ${sidebarCollapsed ? 'justify-center py-3' : 'px-3 py-2.5'}`}
                    >
                      {/* Active indicator */}
                      {isActive && (
                        <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-blue-400 to-blue-500 shadow-sm shadow-blue-400/30" />
                      )}

                      {/* Active background */}
                      <div
                        className={`absolute inset-x-2 inset-y-0 rounded-lg transition-all duration-200 ${
                          isActive
                            ? 'bg-white/[0.08] shadow-sm shadow-black/20'
                            : 'opacity-0 hover:opacity-100 bg-white/[0.03]'
                        }`}
                      />

                      <Icon className={`relative z-10 h-4 w-4 shrink-0 transition-all duration-200 ${
                        isActive ? 'text-blue-300' : ''
                      }`} />

                      {!sidebarCollapsed && (
                        <span className={`relative z-10 truncate text-sm ${isActive ? 'font-medium' : ''}`}>
                          {item.label}
                        </span>
                      )}

                      {/* Badge notification */}
                      {!sidebarCollapsed && item.badge && (
                        <span className="relative z-10 ml-auto mr-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-gradient-to-r from-red-500 to-red-400 px-1 text-[10px] font-semibold text-white shadow-sm shadow-red-500/30">
                          {item.badge}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            ))}
          </nav>

          {/* Collapse toggle */}
          <div className="relative border-t border-white/[0.06] p-2">
            <button
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="flex w-full items-center justify-center gap-2 rounded-lg py-2 text-xs text-slate-500 transition-all duration-200 hover:bg-white/[0.04] hover:text-slate-300"
            >
              {sidebarCollapsed ? (
                <PanelLeft className="h-4 w-4" />
              ) : (
                <>
                  <PanelLeftClose className="h-4 w-4" />
                  <span>收起菜单</span>
                </>
              )}
            </button>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 bg-subtle-grid">
          <div className="mx-auto max-w-7xl animate-in">
            {activeTab === 'chat' && <SettlementChat currentRole={currentRole} prefilledMessage={chatPrefill} onPrefillConsumed={() => setChatPrefill('')} />}
            {activeTab === 'settlement' && <SettlementExceptionList onViewSteps={(exc) => { setActiveTab('chat'); setChatPrefill(`请帮我处理结算异常 ${exc.errorCode}: ${exc.errorMsg}`) }} />}
            {activeTab === 'qc' && <DischargeQC currentRole={currentRole} />}
            {activeTab === 'dashboard' && <Dashboard currentRole={currentRole} />}
            {activeTab === 'mcp' && <McpManagement />}
            {activeTab === 'knowledge' && <KnowledgeExplorer />}
            {activeTab === 'model' && <ModelTest />}
          </div>
        </main>
      </div>
    </div>
  )
}

function SettlementExceptionList({ onViewSteps }: { onViewSteps?: (exc: { id: string; patientName: string; errorCode: string; errorMsg: string; priority: string; status: string }) => void }) {
  const exceptions = [
    { id: 'SE001', patientName: '张三', errorCode: 'ERR_001', errorMsg: '患者待遇资格校验不通过', priority: '高', status: '待处理' },
    { id: 'SE002', patientName: '李四', errorCode: 'ERR_002', errorMsg: '诊疗项目目录对码错误', priority: '中', status: '处理中' },
    { id: 'SE003', patientName: '王五', errorCode: 'ERR_003', errorMsg: 'DRG分组结果与费用不匹配', priority: '高', status: '待处理' },
  ]

  const priorityColors: Record<string, string> = {
    高: 'bg-red-50 text-red-700 border-red-200/60',
    中: 'bg-amber-50 text-amber-700 border-amber-200/60',
    低: 'bg-emerald-50 text-emerald-700 border-emerald-200/60',
  }
  const statusColors: Record<string, string> = {
    待处理: 'bg-slate-100 text-slate-700',
    处理中: 'bg-blue-50 text-blue-700',
    已完成: 'bg-emerald-50 text-emerald-700',
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-slate-900">医保结算异常导办</h2>
          <p className="mt-1 text-sm text-slate-500">实时待处理结算异常列表，点击可查看AI导办步骤</p>
        </div>
        <Badge className="bg-red-50 text-red-700 border border-red-200/60 shadow-sm">
          <span className="relative mr-1 flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
          </span>
          3个异常待处理
        </Badge>
      </div>
      <div className="grid gap-4">
        {exceptions.map((exc, i) => (
          <Card key={exc.id} className="overflow-hidden border-slate-200/80 p-0">
            <div className="flex items-start gap-5 p-5">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border text-sm font-bold ${
                exc.priority === '高' ? 'bg-red-50 border-red-200 text-red-600' :
                exc.priority === '中' ? 'bg-amber-50 border-amber-200 text-amber-600' :
                'bg-emerald-50 border-emerald-200 text-emerald-600'
              }`}>
                {i + 1}
              </div>
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold text-slate-900">{exc.patientName}</h3>
                  <Badge variant="outline" className={priorityColors[exc.priority]}>{exc.priority}优先级</Badge>
                  <Badge variant="outline" className={statusColors[exc.status]}>{exc.status}</Badge>
                </div>
                <p className="text-sm text-slate-400">错误码: {exc.errorCode}</p>
                <p className="text-sm text-slate-600">{exc.errorMsg}</p>
              </div>
              <div className="shrink-0">
                <Button variant="outline" size="sm" onClick={() => onViewSteps?.(exc)} className="group">
                  <Sparkles className="mr-1.5 h-3.5 w-3.5 text-blue-500 transition-transform group-hover:scale-110" />
                  查看处理步骤
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
