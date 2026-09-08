'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Database, Loader2, AlertCircle, RefreshCw, Search, X,
  Table2, Brain, Sigma, MousePointerClick, Network, Gauge, FolderSearch,
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

const TYPE_META: Record<CatalogAssetType, { label: string; cls: string; dot: string; icon: ReactNode }> = {
  source_table: { label: '源表', cls: 'bg-sky-50 text-sky-700', dot: 'bg-sky-500', icon: <Table2 className="size-3" /> },
  semantic_object: { label: '语义对象', cls: 'bg-violet-50 text-violet-700', dot: 'bg-violet-500', icon: <Brain className="size-3" /> },
  metric: { label: '指标', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500', icon: <Sigma className="size-3" /> },
  consumer: { label: '消费方', cls: 'bg-amber-50 text-amber-700', dot: 'bg-amber-500', icon: <MousePointerClick className="size-3" /> },
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
  const qualityDot =
    sync?.quality_status === 'ok'
      ? 'bg-emerald-500'
      : sync
        ? 'bg-red-500'
        : 'bg-slate-300'
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[
        { label: '门诊同步 P95', value: sync?.p95_latency_seconds != null ? `${sync.p95_latency_seconds.toFixed(1)}s` : '—', mono: true },
        {
          label: '质量状态',
          node: (
            <span className="flex items-center gap-1.5">
              <span className={`size-1.5 rounded-full ${qualityDot}`} />
              <span className={qualityCls}>{sync?.quality_status || '—'}</span>
            </span>
          ),
        },
        { label: '最近批次', value: sync?.last_batch_id ? sync.last_batch_id.slice(0, 8) : '—', mono: true },
        { label: '质量门禁任务', value: String(sla?.quality_gates.length ?? 0) },
      ].map((c) => (
        <div key={c.label} className="rounded-2xl border border-slate-200 bg-white p-3.5 shadow-sm">
          <p className="text-[11px] text-slate-400">{c.label}</p>
          {'node' in c && c.node
            ? <div className="mt-1.5 text-sm font-semibold text-slate-800">{c.node}</div>
            : (
              <p className={`mt-1.5 text-lg font-semibold text-slate-800 ${c.mono ? 'font-mono text-sm tabular-nums' : ''}`}>
                {c.value}
              </p>
            )}
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
          <li key={`${e.upstream}-${e.downstream}-${i}`} className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-slate-50">
            <TypeBadge type={node.asset_type} />
            <span className="truncate text-slate-700">{node.name}</span>
            <span className="shrink-0 text-[10px] text-slate-400">{RELATION_LABEL[e.relation] ?? e.relation}</span>
            {node.last_batch_id && (
              <span className="shrink-0 font-mono text-[10px] text-slate-400">
                批次 {node.last_batch_id.slice(0, 8)}
              </span>
            )}
          </li>
        )
      })}
      {edges.length > 20 && (
        <li className="px-1.5 text-[10px] text-slate-400">… 其余 {edges.length - 20} 条已折叠</li>
      )}
    </ul>
  )

  return (
    <div className="space-y-3">
      <div>
        <p className="mb-1 text-[11px] font-semibold text-slate-500">上游（{upstream.length}）</p>
        {upstream.length ? renderList(upstream, 'upstream') : <p className="text-xs text-slate-400">无</p>}
      </div>
      <div>
        <p className="mb-1 text-[11px] font-semibold text-slate-500">下游（{downstream.length}）</p>
        {downstream.length ? renderList(downstream, 'downstream') : <p className="text-xs text-slate-400">无</p>}
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

  const rows: [string, ReactNode][] = [
    ['资产键', <span key="k" className="font-mono text-xs">{asset.asset_key}</span>],
    ['负责人', asset.owner || '—'],
    ['刷新频率', asset.refresh_freq || '—'],
    ['语义版本', asset.semantic_version ? `v${asset.semantic_version}` : '—'],
    ['最近批次', asset.last_batch_id ? <span key="b" className="font-mono text-xs">{asset.last_batch_id}</span> : '—'],
    ['更新时间', fmtTime(asset.updated_at)],
  ]

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 p-4">
        <div className="flex min-w-0 items-center gap-2">
          <TypeBadge type={asset.asset_type} />
          <p className="truncate text-sm font-semibold text-slate-800">{asset.name}</p>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50"
          aria-label="关闭详情"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="p-4">
        {asset.description && <p className="mb-3 text-xs leading-relaxed text-slate-500">{asset.description}</p>}
        <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-3">
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt className="text-[10px] text-slate-400">{label}</dt>
              <dd className="mt-0.5 text-xs text-slate-700">{value}</dd>
            </div>
          ))}
        </dl>
        {Object.keys(asset.sample_summary).length > 0 && (
          <p className="mb-3 rounded-lg bg-slate-50/80 px-2.5 py-2 text-[11px] leading-relaxed text-slate-500 ring-1 ring-slate-100">
            脱敏摘要：{Object.entries(asset.sample_summary).map(([k, v]) => `${k}=${String(v)}`).join('，')}
          </p>
        )}
        <div className="border-t border-slate-100 pt-3">
          <div className="mb-2 flex items-center gap-1.5">
            <Network className="size-3.5 text-slate-400" />
            <p className="text-[11px] font-semibold text-slate-500">血缘</p>
          </div>
          {lineageError && <p className="flex items-center gap-1.5 text-xs text-red-500"><AlertCircle className="size-3" />{lineageError}</p>}
          {!lineage && !lineageError && (
            <div className="space-y-2" aria-hidden>
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-6 animate-pulse rounded-lg bg-slate-100" />
              ))}
            </div>
          )}
          {lineage && <LineageView lineage={lineage} />}
        </div>
      </div>
    </div>
  )
}

