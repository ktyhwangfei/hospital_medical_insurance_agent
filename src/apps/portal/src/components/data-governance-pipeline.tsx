'use client'

// 数据治理中心总览（架构设计 V3.0 §2）：
// ① 语义标准横条——业务语义是横向贯穿数据治理与数据消费的纽带，不是流水线的一个阶段；
// ② 数据资产生命周期——数据接入 → 数据探查 → 数据同步 → 数据建模 → 数据加工 → 质量与发布 → 数据资产。
// 各阶段状态聚合自既有只读接口，单接口失败独立降级为「—」。
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Database, ScanSearch, Layers, Workflow, ShieldCheck, FolderSearch, RefreshCw } from 'lucide-react'

import { getDataGovernanceOverview } from '@/lib/data-governance-api'
import { listDataModels } from '@/lib/data-model-api'
import { listSyncTables } from '@/lib/data-governance-api'
import { getSemanticSummary } from '@/lib/policy-knowledge-api'
import { listFlows } from '@/lib/flow-api'

const DISCOVERY_RESULTS_URL = '/api/v1/medical-insurance-ai-agent/semantic/discovery/results'

interface PipelineStats {
  sourceCount: number | null
  profiledTables: number | null
  profiledFields: number | null
  objectsCount: number | null
  metricsCount: number | null
  mappedFields: number | null
  unmappedFields: number | null
  modelsCount: number | null
  flowCount: number | null
  publishedFlows: number | null
  syncTables: number | null
  syncRows: number | null
}

const EMPTY: PipelineStats = {
  sourceCount: null, profiledTables: null, profiledFields: null,
  objectsCount: null, metricsCount: null, mappedFields: null, unmappedFields: null,
  modelsCount: null, flowCount: null, publishedFlows: null,
  syncTables: null, syncRows: null,
}

interface DiscoveryResults {
  total_tables?: number
  total_fields?: number
  mapped_fields?: number
  unmapped_fields?: number
}

async function fetchDiscoveryResults(): Promise<DiscoveryResults> {
  const res = await fetch(DISCOVERY_RESULTS_URL)
  if (!res.ok) throw new Error(`discovery results ${res.status}`)
  return res.json() as Promise<DiscoveryResults>
}

const num = (value: number | null) => (value === null ? '—' : String(value))

// ── 语义标准横条：横向纽带，横跨生命周期之上 ──────────────────────

function SemanticStandardBar({ stats }: { stats: PipelineStats }) {
  return (
    <Link
      href="/semantic-layer"
      data-testid="semantic-standard-bar"
      className="group block rounded-xl border border-dashed border-violet-300 bg-violet-50/50 px-4 py-3 transition-colors hover:border-violet-400 hover:bg-violet-50"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="text-xs font-semibold text-violet-700">语义标准（横向贯穿）</span>
        <span className="text-xs text-violet-600">
          业务对象 {num(stats.objectsCount)} · 指标 {num(stats.metricsCount)} · 语义映射 已确认 {num(stats.mappedFields)} / 待确认 {num(stats.unmappedFields)}
        </span>
        <span className="ml-auto text-[11px] text-violet-400 group-hover:text-violet-600">
          业务对象 / 指标 / 维度 / 值域 / 语义映射 → 语义层
        </span>
      </div>
    </Link>
  )
}

// ── 数据资产生命周期阶段卡 ─────────────────────────────────────

interface StageSpec {
  key: string
  title: string
  href: string | null
  icon: React.ReactNode
  lines: string[]
  pending?: string
}

function StageCard({ stage }: { stage: StageSpec }) {
  const body = (
    <>
      <div className="flex items-center gap-2">
        <span className={`flex size-6 shrink-0 items-center justify-center rounded-md ${
          stage.pending
            ? 'bg-slate-100 text-slate-400'
            : 'bg-slate-100 text-slate-600 group-hover:bg-blue-100 group-hover:text-blue-700'
        }`}>
          {stage.icon}
        </span>
        <div className="min-w-0">
          <p className={`truncate text-sm font-semibold ${stage.pending ? 'text-slate-400' : 'text-slate-800'}`}>
            {stage.title}
          </p>
        </div>
        {stage.pending && (
          <span className="ml-auto shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-400">
            {stage.pending}
          </span>
        )}
      </div>
      <div className="mt-2 space-y-0.5">
        {stage.lines.map((line) => (
          <p key={line} className={`truncate text-xs ${stage.pending ? 'text-slate-400' : 'text-slate-500'}`}>{line}</p>
        ))}
      </div>
    </>
  )

  const className = `group min-w-0 flex-1 rounded-xl border p-3 shadow-sm transition-colors ${
    stage.pending
      ? 'border-dashed border-slate-200 bg-slate-50/60'
      : 'border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/40'
  }`

  return stage.href
    ? <Link href={stage.href} data-testid={`pipeline-stage-${stage.key}`} className={className}>{body}</Link>
    : <div data-testid={`pipeline-stage-${stage.key}`} className={className}>{body}</div>
}

