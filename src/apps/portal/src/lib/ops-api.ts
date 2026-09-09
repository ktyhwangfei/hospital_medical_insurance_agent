// 健康运营 API 客户端 — issue #45 P0（/ops 问题库 + 手动巡检）。
// DTO 字段与后端 src/domain/ops/models.py 逐字段对齐（snake_case 直传）。
import { requestJson } from './api-client'

// ── 枚举白名单（与后端冻结值一致，勿单侧扩充）──

export type OpsAssetType = 'skill' | 'knowledge' | 'data' | 'runtime'
export type OpsSeverity = 'info' | 'warning' | 'critical'
export type OpsFindingStatus = 'open' | 'resolved' | 'ignored'

// ── DTO ──

export interface OpsFindingDto {
  finding_id: string
  asset_type: OpsAssetType
  asset_id: string
  check_id: string
  severity: OpsSeverity
  status: OpsFindingStatus
  fingerprint: string
  payload: Record<string, unknown>
  first_seen_at: string
  last_seen_at: string
  occurrence_count: number
  diagnosis: Record<string, unknown> | null
  revision: number
}

export interface OpsFindingPageDto {
  items: OpsFindingDto[]
  total: number
  page: number
  page_size: number
}

export interface OpsCheckerErrorDto {
  check_id: string
  message: string
}

export interface OpsInspectionResultDto {
  checked_at: string
  check_count: number
  finding_count: number
  findings: OpsFindingDto[]
  checker_errors: OpsCheckerErrorDto[]
}

export interface OpsFindingsQuery {
  status?: OpsFindingStatus
  severity?: OpsSeverity
  asset_type?: OpsAssetType
  page?: number
  page_size?: number
}

export type OpsFindingEventType = 'ignored' | 'reopened'

export interface OpsFindingEventDto {
  event_id: string
  finding_id: string
  event_type: OpsFindingEventType
  actor: string
  reason: string | null
  created_at: string
}

export interface OpsFindingDetailDto {
  finding: OpsFindingDto
  events: OpsFindingEventDto[]
}

// ── 鉴权（与 data-governance-api 同模式：sessionStorage → dev 环境变量 token）──

function opsToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('ops-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_OPS_TOKEN || null
}

export function hasOpsPermission(permission: 'read' | 'write'): boolean {
  const token = opsToken()
  if (!token) return process.env.NODE_ENV !== 'production'
  try {
    const payload = token.replace(/^Bearer\s+/i, '').split('.')[1]
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const permissions = JSON.parse(atob(base64)).permissions
    return Array.isArray(permissions) && permissions.includes(`ops:${permission}`)
  } catch {
    return false
  }
}

async function opsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = opsToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson<T>(`/ops${path}`, { ...init, headers })
}

// ── 端点 ──

export async function runOpsInspection(): Promise<OpsInspectionResultDto> {
  return opsRequest<OpsInspectionResultDto>('/inspections', { method: 'POST' })
}

export async function listOpsFindings(query: OpsFindingsQuery): Promise<OpsFindingPageDto> {
  const params = new URLSearchParams()
  if (query.status) params.set('status', query.status)
  if (query.severity) params.set('severity', query.severity)
  if (query.asset_type) params.set('asset_type', query.asset_type)
  if (query.page) params.set('page', String(query.page))
  if (query.page_size) params.set('page_size', String(query.page_size))
  const suffix = params.toString()
  return opsRequest<OpsFindingPageDto>(`/findings${suffix ? `?${suffix}` : ''}`)
}

// ── #50 详情与生命周期 ──

export async function getOpsFinding(findingId: string): Promise<OpsFindingDetailDto> {
  return opsRequest<OpsFindingDetailDto>(`/findings/${encodeURIComponent(findingId)}`)
}

export async function ignoreOpsFinding(
  findingId: string,
  expectedRevision: number,
  reason: string,
): Promise<OpsFindingDetailDto> {
  return opsRequest<OpsFindingDetailDto>(
    `/findings/${encodeURIComponent(findingId)}/ignore?expected_revision=${expectedRevision}`,
    { method: 'POST', body: JSON.stringify({ reason }) },
  )
}

export async function reopenOpsFinding(
  findingId: string,
  expectedRevision: number,
): Promise<OpsFindingDetailDto> {
  return opsRequest<OpsFindingDetailDto>(
    `/findings/${encodeURIComponent(findingId)}/reopen?expected_revision=${expectedRevision}`,
    { method: 'POST' },
  )
}