// ── 骨架屏 ──────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div className="h-5 w-14 animate-pulse rounded-full bg-slate-100" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="h-4 w-2/5 animate-pulse rounded bg-slate-100" />
        <div className="h-3 w-3/5 animate-pulse rounded bg-slate-100/70" />
      </div>
      <div className="h-3 w-16 animate-pulse rounded bg-slate-100" />
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

  const typeCounts = useMemo(() => {
    const c: Record<CatalogAssetType, number> = { source_table: 0, semantic_object: 0, metric: 0, consumer: 0 }
    for (const a of assets) c[a.asset_type] += 1
    return c
  }, [assets])

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
    <div className="relative mx-auto flex w-full max-w-[1400px] flex-col gap-5 px-4 py-6 sm:px-6 sm:py-8">
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#f8fafc_0%,#f1f5f9_100%)]" />
      </div>

      {/* 页头 */}
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-sky-500/10 ring-1 ring-sky-500/20">
            <Database className="size-5.5 text-sky-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">数据目录</h1>
            <p className="mt-1 text-sm text-slate-500">资产清单 / 搜索 / 血缘 / SLA</p>
          </div>
        </div>
        <button
          onClick={doRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 shadow-sm transition-all duration-200 hover:border-slate-300 hover:bg-white hover:text-slate-800 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
        >
          {refreshing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          刷新目录
        </button>
      </header>

      {refreshNote && (
        <p className="inline-flex w-fit items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-[11px] text-slate-500">
          <RefreshCw className="size-3" />{refreshNote}
        </p>
      )}

      {/* 当前清单统计 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1.5 text-xs text-slate-600 backdrop-blur">
          <FolderSearch className="size-3.5 text-sky-600" />
          <span className="tabular-nums font-semibold text-slate-900">{assets.length}</span>
          <span>当前清单</span>
        </span>
        {(Object.keys(TYPE_META) as CatalogAssetType[]).map((t) => {
          const m = TYPE_META[t]
          return (
            <span key={t} className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1.5 text-xs text-slate-600 backdrop-blur">
              <span className={`size-1.5 rounded-full ${m.dot}`} />
              <span className="tabular-nums font-semibold text-slate-900">{typeCounts[t]}</span>
              <span>{m.label}</span>
            </span>
          )
        })}
      </div>

      {/* SLA 概览 */}
      <section className="space-y-2">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
          <Gauge className="size-3.5" /> SLA 概览
        </div>
        <SlaStrip sla={sla} />
      </section>

      {/* Tabs + 搜索 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex w-fit items-center gap-1 rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200/70">
          {TYPE_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-xl px-3.5 py-1.5 text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50 ${
                tab === t.key ? 'bg-sky-100 text-sky-800 shadow-sm' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative min-w-[220px] max-w-[340px] flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            placeholder="搜索名称 / 描述 / 资产键"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            className="w-full rounded-xl border border-slate-200 bg-white/80 py-2.5 pl-10 pr-3 text-sm text-slate-800 shadow-sm outline-none transition-all duration-200 placeholder:text-slate-400 focus:border-sky-300 focus:bg-white focus:ring-2 focus:ring-sky-200/40"
          />
        </div>
      </div>

      {error && (
        <p className="flex items-center gap-1.5 rounded-xl border border-red-200 bg-red-50/60 px-3 py-2 text-xs text-red-600">
          <AlertCircle className="size-3.5 shrink-0" />{error}
        </p>
      )}

      {/* 主从布局：左=清单，右=详情（移动端详情置顶，保持原「详情在列表上方」的浏览习惯） */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_400px]">
        <section className="order-last min-w-0 lg:order-none">
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            {loading ? (
              <div className="divide-y divide-slate-100">
                {Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)}
              </div>
            ) : assets.length === 0 ? (
              <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
                <div className="flex size-11 items-center justify-center rounded-2xl bg-slate-100 ring-1 ring-slate-200/60">
                  <Database className="size-5.5 text-slate-300" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-700">无匹配资产</p>
                  <p className="mt-1 text-xs text-slate-400">试试切换类型标签，或清除搜索关键词。</p>
                </div>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {assets.map((a, i) => (
                  <li
                    key={a.asset_id}
                    className="animate-in fade-in-0 slide-in-from-bottom-2 duration-500 ease-out"
                    style={{ animationDelay: `${Math.min(i, 12) * 50}ms`, animationFillMode: 'backwards' }}
                  >
                    <button
                      onClick={() => setSelected(a)}
                      className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-300/50 ${
                        selected?.asset_id === a.asset_id ? 'bg-sky-50/60' : 'hover:bg-slate-50/70'
                      }`}
                    >
                      <TypeBadge type={a.asset_type} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-slate-800">{a.name}</span>
                        {a.description && (
                          <span className="block truncate text-[11px] text-slate-400">{a.description}</span>
                        )}
                      </span>
                      {a.semantic_version && (
                        <span className="shrink-0 text-[10px] text-slate-400">v{a.semantic_version}</span>
                      )}
                      {a.last_batch_id && (
                        <span className="shrink-0 font-mono text-[10px] text-slate-400">
                          {a.last_batch_id.slice(0, 8)}
                        </span>
                      )}
                      {a.owner && <span className="shrink-0 text-[11px] text-slate-500">{a.owner}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {selected && (
          <aside className="order-first lg:order-none lg:sticky lg:top-0">
            <AssetDetail asset={selected} onClose={() => setSelected(null)} />
          </aside>
        )}
      </div>
    </div>
  )
}