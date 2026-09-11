// 门诊运营分析 API 客户端 — issue #40 P3 受控问数与运营指导。
// DTO 字段与后端 src/domain/ops_analytics/models.py 逐字段对齐（snake_case 直传）。
// 鉴权与 /ops 同一 token（ops:read 权限同一签名 JWT）。
import { requestJson } from './api-client'

// ── 枚举白名单（与后端冻结值一致，勿单侧扩充）──

export type OpsResultStatus = 'complete' | 'partial' | 'unavailable'
export type OpsAnalyticsDimension = 'fund_type' | 'cure_type' | 'settle_state' | 'department'

// ── DTO ──

export interface OpsMetricCardDto {
  metric_code: string
  name: string
  unit: string
  precision: number
  result_status: OpsResultStatus
  value: number | null
  halt_reason: string | null
  halt_detail: string | null
}

export interface OpsOverviewDto {
  result_status: OpsResultStatus
  halt_reason: string | null
  generated_at: string
  date_min: string | null
  date_max: string | null
  row_count: number
  semantic_version: string | null
  data_batch_ids: string[]
  cards: OpsMetricCardDto[]
}

export interface OpsDimensionItemDto {
  code: string
  label: string
  valid_count: number
  total_fee: number
  fund_pay: number
  self_pay: number
  share: number
}

export interface OpsDimensionBreakdownDto {
  dimension: OpsAnalyticsDimension
  dimension_name: string
  result_status: OpsResultStatus
  halt_reason: string | null
  halt_detail: string | null
  data_batch_ids: string[]
  items: OpsDimensionItemDto[]
}

export interface OpsTrendPointDto {
  month: string
  valid_count: number
  total_fee: number
  fund_pay: number
  self_pay: number
}

export interface OpsDrillRowDto {
  trade_no: string
  trade_date: string | null
  fund_type: string | null
  cure_type: string | null
  settle_state: string | null
  total_fee: number
  fund_pay: number
  self_pay: number
  data_batch_id: string | null
}

export interface OpsDrillResultDto {
  result_status: OpsResultStatus
  halt_reason: string | null
  total: number
  limit: number
  offset: number
  data_batch_ids: string[]
  rows: OpsDrillRowDto[]
}

export interface OpsConclusionDto {
  text: string
  citations: Array<{ type: string; data_batch_id?: string; metric_code?: string }>
}

export interface OpsWeekDeltaDto {
  metric_code: string
  name: string
  unit: string
  precision: number
  current: number | null
  previous: number | null
  delta: number | null
  pct: number | null
  direction: 'up' | 'down' | 'flat' | 'unknown'
}

export interface OpsWeeklyReportDto {
  week_start: string
  result_status: OpsResultStatus
  halt_reason: string | null
  current_week_rows: number
  previous_week_rows: number
  deltas: OpsWeekDeltaDto[]
  conclusions: OpsConclusionDto[]
  summary: string | null
  uncertainties: string[]
  data_batch_ids: string[]
}

// ── 鉴权（与 ops-api 同 token：ops:read 同一签名 JWT）──

function opsToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('ops-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_OPS_TOKEN || null
}

async function opsAnalyticsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = opsToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson<T>(`/ops-analytics${path}`, { ...init, headers })
}

// ── 端点 ──

export async function getOpsOverview(): Promise<OpsOverviewDto> {
  return opsAnalyticsRequest<OpsOverviewDto>('/overview')
}

export async function getOpsTrend(months = 12): Promise<{ points: OpsTrendPointDto[] }> {
  return opsAnalyticsRequest<{ points: OpsTrendPointDto[] }>(`/trend?months=${months}`)
}

export async function getOpsBreakdown(
  dimension: OpsAnalyticsDimension,
  topN = 10,
): Promise<OpsDimensionBreakdownDto> {
  return opsAnalyticsRequest<OpsDimensionBreakdownDto>(
    `/breakdown?dimension=${dimension}&top_n=${topN}`,
  )
}

export interface OpsDrillQuery {
  dimension?: OpsAnalyticsDimension | 'fund_type' | 'cure_type' | 'settle_state'
  value?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export async function getOpsDrill(query: OpsDrillQuery): Promise<OpsDrillResultDto> {
  const params = new URLSearchParams()
  if (query.dimension) params.set('dimension', query.dimension)
  if (query.value) params.set('value', query.value)
  if (query.date_from) params.set('date_from', query.date_from)
  if (query.date_to) params.set('date_to', query.date_to)
  if (query.limit) params.set('limit', String(query.limit))
  if (query.offset) params.set('offset', String(query.offset))
  const suffix = params.toString()
  return opsAnalyticsRequest<OpsDrillResultDto>(`/drill${suffix ? `?${suffix}` : ''}`)
}

export async function getOpsWeeklyReport(weekStart?: string): Promise<OpsWeeklyReportDto> {
  return opsAnalyticsRequest<OpsWeeklyReportDto>(
    `/weekly-report${weekStart ? `?week_start=${weekStart}` : ''}`,
  )
}
