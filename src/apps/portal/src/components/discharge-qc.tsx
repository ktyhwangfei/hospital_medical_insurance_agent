'use client'

import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertTriangle,
  CheckCircle2,
  User,
  FileText,
  ChevronRight,
  ShieldAlert,
  Activity,
  RefreshCw,
} from 'lucide-react'
import { listWorkflows } from '@/lib/api-client'
import type { RoleId, WorkflowItem } from '@/lib/types'

type QcRiskLevel = '高' | '中' | '低'
type QcRiskStatus = '待处理' | '处理中' | '已完成'

interface QcRisk {
  id: number
  type: string
  level: QcRiskLevel
  description: string
  source: string
  status: QcRiskStatus
  assignee: string
}

interface QcCase {
  id: string
  patientName: string
  patientId: string
  department: string
  doctor: string
  expectedDischarge: string
  completionRate: number
  risks: QcRisk[]
}

const riskLevels: QcRiskLevel[] = ['高', '中', '低']

function toQcCase(wf: WorkflowItem): QcCase {
  const steps = (wf.steps ?? []) as Array<{ step_id: string; status: string; error?: string }>
  const completedSteps = steps.filter((s) => s.status === 'completed').length
  const totalSteps = steps.length || 4 // default to 4 if no steps yet
  const completionRate = Math.round((completedSteps / totalSteps) * 100)

  const risks: QcRisk[] = steps.map((step, idx) => {
    const level: QcRiskLevel = step.status === 'error' ? '高' : idx % 3 === 0 ? '中' : '低'
    const statusMap: Record<string, QcRiskStatus> = {
      pending: '待处理',
      processing: '处理中',
      completed: '已完成',
      error: '待处理',
    }
    return {
      id: idx + 1,
      type: step.step_id.replace(/_/g, ''),
      level,
      description: step.error ?? `待完成步骤: ${step.step_id}`,
      source: '智能质控引擎',
      status: statusMap[step.status] ?? '待处理',
      assignee: '质控员',
    }
  })

  // If no workflow steps, use fallback risks based on scenario defaults
  if (risks.length === 0) {
    risks.push(
      {
        id: 1,
        type: '结算准备',
        level: '中',
        description: '费用上传完整性待确认',
        source: '首信医保接口',
        status: '待处理',
        assignee: '收费员',
      },
      {
        id: 2,
        type: '合规风险',
        level: '中',
        description: '诊疗合规性待审核',
        source: '东软事前审核',
        status: '待处理',
        assignee: '临床医生',
      },
      {
        id: 3,
        type: 'DRG风险',
        level: '中',
        description: '主要诊断与手术操作匹配性待检查',
        source: '大瑞集思DRG',
        status: '待处理',
        assignee: '病案室',
      },
    )
  }

  return {
    id: wf.workflow_id,
    patientName: wf.patient_name ?? wf.patient?.name ?? '未知患者',
    patientId: wf.patient_id ?? wf.patient?.patient_id ?? '',
    department: '待确认',
    doctor: '待确认',
    expectedDischarge: '待确认',
    completionRate,
    risks,
  }
}

