'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import {
  FileText, Boxes, ListTree, AlertTriangle, ArrowRight, Loader2,
  ShieldCheck, Compass, Activity,
} from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'
const MILVUS_API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'
const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

interface PipelineSummary {
  documents_count: number
  documents_raw: number
  extractions_count: number
  extractions_draft: number
  extractions_reviewed: number
  extractions_published: number
}

interface SemanticSummary {
  domains_count: number
  objects_count: number
  metrics_count: number
  mapped_count: number
  unmapped_count: number
  mapping_rate: number
  value_missing_count: number
  skill_references: number
  discovery_tables: number
  discovery_fields: number
  discovery_unmapped: number
}

interface SchemaUpdateTask {
  task_id: string
  metric_code: string
  strategy: string
  status: string  // pending | running | done | failed
  progress: number
  total: number
  processed: number
  updated_at?: string
}

const TASK_STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  pending: { label: '待执行', cls: 'bg-slate-100 text-slate-600' },
  running: { label: '执行中', cls: 'bg-blue-100 text-blue-700' },
  done: { label: '已完成', cls: 'bg-emerald-100 text-emerald-700' },
  failed: { label: '失败', cls: 'bg-red-100 text-red-700' },
}

export default function PolicyPipelineDashboard() {
  const [data, setData] = useState<PipelineSummary | null>(null)
  const [milvusTotal, setMilvusTotal] = useState(0)
  const [semantic, setSemantic] = useState<SemanticSummary | null>(null)
  const [tasks, setTasks] = useState<SchemaUpdateTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [summaryRes, statsRes, semanticRes, tasksRes] = await Promise.all([
        fetch(`${API}/summary`),
        fetch(`${MILVUS_API}/stats`),
        fetch(`${SEMANTIC_API}/summary`),
        fetch(`${API}/schema-update/tasks`),
      ])
      if (summaryRes.ok) setData(await summaryRes.json())
      if (statsRes.ok) {
        const s = await statsRes.json()
        setMilvusTotal(s.total || 0)
      }
      if (semanticRes.ok) setSemantic(await semanticRes.json())
      if (tasksRes.ok) setTasks(await tasksRes.json())
    } catch {
      setError('无法连接后端')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <Loader2 className="size-6 text-blue-500 animate-spin" />
        <span className="text-sm text-slate-400">加载管线数据...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
    )
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
        管线概览数据暂不可用，请确认后端 policy-pipeline 接口已启用。
      </div>
    )
  }

  const d = data
  const pendingDocs = d.documents_raw
  const pendingReview = d.extractions_draft

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            政策知识管线
          </span>
          <span className="text-xs text-slate-500">从政策原文到知识规则的全流程管理</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">概览</h2>
      </header>

      {/* Top Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Link href="/policy-knowledge/documents" className="block group">
          <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all hover:border-blue-400/50 hover:shadow-md">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="size-4 text-blue-500" />
              <span className="text-xs text-slate-500">政策原文</span>
            </div>
            <div className="text-2xl font-bold text-blue-600">{d.documents_count}</div>
            {pendingDocs > 0 && <div className="mt-1 text-xs text-amber-600">{pendingDocs} 条待提取</div>}
          </div>
        </Link>

        <Link href="/policy-knowledge/facts" className="block group">
          <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all hover:border-purple-400/50 hover:shadow-md">
            <div className="flex items-center gap-2 mb-2">
              <Boxes className="size-4 text-purple-500" />
              <span className="text-xs text-slate-500">事实/提取</span>
            </div>
            <div className="text-2xl font-bold text-purple-600">{d.extractions_count}</div>
            {pendingReview > 0 && <div className="mt-1 text-xs text-amber-600">{pendingReview} 条待审核</div>}
          </div>
        </Link>

        <Link href="/policy-knowledge/structured" className="block group">
          <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all hover:border-emerald-400/50 hover:shadow-md">
            <div className="flex items-center gap-2 mb-2">
              <ListTree className="size-4 text-emerald-500" />
              <span className="text-xs text-slate-500">已入库规则</span>
            </div>
            <div className="text-2xl font-bold text-emerald-600">{milvusTotal}</div>
          </div>
        </Link>

        <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="size-4 text-amber-500" />
            <span className="text-xs text-slate-500">待处理</span>
          </div>
          <div className="text-2xl font-bold text-amber-600">{pendingDocs + pendingReview}</div>
        </div>
      </div>

      {/* 3-Step Pipeline Progress */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 mb-4">处理流程</h3>
        <div className="flex items-center gap-0">
          {/* Step 1 */}
          <div className="flex-1 text-center">
            <div className={`inline-flex size-10 items-center justify-center rounded-full text-sm font-bold ${d.documents_count > 0 ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-400'}`}>1</div>
            <div className="mt-1.5 text-xs font-medium text-slate-600">政策原文</div>
            <div className="text-[10px] text-slate-400">{d.documents_count} 条</div>
          </div>
          <ArrowRight className="size-4 text-slate-300 shrink-0" />
          {/* Step 2 */}
          <div className="flex-1 text-center">
            <div className={`inline-flex size-10 items-center justify-center rounded-full text-sm font-bold ${d.extractions_count > 0 ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-400'}`}>2</div>
            <div className="mt-1.5 text-xs font-medium text-slate-600">事实拆分</div>
            <div className="text-[10px] text-slate-400">{d.extractions_count} 条</div>
          </div>
          <ArrowRight className="size-4 text-slate-300 shrink-0" />
          {/* Step 3 */}
          <div className="flex-1 text-center">
            <div className={`inline-flex size-10 items-center justify-center rounded-full text-sm font-bold ${milvusTotal > 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>3</div>
            <div className="mt-1.5 text-xs font-medium text-slate-600">结构化入库</div>
            <div className="text-[10px] text-slate-400">{milvusTotal} 条</div>
          </div>
        </div>
      </div>

      {/* 质量与映射概览（9.2 新增） */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-4">
          <ShieldCheck className="size-4 text-indigo-500" />
          <h3 className="text-sm font-semibold text-slate-700">质量与映射概览</h3>
          <Link href="/policy-knowledge/discovery" className="ml-auto text-xs text-slate-400 hover:text-slate-600">
            发现 →
          </Link>
        </div>
        {semantic ? (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div>
              <div className="text-xs text-slate-500">指标映射率</div>
              <div className="mt-1 text-2xl font-bold text-indigo-600">{Math.round(semantic.mapping_rate * 100)}%</div>
              <div className="text-[10px] text-slate-400">{semantic.mapped_count}/{semantic.metrics_count} 指标已映射</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">未映射指标</div>
              <div className="mt-1 text-2xl font-bold text-amber-600">{semantic.unmapped_count}</div>
              <div className="text-[10px] text-slate-400">值域缺失 {semantic.value_missing_count}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">语义层规模</div>
              <div className="mt-1 text-2xl font-bold text-slate-700">{semantic.metrics_count}</div>
              <div className="text-[10px] text-slate-400">{semantic.domains_count} 域 / {semantic.objects_count} 对象</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">数据源扫描</div>
              <div className="mt-1 text-2xl font-bold text-slate-700">{semantic.discovery_tables}</div>
              <div className="text-[10px] text-slate-400">{semantic.discovery_fields} 字段 / {semantic.discovery_unmapped} 未映射</div>
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-400">语义层 summary 接口暂不可用。</div>
        )}
      </div>

      {/* 更新任务状态（9.2 新增） */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="size-4 text-cyan-500" />
          <h3 className="text-sm font-semibold text-slate-700">schema 演化任务</h3>
        </div>
        {tasks.length > 0 ? (
          <div className="flex flex-col gap-2">
            {tasks.slice(0, 5).map((t) => {
              const st = TASK_STATUS_LABEL[t.status] || { label: t.status, cls: 'bg-slate-100 text-slate-600' }
              return (
                <div key={t.task_id} className="flex items-center gap-3 rounded-lg border border-slate-100 px-3 py-2">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${st.cls}`}>{st.label}</span>
                  <code className="text-xs text-slate-600">{t.metric_code}</code>
                  <span className="text-xs text-slate-400">{t.strategy}</span>
                  <div className="ml-auto flex items-center gap-2">
                    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full bg-cyan-500" style={{ width: `${t.progress}%` }} />
                    </div>
                    <span className="text-xs text-slate-500">{t.processed}/{t.total}</span>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Compass className="size-3.5" />暂无 schema 演化任务。
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link href="/policy-knowledge/documents" className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50/50 px-4 py-3 text-sm font-medium text-blue-700 hover:bg-blue-50 transition-colors">
          <FileText className="size-4" /> 管理政策原文
          <ArrowRight className="size-3.5 ml-auto" />
        </Link>
        <Link href="/policy-knowledge/facts" className="flex items-center gap-3 rounded-lg border border-purple-200 bg-purple-50/50 px-4 py-3 text-sm font-medium text-purple-700 hover:bg-purple-50 transition-colors">
          <Boxes className="size-4" /> 事实拆分与提取
          <ArrowRight className="size-3.5 ml-auto" />
        </Link>
        <Link href="/policy-knowledge/structured" className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50/50 px-4 py-3 text-sm font-medium text-emerald-700 hover:bg-emerald-50 transition-colors">
          <ListTree className="size-4" /> 结构化检索
          <ArrowRight className="size-3.5 ml-auto" />
        </Link>
      </div>
    </div>
  )
}