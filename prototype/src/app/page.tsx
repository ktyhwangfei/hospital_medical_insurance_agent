'use client'

import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MessageCircle, AlertTriangle, ClipboardCheck, BarChart3, Server, BookOpen, FlaskConical, Wifi, WifiOff } from 'lucide-react'
import SettlementChat from '@/components/settlement-chat'
import DischargeQC from '@/components/discharge-qc'
import Dashboard from '@/components/dashboard'
import RoleSwitcher from '@/components/role-switcher'
import McpManagement from '@/components/mcp-management'
import KnowledgeExplorer from '@/components/knowledge-explorer'
import ModelTest from '@/components/model-test'
import { useApiContext } from '@/lib/api-context'

export default function Home() {
  const [currentRole, setCurrentRole] = useState('insurance_office')
  const { connectionStatus } = useApiContext()

  const roleNames: Record<string, string> = {
    cashier: '收费员',
    insurance_office: '医保办',
    it_department: '信息科',
    medical_record: '病案室',
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      {/* 顶部导航栏 */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white text-xl font-bold">医</span>
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">医保AI导办与运营协同平台</h1>
              <p className="text-xs text-gray-500">原型演示系统 v1.0</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <Badge
              variant="outline"
              className={connectionStatus === 'connected' ? 'bg-green-50 text-green-700' : connectionStatus === 'fallback' ? 'bg-orange-50 text-orange-700' : 'bg-gray-50 text-gray-600'}
            >
              {connectionStatus === 'connected' ? <Wifi className="w-3 h-3 mr-1" /> : <WifiOff className="w-3 h-3 mr-1" />}
              {connectionStatus === 'connected' ? '已连接' : connectionStatus === 'fallback' ? '离线模式' : '未检测'}
            </Badge>
            <RoleSwitcher currentRole={currentRole} onRoleChange={setCurrentRole} />
            <Badge variant="outline" className="bg-blue-50">
              当前角色: {roleNames[currentRole]}
            </Badge>
          </div>
        </div>
      </header>

      {/* 主内容区 */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Tabs defaultValue="chat" className="space-y-6">
          <TabsList className="grid h-auto w-full grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-7">
            <TabsTrigger value="chat" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <MessageCircle className="w-4 h-4" />
              AI导办对话
            </TabsTrigger>
            <TabsTrigger value="settlement" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <AlertTriangle className="w-4 h-4" />
              结算异常导办
            </TabsTrigger>
            <TabsTrigger value="qc" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <ClipboardCheck className="w-4 h-4" />
              出院前联合质控
            </TabsTrigger>
            <TabsTrigger value="dashboard" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <BarChart3 className="w-4 h-4" />
              运营驾驶舱
            </TabsTrigger>
            <TabsTrigger value="mcp" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <Server className="w-4 h-4" />
              MCP管理
            </TabsTrigger>
            <TabsTrigger value="knowledge" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <BookOpen className="w-4 h-4" />
              知识浏览
            </TabsTrigger>
            <TabsTrigger value="model" className="flex h-auto min-h-9 items-center gap-2 whitespace-normal">
              <FlaskConical className="w-4 h-4" />
              模型测试
            </TabsTrigger>
          </TabsList>

          <TabsContent value="chat">
            <SettlementChat currentRole={currentRole} />
          </TabsContent>

          <TabsContent value="settlement">
            <SettlementExceptionList />
          </TabsContent>

          <TabsContent value="qc">
            <DischargeQC currentRole={currentRole} />
          </TabsContent>

          <TabsContent value="dashboard">
            <Dashboard currentRole={currentRole} />
          </TabsContent>

          <TabsContent value="mcp">
            <McpManagement />
          </TabsContent>

          <TabsContent value="knowledge">
            <KnowledgeExplorer />
          </TabsContent>

          <TabsContent value="model">
            <ModelTest />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  )
}

// 结算异常列表组件
function SettlementExceptionList() {
  const exceptions = [
    {
      id: 'SE001',
      patientName: '张三',
      errorCode: 'ERR_001',
      errorMsg: '患者待遇资格校验不通过',
      priority: '高',
      status: '待处理',
    },
    {
      id: 'SE002',
      patientName: '李四',
      errorCode: 'ERR_002',
      errorMsg: '诊疗项目目录对码错误',
      priority: '中',
      status: '处理中',
    },
    {
      id: 'SE003',
      patientName: '王五',
      errorCode: 'ERR_003',
      errorMsg: 'DRG分组结果与费用不匹配',
      priority: '高',
      status: '待处理',
    },
  ]

  const priorityColors: Record<string, string> = {
    高: 'bg-red-100 text-red-800',
    中: 'bg-yellow-100 text-yellow-800',
    低: 'bg-green-100 text-green-800',
  }

  const statusColors: Record<string, string> = {
    待处理: 'bg-gray-100 text-gray-800',
    处理中: 'bg-blue-100 text-blue-800',
    已完成: 'bg-green-100 text-green-800',
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">医保结算异常导办</h2>
        <Badge className="bg-red-100 text-red-800">3个异常待处理</Badge>
      </div>

      <div className="grid gap-4">
        {exceptions.map((exc) => (
          <Card key={exc.id} className="p-6 hover:shadow-lg transition-shadow">
            <div className="flex items-start justify-between">
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <h3 className="text-lg font-semibold">{exc.patientName}</h3>
                  <Badge className={priorityColors[exc.priority]}>{exc.priority}优先级</Badge>
                  <Badge className={statusColors[exc.status]}>{exc.status}</Badge>
                </div>
                <p className="text-sm text-gray-600">
                  <span className="font-medium">错误码:</span> {exc.errorCode}
                </p>
                <p className="text-sm text-gray-800">{exc.errorMsg}</p>
              </div>
              <Button variant="outline" size="sm">
                查看处理步骤
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
