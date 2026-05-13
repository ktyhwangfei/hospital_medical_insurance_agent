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

export interface WorkflowListItem {
  workflow_id: string
  scenario: string
  status: string
  patient_id?: string
  patient_name?: string
  patient?: { name?: string; patient_id?: string }
  encounter_id?: string
  error_code?: string
  error_msg?: string
  exception_type?: string
  priority?: string
  detected_at?: string
  created_at?: string
  current_step?: string
  steps?: Array<{
    step_id: string
    status: string
    error?: string
  }>
  context?: Record<string, unknown>
  [key: string]: unknown
}

export interface WorkflowListResponse {
  workflows: WorkflowListItem[]
  total: number
  fallback?: boolean
}

/** Alias for backward compatibility */
export type WorkflowItem = WorkflowListItem

export interface ErrorCodeItem {
  error_code: string
  description?: string
  exception_type?: string
  responsible_role?: string
  recommendation?: string
  [key: string]: unknown
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
  | 'stream:start' | 'stream:step' | 'stream:intent_trace'
  | 'stream:delta' | 'stream:tool_call' | 'stream:tool_result'
  | 'stream:final' | 'stream:error' | 'stream:done'

// ── New streaming event payloads ─────────────────────────────────
export interface ToolCallPayload {
  call_id: string
  request_id: string
  tool_name: string
  params: Record<string, unknown>
  event_timestamp: string
}

export interface ToolResultPayload {
  call_id: string
  request_id: string
  result: Record<string, unknown>
  duration_ms: number
  event_timestamp: string
}

export interface StreamStepPayload {
  step: string
  message: string
  request_id: string
  event_timestamp: string
}

export interface StreamIntentTracePayload {
  intent: string
  confidence: number
  trace: Record<string, unknown>
  request_id: string
  event_timestamp: string
}

export interface StreamDeltaPayload {
  content: string
  request_id: string
  event_timestamp: string
}

export interface StreamStartPayload {
  intent: string
  confidence: number
  request_id: string
  event_timestamp: string
}

export interface StreamFinalPayload {
  response: AgentResponse
  request_id: string
  event_timestamp: string
}

export interface StreamErrorPayload {
  error_code: string
  message: string
  request_id: string
  event_timestamp: string
}

export interface StreamDonePayload {
  request_id: string
  event_timestamp: string
}

export type StreamingEventPayload =
  | StreamStartPayload
  | StreamStepPayload
  | StreamIntentTracePayload
  | StreamDeltaPayload
  | ToolCallPayload
  | ToolResultPayload
  | StreamFinalPayload
  | StreamErrorPayload
  | StreamDonePayload

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


