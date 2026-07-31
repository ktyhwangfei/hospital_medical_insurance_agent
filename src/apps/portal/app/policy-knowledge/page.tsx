'use client'

// 政策知识治理 · 概览（治理看板）。
// 生命周期分布 + 待审 + 低置信预警 + 影响分析占位 + discovery 入口。
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.2]
//
// 数据聚合：policy-pipeline/summary（extraction 计数）+ policy-knowledge/stats（Milvus 已发布）。

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import {
  FileText, Anchor, Lightbulb, ShieldCheck, AlertTriangle, Loader2,
  Compass, Activity, GitBranch, Gauge,
} from 'lucide-react'

const PIPELINE_API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'
const MILVUS_API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'

interface PipelineSummary {
  documents_count: number
  documents_raw: number
  extractions_count: number
  extractions_draft: number
  extractions_reviewed: number
  extractions_published: number
}

const LC_BAR: { key: string; label: string; color: string }[] = [
  { key: 'draft', label: '待审 Draft', color: 'bg-slate-400' },
  { key: 'reviewed', label: '待发布 Review', color: 'bg-amber-400' },
  { key: 'published', label: '已发布 Published', color: 'bg-emerald-500' },
  { key: 'rejected', label: '已驳回', color: 'bg-red-400' },
]

