'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Activity,
  BookOpen,
  FlaskConical,
  Layers,
  Server,
  Shield,
  Wrench,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const navItems = [
  { href: '/mcp', label: 'MCP 管理', icon: Server, description: '注册和管理 MCP 服务与能力' },
  { href: '/knowledge', label: '知识管理', icon: BookOpen, description: '浏览知识资产、规则和模板' },
  { href: '/model', label: '模型测试', icon: FlaskConical, description: '测试模型服务连通性与响应' },
  { href: '/skills', label: '技能管理', icon: Layers, description: '管理工具与编排技能' },
]

const overviewCards = [
  {
    title: '平台管理控制台',
    description: '院端医保智能体系统的后台管理界面，提供 MCP 服务注册、知识资产管理、模型服务测试和技能编排配置等功能。',
    icon: Shield,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
  },
  {
    title: '系统状态',
    description: '所有管理功能通过 FastAPI 后端与 PostgreSQL/Redis/Milvus 数据层交互。页面右上角显示 API 连接状态。',
    icon: Activity,
    color: 'text-green-600',
    bgColor: 'bg-green-50',
  },
  {
    title: '工具与技能',
    description: '技能管理页面支持创建和编辑工具（Tools）与编排技能（Skills），基于 Anthropic Skills 规范。',
    icon: Wrench,
    color: 'text-purple-600',
    bgColor: 'bg-purple-50',
  },
]

export default function AdminDashboard() {
  const pathname = usePathname()

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900">欢迎使用管理控制台</h2>
        <p className="text-sm text-gray-500 mt-1">从左侧导航选择管理功能，或浏览下方快速入口</p>
      </div>

      {/* Navigation cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = pathname === item.href
          return (
            <Link key={item.href} href={item.href}>
              <Card className={`cursor-pointer hover:shadow-md transition-all duration-200 h-full ${
                isActive ? 'border-blue-200 shadow-sm' : 'hover:border-blue-200'
              }`}>
                <CardContent className="p-5">
                  <div className="flex items-start gap-4">
                    <div className="p-2.5 rounded-lg bg-blue-50 shrink-0">
                      <Icon className="w-5 h-5 text-blue-600" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="font-semibold text-gray-900">{item.label}</h3>
                      <p className="text-sm text-gray-500 mt-1">{item.description}</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </Link>
          )
        })}
      </div>

      {/* Overview cards */}
      <div className="space-y-4">
        {overviewCards.map((card) => {
          const Icon = card.icon
          return (
            <Card key={card.title}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <div className={`p-1.5 rounded-lg ${card.bgColor}`}>
                    <Icon className={`w-4 h-4 ${card.color}`} />
                  </div>
                  {card.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-gray-600 leading-relaxed">{card.description}</p>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
