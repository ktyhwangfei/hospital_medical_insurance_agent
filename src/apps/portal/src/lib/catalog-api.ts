// 数据目录 API 客户端 — issue #38（资产清单/搜索/血缘/SLA，只读无鉴权）。
// DTO 字段与后端 src/runtime/catalog/service.py 逐字段对齐（snake_case 直传）。
import { requestJson } from './api-client'

export type CatalogAssetType = 'dataset' | 'field' | 'object' | 'metric' | 'consumer'

export interface CatalogAssetDto {
  asset_type: CatalogAssetType
  asset_id: string
  title: string
  subtitle: string | null
  matched_on: string[]
}

export interface CatalogSearchResultDto {
  query: string
  total: number
  items: CatalogAssetDto[]
}

export interface CatalogOverviewDto {
  counts: Record<CatalogAssetType, number>
  sla_sources: number
}

export interface CatalogKVDto {
  key: string
  value: string | null
}

export interface CatalogDatasetLiteDto {
  dataset_code: string
  object_code: string
  datasource_id: string
  table_name: string
  name: string
  status: string
}

export interface CatalogFieldInfoDto {
  field_code: string
  dataset_code: string
  column_name: string
  name: string
  field_role: string
  semantic_type: string
  value_domain: string | null
  nullable: boolean
  status: string
  description: string | null
  is_primary_key: boolean
}

export interface CatalogMetricLiteDto {
  metric_code: string
  name: string
  object_code: string
  status: string
  owner: string | null
  definition: string | null
}

export interface CatalogConsumerInfoDto {
  consumer_id: string
  name: string
  kind: string
  consumed_objects: string[]
  consumed_metrics: string[]
}

export interface CatalogBatchInfoDto {
  batch_id: string
  source_id: string
  mode: string
  semantic_version: string | null
  published_at: string
  source_committed_at: string | null
  row_count: number
  quality_status: string | null
  latency_seconds: number | null
}

export interface CatalogVersionInfoDto {
  version: string
  published_at: string
  published_by: string | null
  changelog: string | null
  metric_count: number
}

export interface CatalogValueMappingDto {
  source_value: string
  standard_value: string
  description: string | null
}

export interface CatalogAssetDetailDto {
  asset: CatalogAssetDto
  summary: CatalogKVDto[]
  fields: CatalogFieldInfoDto[]
  metrics: CatalogMetricLiteDto[]
  datasets: CatalogDatasetLiteDto[]
  consumers: CatalogConsumerInfoDto[]
  batches: CatalogBatchInfoDto[]
  versions: CatalogVersionInfoDto[]
  value_mappings: CatalogValueMappingDto[]
}

export interface CatalogLineageDto {
  asset: CatalogAssetDto
  sources: string[]
  batches: CatalogBatchInfoDto[]
  datasets: CatalogDatasetLiteDto[]
  fields: CatalogFieldInfoDto[]
  metrics: CatalogMetricLiteDto[]
  consumers: CatalogConsumerInfoDto[]
  versions: CatalogVersionInfoDto[]
}

export interface CatalogSourceSlaDto {
  source_id: string
  source_name: string
  connection_status: string
  job_status: string | null
  p95_latency_seconds: number | null
  last_non_empty_latency_seconds: number | null
  non_empty_sample_count: number
  quality_status: string | null
  semantic_version: string | null
  last_batch: CatalogBatchInfoDto | null
  recent_runs_total: number
  recent_runs_succeeded: number
  recent_runs_failed: number
  last_run_at: string | null
  last_error_code: string | null
}

export interface CatalogSlaBoardDto {
  generated_at: string
  sources: CatalogSourceSlaDto[]
  recent_batches: CatalogBatchInfoDto[]
}

export function searchCatalog(
  q: string,
  options?: { asset_type?: CatalogAssetType; limit?: number },
): Promise<CatalogSearchResultDto> {
  const params = new URLSearchParams({ q })
  if (options?.asset_type) params.set('asset_type', options.asset_type)
  if (options?.limit) params.set('limit', String(options.limit))
  return requestJson<CatalogSearchResultDto>(`/catalog/search?${params.toString()}`)
}

export function getCatalogOverview(): Promise<CatalogOverviewDto> {
  return requestJson<CatalogOverviewDto>('/catalog/overview')
}

export function getCatalogSla(): Promise<CatalogSlaBoardDto> {
  return requestJson<CatalogSlaBoardDto>('/catalog/sla')
}

export function getCatalogAsset(
  assetType: CatalogAssetType,
  assetId: string,
): Promise<CatalogAssetDetailDto> {
  return requestJson<CatalogAssetDetailDto>(
    `/catalog/assets/${assetType}/${encodeURIComponent(assetId)}`,
  )
}

export function getCatalogLineage(
  assetType: CatalogAssetType,
  assetId: string,
): Promise<CatalogLineageDto> {
  return requestJson<CatalogLineageDto>(
    `/catalog/lineage/${assetType}/${encodeURIComponent(assetId)}`,
  )
}