export default function GovernanceDashboard() {
  const [data, setData] = useState<PipelineSummary | null>(null)
  const [milvusTotal, setMilvusTotal] = useState(0)
  const [lowConfCount, setLowConfCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [summaryRes, statsRes] = await Promise.all([
        fetch(`${PIPELINE_API}/summary`),
        fetch(`${MILVUS_API}/stats`),
      ])
      if (summaryRes.ok) setData(await summaryRes.json())
      if (statsRes.ok) { const s = await statsRes.json(); setMilvusTotal(s.total || 0) }

      // 低置信预警：扫一页 extractions 统计 < 0.8（轻量，仅预警示意）
      try {
        const r = await fetch(`${PIPELINE_API}/extractions?page=1&page_size=100`)
        if (r.ok) {
          const d = await r.json()
          const items = d.items || []
          setLowConfCount(items.filter((e: any) => (e.confidence ?? 1) < 0.8).length)
        }
      } catch { /* ignore */ }
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
        <span className="text-sm text-slate-400">加载治理数据...</span>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error || '治理概览数据暂不可用，请确认后端 policy-pipeline 接口已启用。'}
      </div>
    )
  }

  const d = data
  const rejected = Math.max(0, d.extractions_count - d.extractions_draft - d.extractions_reviewed - d.extractions_published)
  const lcCounts: Record<string, number> = {
    draft: d.extractions_draft,
    reviewed: d.extractions_reviewed,
    published: d.extractions_published,
    rejected,
  }
  const lcTotal = d.extractions_count || 1
  const pendingReview = d.extractions_draft

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <header className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">治理概览</h2>
        <p className="text-xs text-slate-500">质量 · 版本 · 审核 · 发布 · 追踪 · 影响分析</p>
      </header>

      {/* 四对象统计 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard href="/policy-knowledge/documents" icon={FileText} color="blue" label="文档" value={d.documents_count} sub={d.documents_raw > 0 ? `${d.documents_raw} 待提取` : undefined} />
        <StatCard href="/policy-knowledge/units" icon={Anchor} color="purple" label="单元 (Unit)" value={d.extractions_count} />
        <StatCard href="/policy-knowledge/knowledge?sub=library" icon={Lightbulb} color="emerald" label="已发布知识" value={milvusTotal} sub="进入检索池" />
        <StatCard href="/policy-knowledge/knowledge?sub=audit" icon={ShieldCheck} color="amber" label="待审知识" value={pendingReview} sub={pendingReview > 0 ? '需人工审核' : undefined} />
      </div>

      {/* 生命周期分布（治理核心可视化）*/}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <GitBranch className="size-4 text-indigo-500" />
          <h3 className="text-sm font-semibold text-slate-700">知识生命周期分布</h3>
          <span className="ml-auto text-xs text-slate-400">共 {d.extractions_count} 条</span>
        </div>
        {/* 堆叠条 */}
        <div className="mb-3 flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
          {LC_BAR.map((b) => {
            const cnt = lcCounts[b.key] || 0
            const pct = (cnt / lcTotal) * 100
            return pct > 0 ? <div key={b.key} className={b.color} style={{ width: `${pct}%` }} title={`${b.label}: ${cnt}`} /> : null
          })}
        </div>
        {/* 图例 + 计数 */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {LC_BAR.map((b) => (
            <div key={b.key} className="flex items-center gap-1.5">
              <span className={`size-2.5 rounded-sm ${b.color}`} />
              <span className="text-[11px] text-slate-500">{b.label}</span>
              <span className="ml-auto text-sm font-semibold text-slate-700">{lcCounts[b.key] || 0}</span>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-1.5 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
          <span className="rounded bg-violet-100 px-1.5 py-0.5 text-violet-700">已替代</span>
          <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-zinc-600">已废止</span>
          两态随版本治理接入（V2.1 §3.1），当前数据暂未承载。
        </div>
      </div>

      {/* 质量 + 影响分析 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 质量概览 */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Gauge className="size-4 text-cyan-500" />
            <h3 className="text-sm font-semibold text-slate-700">质量概览</h3>
          </div>
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-amber-500" />
              <span className="text-xs text-slate-500">低置信预警 (&lt;0.8)</span>
              <span className="ml-auto text-lg font-bold text-amber-600">{lowConfCount}</span>
              <Link href="/policy-knowledge/knowledge?sub=audit" className="ml-2 text-[10px] text-slate-400 hover:text-slate-600">查看 →</Link>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <ShieldCheck className="size-4 text-slate-300" />
              质量门禁（填充率 / 值域合规率 / 黄金样本一致性）随提取增强接入。
            </div>
          </div>
        </div>

        {/* 影响分析（占位）*/}
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <Activity className="size-4 text-indigo-500" />
            <h3 className="text-sm font-semibold text-slate-700">影响分析</h3>
            <span className="ml-auto rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">待接入</span>
          </div>
          <p className="text-xs leading-relaxed text-slate-500">
            政策变更 → 定位受影响 Unit → 关联 Knowledge → 经提取契约反查 Metric（止于此，Skill/Agent 独立消费）。
            影响链 <code className="rounded bg-slate-100 px-1 text-[10px]">Document → Unit → Knowledge → Metric</code> 随文档版本治理接入。
          </p>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link href="/policy-knowledge/documents" className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50/50 px-4 py-3 text-sm font-medium text-blue-700 hover:bg-blue-50 transition-colors">
          <FileText className="size-4" /> 管理文档 <span className="ml-auto text-slate-300">→</span>
        </Link>
        <Link href="/policy-knowledge/units" className="flex items-center gap-3 rounded-lg border border-purple-200 bg-purple-50/50 px-4 py-3 text-sm font-medium text-purple-700 hover:bg-purple-50 transition-colors">
          <Anchor className="size-4" /> 浏览单元 <span className="ml-auto text-slate-300">→</span>
        </Link>
        <Link href="/policy-knowledge/knowledge?sub=audit" className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50/50 px-4 py-3 text-sm font-medium text-amber-700 hover:bg-amber-50 transition-colors">
          <ShieldCheck className="size-4" /> 知识审核 <span className="ml-auto text-slate-300">→</span>
        </Link>
      </div>

      {/* Discovery 入口（候选指标回写语义层）*/}
      <Link href="/policy-knowledge/discovery" className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-600">
        <Compass className="size-3.5" /> 发现（扫描高频实体/关系 → 候选指标回写语义层）→
      </Link>
    </div>
  )
}

function StatCard({
  href, icon: Icon, color, label, value, sub,
}: {
  href: string
  icon: React.ComponentType<{ className?: string }>
  color: 'blue' | 'purple' | 'emerald' | 'amber'
  label: string
  value: number
  sub?: string
}) {
  const palette: Record<string, string> = {
    blue: 'hover:border-blue-400/50 text-blue-600',
    purple: 'hover:border-purple-400/50 text-purple-600',
    emerald: 'hover:border-emerald-400/50 text-emerald-600',
    amber: 'hover:border-amber-400/50 text-amber-600',
  }
  return (
    <Link href={href} className="block group">
      <div className={`rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm transition-all ${palette[color]} hover:shadow-md`}>
        <div className="mb-2 flex items-center gap-2">
          <Icon className="size-4" />
          <span className="text-xs text-slate-500">{label}</span>
        </div>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
      </div>
    </Link>
  )
}
