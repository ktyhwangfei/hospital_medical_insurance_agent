'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Database, Loader2, AlertCircle, RefreshCw, Search, X,
  Table2, Brain, Sigma, MousePointerClick, Network, Gauge,
} from 'lucide-react'
import {
  getCatalogAssetLineage,
  getCatalogSla,
  listCatalogAssets,
  refreshCatalog,
} from '@/lib/data-catalog-api'
import type {
  AssetLineage,
  CatalogAsset,
  CatalogAssetType,
  DataCatalogSlaResponse,
  LineageNode,
} from '@/lib/data-catalog-api'

// ── 工具 ────────────────────────────────────────────────────

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
  } catch { return iso }
}

const TYPE_META: Record<CatalogAssetType, { label: string; cls: string; icon: React.ReactNode }> = {
  source_table: { label: '源表', cls: 'bg-sky-50 text-sky-700', icon: <Table2 className="size-3" /> },
  semantic_object: { label: '语义对象', cls: 'bg-violet-50 text-violet-700', icon: <Brain className="size-3" /> },
  metric: { label: '指标', cls: 'bg-emerald-50 text-emerald-700', icon: <Sigma className="size-3" /> },
  consumer: { label: '消费方', cls: 'bg-amber-50 text-amber-700', icon: <MousePointerClick className="size-3" /> },
}

const TYPE_TABS: { key: CatalogAssetType | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'source_table', label: '源表' },
  { key: 'semantic_object', label: '语义对象' },
  { key: 'metric', label: '指标' },
  { key: 'consumer', label: '消费方' },
]

