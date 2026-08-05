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

// --- Infra Skill Types ---

export interface InfraSkillItem {
  skill_id: string
  skill_name: string
  business_action: string
  business_object: string
  include_keywords: string[]
  excluded_intents: string[]
}

export interface SkillValidationIssueResponse {
  code: string
  message: string
  path?: string | null
}

export interface SkillVersionResponse {
  version_id: string
  skill_id: string
  semantic_version: string
  source_commit: string
  source_path: string
  artifact_hash: string
  manifest_snapshot: Record<string, unknown>
  dependency_snapshot: Record<string, unknown>
  file_count: number
  validation_status: 'pending' | 'passed' | 'failed'
  validation_issues: SkillValidationIssueResponse[]
  created_by: string
  created_at: string
}

export interface InfraSkillCatalogItem extends InfraSkillItem {
  semantic_version: string
  artifact_hash: string
  artifact_status: 'registered' | 'changed' | 'unregistered'
  file_count: number
  registered_version?: SkillVersionResponse | null
}

export interface InfraSkillCatalogResponse {
  items: InfraSkillCatalogItem[]
  page: number
  page_size: number
  total: number
}

export interface SkillVersionSyncRequest {
  source_commit?: string
  created_by: string
}

export interface InfraSkillFilesStructure {
  agents: string[]
  schemas: string[]
  templates: string[]
  scripts: string[]
  references: string[]
  tests: string[]
  strategies: string[]
}

export interface FieldMappingItem {
  label: string
  description: string
  db_source: string
}

export interface FieldMappingResponse {
  target_field: Record<string, unknown>
  settlement_fields: Record<string, FieldMappingItem>
  defaults: Record<string, string>
}

export interface InfraSkillDetailResponse {
  skill_id: string
  skill_name: string
  business_action: string
  business_object: string
  include_keywords: string[]
  excluded_intents: string[]
  manifest: Record<string, unknown>
  readme: string
  files_structure: InfraSkillFilesStructure
  field_mapping: FieldMappingResponse | null
}

export interface SkillRouteTestRequest {
  question: string
}

export interface SkillRouteTestResponse {
  question: string
  matched_skill_id?: string | null
  confidence: number
  match_method: string
  matched_keywords: string[]
  excluded_keywords: string[]
  candidates: Array<{
    skill_id: string
    skill_name: string
    confidence: number
    matched_keywords: string[]
    match_method: string
  }>
}

export interface SkillExecuteTestRequest {
  question: string
  target_fee_item?: string | null
  context?: Record<string, unknown>
  evidence?: Record<string, unknown>
  status?: Record<string, unknown>
}

export interface SkillExecuteTestResponse {
  skill_id: string
  status: string
  result: unknown
  warnings: string[]
  citations: Array<Record<string, unknown>>
  uncertainties: string[]
  trace: Array<Record<string, unknown>>
  input_summary: Record<string, unknown>
  latency_ms?: number | null
}

export interface InfraSkillOverviewItem {
  skill_id: string
  skill_name: string
  business_action: string
  business_object: string
  loaded: boolean
  manifest_valid: boolean
  field_mapping_configured: boolean
  metric_count: number
  last_test_status?: string | null
  warnings: string[]
}

export interface InfraSkillOverviewResponse {
  skill_count: number
  skills: InfraSkillOverviewItem[]
}

// ── 语义层（最新）：技能↔指标关系 ─────────────────────────────────

/** GET /semantic/skills/{skill_id}/metrics —— 技能引用的语义指标 */
export interface SkillSemanticMetric {
  metric_code: string
  name: string
  object_code: string
  usage_count: number
}

/** GET /semantic/metrics/{code} —— 指标详情（取数映射/质量/值域状态） */
export interface SemanticMetricDetail {
  metric_code: string
  name: string
  definition: string | null
  object_code: string
  metric_type: string
  semantic_type: string | null
  unit: string | null
  required: boolean
  importance: string
  value_domain: string | null
  source_object: string | null
  source_field: string | null
  source_adapter_port: string | null
  usage_count: number
  quality_score: number
  version: string
  status: string
}

// ── 语义层：技能查询计划与试运行 ───────────────────────────────

/** GET /semantic/skills/{id}/query-plan */
export interface QueryPlanTable {
  table: string
  columns: string[]
  metrics: { metric_code: string; name: string; column: string; semantic_type: string | null }[]
}
export interface SkillQueryPlan {
  total_metrics: number
  mapped_count: number
  unmapped_count: number
  filter_column: string
  filter_context_key: string
  tables: QueryPlanTable[]
  unmapped: { metric_code: string; unmapped: boolean; reason?: string; name?: string }[]
}

/** POST /semantic/skills/{id}/query-execute */
export interface QueryExecuteItem {
  metric_code: string
  name: string
  source_field: string | null
  value: unknown
}
export interface SkillQueryExecuteResult {
  skill_id: string
  djh: string | number
  items: QueryExecuteItem[]
}

/** GET /semantic/skills/{id}/consistency-check?djh=X */
export interface ConsistencyItem {
  metric_code: string
  name: string
  semantic_value: unknown
  semantic_joined_value: unknown
  business_sql_value: unknown
  compared: boolean
  match: boolean
  joined_match: boolean
}
export interface ConsistencyCheckResult {
  skill_id: string
  djh: string
  supported: boolean
  message?: string
  business_sql_error: string | null
  summary: {
    compared: number
    flat_matched: number
    flat_mismatched: number
    joined_matched: number
    joined_mismatched: number
  }
  items: ConsistencyItem[]
}

// ── QA History Types ────────────────────────────────────────────

export interface QAWorkflowStep {
  step_id: string
  status: string
}

export interface QATask {
  task_id: string
  task_type: string
  status: string
  description: string
  executor_type: string
  step_id?: string
  duration_ms?: number
  error_message?: string
  created_at: string
  input_data: Record<string, unknown>
  output_data: Record<string, unknown>
}

export interface QAWorkflow {
  workflow_id: string
  scenario: string
  status: string
  current_step?: string
  steps: QAWorkflowStep[]
  tasks: QATask[]
}

export interface QASession {
  session_id: string
  user_id: string
  role: string
  created_at: string
  last_active: string
  workflows: QAWorkflow[]
}

export interface QAHistoryResponse {
  total: number
  limit: number
  offset: number
  items: QASession[]
}