export default function DischargeQC({ currentRole: _currentRole }: { currentRole: RoleId }) {
  const [qcCases, setQcCases] = useState<QcCase[]>([])
  const [selectedCase, setSelectedCase] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchCases = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const workflows = await listWorkflows({ scenario: 'pre_discharge_qc' })
      setQcCases(workflows.map(toQcCase))
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载质控数据失败'
      setError(message)
      setQcCases([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCases()
  }, [fetchCases])

  const levelColors: Record<QcRiskLevel, string> = {
    高: 'bg-red-50 text-red-800 border-red-200/60',
    中: 'bg-amber-50 text-amber-800 border-amber-200/60',
    低: 'bg-emerald-50 text-emerald-800 border-emerald-200/60',
  }

  const levelIcons: Record<QcRiskLevel, React.ComponentType<{ className?: string }>> = {
    高: ShieldAlert,
    中: AlertTriangle,
    低: CheckCircle2,
  }

  const statusColors: Record<QcRiskStatus, string> = {
    待处理: 'bg-slate-100 text-slate-700 border-slate-200',
    处理中: 'bg-blue-50 text-blue-700 border-blue-200',
    已完成: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  }

  // Loading state
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="h-7 w-48 animate-pulse rounded bg-slate-200" />
            <div className="mt-2 h-4 w-72 animate-pulse rounded bg-slate-200" />
          </div>
          <div className="h-6 w-28 animate-pulse rounded bg-slate-200" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="border-slate-200/70 overflow-hidden">
              <CardHeader className="pb-2">
                <div className="space-y-2">
                  <div className="h-5 w-24 animate-pulse rounded bg-slate-200" />
                  <div className="h-3 w-32 animate-pulse rounded bg-slate-200" />
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="h-3 w-full animate-pulse rounded bg-slate-200" />
                  <div className="h-1.5 w-full animate-pulse rounded bg-slate-200" />
                </div>
                <div className="h-8 w-32 animate-pulse rounded bg-slate-200" />
                <div className="h-9 w-full animate-pulse rounded bg-slate-200" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="space-y-6">
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>加载质控数据失败</AlertTitle>
          <AlertDescription>
            <p className="mb-2">{error}</p>
            <Button variant="outline" size="sm" onClick={fetchCases} className="gap-1.5">
              <RefreshCw className="size-3.5" />
              重试
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-slate-900">出院前联合质控</h2>
          <p className="mt-1 text-sm text-slate-500">
            智能聚合首信、东软、大瑞集思、医保数据中台的风险提示
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchCases} className="gap-1.5">
            <RefreshCw className="size-3.5" />
            刷新
          </Button>
          <Badge className="bg-gradient-to-r from-orange-50 to-amber-50 text-amber-800 border border-amber-200/60 shadow-sm">
            <span className="relative mr-1 flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
            </span>
            {qcCases.length}个患者待质控
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {qcCases.map((qc) => {
          return (
            <Card
              key={qc.id}
              className={`border-slate-200/70 overflow-hidden transition-all duration-200 cursor-pointer group hover:shadow-md ${
                selectedCase === qc.id ? 'ring-2 ring-blue-500/40 shadow-md' : ''
              }`}
              onClick={() => setSelectedCase(qc.id === selectedCase ? null : qc.id)}
            >
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-lg font-semibold">{qc.patientName}</CardTitle>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {qc.department} · {qc.doctor}
                    </p>
                  </div>
                  <Badge variant="outline" className="text-[10px] bg-white text-slate-500 border-slate-200">
                    预计{qc.expectedDischarge}出院
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* 完成率 */}
                <div>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-slate-500">质控完成率</span>
                    <span className={`font-semibold ${
                      qc.completionRate < 50 ? 'text-rose-600' :
                      qc.completionRate < 80 ? 'text-amber-600' :
                      'text-emerald-600'
                    }`}>
                      {qc.completionRate}%
                    </span>
                  </div>
                  <Progress value={qc.completionRate} className="h-1.5 bg-slate-100" />
                </div>

                {/* 风险统计 */}
                <div className="flex gap-2 flex-wrap">
                  {riskLevels.map((level) => {
                    const count = qc.risks.filter((risk) => risk.level === level).length
                    if (count === 0) return null
                    return (
                      <Badge key={level} className={`${levelColors[level]} text-[10px]`}>
                        {level}风险 {count}项
                      </Badge>
                    )
                  })}
                </div>

                {/* 风险列表预览 */}
                <div className="space-y-2">
                  {qc.risks.slice(0, 2).map((risk) => {
                    const RiskIcon = levelIcons[risk.level]
                    return (
                      <div key={risk.id} className="flex items-start gap-2.5 text-sm rounded-lg bg-slate-50/50 p-2.5">
                        <RiskIcon className={`w-4 h-4 mt-0.5 shrink-0 ${
                          risk.level === '高' ? 'text-red-500' :
                          risk.level === '中' ? 'text-amber-500' :
                          'text-emerald-500'
                        }`} />
                        <span className="text-slate-700 leading-snug">{risk.description}</span>
                      </div>
                    )
                  })}
                  {qc.risks.length > 2 && (
                    <p className="text-xs text-slate-400 text-center">还有{qc.risks.length - 2}项风险...</p>
                  )}
                </div>

                <Button
                  variant="outline"
                  className="w-full border-slate-200 bg-white/50 hover:bg-slate-50 text-slate-700 group"
                  size="sm"
                  onClick={(e) => { e.stopPropagation(); setSelectedCase(qc.id === selectedCase ? null : qc.id) }}
                >
                  <span>查看详细清单</span>
                  <ChevronRight className="w-4 h-4 ml-1 group-hover:translate-x-0.5 transition-transform" />
                </Button>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* 空状态 */}
      {qcCases.length === 0 && !loading && !error && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <CheckCircle2 className="size-12 text-slate-300" />
          <p className="mt-4 text-sm font-medium text-slate-500">暂无待质控患者</p>
          <p className="text-xs text-slate-400">当前没有需要出院前联合质控的患者</p>
        </div>
      )}

      {/* 展开详情 */}
      {selectedCase && (
        <Card className="mt-6 border-slate-200/70 overflow-hidden animate-in">
          <CardHeader className="pb-3 border-b border-slate-100">
            <CardTitle className="flex items-center gap-2 text-base">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-50">
                <FileText className="w-4 h-4 text-blue-600" />
              </div>
              联合质控清单 — {qcCases.find((q) => q.id === selectedCase)?.patientName}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="space-y-3">
              {qcCases
                .find((q) => q.id === selectedCase)
                ?.risks.map((risk) => {
                  const RiskIcon = levelIcons[risk.level]
                  return (
                    <Alert key={risk.id} className={`border ${levelColors[risk.level]} bg-white`}>
                      <RiskIcon className="h-4 w-4" />
                      <AlertTitle className="flex items-center justify-between text-sm font-semibold">
                        <span>
                          [{risk.type}] {risk.description}
                        </span>
                        <Badge className={`${statusColors[risk.status]} text-[10px] ml-2`}>{risk.status}</Badge>
                      </AlertTitle>
                      <AlertDescription>
                        <div className="mt-2 space-y-1.5 text-xs">
                          <div className="flex items-center gap-2 text-slate-500">
                            <Activity className="w-3 h-3" />
                            <span>数据来源: {risk.source}</span>
                          </div>
                          <div className="flex items-center gap-2 text-slate-500">
                            <User className="w-3 h-3" />
                            <span>责任角色: {risk.assignee}</span>
                          </div>
                        </div>
                      </AlertDescription>
                    </Alert>
                  )
                })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
