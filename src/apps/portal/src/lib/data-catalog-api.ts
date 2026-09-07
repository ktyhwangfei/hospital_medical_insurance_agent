import { requestJson } from './api-client'

// ── 数据目录 API（Issue #38）──
// 对应后端 src/runtime/api/data_catalog_routes.py（裸 Pydantic 响应，非 AgentResponse 包装）

export type CatalogAssetType = 'source_table' | 'semantic_object' | 'metric' | 'consumer'

export interface CatalogAsset {
  asset_id: string
  asset_type: CatalogAssetType
  asset_key: string
  name: string
  description: string
  owner: string
  refresh_freq: string
  value_ranges: Record<string, unknown>
  sample_summary: Record<string, unknown>
  semantic_object_code: string | null
  semantic_version: string | null
  last_batch_id: string | null
  source_ref: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CatalogAssetListResponse {
  items: CatalogAsset[]
  limit: number
  offset: number
}

export interface CatalogRefreshResponse {
  upserted: number
  pruned: number
}

export interface LineageNode {
  asset_id: string
  asset_key: string
  asset_type: CatalogAssetType
  name: string
  semantic_version: string | null
  last_batch_id: string | null
}

export interface LineageEdge {
  upstream: string
  downstream: string
  relation: 'feeds' | 'belongs_to' | 'consumed_by' | string
}

export interface AssetLineage {
  root: string
  nodes: LineageNode[]
  edges: LineageEdge[]
}

export interface OutpatientSyncSla {
  source_id: string
  last_batch_id: string | null
  last_published_at: string | null
  p95_latency_seconds: number | null
  non_empty_sample_count: number
  quality_status: string
}

export interface QualityGateScore {
  task_id: string
  metric_code: string
  status: string
  golden_score: Record<string, unknown>
  created_at: string | null
}

export interface DataCatalogSlaResponse {
  outpatient_sync: OutpatientSyncSla | null
  quality_gates: QualityGateScore[]
}

export interface CatalogAssetFilter {
  asset_type?: CatalogAssetType
  keyword?: string
  limit?: number
  offset?: number
}

export async function listCatalogAssets(
  filter: CatalogAssetFilter = {},
): Promise<CatalogAssetListResponse> {
  const params = new URLSearchParams()
  if (filter.asset_type) params.set('asset_type', filter.asset_type)
  if (filter.keyword) params.set('keyword', filter.keyword)
  if (filter.limit) params.set('limit', String(filter.limit))
  if (filter.offset) params.set('offset', String(filter.offset))
  const query = params.toString()
  return requestJson<CatalogAssetListResponse>(
    `/data-catalog/assets${query ? `?${query}` : ''}`,
  )
}

export async function getCatalogAsset(assetId: string): Promise<CatalogAsset> {
  return requestJson<CatalogAsset>(
    `/data-catalog/assets/${encodeURIComponent(assetId)}`,
  )
}

export async function getCatalogAssetLineage(assetId: string): Promise<AssetLineage> {
  return requestJson<AssetLineage>(
    `/data-catalog/assets/${encodeURIComponent(assetId)}/lineage`,
  )
}

export async function refreshCatalog(): Promise<CatalogRefreshResponse> {
  return requestJson<CatalogRefreshResponse>('/data-catalog/refresh', {
    method: 'POST',
  })
}

export async function getCatalogSla(): Promise<DataCatalogSlaResponse> {
  return requestJson<DataCatalogSlaResponse>('/data-catalog/sla')
}