export function DataGovernancePipeline() {
  const [stats, setStats] = useState<PipelineStats>(EMPTY)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [overview, discovery, semantic, flows, models] = await Promise.allSettled([
        getDataGovernanceOverview(),
        fetchDiscoveryResults(),
        getSemanticSummary(),
        listFlows(),
        listDataModels(),
      ])
      if (cancelled) return
      // 数据同步阶段：取第一个数据源的选表同步清单
      let syncTables: number | null = null
      let syncRows: number | null = null
      if (overview.status === 'fulfilled' && overview.value.sources.length > 0) {
        try {
          const tables = await listSyncTables(overview.value.sources[0].sourceId)
          if (!cancelled) {
            syncTables = tables.length
            syncRows = tables.reduce((sum, t) => sum + (t.last_row_count ?? 0), 0)
          }
        } catch { /* 降级为 — */ }
      }
      setStats({
        sourceCount: overview.status === 'fulfilled' ? overview.value.dataSourceCount : null,
        profiledTables: discovery.status === 'fulfilled' ? discovery.value.total_tables ?? null : null,
        profiledFields: discovery.status === 'fulfilled' ? discovery.value.total_fields ?? null : null,
        objectsCount: semantic.status === 'fulfilled' ? semantic.value.objects_count ?? null : null,
        metricsCount: semantic.status === 'fulfilled' ? semantic.value.metrics_count : null,
        mappedFields: discovery.status === 'fulfilled' ? discovery.value.mapped_fields ?? null : null,
        unmappedFields: discovery.status === 'fulfilled' ? discovery.value.unmapped_fields ?? null : null,
        flowCount: flows.status === 'fulfilled' ? flows.value.length : null,
        publishedFlows: flows.status === 'fulfilled'
          ? flows.value.filter((f) => f.status === 'published').length : null,
        modelsCount: models.status === 'fulfilled' ? models.value.length : null,
        syncTables,
        syncRows,
      })
    })()
    return () => { cancelled = true }
  }, [])

  const stages: StageSpec[] = [
    {
      key: 'ingestion', title: '数据接入', href: '/data-governance/data-sources',
      icon: <Database className="size-3.5" />,
      lines: [`数据源 ${num(stats.sourceCount)} 个`, '登记 / 凭据 / 同步'],
    },
    {
      key: 'profiling', title: '数据探查', href: '/data-governance/profiling',
      icon: <ScanSearch className="size-3.5" />,
      lines: [`表画像 ${num(stats.profiledTables)} / 字段 ${num(stats.profiledFields)}`, '类型 / 非空率 / 值分布'],
    },
    {
      key: 'sync', title: '数据同步', href: '/data-governance/sync-jobs',
      icon: <RefreshCw className="size-3.5" />,
      lines: [`选表 ${num(stats.syncTables)} 张 / ${num(stats.syncRows)} 行`, '契约管道 + 选表直通'],
    },
    {
      key: 'modeling', title: '数据建模', href: '/data-governance/modeling',
      icon: <Layers className="size-3.5" />,
      lines: [`数据模型 ${num(stats.modelsCount)} 个`, 'ODS → DWD 结构标准 / 多源标准化'],
    },
    {
      key: 'transformation', title: '数据加工', href: '/data-governance/flows',
      icon: <Workflow className="size-3.5" />,
      lines: [`治理 Flow ${num(stats.flowCount)} 个`, '编排 / 编译 / 物化'],
    },
    {
      key: 'quality', title: '质量与发布', href: '/data-governance/quality',
      icon: <ShieldCheck className="size-3.5" />,
      lines: [`已发布 ${num(stats.publishedFlows)} 个`, '质量门禁 / 版本发布 / 回滚'],
    },
    {
      key: 'asset', title: '数据资产', href: '/data-governance/assets',
      icon: <FolderSearch className="size-3.5" />,
      lines: ['资产目录', '血缘 / 负责人 / SLA'],
    },
  ]

  return (
    <section aria-label="数据治理总览" data-testid="data-governance-pipeline" className="space-y-2">
      <SemanticStandardBar stats={stats} />
      <div className="flex flex-col gap-2 md:flex-row md:items-stretch">
        {stages.map((stage, index) => (
          <div key={stage.key} className="flex min-w-0 flex-1 items-center gap-2">
            <StageCard stage={stage} />
            {index < stages.length - 1 && (
              <ArrowRight aria-hidden="true" className="hidden size-4 shrink-0 text-slate-300 md:block" />
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
