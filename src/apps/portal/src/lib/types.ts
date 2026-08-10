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

export type SkillGovernanceStatus =
  | 'gate_failed'
  | 'pending_approval'
  | 'needs_evaluation'
  | 'artifact_changed'
  | 'healthy'

export type SkillWorkbenchTab =
  | 'overview'
  | 'versions'
  | 'evaluation'
  | 'release'
  | 'development'

export interface SkillWorkbenchSummary {
  total: number
  healthy: number
  needs_evaluation: number
  pending_approval: number
  test_active: number
  updated_at: string
}

export interface SkillWorkbenchItem {
  skill_id: string
  skill_name: string
  business_action: string
  business_object: string
  semantic_version: string
  artifact_status: 'registered' | 'changed' | 'unregistered'
  validation_status: 'pending' | 'passed' | 'failed'
  latest_eval_status: SkillEvalRunResponse['status'] | null
  test_release_status: SkillReleaseResponse['status'] | null
  test_active_version: string | null
  governance_status: SkillGovernanceStatus
  attention_reason: string | null
}

export interface SkillWorkbenchResponse {
  summary: SkillWorkbenchSummary
  items: SkillWorkbenchItem[]
  total: number
  page: number
  page_size: number
}

export interface SkillVersionSyncRequest {
  source_commit?: string
  created_by: string
}

