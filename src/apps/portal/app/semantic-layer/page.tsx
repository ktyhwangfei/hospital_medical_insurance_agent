'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress, ProgressIndicator, ProgressTrack } from '@/components/ui/progress'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import {
  Building2, Box, BarChart3, Link2, Search,
  ArrowRight, CheckCircle2, Layers, Database,
} from 'lucide-react'

// ── API Response Types ──────────────────────────────────────────

interface DomainProgress {
  domain_code: string
  name: string
  total_metrics: number
  mapped_metrics: number
  percentage: number
}

interface SemanticSummary {
  domains_count: number
  objects_count: number
  metrics_count: number
  mapped_count: number
  unmapped_count: number
  value_missing_count: number
  mapping_rate: number
  skill_references: number
  domain_progress: DomainProgress[]
  discovery_tables: number
  discovery_fields: number
  discovery_unmapped: number
}

// ── API Path ─────────────────────────────────────────────────────

const API_PATH = '/api/v1/medical-insurance-ai-agent/semantic/summary'

// ── Helpers ──────────────────────────────────────────────────────

function progressBarColor(pct: number): string {
  if (pct >= 100) return 'bg-emerald-500'
  if (pct > 70) return 'bg-blue-500'
  return 'bg-amber-500'
}

function badgeStyle(pct: number): string {
  if (pct >= 100) return 'bg-emerald-50 text-emerald-600 border-emerald-200'
  if (pct > 70) return 'bg-blue-50 text-blue-600 border-blue-200'
  return 'bg-amber-50 text-amber-600 border-amber-200'
}

// ── Section Card (reusable) ──────────────────────────────────────

