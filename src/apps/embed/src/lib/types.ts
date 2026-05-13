export type RoleId = 'cashier' | 'medical_office' | 'information_department' | 'medical_record_staff' | 'clinician'

export type Skill = {
  skill_id: string
  name: string
  description: string
  owner: string
  enabled: boolean
  risk_level: string
  intent_keywords: string[]
  required_roles: string[]
  skill_metadata: {
    author: string
    version: string
    category?: string
    tags: string[]
  }
}

export type ApiConnectionStatus = 'unknown' | 'connected' | 'fallback'

export interface Citation {
  source_type: string
  source_id: string
  summary: string
}

export interface AgentTask {
  task_id?: string
  task_type?: string
  status?: string
  description?: string
  action?: string
  [key: string]: unknown
}

export interface ChatRequest {
  user_id: string
  role: string
  message: string
  patient_id?: string
  encounter_id?: string
}

export interface AgentResponse {
  scenario?: string | null
  status: string
  result: Record<string, unknown>
  citations: Citation[]
  tasks: AgentTask[]
  missing_fields: string[]
  uncertainties: string[]
  blocked_actions: string[]
  audit: Record<string, unknown>
  fallback?: boolean
}

export interface PatientContextResponse {
  patient: Record<string, unknown>
  visible_fields: string[]
  encounter_id?: string | null
  settlement_status?: string | null
  audit_risks?: unknown[] | null
  fallback?: boolean
}

export interface TaskConfirmRequest {
  task_id: string
  action: 'confirm' | 'reject'
  user_id: string
  reason?: string
}

export interface TaskConfirmResponse {
  task_id: string
  status: string
  confirmed_by: string
  confirmed_at: string
  reason?: string | null
  result: Record<string, unknown>
  fallback?: boolean
}

export interface WorkflowStatusResponse {
  workflow_id: string
  status: string
  fallback?: boolean
}

export interface TaskStatusResponse {
  task_id: string
  status: string
  fallback?: boolean
}

export interface ModelTestRequest {
  message: string
  scene: string
}

export interface ModelTestResponse {
  content: string
  model_name: string
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  fallback?: boolean
}

export type McpTransport = 'stdio' | 'sse' | 'streamable_http'
export type McpServerStatus = 'enabled' | 'disabled' | 'degraded' | 'unhealthy'

export interface McpServer {
  server_id: string
  name: string
  endpoint: string
  transport: McpTransport
  status: McpServerStatus
  protocol_version?: string | null
  auth_headers: Record<string, string>
  metadata: Record<string, unknown>
  fallback?: boolean
}

export interface McpStorageHealth {
  status: string
  backend?: string
  details?: Record<string, unknown>
  fallback?: boolean
  [key: string]: unknown
}

export type SseEventType = 'start' | 'step' | 'delta' | 'final' | 'error' | 'done' | 'token' | 'intent_trace'

export interface IntentCandidate {
  intent_id: string
  score: number
  source: string
  matched_keywords: string[]
}

export interface IntentTrace {
  intent: string
  confidence: number
  status: string
  top_candidates: IntentCandidate[]
  missing_fields: string[]
  clarification_needed: boolean
  clarification_question: string | null
  original_message: string | null
  rewrite_changes: string[]
  entities: Record<string, unknown>
  citations: string[]
  raw_message: string
}

export interface SseEvent<T = unknown> {
  event: SseEventType
  data: T
}

export interface ApiErrorDetail {
  error_code: string
  message: string
  audit_event?: Record<string, unknown>
}

export class ApiClientError extends Error {
  readonly status: number
  readonly detail: ApiErrorDetail

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message)
    this.name = 'ApiClientError'
    this.status = status
    this.detail = detail
  }
}
