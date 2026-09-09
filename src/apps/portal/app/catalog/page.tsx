'use client'

// 数据目录 /catalog 页 — issue #38：三级资产统一搜索（源表字段→对象/指标→消费方）
// + 详情/血缘抽屉 + 同步 SLA 看板（只读聚合，不新增存储）。
import { useCallback, useEffect, useRef, useState } from 'react'
import { Library, Loader2, Search } from 'lucide-react'
import {
  getCatalogOverview,
  getCatalogSla,
  searchCatalog,
  type CatalogAssetDto,
  type CatalogAssetType,
  type CatalogOverviewDto,
  type CatalogSlaBoardDto,
  type CatalogSearchResultDto,
} from '@/lib/catalog-api'
import { ApiClientError } from '@/lib/types'
import AssetDetailDrawer from './asset-detail-drawer'
import { ASSET_TYPE_BADGES, ASSET_TYPE_LABELS, formatDateTime, formatSeconds } from './shared'

const selectCls =
  'rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none'

function qualityBadge(status: string | null): string {
  if (status === 'passed') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'failed') return 'border-red-200 bg-red-50 text-red-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

export default function CatalogPage() {
  const [tab, setTab] = useState<'assets' | 'sla'>('assets')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [assetType, setAssetType] = useState<CatalogAssetType | ''>('')
  const [result, setResult] = useState<CatalogSearchResultDto | null>(null)
  const [overview, setOverview] = useState<CatalogOverviewDto | null>(null)
  const [sla, setSla] = useState<CatalogSlaBoardDto | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<CatalogAssetDto | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 搜索输入防抖 300ms
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebounced(query.trim()), 300)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [query])

  const runSearch = useCallback(async () => {
    if (!debounced) {
      setResult(null)
      return
    }
    try {
      setLoading(true)
      const data = await searchCatalog(debounced, {
        asset_type: assetType || undefined,
        limit: 20,
      })
      setResult(data)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [debounced, assetType])

  useEffect(() => { runSearch() }, [runSearch])

  const loadSidePanel = useCallback(async () => {
    if (tab !== 'sla') return
    try {
      const [overviewData, slaData] = await Promise.all([
        getCatalogOverview(),
        getCatalogSla(),
      ])
      setOverview(overviewData)
      setSla(slaData)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiClientError ? e.message : String(e))
    }
  }, [tab])

  useEffect(() => {
    getCatalogOverview()
      .then(setOverview)
      .catch(() => setOverview(null))
  }, [])
  useEffect(() => { loadSidePanel() }, [loadSidePanel])

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="flex items-start gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-slate-900 text-white">
          <Library className="size-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-900">数据目录</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            三级资产只读目录：源表字段 → 语义对象/指标 → 消费方（Skill）；含血缘与同步 SLA 看板
          </p>
        </div>
      </header>

      {overview && (
        <div className="mt-4 flex flex-wrap gap-2 text-xs" data-testid="catalog-overview-chips">
          {(Object.keys(ASSET_TYPE_LABELS) as CatalogAssetType[]).map((type) => (
            <span key={type} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-600">
              {ASSET_TYPE_LABELS[type]} {overview.counts[type] ?? 0}
            </span>
          ))}
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-600">
            数据源 {overview.sla_sources}
          </span>
        </div>
      )}

      <div className="mt-4 flex gap-1 border-b border-slate-200" data-testid="catalog-tabs">
        {(['assets', 'sla'] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${
              tab === key
                ? 'border-slate-900 text-slate-900'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {key === 'assets' ? '资产目录' : 'SLA 看板'}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="catalog-error">
          {error}
        </p>
      )}

      {tab === 'assets' && (
        <section className="mt-4 space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-slate-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索资产名称 / 编码 / 描述 / 指标同义词…"
                className="w-full rounded-md border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-xs text-slate-700 focus:border-slate-400 focus:outline-none"
                data-testid="catalog-search-input"
              />
            </div>
            <select
              value={assetType}
              onChange={(event) => setAssetType(event.target.value as CatalogAssetType | '')}
              className={selectCls}
              aria-label="资产类型"
              data-testid="catalog-type-filter"
            >
              <option value="">全部类型</option>
              {(Object.keys(ASSET_TYPE_LABELS) as CatalogAssetType[]).map((type) => (
                <option key={type} value={type}>
                  {ASSET_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </div>

          {loading && (
            <div className="flex h-20 items-center justify-center gap-2 text-sm text-slate-500">
              <Loader2 className="size-4 animate-spin" /> 搜索中…
            </div>
          )}

          {!loading && !debounced && (
            <p className="rounded-md border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400" data-testid="catalog-search-hint">
              输入关键词开始搜索，如「结算」「自付」「mz_trade」
            </p>
          )}

          {!loading && debounced && result && (
            <div data-testid="catalog-search-results">
              <p className="mb-2 text-xs text-slate-500">
                「{result.query}」共 {result.total} 个资产{result.total > result.items.length ? `，展示前 ${result.items.length} 个` : ''}
              </p>
              {result.items.length === 0 && (
                <p className="rounded-md border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400" data-testid="catalog-search-empty">
                  未匹配到任何资产
                </p>
              )}
              <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
                {result.items.map((asset) => (
                  <li key={`${asset.asset_type}:${asset.asset_id}`}>
                    <button
                      type="button"
                      onClick={() => setSelected(asset)}
                      className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-50"
                      data-testid={`catalog-result-${asset.asset_type}`}
                    >
                      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-medium ${ASSET_TYPE_BADGES[asset.asset_type]}`}>
                        {ASSET_TYPE_LABELS[asset.asset_type]}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-slate-800">{asset.title}</span>
                        {asset.subtitle && (
                          <span className="block truncate font-mono text-[11px] text-slate-500">{asset.subtitle}</span>
                        )}
                      </span>
                      {asset.matched_on.length > 0 && (
                        <span className="hidden shrink-0 text-[11px] text-slate-400 sm:block">
                          命中 {asset.matched_on.join(' / ')}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {tab === 'sla' && (
        <section className="mt-4 space-y-4">
          {!sla && !error && (
            <div className="flex h-20 items-center justify-center gap-2 text-sm text-slate-500">
              <Loader2 className="size-4 animate-spin" /> 加载中…
            </div>
          )}
          {sla && (
            <>
              <div className="grid gap-3 md:grid-cols-2" data-testid="catalog-sla-sources">
                {sla.sources.map((source) => (
                  <div key={source.source_id} className="rounded-md border border-slate-200 p-3 text-xs" data-testid="catalog-sla-card">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-800">{source.source_name}</span>
                      <span className="font-mono text-[11px] text-slate-400">{source.source_id}</span>
                    </div>
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <dt className="text-slate-500">连接</dt>
                      <dd className="text-slate-800">{source.connection_status}</dd>
                      <dt className="text-slate-500">任务</dt>
                      <dd className="text-slate-800">{source.job_status ?? '—'}</dd>
                      <dt className="text-slate-500">P95 延迟</dt>
                      <dd className="text-slate-800">
                        {source.p95_latency_seconds === null ? '—' : formatSeconds(source.p95_latency_seconds)}
                        <span className="ml-1 text-[11px] text-slate-400">（样本 {source.non_empty_sample_count}）</span>
                      </dd>
                      <dt className="text-slate-500">质量门</dt>
                      <dd>
                        <span className={`rounded border px-1.5 py-0.5 text-[11px] ${qualityBadge(source.quality_status)}`}>
                          {source.quality_status ?? '—'}
                        </span>
                      </dd>
                      <dt className="text-slate-500">语义版本</dt>
                      <dd className="font-mono text-[11px] text-slate-800">{source.semantic_version ?? '—'}</dd>
                      <dt className="text-slate-500">近 {source.recent_runs_total} 次运行</dt>
                      <dd className="text-slate-800">
                        成功 {source.recent_runs_succeeded} / 失败 {source.recent_runs_failed}
                        {source.last_error_code && (
                          <span className="ml-1 rounded border border-red-200 bg-red-50 px-1 text-[11px] text-red-700">
                            {source.last_error_code}
                          </span>
                        )}
                      </dd>
                    </dl>
                    {source.last_batch && (
                      <p className="mt-2 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
                        最近批次 {source.last_batch.batch_id.slice(0, 8)} · {source.last_batch.row_count} 行 ·{' '}
                        {formatDateTime(source.last_batch.published_at)}
                      </p>
                    )}
                  </div>
                ))}
              </div>

              {sla.recent_batches.length > 0 && (
                <div>
                  <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">最近批次</h2>
                  <table className="w-full text-xs" data-testid="catalog-recent-batches">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-slate-500">
                        <th className="py-1.5 pr-2 font-medium">批次</th>
                        <th className="py-1.5 pr-2 font-medium">数据源</th>
                        <th className="py-1.5 pr-2 font-medium">模式</th>
                        <th className="py-1.5 pr-2 font-medium">行数</th>
                        <th className="py-1.5 pr-2 font-medium">质量门</th>
                        <th className="py-1.5 pr-2 font-medium">语义版本</th>
                        <th className="py-1.5 font-medium">发布时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sla.recent_batches.map((batch) => (
                        <tr key={batch.batch_id} className="border-b border-slate-100">
                          <td className="py-1.5 pr-2 font-mono text-[11px]">{batch.batch_id.slice(0, 8)}</td>
                          <td className="py-1.5 pr-2 font-mono text-[11px] text-slate-500">{batch.source_id}</td>
                          <td className="py-1.5 pr-2">{batch.mode}</td>
                          <td className="py-1.5 pr-2">{batch.row_count}</td>
                          <td className="py-1.5 pr-2">
                            <span className={`rounded border px-1.5 py-0.5 text-[11px] ${qualityBadge(batch.quality_status)}`}>
                              {batch.quality_status ?? '—'}
                            </span>
                          </td>
                          <td className="py-1.5 pr-2 font-mono text-[11px]">{batch.semantic_version ?? '—'}</td>
                          <td className="py-1.5 text-slate-500">{formatDateTime(batch.published_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {selected && (
        <AssetDetailDrawer asset={selected} onClose={() => setSelected(null)} />
      )}
    </main>
  )
}