function SectionCard({
  icon: Icon,
  iconColor,
  iconBg,
  title,
  description,
  stats,
  href,
}: {
  icon: React.ComponentType<{ className?: string }>
  iconColor: string
  iconBg: string
  title: string
  description: string
  stats: { label: string; value: string | number; accent?: string }[]
  href: string
}) {
  return (
    <Link href={href} className="block group">
      <Card className="h-full border-slate-200/70 bg-white/80 backdrop-blur shadow-sm transition-all duration-200 hover:border-blue-400/50 hover:bg-white hover:shadow-md">
        <CardContent className="flex flex-col gap-4 px-5 py-5">
          {/* Header */}
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${iconBg} ${iconColor}`}>
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-base font-semibold text-slate-800 transition-colors group-hover:text-blue-600">
                {title}
              </h3>
              <p className="line-clamp-1 text-xs text-slate-500">{description}</p>
            </div>
            <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition-all group-hover:translate-x-0.5 group-hover:text-blue-500" />
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-3">
            {stats.map((stat, index) => (
              <div key={index} className="text-center">
                <div className={`text-lg font-bold tabular-nums ${stat.accent ?? 'text-slate-700'}`}>
                  {stat.value}
                </div>
                <div className="text-[10px] text-slate-400">{stat.label}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

// ── Main Page ────────────────────────────────────────────────────

export default function SemanticLayerDashboard() {
  const [data, setData] = useState<SemanticSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)

    fetch(API_PATH)
      .then((res) => {
        if (!res.ok) throw new Error(`请求失败 (${res.status})`)
        return res.json() as Promise<SemanticSummary>
      })
      .then((json) => {
        setData(json)
        setLoading(false)
      })
      .catch((err: Error) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  // ── Skeleton Loading ────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="border border-slate-200 bg-white shadow-sm">
              <CardHeader className="pb-2">
                <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
              </CardHeader>
              <CardContent>
                <div className="h-8 w-12 animate-pulse rounded bg-slate-200" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Card key={i} className="border border-slate-200 bg-white shadow-sm">
              <CardContent className="px-5 py-5">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 animate-pulse rounded-xl bg-slate-200" />
                  <div className="flex-1">
                    <div className="h-4 w-20 animate-pulse rounded bg-slate-200" />
                    <div className="mt-1 h-3 w-32 animate-pulse rounded bg-slate-200" />
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3">
                  {Array.from({ length: 3 }).map((_, j) => (
                    <div key={j} className="h-10 animate-pulse rounded bg-slate-200" />
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  // ── Error State ─────────────────────────────────────────────
  if (error) {
    return (
      <Alert variant="destructive" className="border-red-200 bg-red-50">
        <AlertTitle className="text-red-600">数据加载失败</AlertTitle>
        <AlertDescription className="text-red-600">{error}</AlertDescription>
      </Alert>
    )
  }

  if (!data) return null

  return (
    <div className="flex flex-col gap-6">
      {/* ── Top Stat Cards (4 columns) ─────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card className="border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-1.5">
            <CardTitle className="text-[11px] font-medium text-slate-500">领域</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-blue-600">
              {data.domains_count}
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-1.5">
            <CardTitle className="text-[11px] font-medium text-slate-500">对象</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-cyan-600">
              {data.objects_count}
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-1.5">
            <CardTitle className="text-[11px] font-medium text-slate-500">指标</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-purple-600">
              {data.metrics_count}
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-1.5">
            <CardTitle className="text-[11px] font-medium text-slate-500">技能引用</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold tracking-tight text-amber-600">
              {data.skill_references}
            </div>
            <p className="text-[10px] text-slate-400 mt-0.5">指标累计被引用次数</p>
          </CardContent>
        </Card>
      </div>

      {/* ── Mapping Overview Strip ────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-5 py-3 shadow-sm">
        <span className="text-sm font-medium text-slate-700">映射总览</span>
        <span className="font-mono text-2xl font-bold tabular-nums text-emerald-600">
          {data.mapping_rate.toFixed(1)}%
        </span>
        {data.mapping_rate >= 100 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200/60">
            <CheckCircle2 className="size-3" /> 已完成
          </span>
        )}
        <div className="h-2 flex-1 min-w-[100px]">
          <Progress value={data.mapping_rate} className="h-2">
            <ProgressTrack className="bg-slate-200 h-2">
              <ProgressIndicator className={progressBarColor(data.mapping_rate)} />
            </ProgressTrack>
          </Progress>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>已映射 <span className="font-mono text-slate-700">{data.mapped_count}</span></span>
          <span>值域缺失 <span className="font-mono text-amber-600">{data.value_missing_count}</span></span>
          <span>未映射 <span className="font-mono text-slate-700">{data.unmapped_count}</span></span>
          <span>总计 <span className="font-mono text-slate-700">{data.metrics_count}</span></span>
        </div>
      </div>

      {/* ── 5 Section Cards + Domain Progress ───────────────────── */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* 业务域 */}
        <SectionCard
          icon={Building2}
          iconColor="text-blue-600"
          iconBg="bg-blue-50"
          title="业务域"
          description="按业务场景组织对象与指标"
          stats={[
            { label: '域数量', value: data.domains_count, accent: 'text-blue-600' },
            { label: '对象数', value: data.objects_count, accent: 'text-cyan-600' },
            { label: '平均完成度', value: `${data.domain_progress.length > 0 ? Math.round(data.domain_progress.reduce((s, d) => s + d.percentage, 0) / data.domain_progress.length) : 0}%`, accent: 'text-slate-600' },
          ]}
          href="/semantic-layer/domain"
        />

        {/* 业务对象 */}
        <SectionCard
          icon={Box}
          iconColor="text-cyan-600"
          iconBg="bg-cyan-50"
          title="业务对象"
          description="管理对象定义及关联指标"
          stats={[
            { label: '对象总数', value: data.objects_count, accent: 'text-cyan-600' },
            { label: '映射率', value: `${data.mapping_rate.toFixed(0)}%`, accent: 'text-emerald-600' },
            { label: '未映射', value: data.unmapped_count, accent: 'text-red-500' },
          ]}
          href="/semantic-layer/object"
        />

        {/* 业务指标 */}
        <SectionCard
          icon={BarChart3}
          iconColor="text-purple-600"
          iconBg="bg-purple-50"
          title="业务指标"
          description="全局浏览与筛选所有指标"
          stats={[
            { label: '指标总数', value: data.metrics_count, accent: 'text-purple-600' },
            { label: '已映射', value: data.mapped_count, accent: 'text-emerald-600' },
            { label: '技能引用', value: data.skill_references, accent: 'text-amber-600' },
          ]}
          href="/semantic-layer/metrics"
        />

        {/* 映射 */}
        <SectionCard
          icon={Link2}
          iconColor="text-emerald-600"
          iconBg="bg-emerald-50"
          title="映射中心"
          description="追踪字段到指标映射关系"
          stats={[
            { label: '映射率', value: `${data.mapping_rate.toFixed(0)}%`, accent: 'text-emerald-600' },
            { label: '已映射', value: data.mapped_count, accent: 'text-emerald-600' },
            { label: '待处理', value: data.unmapped_count, accent: 'text-red-500' },
          ]}
          href="/semantic-layer/mapping"
        />

        {/* 发现 */}
        <SectionCard
          icon={Search}
          iconColor="text-amber-600"
          iconBg="bg-amber-50"
          title="发现中心"
          description="扫描表结构自动发现字段"
          stats={[
            { label: '扫描表数', value: data.discovery_tables, accent: 'text-blue-600' },
            { label: '发现字段', value: data.discovery_fields, accent: 'text-purple-600' },
            { label: '待映射', value: data.discovery_unmapped, accent: 'text-red-500' },
          ]}
          href="/semantic-layer/discovery"
        />
      </div>

      {/* ── Domain Construction Progress ────────────────────────── */}
      {data.domain_progress.length > 0 && (
        <Card className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base text-slate-800">
              <Layers className="h-4 w-4 text-blue-500" />
              领域建设进度
              <span className="ml-auto text-xs font-normal text-slate-400">
                {data.domain_progress.length} 个域
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.domain_progress.map((domain, index) => (
              <div key={domain.domain_code} className="flex items-center gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-medium text-slate-500">
                  {index + 1}
                </span>

                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center justify-between gap-3">
                    <Link
                      href={`/semantic-layer/domain/${domain.domain_code}`}
                      className="text-sm font-medium text-slate-700 transition-colors hover:text-blue-600 truncate"
                    >
                      {domain.name}
                    </Link>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="font-mono text-[11px] tabular-nums text-slate-500">
                        {domain.mapped_metrics}/{domain.total_metrics}
                      </span>
                      <Badge variant="outline" className={badgeStyle(domain.percentage)}>
                        {domain.percentage.toFixed(0)}%
                      </Badge>
                    </div>
                  </div>
                  <Progress value={domain.percentage}>
                    <ProgressTrack className="bg-slate-200">
                      <ProgressIndicator className={progressBarColor(domain.percentage)} />
                    </ProgressTrack>
                  </Progress>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
