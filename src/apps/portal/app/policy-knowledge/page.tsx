'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { FileText, Scissors, Database, AlertTriangle, ArrowRight, Loader2 } from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'
const MILVUS_API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'

interface PipelineSummary {
  documents_count: number
  documents_raw: number
  extractions_count: number
  extractions_draft: number
  extractions_reviewed: number
  extractions_published: number
}

export default function PolicyPipelineDashboard() {
  const [data, setData] = useState<PipelineSummary | null>(null)
  const [milvusTotal, setMilvusTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [summaryRes, statsRes] = await Promise.all([
        fetch(`${API}/summary`),
        fetch(`${MILVUS_API}/stats`),
      ])
      if (summaryRes.ok) setData(await summaryRes.json())
      if (statsRes.ok) {
        const s = await statsRes.json()
        setMilvusTotal(s.total || 0)
      }
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
  const totalSteps = d.documents_count + d.extractions_count + milvusTotal
  const step1Pct = totalSteps > 0 ? Math.round((d.documents_count / Math.max(totalSteps, 1)) * 100) : 0
  const step2Pct = totalSteps > 0 ? Math.round(((d.documents_count + d.extractions_count) / Math.max(totalSteps, 1)) * 100) : 0

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
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">管线概览</h2>
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

        <Link href="/policy-knowledge/segments" className="block group">
          <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all hover:border-purple-400/50 hover:shadow-md">
            <div className="flex items-center gap-2 mb-2">
              <Scissors className="size-4 text-purple-500" />
              <span className="text-xs text-slate-500">政策片段</span>
            </div>
            <div className="text-2xl font-bold text-purple-600">{d.extractions_count}</div>
            {pendingReview > 0 && <div className="mt-1 text-xs text-amber-600">{pendingReview} 条待审核</div>}
          </div>
        </Link>

        <Link href="/policy-knowledge/rules" className="block group">
          <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all hover:border-emerald-400/50 hover:shadow-md">
            <div className="flex items-center gap-2 mb-2">
              <Database className="size-4 text-emerald-500" />
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
            <div className="mt-1.5 text-xs font-medium text-slate-600">政策片段</div>
            <div className="text-[10px] text-slate-400">{d.extractions_count} 条</div>
          </div>
          <ArrowRight className="size-4 text-slate-300 shrink-0" />
          {/* Step 3 */}
          <div className="flex-1 text-center">
            <div className={`inline-flex size-10 items-center justify-center rounded-full text-sm font-bold ${milvusTotal > 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>3</div>
            <div className="mt-1.5 text-xs font-medium text-slate-600">入库生效</div>
            <div className="text-[10px] text-slate-400">{milvusTotal} 条</div>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link href="/policy-knowledge/documents" className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50/50 px-4 py-3 text-sm font-medium text-blue-700 hover:bg-blue-50 transition-colors">
          <FileText className="size-4" /> 管理政策原文
          <ArrowRight className="size-3.5 ml-auto" />
        </Link>
        <Link href="/policy-knowledge/segments" className="flex items-center gap-3 rounded-lg border border-purple-200 bg-purple-50/50 px-4 py-3 text-sm font-medium text-purple-700 hover:bg-purple-50 transition-colors">
          <Scissors className="size-4" /> 管理政策片段
          <ArrowRight className="size-3.5 ml-auto" />
        </Link>
        <Link href="/policy-knowledge/rules" className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50/50 px-4 py-3 text-sm font-medium text-emerald-700 hover:bg-emerald-50 transition-colors">
          <Database className="size-4" /> 查看已入库规则
          <ArrowRight className="size-3.5 ml-auto" />
        </Link>
      </div>
    </div>
  )
}