function TypeBadge({ type }: { type: CatalogAssetType }) {
  const m = TYPE_META[type]
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-px text-[10px] font-semibold ${m.cls}`}>
      {m.icon}{m.label}
    </span>
  )
}

// ── SLA 看板条 ──────────────────────────────────────────────

function SlaStrip({ sla }: { sla: DataCatalogSlaResponse | null }) {
  const sync = sla?.outpatient_sync
  const qualityCls =
    sync?.quality_status === 'ok'
      ? 'text-emerald-600'
      : sync
        ? 'text-red-600'
        : 'text-neutral-400'
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[
        { label: '门诊同步 P95', value: sync?.p95_latency_seconds != null ? `${sync.p95_latency_seconds.toFixed(1)}s` : '—' },
        { label: '质量状态', value: sync?.quality_status || '—', cls: qualityCls },
        { label: '最近批次', value: sync?.last_batch_id ? sync.last_batch_id.slice(0, 8) : '—', mono: true },
        { label: '质量门禁任务', value: String(sla?.quality_gates.length ?? 0) },
      ].map((c) => (
        <div key={c.label} className="rounded-2xl border border-neutral-200 bg-white p-3 shadow-sm">
          <p className="text-[11px] text-neutral-400">{c.label}</p>
          <p className={`mt-1 text-lg font-semibold ${c.cls ?? 'text-neutral-800'} ${c.mono ? 'font-mono text-sm' : ''}`}>
            {c.value}
          </p>
        </div>
      ))}
    </div>
  )
}

// ── 血缘视图（上下游分组列表，子图大时截断展示）──────────────

const RELATION_LABEL: Record<string, string> = {
  feeds: '供给数据',
  belongs_to: '归属对象',
  consumed_by: '被消费',
}

function LineageView({ lineage }: { lineage: AssetLineage }) {
  const byId = new Map<string, LineageNode>(lineage.nodes.map((n) => [n.asset_id, n]))
  const upstream = lineage.edges.filter((e) => e.downstream === lineage.root)
  const downstream = lineage.edges.filter((e) => e.upstream === lineage.root)

  const renderList = (edges: typeof lineage.edges, pick: 'upstream' | 'downstream') => (
    <ul className="space-y-1">
      {edges.slice(0, 20).map((e, i) => {
        const node = byId.get(e[pick])
        if (!node) return null
        return (
          <li key={`${e.upstream}-${e.downstream}-${i}`} className="flex items-center gap-2 text-xs">
            <TypeBadge type={node.asset_type} />
            <span className="truncate text-neutral-700">{node.name}</span>
            <span className="shrink-0 text-[10px] text-neutral-400">{RELATION_LABEL[e.relation] ?? e.relation}</span>
            {node.last_batch_id && (
              <span className="shrink-0 font-mono text-[10px] text-neutral-400">
                批次 {node.last_batch_id.slice(0, 8)}
              </span>
            )}
          </li>
        )
      })}
      {edges.length > 20 && (
        <li className="text-[10px] text-neutral-400">… 其余 {edges.length - 20} 条已折叠</li>
      )}
    </ul>
  )

  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 text-[11px] font-semibold text-neutral-500">上游（{upstream.length}）</p>
        {upstream.length ? renderList(upstream, 'upstream') : <p className="text-xs text-neutral-400">无</p>}
      </div>
      <div>
        <p className="mb-1 text-[11px] font-semibold text-neutral-500">下游（{downstream.length}）</p>
        {downstream.length ? renderList(downstream, 'downstream') : <p className="text-xs text-neutral-400">无</p>}
      </div>
    </div>
  )
}

// ── 详情面板 ────────────────────────────────────────────────

function AssetDetail({ asset, onClose }: { asset: CatalogAsset; onClose: () => void }) {
  const [lineage, setLineage] = useState<AssetLineage | null>(null)
  const [lineageError, setLineageError] = useState<string | null>(null)

  useEffect(() => {
    setLineage(null); setLineageError(null)
    getCatalogAssetLineage(asset.asset_id)
      .then(setLineage)
      .catch((e) => setLineageError(e instanceof Error ? e.message : '血缘加载失败'))
  }, [asset.asset_id])

  const rows: [string, React.ReactNode][] = [
    ['资产键', <span key="k" className="font-mono text-xs">{asset.asset_key}</span>],
    ['负责人', asset.owner || '—'],
    ['刷新频率', asset.refresh_freq || '—'],
    ['语义版本', asset.semantic_version ? `v${asset.semantic_version}` : '—'],
    ['最近批次', asset.last_batch_id ? <span key="b" className="font-mono text-xs">{asset.last_batch_id}</span> : '—'],
    ['更新时间', fmtTime(asset.updated_at)],
  ]

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TypeBadge type={asset.asset_type} />
          <p className="text-sm font-semibold text-neutral-800">{asset.name}</p>
        </div>
        <button onClick={onClose} className="rounded-lg p-1 text-neutral-400 hover:bg-neutral-100" aria-label="关闭详情">
          <X className="size-4" />
        </button>
      </div>
      {asset.description && <p className="mb-3 text-xs text-neutral-500">{asset.description}</p>}
      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[10px] text-neutral-400">{label}</dt>
            <dd className="text-xs text-neutral-700">{value}</dd>
          </div>
        ))}
      </dl>
      {Object.keys(asset.sample_summary).length > 0 && (
        <p className="mb-3 text-[11px] text-neutral-500">
          脱敏摘要：{Object.entries(asset.sample_summary).map(([k, v]) => `${k}=${String(v)}`).join('，')}
        </p>
      )}
      <div className="border-t border-neutral-100 pt-3">
        <div className="mb-2 flex items-center gap-1.5">
          <Network className="size-3.5 text-neutral-400" />
          <p className="text-[11px] font-semibold text-neutral-500">血缘</p>
        </div>
        {lineageError && <p className="text-xs text-red-500">{lineageError}</p>}
        {!lineage && !lineageError && (
          <p className="flex items-center gap-1 text-xs text-neutral-400"><Loader2 className="size-3 animate-spin" />加载中</p>
        )}
        {lineage && <LineageView lineage={lineage} />}
      </div>
    </div>
  )
}

// ── 主页面 ──────────────────────────────────────────────────

export default function DataCatalogPage() {
  const [tab, setTab] = useState<CatalogAssetType | 'all'>('all')
  const [keyword, setKeyword] = useState('')
  const [assets, setAssets] = useState<CatalogAsset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<CatalogAsset | null>(null)
  const [sla, setSla] = useState<DataCatalogSlaResponse | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshNote, setRefreshNote] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const body = await listCatalogAssets({
        asset_type: tab === 'all' ? undefined : tab,
        keyword: keyword.trim() || undefined,
        limit: 200,
      })
      setAssets(body.items)
    } catch (e) {
      setError(e instanceof Error ? e.message : '目录加载失败')
    } finally { setLoading(false) }
  }, [tab, keyword])

  useEffect(() => { load() }, [load])
  useEffect(() => { getCatalogSla().then(setSla).catch(() => setSla(null)) }, [])

  const doRefresh = async () => {
    setRefreshing(true); setRefreshNote(null)
    try {
      const stats = await refreshCatalog()
      setRefreshNote(`已刷新：写入 ${stats.upserted}，清理 ${stats.pruned}`)
      await load()
      getCatalogSla().then(setSla).catch(() => undefined)
    } catch (e) {
      setRefreshNote(e instanceof Error ? e.message : '刷新失败')
    } finally { setRefreshing(false) }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="size-5 text-sky-600" />
          <h1 className="text-lg font-semibold text-neutral-800">数据目录</h1>
          <span className="text-[11px] text-neutral-400">资产清单 / 搜索 / 血缘 / SLA</span>
        </div>
        <button
          onClick={doRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-600 shadow-sm hover:bg-neutral-50 disabled:opacity-40"
        >
          {refreshing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          刷新目录
        </button>
      </div>
      {refreshNote && <p className="text-xs text-neutral-500">{refreshNote}</p>}

      <div className="flex items-center gap-1.5 text-[11px] text-neutral-400">
        <Gauge className="size-3.5" /> SLA 概览
      </div>
      <SlaStrip sla={sla} />

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-neutral-200 bg-white p-0.5 shadow-sm">
          {TYPE_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                tab === t.key ? 'bg-sky-50 text-sky-700' : 'text-neutral-500 hover:text-neutral-800'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-neutral-400" />
          <input
            placeholder="搜索名称 / 描述 / 资产键"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            className="w-full rounded-xl border border-neutral-200 bg-white/80 py-2 pl-9 pr-3 text-sm shadow-sm outline-none focus:border-sky-300"
          />
        </div>
      </div>

      {error && (
        <p className="flex items-center gap-1.5 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
          <AlertCircle className="size-3.5" />{error}
        </p>
      )}

      {selected && <AssetDetail asset={selected} onClose={() => setSelected(null)} />}

      <div className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
        {loading ? (
          <p className="flex items-center justify-center gap-2 py-10 text-sm text-neutral-400">
            <Loader2 className="size-4 animate-spin" />加载中
          </p>
        ) : assets.length === 0 ? (
          <p className="py-10 text-center text-sm text-neutral-400">无匹配资产</p>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {assets.map((a) => (
              <li key={a.asset_id}>
                <button
                  onClick={() => setSelected(a)}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-sky-50/40"
                >
                  <TypeBadge type={a.asset_type} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-neutral-800">{a.name}</span>
                    {a.description && (
                      <span className="block truncate text-[11px] text-neutral-400">{a.description}</span>
                    )}
                  </span>
                  {a.semantic_version && (
                    <span className="shrink-0 text-[10px] text-neutral-400">v{a.semantic_version}</span>
                  )}
                  {a.last_batch_id && (
                    <span className="shrink-0 font-mono text-[10px] text-neutral-400">
                      {a.last_batch_id.slice(0, 8)}
                    </span>
                  )}
                  {a.owner && <span className="shrink-0 text-[11px] text-neutral-500">{a.owner}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