export interface SkillEvalCaseResponse {
  case_id: string
  suite_version: number
  question_template: string
  expected_skill_id?: string | null
  required: boolean
  risk_tags: string[]
  business_tags: string[]
  source_type: string
  source_ref: string
  contains_sensitive_data: boolean
  enabled: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export interface SkillEvalCaseListResponse {
  items: SkillEvalCaseResponse[]
  suite_version: number
  total: number
}

export interface SkillEvalCaseCreateRequest {
  question_template: string
  expected_skill_id?: string | null
  required?: boolean
  risk_tags?: string[]
  business_tags?: string[]
  source_type?: string
  source_ref?: string
  contains_sensitive_data?: false
}

export interface SkillEvalMetricsResponse {
  total: number
  passed: number
  required_total: number
  required_passed: number
  top1_accuracy: number
  baseline_top1_accuracy: number
  regression_count: number
  new_false_takeover_count: number
  gate_passed: boolean
}

export interface SkillEvalResultResponse {
  case_id: string
  expected_skill_id?: string | null
  candidate_skill_id?: string | null
  baseline_skill_id?: string | null
  candidate_confidence: number
  baseline_confidence: number
  candidate_passed: boolean
  baseline_passed: boolean
  required: boolean
  diff: 'unchanged_pass' | 'unchanged_fail' | 'new_pass' | 'new_failure' | 'route_changed'
  candidate_keywords: string[]
  baseline_keywords: string[]
}

export interface SkillEvalRunResponse {
  run_id: string
  skill_id: string
  version_id: string
  baseline_version_id?: string | null
  suite_version: number
  config_hash: string
  routing_manifest_hash: string
  status: 'running' | 'passed' | 'failed' | 'cancelled' | 'error'
  metrics: SkillEvalMetricsResponse
  results: SkillEvalResultResponse[]
  case_snapshots: SkillEvalCaseResponse[]
  created_by: string
  created_at: string
  completed_at?: string | null
}

export interface SkillEvalRunListResponse {
  items: SkillEvalRunResponse[]
  total: number
}

export interface SkillEvalRunCreateRequest {
  version_id: string
  baseline_version_id?: string | null
}

export type SkillCandidateEvaluationStatus =
  | 'completed'
  | 'failed'
  | 'blocked_by_evaluator'

export interface SkillCandidateRouteEvaluationResponse {
  artifact_hash: string
  case_snapshot_hash: string
  status: SkillCandidateEvaluationStatus
  metrics: SkillEvalMetricsResponse | null
  results: SkillEvalResultResponse[]
  blocked_reason: string | null
}

export interface SkillCandidateBehaviorResultResponse {
  case_id: string
  status: 'passed' | 'failed' | 'blocked_by_evaluator'
  passed: boolean
  output: Record<string, unknown> | null
  blocked_reason: string | null
}

export interface SkillCandidateBehaviorEvaluationResponse {
  artifact_hash: string
  case_snapshot_hash: string
  status: SkillCandidateEvaluationStatus
  results: SkillCandidateBehaviorResultResponse[]
  blocked_reason: string | null
}

export interface SkillReleaseResponse {
  release_id: string
  skill_id: string
  version_id: string
  environment: 'dev' | 'test'
  status: 'candidate' | 'approval_pending' | 'approved' | 'active' | 'retired'
  baseline_release_id?: string | null
  eval_run_id: string
  artifact_hash: string
  config_hash: string
  rollout_percent: 0 | 100
  runtime_mode: 'shadow'
  revision: number
  created_by: string
  created_at: string
  activated_at?: string | null
  retired_at?: string | null
  approval?: SkillReleaseApprovalSummary | null
}

export interface SkillReleaseApprovalSummary {
  approved_by: string
  approver_role: string
  approved_at: string
}

export interface SkillReleaseListResponse {
  items: SkillReleaseResponse[]
  total: number
}

export interface SkillReleaseCreateRequest {
  version_id: string
  eval_run_id: string
  environment: 'dev' | 'test'
}

export interface SkillReleaseTransitionRequest {
  expected_revision: number
}

export interface SkillReleaseApproveRequest extends SkillReleaseTransitionRequest {
  reason: string
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



// ── Skill 草稿与生命周期（P7/P8）──────────────────────────────────

export type SkillDraftStatus = 'editing' | 'validated' | 'materialized' | 'deleted'
export type SkillDraftSourceType = 'template' | 'copy' | 'import' | 'ai_generated'
export type SkillLifecycleStatus = 'enabled' | 'disabled' | 'archived'

export interface SkillAIStructuredBasic {
  skill_id: string
  skill_name: string
  description: string
  owner: string
}

export interface SkillAIStructuredBusinessMounting {
  business_action: string
  business_object: string
  include_keywords: string[]
  excluded_intents: string[]
}

export interface SkillAIStructuredInput {
  metric_code: string
  alias: string
  required: boolean
  purpose: string
}

export interface SkillAIStructuredConfig {
  basic: SkillAIStructuredBasic
  business_mounting: SkillAIStructuredBusinessMounting
  inputs: SkillAIStructuredInput[]
  schemas: {
    input: Record<string, unknown>
    output: Record<string, unknown>
  }
}

export interface SkillBusinessMounting {
  business_action: string
  business_object: string
  include_keywords?: string[]
  keywords?: string[]
  excluded_intents?: string[]
}

export interface SkillInputSpec {
  metric_code: string
  alias?: string
  required: boolean
  purpose?: string
}

export interface SkillStructuredConfig {
  basic?: SkillAIStructuredBasic
  description?: string
  owner?: string
  business_mounting: SkillBusinessMounting
  inputs?: SkillInputSpec[]
  schemas?: {
    input: Record<string, unknown>
    output: Record<string, unknown>
  }
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
}

export function isSkillAIStructuredConfig(
  config: SkillStructuredConfig,
): config is SkillAIStructuredConfig {
  return Boolean(
    config.basic &&
    config.schemas &&
    Array.isArray(config.business_mounting.include_keywords),
  )
}

// 编译期契约：AI 提案被接受后的配置必须可直接作为草稿配置。
type AssertTrue<T extends true> = T
export type SkillAIConfigDraftCompatibility = AssertTrue<
  SkillAIStructuredConfig extends SkillStructuredConfig ? true : false
>

export interface SkillMetricVersionRef {
  metric_code: string
  object_code: string
  object_version: number
  status: 'published'
}

export interface SkillAIGenerationProvenance {
  model_type: string
  scene: 'skill_authoring'
  prompt_version: string
  metric_versions: SkillMetricVersionRef[]
  generated_at: string
  content_hash: string
}

export interface SkillAIValidationPreview {
  issues: SkillValidationIssue[]
  has_blocking: boolean
  blocking_ok: boolean
}

export interface SkillAIGenerationProposal {
  generation_id: string
  proposal_hash: string
  structured_config: SkillAIStructuredConfig
  raw_files: Record<string, string>
  validation_preview: SkillAIValidationPreview
  provenance: SkillAIGenerationProvenance
  citations: Citation[]
  uncertainties: string[]
}

export interface SkillAIGenerateRequest {
  description: string
  metric_codes: string[]
}

export interface SkillAIOptimizeRequest extends SkillAIGenerateRequest {
  expected_revision: number
}

export interface SkillAIOptimizationDiff {
  scope: 'field' | 'file'
  change_type: 'added' | 'changed' | 'removed'
  path: string
  before: string | null
  after: string | null
}

export interface SkillAIOptimizationProposal {
  base_revision: number
  proposal_hash: string
  structured_config: SkillAIStructuredConfig
  raw_files: Record<string, string>
  validation_preview: SkillAIValidationPreview
  provenance: SkillAIGenerationProvenance
  diff: SkillAIOptimizationDiff[]
  citations: Citation[]
  uncertainties: string[]
}

export interface SkillAIAcceptRequest {
  generation_id: string
  proposal_hash: string
  skill_id: string
  skill_name: string
  structured_config: SkillAIStructuredConfig
  raw_files: Record<string, string>
  provenance: SkillAIGenerationProvenance
}

export interface SkillDraftResponse {
  draft_id: string
  skill_id: string
  skill_name: string
  status: SkillDraftStatus
  source_type: SkillDraftSourceType
  structured_config: SkillStructuredConfig
  raw_files?: Record<string, string>
  validation_report?: { blocking: unknown[]; warnings: unknown[] }
  validation_blocking_ok: boolean
  revision: number
  etag: string
  created_at: string
  updated_at: string
  created_by: string
}

export interface SkillDraftListResponse {
  items: SkillDraftResponse[]
  total: number
}

export interface SkillDraftCreateRequest {
  skill_id: string
  skill_name: string
  description?: string
  owner?: string
  business_action?: string
  business_object?: string
}

export interface SkillDraftCopyRequest {
  source_skill_id: string
  new_skill_id: string
}

export interface SkillDraftSaveRequest {
  structured_config: SkillStructuredConfig
  raw_files?: Record<string, string>
  expected_revision: number
  etag?: string
}

export type SkillValidationSeverity = 'blocking' | 'warning'

export interface SkillValidationIssue {
  code: string
  message: string
  severity: SkillValidationSeverity
  path: string | null
}

export interface SkillValidationResponse {
  draft_id: string
  issues: SkillValidationIssue[]
  has_blocking: boolean
  blocking_ok: boolean
  revision: number
}

export interface SkillPackageFile {
  path: string
  content: string
}

export interface SkillPackagePreviewResponse {
  draft_id: string
  files: SkillPackageFile[]
}

export interface SkillMaterializeRequest {
  draft_id: string
  expected_revision: number
  reason: string
}

export interface SkillMaterializeResponse {
  skill_id: string
  version_id: string
  artifact_written: boolean
  draft_revision: number
}

export interface SkillDefinitionResponse {
  skill_id: string
  skill_name: string
  business_action: string
  business_object: string
  lifecycle_status: SkillLifecycleStatus
  semantic_dependency_changed: boolean
  current_version_id: string | null
  revision: number
  disabled_at: string | null
  archived_at: string | null
}

export interface SkillLifecycleTransitionRequest {
  expected_revision: number
  reason: string
}

// ── 语义层输入指标（P4）──────────────────────────────────────────

export interface SkillInputSelectorNode {
  domain_code: string
  name: string
  objects: {
    object_code: string
    name: string
    definition: string
    status: string
    current_version: string | null
    metrics: {
      metric_code: string
      name: string
      definition: string
      source_type: string
      status: string
      current_version: string | null
      quality_score: number | null
    }[]
  }[]
}

export interface SkillInputSelectorResponse {
  tree: SkillInputSelectorNode[]
}

export interface SkillInputValidationIssue {
  metric_code: string
  code: string
  message: string
}

export interface SkillInputValidationResponse {
  ok: boolean
  issues: SkillInputValidationIssue[]
}

export interface SkillQueryPlanResponse {
  metric_codes: string[]
  plan: {
    object_code: string
    query_implementation: string
    fields: { field: string; metric_code: string }[]
  }[]
}
