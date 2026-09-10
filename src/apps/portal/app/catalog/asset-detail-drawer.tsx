'use client'

// 数据目录资产详情抽屉 — issue #38：详情分节 + 血缘链（源→批次→数据集/字段→指标→消费方+语义版本）。
import { useEffect, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import {
  getCatalogAsset,
  getCatalogLineage,
  type CatalogAssetDetailDto,
  type CatalogAssetDto,
  type CatalogLineageDto,
} from '@/lib/catalog-api'
import { ApiClientError } from '@/lib/types'
import { ASSET_TYPE_BADGES, ASSET_TYPE_LABELS, FIELD_ROLE_LABELS, formatDateTime } from './shared'

interface Props {
  asset: CatalogAssetDto
  onClose: () => void
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2" data-testid={`catalog-section-${title}`}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  )
}

function BatchList({ batches }: { batches: CatalogLineageDto['batches'] }) {
  return (
    <ul className="space-y-1.5">
      {batches.map((batch) => (
        <li key={batch.batch_id} className="rounded-md border border-slate-200 px-2.5 py-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-slate-500">
              {batch.batch_id.slice(0, 8)}
            </span>
            <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600">
              {batch.mode}
            </span>
            {batch.quality_status && (
              <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">
                质量门 {batch.quality_status}
              </span>
            )}
            <span className="text-slate-500">{batch.row_count} 行</span>
            {batch.semantic_version && (
              <span className="text-slate-500">语义版本 {batch.semantic_version}</span>
            )}
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            发布 {formatDateTime(batch.published_at)}
          </p>
        </li>
      ))}
    </ul>
  )
}

export default function AssetDetailDrawer({ asset, onClose }: Props) {
  const [detail, setDetail] = useState<CatalogAssetDetailDto | null>(null)
  const [lineage, setLineage] = useState<CatalogLineageDto | null>(null)
  const [tab, setTab] = useState<'detail' | 'lineage'>('detail')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setDetail(null)
    setLineage(null)
    setTab('detail')
    getCatalogAsset(asset.asset_type, asset.asset_id)
      .then((result) => { if (!cancelled) setDetail(result) })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiClientError ? e.message : String(e))
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [asset.asset_type, asset.asset_id])

  const loadLineage = () => {
    setTab('lineage')
    if (lineage) return
    setLoading(true)
    getCatalogLineage(asset.asset_type, asset.asset_id)
      .then(setLineage)
      .catch((e) => setError(e instanceof ApiClientError ? e.message : String(e)))
      .finally(() => setLoading(false))
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" data-testid="catalog-drawer-mask">
      <div
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white p-5 shadow-xl"
        data-testid="catalog-drawer"
        role="dialog"
        aria-label="资产详情"
      >
        <div className="flex items-start gap-3">
          <span
            className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${ASSET_TYPE_BADGES[asset.asset_type]}`}
          >
            {ASSET_TYPE_LABELS[asset.asset_type]}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold text-slate-900">{asset.title}</h2>
            {asset.subtitle && (
              <p className="truncate font-mono text-[11px] text-slate-500">{asset.subtitle}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="mt-3 flex gap-1 border-b border-slate-200" data-testid="catalog-drawer-tabs">
          {(['detail', 'lineage'] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={key === 'lineage' ? loadLineage : () => setTab('detail')}
              className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${
                tab === key
                  ? 'border-slate-900 text-slate-900'
                  : 'border-transparent text-slate-500 hover:text-slate-700'
              }`}
            >
              {key === 'detail' ? '详情' : '血缘'}
            </button>
          ))}
        </div>

        {error && (
          <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="catalog-drawer-error">
            {error}
          </p>
        )}
        {loading && (
          <div className="flex h-24 items-center justify-center gap-2 text-sm text-slate-500">
            <Loader2 className="size-4 animate-spin" /> 加载中…
          </div>
        )}

        {!loading && tab === 'detail' && detail && (
          <div className="mt-4 space-y-5">
            {detail.summary.length > 0 && (
              <Section title="摘要">
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                  {detail.summary
                    .filter((kv) => kv.value !== null && kv.value !== undefined)
                    .map((kv) => (
                      <div key={kv.key} className="col-span-2 grid grid-cols-subgrid">
                        <dt className="text-slate-500">{kv.key}</dt>
                        <dd className="break-words text-slate-800">{kv.value}</dd>
                      </div>
                    ))}
                </dl>
              </Section>
            )}
            {detail.value_mappings.length > 0 && (
              <Section title="值域码表">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="py-1 pr-2 font-medium">来源值</th>
                      <th className="py-1 pr-2 font-medium">标准值</th>
                      <th className="py-1 font-medium">说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.value_mappings.map((mapping) => (
                      <tr key={`${mapping.source_value}-${mapping.standard_value}`} className="border-b border-slate-100">
                        <td className="py-1 pr-2 font-mono text-[11px]">{mapping.source_value}</td>
                        <td className="py-1 pr-2 text-slate-800">{mapping.standard_value}</td>
                        <td className="py-1 text-slate-500">{mapping.description ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}
            {detail.fields.length > 0 && (
              <Section title="字段">
                <ul className="space-y-1">
                  {detail.fields.map((field) => (
                    <li key={field.field_code} className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-800">{field.name}</span>
                        <span className="font-mono text-[11px] text-slate-500">{field.column_name}</span>
                        <span className="rounded border border-slate-200 bg-slate-50 px-1 text-[11px] text-slate-600">
                          {FIELD_ROLE_LABELS[field.field_role] ?? field.field_role}
                        </span>
                        {field.is_primary_key && (
                          <span className="rounded border border-amber-200 bg-amber-50 px-1 text-[11px] text-amber-700">主键</span>
                        )}
                      </div>
                      {field.description && (
                        <p className="mt-0.5 text-[11px] text-slate-500">{field.description}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </Section>
            )}
            {detail.metrics.length > 0 && (
              <Section title="指标">
                <ul className="space-y-1">
                  {detail.metrics.map((metric) => (
                    <li key={metric.metric_code} className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-800">{metric.name}</span>
                        <span className="font-mono text-[11px] text-slate-500">{metric.metric_code}</span>
                        {metric.owner && (
                          <span className="rounded border border-slate-200 bg-slate-50 px-1 text-[11px] text-slate-600">
                            负责人 {metric.owner}
                          </span>
                        )}
                      </div>
                      {metric.definition && (
                        <p className="mt-0.5 text-[11px] text-slate-500">{metric.definition}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </Section>
            )}
            {detail.datasets.length > 0 && (
              <Section title="数据集">
                <ul className="space-y-1 text-xs">
                  {detail.datasets.map((dataset) => (
                    <li key={dataset.dataset_code} className="rounded-md border border-slate-200 px-2.5 py-1.5">
                      <span className="font-medium text-slate-800">{dataset.name}</span>
                      <span className="ml-2 font-mono text-[11px] text-slate-500">
                        {dataset.datasource_id}.{dataset.table_name}
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}
            {detail.consumers.length > 0 && (
              <Section title="消费方">
                <ul className="space-y-1 text-xs">
                  {detail.consumers.map((consumer) => (
                    <li key={consumer.consumer_id} className="rounded-md border border-slate-200 px-2.5 py-1.5">
                      <span className="font-medium text-slate-800">{consumer.name}</span>
                      <span className="ml-2 font-mono text-[11px] text-slate-500">{consumer.consumer_id}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}
            {detail.batches.length > 0 && (
              <Section title="数据批次">
                <BatchList batches={detail.batches} />
              </Section>
            )}
            {detail.versions.length > 0 && (
              <Section title="语义版本">
                <ul className="space-y-1 text-xs">
                  {detail.versions.map((version) => (
                    <li key={version.version} className="rounded-md border border-slate-200 px-2.5 py-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-slate-800">v{version.version}</span>
                        <span className="text-slate-500">{formatDateTime(version.published_at)}</span>
                        <span className="text-slate-500">{version.metric_count} 指标</span>
                        {version.published_by && (
                          <span className="text-slate-400">by {version.published_by}</span>
                        )}
                      </div>
                      {version.changelog && (
                        <p className="mt-0.5 text-[11px] text-slate-500">{version.changelog}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </Section>
            )}
          </div>
        )}

        {!loading && tab === 'lineage' && lineage && (
          <div className="mt-4 space-y-5" data-testid="catalog-lineage-view">
            <p className="rounded-md bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
              血缘链：数据源 → 同步批次 → 投影表/字段 → 指标 → 消费方（含语义版本）
            </p>
            <Section title="数据源">
              <div className="flex flex-wrap gap-1.5 text-xs">
                {lineage.sources.length === 0 && <span className="text-slate-400">—</span>}
                {lineage.sources.map((source) => (
                  <span key={source} className="rounded border border-sky-200 bg-sky-50 px-2 py-1 font-mono text-[11px] text-sky-700">
                    {source}
                  </span>
                ))}
              </div>
            </Section>
            <Section title="同步批次">
              {lineage.batches.length ? <BatchList batches={lineage.batches} /> : <span className="text-xs text-slate-400">无（非落地库链路）</span>}
            </Section>
            <Section title="投影表 / 字段">
              <ul className="space-y-1 text-xs">
                {lineage.datasets.map((dataset) => (
                  <li key={dataset.dataset_code} className="rounded-md border border-slate-200 px-2.5 py-1.5">
                    <span className="font-medium text-slate-800">{dataset.name}</span>
                    <span className="ml-2 font-mono text-[11px] text-slate-500">
                      {dataset.datasource_id}.{dataset.table_name}
                    </span>
                    {lineage.fields
                      .filter((field) => field.dataset_code === dataset.dataset_code)
                      .map((field) => (
                        <span key={field.field_code} className="ml-2 rounded border border-violet-200 bg-violet-50 px-1 text-[11px] text-violet-700">
                          {field.name}
                        </span>
                      ))}
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="指标">
              <div className="flex flex-wrap gap-1.5 text-xs">
                {lineage.metrics.length === 0 && <span className="text-slate-400">—</span>}
                {lineage.metrics.map((metric) => (
                  <span key={metric.metric_code} className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700">
                    {metric.name}
                  </span>
                ))}
              </div>
            </Section>
            <Section title="消费方">
              <div className="flex flex-wrap gap-1.5 text-xs">
                {lineage.consumers.length === 0 && <span className="text-slate-400">—</span>}
                {lineage.consumers.map((consumer) => (
                  <span key={consumer.consumer_id} className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">
                    {consumer.name}
                  </span>
                ))}
              </div>
            </Section>
            <Section title="语义版本">
              <div className="flex flex-wrap gap-1.5 text-xs">
                {lineage.versions.length === 0 && <span className="text-slate-400">—</span>}
                {lineage.versions.map((version) => (
                  <span key={version.version} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-slate-600">
                    v{version.version} · {formatDateTime(version.published_at)}
                  </span>
                ))}
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  )
}
