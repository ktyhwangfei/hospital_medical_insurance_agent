// 筛查规则管理 API 客户端 — issue #86 规则管理（管理入口）。
// DTO 字段与后端 src/runtime/api/screening_rule_routes.py 逐字段对齐（snake_case 直传）。
import { requestJson } from './api-client'

export type RuleClassDto = 'executable' | 'needs_mapping' | 'not_executable'
export type RuleStatusDto = 'candidate' | 'approved' | 'disabled'
export type RunStatusDto = 'running' | 'succeeded' | 'failed'
export type FindingTypeDto = 'mismatch' | 'insufficient_material'
export type VerifyStatusDto = 'pending' | 'follow' | 'not_follow' | 'insufficient'

export interface ChecklistItemDto {
  item_ref: string
  clause: string
  rule_class: RuleClassDto
  mapping_gap: string | null
  candidate_rule_id: string | null
}

export interface UploadChecklistResponseDto {
  source_doc: string
  items: ChecklistItemDto[]
  candidate_rule_ids: string[]
}

export interface ScreeningRuleDto {
  rule_id: string
  source_doc: string
  source_clause: string
  title: string
  condition_text: string
  rule_class: RuleClassDto
  mapping_gap: string | null
  status: RuleStatusDto
  source_item_ref: string | null
  created_at: string
  updated_at: string
  approved_at: string | null
  approved_by: string | null
}

export interface ScreeningRunDto {
  run_id: string
  started_at: string
  finished_at: string | null
  status: RunStatusDto
  time_range_start: string
  time_range_end: string
  error_message: string | null
  created_by: string
  rule_ids: string[]
  finding_counts: Record<string, number>
}

export interface ScreeningFindingDto {
  finding_id: string
  run_id: string
  rule_id: string
  settlement_key: string
  fee_line_id: string | null
  item_code: string | null
  item_name: string | null
  amount: number | null
  finding_type: FindingTypeDto
  primary_finding_id: string
  evidence_clause: string
  evidence_facts: Record<string, unknown>
  verify_status: VerifyStatusDto
  created_at: string
}

// ── 鉴权（与 question-library 同模式：sessionStorage → dev 环境变量 token）──

function ruleManagementToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('rule-management-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_RULE_MANAGEMENT_TOKEN || null
}

export function hasRuleManagementPermission(permission: 'read' | 'write'): boolean {
  const token = ruleManagementToken()
  if (!token) return process.env.NODE_ENV !== 'production'
  try {
    const payload = token.replace(/^Bearer\s+/i, '').split('.')[1]
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const permissions = JSON.parse(atob(base64)).permissions
    return Array.isArray(permissions) && permissions.includes(`rule_management:${permission}`)
  } catch {
    return false
  }
}

async function rmRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = ruleManagementToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson<T>(`/rule-management${path}`, { ...init, headers })
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

// ── 上传与分类 ──

export function uploadChecklist(sourceDoc: string, content: string): Promise<UploadChecklistResponseDto> {
  return rmRequest<UploadChecklistResponseDto>('/checklists', jsonInit('POST', { source_doc: sourceDoc, content }))
}

// ── 规则生命周期 ──

export interface CreateRuleRequestDto {
  source_doc: string
  source_clause: string
  title: string
  condition_text: string
  rule_class: RuleClassDto
  condition_spec?: Record<string, unknown> | null
  mapping_gap?: string | null
  source_item_ref?: string | null
}

export function createRule(request: CreateRuleRequestDto): Promise<ScreeningRuleDto> {
  return rmRequest<ScreeningRuleDto>('/rules', jsonInit('POST', request))
}

export function listRules(filter?: { rule_class?: RuleClassDto; status?: RuleStatusDto }): Promise<ScreeningRuleDto[]> {
  const params = new URLSearchParams()
  if (filter?.rule_class) params.set('rule_class', filter.rule_class)
  if (filter?.status) params.set('status', filter.status)
  const query = params.toString()
  return rmRequest<ScreeningRuleDto[]>(`/rules${query ? `?${query}` : ''}`)
}

export function updateRule(
  ruleId: string,
  patch: { title?: string; condition_text?: string; mapping_gap?: string | null },
): Promise<ScreeningRuleDto> {
  return rmRequest<ScreeningRuleDto>(`/rules/${encodeURIComponent(ruleId)}`, jsonInit('PATCH', patch))
}

export function approveRule(ruleId: string): Promise<ScreeningRuleDto> {
  return rmRequest<ScreeningRuleDto>(`/rules/${encodeURIComponent(ruleId)}/approve`, { method: 'POST' })
}

export function disableRule(ruleId: string): Promise<ScreeningRuleDto> {
  return rmRequest<ScreeningRuleDto>(`/rules/${encodeURIComponent(ruleId)}/disable`, { method: 'POST' })
}

// ── 执行批次 ──

export function startRun(request: {
  time_range_start: string
  time_range_end: string
  rule_ids?: string[]
}): Promise<ScreeningRunDto> {
  return rmRequest<ScreeningRunDto>('/runs', jsonInit('POST', request))
}

export function listRuns(limit = 20): Promise<ScreeningRunDto[]> {
  return rmRequest<ScreeningRunDto[]>(`/runs?limit=${limit}`)
}

export function getRun(runId: string): Promise<ScreeningRunDto> {
  return rmRequest<ScreeningRunDto>(`/runs/${encodeURIComponent(runId)}`)
}

// ── 两本名单与核实 ──

export function listFindings(filter?: {
  run_id?: string
  rule_id?: string
  finding_type?: FindingTypeDto
  limit?: number
}): Promise<ScreeningFindingDto[]> {
  const params = new URLSearchParams()
  if (filter?.run_id) params.set('run_id', filter.run_id)
  if (filter?.rule_id) params.set('rule_id', filter.rule_id)
  if (filter?.finding_type) params.set('finding_type', filter.finding_type)
  if (filter?.limit) params.set('limit', String(filter.limit))
  const query = params.toString()
  return rmRequest<ScreeningFindingDto[]>(`/findings${query ? `?${query}` : ''}`)
}

export function verifyFinding(findingId: string, verifyStatus: VerifyStatusDto): Promise<ScreeningFindingDto> {
  return rmRequest<ScreeningFindingDto>(
    `/findings/${encodeURIComponent(findingId)}/verify`,
    jsonInit('POST', { verify_status: verifyStatus }),
  )
}
