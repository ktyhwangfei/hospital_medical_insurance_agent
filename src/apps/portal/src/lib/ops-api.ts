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
  // ── #52：运行留痕字段（经调度器触发时回填）──
  inspection_id: string | null
  trigger_source: OpsInspectionTrigger | null
  new_finding_count: number
}

export interface OpsFindingsQuery {
  status?: OpsFindingStatus
  severity?: OpsSeverity
  asset_type?: OpsAssetType
  page?: number
  page_size?: number
}

export type OpsFindingEventType = 'ignored' | 'reopened' | 'resolved'

export interface OpsFindingEventDto {
  event_id: string
  finding_id: string
  event_type: OpsFindingEventType
  actor: string
  reason: string | null
  created_at: string
}

// ── #53 L1 自动修复 ──

export type RemediationRiskLevel = 'L1' | 'L2'
export type RemediationRunStatus = 'succeeded' | 'failed'
export type VerificationResult = 'passed' | 'failed'

export interface OpsRemediationActionDto {
  action: string
  check_id: string
  risk_level: RemediationRiskLevel
  description: string
}

export interface OpsRemediationRunDto {
  run_id: string
  finding_id: string
  action: string
  risk_level: RemediationRiskLevel
  status: RemediationRunStatus
  before_evidence: Record<string, unknown>
  after_evidence: Record<string, unknown>
  verification_result: VerificationResult | null
  created_by: string
  created_at: string
}

export interface OpsFindingDetailDto {
  finding: OpsFindingDto
  events: OpsFindingEventDto[]
  remediations: OpsRemediationRunDto[]
}

export interface OpsRemediationResultDto {
  run: OpsRemediationRunDto
  detail: OpsFindingDetailDto
}

// ── #51 P1-5 LLM 智能诊断 ──

export type DiagnosisStatus = 'complete' | 'insufficient_evidence'
export type DiagnosisActionLevel = 'L1' | 'L2' | 'L3'

export interface DiagnosisCitationDto {
  citation_id: string
  source: string
  quote: string
}

export interface DiagnosisActionDto {
  level: DiagnosisActionLevel
  description: string
  citation_ids: string[]
}

export interface OpsDiagnosisReportDto {
  finding_id: string
  status: DiagnosisStatus
  root_cause: string | null
  citations: DiagnosisCitationDto[]
  uncertainties: string[]
  actions: DiagnosisActionDto[]
  model_route: { scene?: string; model_type?: string; model_name?: string }
  generated_by: string
  generated_at: string
}

export interface OpsDiagnosisResultDto {
  finding: OpsFindingDto
  report: OpsDiagnosisReportDto
}

// ── #52 P1-6 定时巡检调度 ──

export type OpsInspectionTrigger = 'manual' | 'scheduled'
export type OpsInspectionStatus = 'running' | 'succeeded' | 'failed'

export interface OpsInspectionRunDto {
  inspection_id: string
  trigger_source: OpsInspectionTrigger
  status: OpsInspectionStatus
  triggered_by: string
  started_at: string
  finished_at: string | null
  finding_count: number
  new_finding_count: number
  checker_errors: OpsCheckerErrorDto[]
}

export interface OpsInspectionSummaryDto {
  interval_minutes: number
  next_run_at: string | null
  in_progress: boolean
  latest: OpsInspectionRunDto | null
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

export async function getOpsInspectionSummary(): Promise<OpsInspectionSummaryDto> {
  return opsRequest<OpsInspectionSummaryDto>('/inspection-summary')
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

export async function listOpsRemediationActions(): Promise<OpsRemediationActionDto[]> {
  return opsRequest<OpsRemediationActionDto[]>('/remediation-actions')
}

export async function remediateOpsFinding(
  findingId: string,
  expectedRevision: number,
): Promise<OpsRemediationResultDto> {
  return opsRequest<OpsRemediationResultDto>(
    `/findings/${encodeURIComponent(findingId)}/remediate?expected_revision=${expectedRevision}`,
    { method: 'POST' },
  )
}

export async function diagnoseOpsFinding(
  findingId: string,
): Promise<OpsDiagnosisResultDto> {
  return opsRequest<OpsDiagnosisResultDto>(
    `/findings/${encodeURIComponent(findingId)}/diagnose`,
    { method: 'POST' },
  )
}
