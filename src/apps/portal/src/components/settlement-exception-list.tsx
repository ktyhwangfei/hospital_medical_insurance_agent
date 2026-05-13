'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock,
  Filter,
  RefreshCw,
  Search,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { listWorkflows } from '@/lib/api-client'
import type { RoleId, WorkflowItem } from '@/lib/types'

type WorkStatus = '待处理' | '处理中' | '已完成'
type Priority = '高' | '中' | '低'

interface DisplayItem {
  id: string
  patientName: string
  patientId: string
  exceptionType: string
  errorCode: string
  errorMsg: string
  detectedAt: string
  status: WorkStatus
  priority: Priority
}

function toDisplayItem(wf: WorkflowItem): DisplayItem {
  const statusMap: Record<string, WorkStatus> = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
  }
  const priorityMap: Record<string, Priority> = {
    high: '高',
    medium: '中',
    low: '低',
  }

  return {
    id: wf.workflow_id,
    patientName: wf.patient_name ?? wf.patient?.name ?? '未知患者',
    patientId: wf.patient_id ?? wf.patient?.patient_id ?? '',
    exceptionType: wf.exception_type ?? wf.scenario ?? '结算异常',
    errorCode: wf.error_code ?? '',
    errorMsg: wf.error_msg ?? '',
    detectedAt: wf.detected_at ?? wf.created_at ?? '',
    status: statusMap[wf.status] ?? (wf.status as WorkStatus),
    priority: priorityMap[wf.priority ?? ''] ?? '中',
  }
}

const priorityColors: Record<Priority, string> = {
  '高': 'bg-rose-50 text-rose-700 ring-rose-200',
  '中': 'bg-amber-50 text-amber-700 ring-amber-200',
  '低': 'bg-slate-50 text-slate-600 ring-slate-200',
}

const statusIcons: Record<WorkStatus, typeof Clock> = {
  '待处理': Clock,
  '处理中': RefreshCw,
  '已完成': CheckCircle2,
}

const statusColors: Record<WorkStatus, string> = {
  '待处理': 'text-rose-600 bg-rose-50 ring-rose-200',
  '处理中': 'text-amber-600 bg-amber-50 ring-amber-200',
  '已完成': 'text-emerald-600 bg-emerald-50 ring-emerald-200',
}

function StatCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string
  value: string
  icon: typeof AlertTriangle
  color: string
}) {
  return (
    <Card size="sm">
      <CardContent className="flex items-center gap-3 px-4 py-3">
        <div className={`flex size-10 items-center justify-center rounded-xl ${color}`}>
          <Icon className="size-5 text-white" />
        </div>
        <div>
          <p className="text-xs text-slate-500">{label}</p>
          <p className="text-lg font-bold text-slate-800">{value}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export default function SettlementExceptionList({
  currentRole: _currentRole,
}: {
  currentRole: RoleId
}) {
  const [items, setItems] = useState<DisplayItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatus, setFilterStatus] = useState<WorkStatus | '全部'>('全部')

  const fetchItems = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const workflows = await listWorkflows({ scenario: 'settlement_exception', status: 'pending,processing' })
      setItems(workflows.map(toDisplayItem))
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载失败'
      setError(message)
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const pendingCount = items.filter((s) => s.status === '待处理').length
  const inProgressCount = items.filter((s) => s.status === '处理中').length
  const highPriorityCount = items.filter((s) => s.priority === '高').length

  const filtered = items.filter((item) => {
    const matchSearch =
      !searchQuery ||
      item.patientName.includes(searchQuery) ||
      item.patientId.includes(searchQuery) ||
      item.errorCode.includes(searchQuery)
    const matchStatus = filterStatus === '全部' || item.status === filterStatus
    return matchSearch && matchStatus
  })

  // Loading skeleton
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Card key={i} size="sm">
              <CardContent className="flex items-center gap-3 px-4 py-3">
                <div className="size-10 animate-pulse rounded-xl bg-slate-200" />
                <div className="space-y-2">
                  <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
                  <div className="h-5 w-12 animate-pulse rounded bg-slate-200" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
        <Card>
          <CardHeader>
            <div className="h-5 w-32 animate-pulse rounded bg-slate-200" />
          </CardHeader>
          <CardContent className="space-y-3 px-5">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="h-8 w-1 animate-pulse rounded-full bg-slate-200" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-40 animate-pulse rounded bg-slate-200" />
                  <div className="h-3 w-64 animate-pulse rounded bg-slate-200" />
                </div>
                <div className="h-5 w-20 animate-pulse rounded bg-slate-200" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="space-y-6">
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>
            <p className="mb-2">{error}</p>
            <Button variant="outline" size="sm" onClick={fetchItems} className="gap-1.5">
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
      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="待处理异常"
          value={String(pendingCount)}
          icon={AlertTriangle}
          color="bg-gradient-to-br from-rose-500 to-rose-600"
        />
        <StatCard
          label="处理中"
          value={String(inProgressCount)}
          icon={RefreshCw}
          color="bg-gradient-to-br from-amber-500 to-amber-600"
        />
        <StatCard
          label="高风险"
          value={String(highPriorityCount)}
          icon={AlertTriangle}
          color="bg-gradient-to-br from-red-500 to-red-600"
        />
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>结算异常列表</CardTitle>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
                <Input
                  placeholder="搜索患者/错误码..."
                  className="h-8 w-56 pl-8 text-sm"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-1 rounded-lg border border-slate-200 p-0.5">
                {(['全部', '待处理', '处理中', '已完成'] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setFilterStatus(s)}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                      filterStatus === s
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-slate-500 hover:text-slate-700'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={fetchItems}>
                <RefreshCw className="size-3.5" />
                刷新
              </Button>
              <Button variant="outline" size="sm" className="gap-1.5">
                <Filter className="size-3.5" />
                筛选
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-0">
          <div className="divide-y divide-slate-100">
            {filtered.map((item) => {
              const StatusIcon = statusIcons[item.status]
              return (
                <div
                  key={item.id}
                  className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-slate-50"
                >
                  {/* Priority indicator */}
                  <div
                    className={`h-8 w-1 shrink-0 rounded-full ${
                      item.priority === '高'
                        ? 'bg-rose-400'
                        : item.priority === '中'
                          ? 'bg-amber-400'
                          : 'bg-slate-300'
                    }`}
                  />

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-slate-800">
                        {item.patientName}
                      </span>
                      <span className="text-xs text-slate-400">{item.patientId}</span>
                      <Badge variant="outline" className="text-[10px] font-normal">
                        {item.exceptionType}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500 truncate">
                      [{item.errorCode}] {item.errorMsg}
                    </p>
                  </div>

                  {/* Meta */}
                  <div className="hidden items-center gap-3 text-xs text-slate-400 sm:flex">
                    <span className="flex items-center gap-1">
                      <Clock className="size-3" />
                      {item.detectedAt}
                    </span>
                  </div>

                  {/* Status */}
                  <Badge
                    variant="outline"
                    className={`inline-flex items-center gap-1 ring-1 ${statusColors[item.status]}`}
                  >
                    <StatusIcon className="size-3" />
                    {item.status}
                  </Badge>

                  {/* Action button */}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="gap-1 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                    onClick={() => {
                      const prefill =
                        `查看处理步骤：患者 ${item.patientName}（${item.patientId}）的结算异常 ${item.errorCode}`
                      window.location.href = `/?prefill=${encodeURIComponent(prefill)}`
                    }}
                  >
                    查看处理步骤
                    <ChevronRight className="size-3" />
                  </Button>
                </div>
              )
            })}
          </div>

          {/* Empty state */}
          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CheckCircle2 className="size-10 text-slate-300" />
              <p className="mt-3 text-sm font-medium text-slate-500">
                {searchQuery || filterStatus !== '全部'
                  ? '暂无匹配的结算异常'
                  : '暂无待处理的结算异常'}
              </p>
              <p className="text-xs text-slate-400">
                {searchQuery || filterStatus !== '全部'
                  ? '尝试调整筛选条件'
                  : '当前没有需要处理的结算异常'}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
