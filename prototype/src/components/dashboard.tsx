'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  BarChart3,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Users,
  FileText,
  Brain,
  PieChart,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
} from 'lucide-react'

const metrics = [
  {
    title: '医保结算成功率',
    value: '96.8%',
    trend: 'up',
    change: '+2.3%',
    icon: CheckCircle2,
    gradient: 'from-emerald-500 to-emerald-600',
    bgLight: 'bg-emerald-50',
    iconColor: 'text-emerald-600',
  },
  {
    title: '结算异常处理时长',
    value: '18分钟',
    trend: 'down',
    change: '-45%',
    icon: Clock,
    gradient: 'from-blue-500 to-blue-600',
    bgLight: 'bg-blue-50',
    iconColor: 'text-blue-600',
  },
  {
    title: '医保拒付金额',
    value: '12.5万',
    trend: 'down',
    change: '-38%',
    icon: AlertTriangle,
    gradient: 'from-rose-500 to-rose-600',
    bgLight: 'bg-rose-50',
    iconColor: 'text-rose-600',
  },
  {
    title: 'AI导办任务完成率',
    value: '87%',
    trend: 'up',
    change: '+15%',
    icon: Brain,
    gradient: 'from-violet-500 to-violet-600',
    bgLight: 'bg-violet-50',
    iconColor: 'text-violet-600',
  },
]

const departmentRank = [
  { name: '骨科', loss: 58, cases: 23, riskScore: 85 },
  { name: '心内科', loss: 42, cases: 18, riskScore: 72 },
  { name: '神经内科', loss: 35, cases: 15, riskScore: 68 },
  { name: '普外科', loss: 28, cases: 12, riskScore: 55 },
  { name: '呼吸科', loss: 20, cases: 10, riskScore: 42 },
]

const riskDistribution = [
  { type: '结算异常', count: 15, percentage: 35, color: 'bg-rose-500' },
  { type: '合规风险', count: 12, percentage: 28, color: 'bg-amber-500' },
  { type: 'DRG风险', count: 8, percentage: 19, color: 'bg-blue-500' },
  { type: '病案质量', count: 8, percentage: 18, color: 'bg-violet-500' },
]

export default function Dashboard({ currentRole: _currentRole }: { currentRole: string }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold tracking-tight text-slate-900">医保运营驾驶舱</h2>
        <p className="mt-1 text-sm text-slate-500">
          实时监测医院医保运营关键指标
        </p>
      </div>

      {/* 核心指标卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((metric) => (
          <Card key={metric.title} className="border-slate-200/70 overflow-hidden group hover:shadow-md transition-all duration-300">
            <CardContent className="p-0">
              <div className="p-5">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">{metric.title}</p>
                    <p className={`text-2xl font-bold tracking-tight ${metric.iconColor}`}>
                      {metric.value}
                    </p>
                  </div>
                  <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${metric.bgLight} ring-1 ring-inset ring-black/[0.02] group-hover:scale-110 transition-transform duration-300`}>
                    <metric.icon className={`w-5 h-5 ${metric.iconColor}`} />
                  </div>
                </div>
                <div className="flex items-center gap-1.5 mt-3 pt-3 border-t border-slate-100">
                  {metric.trend === 'up' ? (
                    <ArrowUpRight className="w-3.5 h-3.5 text-emerald-600" />
                  ) : (
                    <ArrowDownRight className="w-3.5 h-3.5 text-emerald-600" />
                  )}
                  <span className="text-sm font-semibold text-emerald-600">
                    {metric.change}
                  </span>
                  <span className="text-xs text-slate-400">较上月</span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 科室亏损排名 */}
        <Card className="border-slate-200/70">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-50">
                <BarChart3 className="w-4 h-4 text-rose-600" />
              </div>
              科室DRG亏损排名
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-5">
              {departmentRank.map((dept, idx) => (
                <div key={dept.name}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2.5">
                      <div className={`flex h-6 w-6 items-center justify-center rounded-lg text-xs font-bold ${
                        idx === 0 ? 'bg-rose-100 text-rose-700' :
                        idx === 1 ? 'bg-amber-100 text-amber-700' :
                        idx === 2 ? 'bg-blue-100 text-blue-700' :
                        'bg-slate-100 text-slate-600'
                      }`}>
                        {idx + 1}
                      </div>
                      <span className="font-medium text-sm text-slate-800">{dept.name}</span>
                    </div>
                    <div className="flex items-center gap-3 text-sm">
                      <span className="font-semibold text-rose-600">亏损{dept.loss}万</span>
                      <span className="text-slate-400 text-xs">{dept.cases}例</span>
                    </div>
                  </div>
                  <div className="relative">
                    <Progress value={dept.riskScore} className="h-2 bg-slate-100" />
                    <div className="absolute right-0 -top-5 text-[10px] text-slate-400">{dept.riskScore}%</div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* 风险分布 */}
        <Card className="border-slate-200/70">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-50">
                <PieChart className="w-4 h-4 text-blue-600" />
              </div>
              风险类型分布
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-5">
              {riskDistribution.map((risk) => (
                <div key={risk.type}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2.5">
                      <div className={`h-2.5 w-2.5 rounded-full ${risk.color}`} />
                      <span className="text-sm font-medium text-slate-700">{risk.type}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-slate-500">{risk.count}项</span>
                      <Badge variant="secondary" className="text-xs font-medium">{risk.percentage}%</Badge>
                    </div>
                  </div>
                  <Progress value={risk.percentage} className="h-2 bg-slate-100" />
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-xl bg-gradient-to-r from-blue-50 to-indigo-50/70 border border-blue-100/60 p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-100">
                  <Brain className="w-4 h-4 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-blue-900">AI 运营洞察</p>
                  <p className="text-xs text-blue-700 mt-1 leading-relaxed">
                    本月结算异常主要集中在费用上传环节，建议加强收费员操作培训。DRG亏损增幅趋缓，质控措施见效。
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 本月工作统计 */}
      <Card className="border-slate-200/70">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-50">
              <Activity className="w-4 h-4 text-violet-600" />
            </div>
            本月AI导办工作统计
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {[
              { label: 'AI对话次数', value: '1,234', icon: Brain, gradient: 'from-blue-500 to-blue-600', bgLight: 'bg-blue-50' },
              { label: '生成质控清单', value: '89', icon: FileText, gradient: 'from-emerald-500 to-emerald-600', bgLight: 'bg-emerald-50' },
              { label: '处理异常数', value: '156', icon: AlertTriangle, gradient: 'from-amber-500 to-amber-600', bgLight: 'bg-amber-50' },
              { label: '活跃用户数', value: '45', icon: Users, gradient: 'from-violet-500 to-violet-600', bgLight: 'bg-violet-50' },
            ].map((stat) => (
              <div key={stat.label} className="group rounded-xl border border-slate-100 bg-white p-5 text-center transition-all duration-200 hover:shadow-md hover:border-slate-200">
                <div className={`mx-auto flex h-10 w-10 items-center justify-center rounded-xl ${stat.bgLight} mb-3 group-hover:scale-110 transition-transform duration-300`}>
                  <stat.icon className={`w-5 h-5 text-${stat.gradient.split(' ')[0].replace('from-', '')}`} />
                </div>
                <p className="text-2xl font-bold tracking-tight text-slate-900">{stat.value}</p>
                <p className="text-xs text-slate-500 mt-1">{stat.label}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
