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

export interface McpCapability {
  capability_id: string
  server_id: string
  capability_type: string
  risk_level: string
  payload_json?: Record<string, unknown>
  fallback?: boolean
}

export interface McpCapabilityCreate {
  capability_id: string
  server_id: string
  capability_type: string
  risk_level: string
  payload_json?: Record<string, unknown>
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

export interface McpCapability {
  capability_id: string
  server_id: string
  capability_type: string
  risk_level: string
  payload_json?: Record<string, unknown>
}

export interface McpCapabilityCreate {
  capability_id: string
  server_id: string
  capability_type: string
  risk_level: string
  payload_json?: Record<string, unknown>
}

export interface ErrorCode {
  error_code: string
  description: string
  exception_type: string
  responsible_role: string
  recommendation: string
}

export interface ErrorCodeCreate {
  error_code: string
  description: string
  exception_type: string
  responsible_role: string
  recommendation: string
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

export interface RuleCreate {
  rule_id: string
  rule_name: string
  category: string
  scenario: string
  rule_content: string
  explanation: string
  applicable_roles: string[]
  risk_level: string
  effective_date: string
  enabled: boolean
}

export interface AssetCreate {
  asset_id: string
  title: string
  source: string
  asset_type: string
  version: string
  summary: string
  visibility: Record<string, unknown>
}

export interface ChunkCreate {
  chunk_id: string
  section: string
  content: string
}

// --- Model Management Types ---

export interface ModelConfig {
  base_url: string
  timeout: number
  max_retries: number
  default_model: string
  fallback?: boolean
}

export interface ModelRouteCreate {
  scene: string
  model_type: string
  model_name: string
  priority: number
  enabled: boolean
}

export interface ModelRouteResponse {
  route_id: string
  scene: string
  model_type: string
  model_name: string
  priority: number
  enabled: boolean
  fallback?: boolean
}

export interface ModelProviderCreate {
  provider_id?: string
  provider_type: string
  base_url: string
  api_key?: string
  default_headers?: Record<string, string>
  enabled?: boolean
}

export interface ModelProviderResponse {
  provider_id: string
  provider_type: string
  base_url: string
  api_key?: string
  default_headers?: Record<string, string>
  enabled: boolean
  fallback?: boolean
}

export interface ModelProviderTestResult {
  success: boolean
  latency_ms: number
  error?: string
}

export interface ListResponse<T> {
  items: T[]
  total: number
}

export interface FallbackChain {
  fallbacks: string[]
}

export type ModelParams = Record<string, unknown>

// --- Appeal Template Types ---

export interface AppealTemplateCreate {
  template_id: string
  template_name: string
  template_type: string
  denial_reason_pattern: string
  content: string
  required_evidence: string[]
  applicable_scenarios: string[]
}

export interface AppealTemplateItem extends AppealTemplateCreate {
  enabled: boolean
  created_at?: string
  updated_at?: string
  fallback?: boolean
}

// --- Prompt Template Types ---

export interface PromptTemplateCreate {
  template_id: string
  template_name: string
  template_type: string
  scenario: string
  role: string
  system_prompt: string
  user_prompt_template?: string
  variables: string[]
  output_format: Record<string, unknown>
}

export interface PromptTemplateItem extends PromptTemplateCreate {
  enabled: boolean
  created_at?: string
  updated_at?: string
  fallback?: boolean
}

export interface RenderPromptRequest {
  template_id: string
  variables: Record<string, string>
}

export interface RenderPromptResponse {
  rendered: string
}
