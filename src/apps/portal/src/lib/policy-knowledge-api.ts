const WORKBENCH_API = '/api/v1/medical-insurance-ai-agent/policy-workbench'
const ALIGNMENT_API = '/api/v1/medical-insurance-ai-agent/semantic/alignment'
const SEMANTIC_PROPOSALS_API = `${ALIGNMENT_API}/proposals`
const PIPELINE_API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

export type MappingStatus = 'mapped' | 'unmapped' | 'not_applicable' | 'invalid'

export interface KnowledgeField {
  field_code: string
  field_name: string
  raw_value: unknown
}

export interface StandardizedField {
  source_field: string
  source_value: unknown
  status: MappingStatus
  metric_code: string | null
  metric_name: string | null
  value_domain: string | null
  standard_value: unknown | null
  binding_id: string | null
}

export interface KnowledgeEvidence {
  evidence_id: string
  document_version_id: string
  unit_id: string
  clause_path: string | null
  page_no: number | null
  exact_quote: string
  start_offset: number | null
  end_offset: number | null
  evidence_role: string
}

export interface SemanticBinding {
  policy_field: string
  semantic_field: string | null
  concept: string | null
  value_domain: string | null
  status: string
}

export interface RuleValidity {
  region: string | null
  start_date: string | null
  end_date: string | null
  policy_version: string | null
}

export interface KnowledgeItem {
  knowledge_id: string
  unit_id: string
  extraction_id: string
  relationship_source: 'persisted' | 'legacy_match'
  business_sentence: string
  source_text: string
  fields: KnowledgeField[]
  standardized_fields: StandardizedField[]
  confidence: {
    completeness: number
    accuracy: number | null
    source_fidelity: number
    model_confidence: number
    value_domain_compliance: number | null
    overall: number
    uncertainties: string[]
  }
  citations: Array<{ evidence: string; title: string }>
  review_status?: 'pending' | 'approved' | 'rejected'
  review_note?: string | null
  // —— V4.1 政策规则单元契约 ——
  rule_group_id?: string | null
  topic_concept?: string | null
  rule_type_enum?: string | null
  rule_type_label?: string | null
  validity?: RuleValidity | null
  variants?: Array<Record<string, unknown>>
  evidences?: KnowledgeEvidence[]
  semantic_bindings?: SemanticBinding[]
}

export interface ApprovedUnit {
  unit_id: string
  doc_id: string
  doc_title: string
  path: string[]
  source_text: string
  order_no: number
  status: 'reviewed' | 'published'
  knowledge_count: number
  knowledge: KnowledgeItem[]
}

export interface WorkbenchDocument {
  doc_id: string
  doc_title: string
  contract_version: string | null
  units: ApprovedUnit[]
}

export interface WorkbenchDocumentSummary {
  doc_id: string
  doc_title: string
  approved_unit_count: number
  knowledge_count: number
}

export interface MetricDraftSource {
  doc_id: string
  unit_id: string
  knowledge_id: string
  source_field: string
  field_name: string
  source_value: unknown
  source_text: string
  contract_version: string
}

export interface SemanticMetricSummary {
  metric_code: string
  name: string
  object_code: string
  metric_type: string
  status: string
}

export interface MetricDraftOptions {
  metricType: string
  semanticType: string | null
  unit: string | null
  valueDomain: string | null
}

export interface PolicyTestCase {
  case_id: string
  name: string
  query: string
  mode: 'precise' | 'semantic' | 'hybrid'
  expected_knowledge_ids: string[]
  filters: Record<string, unknown>
  required: boolean
  active: boolean
  case_set_version: number
}

export interface KnowledgeRelease {
  release_id: string
  status: 'building' | 'ready' | 'testing' | 'passed' | 'failed' | 'active' | 'retired'
  facts_collection: string
  rules_collection: string
  contract_version: string
  case_set_version: number
  config_hash: string
  source_change_set_id?: string | null
  quality_score: number | null
  consistency_score: number | null
  build_error?: string | null
  created_at?: string
  promoted_at?: string | null
  promoted_by?: string | null
}

export interface QualityRun {
  run_id: string
  release_id: string
  baseline_release_id: string | null
  status: 'queued' | 'running' | 'passed' | 'failed'
  candidate_score: number | null
  baseline_score: number | null
  consistency_score: number | null
  blocked_reasons: string[]
  repeat_count: number
  case_set_version: number
  config_hash: string
}

/** Read-only gate snapshot for display; the promote POST always revalidates server-side. */
export interface ReleaseGateStatus {
  release_id: string
  can_promote: boolean
  current_case_set_version: number
  active_release_id: string | null
  latest_run: QualityRun | null
  blocked_reasons: string[]
  sync_pending: boolean
  sync_pending_reasons: string[]
}

export const QUALITY_RUN_CONFIG = {
  repeat_count: 3,
  minimum_quality: 0.8,
  minimum_consistency: 0.9,
} as const
export const QUALITY_CONFIG_HASH = '197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22'

export interface PolicyKnowledgeApiAuditEvent {
  task_id?: string | null
  unit_revision_id?: string | null
  target_href?: string | null
  release_id?: string | null
  source_change_set_id?: string | null
  [key: string]: unknown
}

export class PolicyKnowledgeApiError extends Error {
  readonly status: number
  readonly errorCode: string | null
  readonly auditEvent: PolicyKnowledgeApiAuditEvent

  constructor(
    message: string,
    status: number,
    errorCode: string | null,
    auditEvent: PolicyKnowledgeApiAuditEvent,
  ) {
    super(message)
    this.name = 'PolicyKnowledgeApiError'
    this.status = status
    this.errorCode = errorCode
    this.auditEvent = auditEvent
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function policyKnowledgeApiError(response: Response, body: unknown): PolicyKnowledgeApiError {
  const detail = isObject(body) ? body.detail : undefined
  if (!isObject(detail)) {
    return new PolicyKnowledgeApiError(
      typeof detail === 'string' && detail ? detail : `请求失败 (${response.status})`,
      response.status,
      null,
      {},
    )
  }

  const message = typeof detail.message === 'string' && detail.message
    ? detail.message
    : `请求失败 (${response.status})`
  const errorCode = typeof detail.error_code === 'string' ? detail.error_code : null
  const auditEvent = isObject(detail.audit_event) ? detail.audit_event : {}
  return new PolicyKnowledgeApiError(message, response.status, errorCode, auditEvent)
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw policyKnowledgeApiError(response, body)
  }
  return response.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export async function semanticReviewRequest(method = 'GET', body?: unknown): Promise<RequestInit> {
  const sessionToken = typeof window === 'undefined'
    ? null
    : window.sessionStorage.getItem('semantic-review-token')?.trim()
  const token = sessionToken || (process.env.NODE_ENV !== 'production'
    ? process.env.NEXT_PUBLIC_SEMANTIC_REVIEW_TOKEN?.trim()
    : null)
  if (!token) {
    throw new PolicyKnowledgeApiError('缺少语义审核登录凭证', 401, 'AUTHENTICATION_REQUIRED', {})
  }
  const headers: Record<string, string> = {
    Authorization: token.startsWith('Bearer ') ? token : `Bearer ${token}`,
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  return {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }
}

export async function semanticReviewJson<T>(
  url: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  return request<T>(url, await semanticReviewRequest(method, body))
}

export interface SemanticMetricContract {
  semantic_type: string | null
  indexed: boolean
  schema_version: number
}

export interface UpdateSemanticMetricResponse {
  status: string
  metric_code: string
  schema_version: number
  requires_reextract: boolean
  task_id: string | null
  task_status: string | null
}

export async function updateSemanticMetric(
  metricCode: string,
  current: SemanticMetricContract,
  changes: Record<string, unknown>,
): Promise<UpdateSemanticMetricResponse> {
  const changesContract = (
    Object.hasOwn(changes, 'semantic_type') && changes.semantic_type !== current.semantic_type
  ) || (
    Object.hasOwn(changes, 'indexed') && changes.indexed !== current.indexed
  )
  const payload = changesContract
    ? { ...changes, expected_schema_version: current.schema_version }
    : changes
  return semanticReviewJson<UpdateSemanticMetricResponse>(
    `/api/v1/medical-insurance-ai-agent/semantic/metrics/${encodeURIComponent(metricCode)}`,
    'PUT',
    payload,
  )
}

export const listSemanticProposals = async (proposalType: SemanticProposalType) =>
  request<SemanticProposal[]>(
    `${SEMANTIC_PROPOSALS_API}?proposal_type=${encodeURIComponent(proposalType)}`,
    await semanticReviewRequest(),
  )

export const getSemanticProposal = async (proposalId: string) =>
  request<SemanticProposal>(
    `${SEMANTIC_PROPOSALS_API}/${encodeURIComponent(proposalId)}`,
    await semanticReviewRequest(),
  )

export const reviewSemanticProposal = async (proposalId: string) =>
  request<SemanticProposal>(
    `${SEMANTIC_PROPOSALS_API}/${encodeURIComponent(proposalId)}/review`,
    await semanticReviewRequest('POST'),
  )

export const acceptSemanticProposal = async (proposalId: string) =>
  request<SemanticProposal>(
    `${SEMANTIC_PROPOSALS_API}/${encodeURIComponent(proposalId)}/accept`,
    await semanticReviewRequest('POST'),
  )

export const publishSemanticProposal = async (proposalId: string) =>
  request<SemanticProposal>(
    `${SEMANTIC_PROPOSALS_API}/${encodeURIComponent(proposalId)}/publish`,
    await semanticReviewRequest('POST'),
  )

export const rejectSemanticProposal = async (proposalId: string, reason: string) =>
  request<SemanticProposal>(
    `${SEMANTIC_PROPOSALS_API}/${encodeURIComponent(proposalId)}/reject`,
    await semanticReviewRequest('POST', { reason: reason.trim() }),
  )

export const resolveDimensionProposal = async (
  proposalId: string,
  payload: {
    conclusion: DimensionReviewConclusion
    suggested_name?: string
    suggested_code?: string
    reason?: string
  },
) => request<SemanticProposal>(
  `${SEMANTIC_PROPOSALS_API}/${encodeURIComponent(proposalId)}/resolve`,
  await semanticReviewRequest('POST', payload),
)

export async function getWorkbenchDocuments(): Promise<WorkbenchDocumentSummary[]> {
  const result = await request<{ items: WorkbenchDocumentSummary[] }>(`${WORKBENCH_API}/documents`)
  return result.items
}

export const getWorkbenchDocument = (docId: string) =>
  request<WorkbenchDocument>(`${WORKBENCH_API}/documents/${encodeURIComponent(docId)}`)

export const listSemanticMetrics = () =>
  request<SemanticMetricSummary[]>('/api/v1/medical-insurance-ai-agent/semantic/metrics?object_code=zcgz')

export interface KnowledgeReviewPayload {
  doc_id: string
  unit_id: string
  knowledge_id: string
  extraction_id?: string | null
  status: 'approved' | 'rejected'
  reviewed_by: string
  note?: string | null
}

/** 记录一组知识的评审结论（通过/驳回），后端落库。 */
export const reviewKnowledge = (knowledgeId: string, payload: KnowledgeReviewPayload) =>
  request<KnowledgeReviewResult>(
    `${WORKBENCH_API}/knowledge/${encodeURIComponent(knowledgeId)}/review`,
    json('POST', payload),
  )

export interface KnowledgeReviewResult {
  review_id: string
  doc_id: string
  unit_id: string
  knowledge_id: string
  status: 'approved' | 'rejected'
  reviewed_by: string
  reviewed_at: string
  note: string | null
}

// —— V4.1 知识变更集 / 已发布快照 ——

export type ChangeItemType = 'ADD' | 'MODIFY' | 'REPLACE' | 'EXPIRE' | 'SEMANTIC_CHANGE'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type KnowledgeBuildTaskStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'WAITING_REVIEW'
  | 'APPROVED_PENDING_RELEASE'
  | 'PUBLISHED'
  | 'RETURNED'
  | 'REJECTED'
  | 'FAILED'
  | 'CANCELLED'

export interface KnowledgeBuildUnitRevision {
  doc_id: string
  unit_id: string
  unit_revision_id: string
}

export interface CreateKnowledgeBuildTaskRequest {
  name: string
  created_by: string
  build_mode: 'INITIAL' | 'REBUILD'
  rebuild_reason?: string | null
  unit_revisions: KnowledgeBuildUnitRevision[]
}

export interface EligibleKnowledgeUnit {
  doc_id: string
  doc_title: string
  unit_id: string
  unit_revision_id: string
  path: string[]
  source_preview: string
  status: 'reviewed' | 'published'
  knowledge_count: number
  availability: 'AVAILABLE' | 'CLAIMED' | 'REBUILD_REQUIRED'
  occupied_by: string | null
  target_href: string | null
}

export interface KnowledgeBuildBlocker {
  code:
    | 'UNIT_NOT_APPROVED'
    | 'UNIT_REVISION_CHANGED'
    | 'UNIT_ALREADY_CLAIMED'
    | 'SEMANTIC_CONTRACT_MISMATCH'
    | 'REBUILD_MODE_REQUIRED'
    | 'REBUILD_REASON_REQUIRED'
  message: string
  doc_id: string | null
  unit_id: string | null
  unit_revision_id: string | null
  task_id: string | null
  target_href: string | null
}

export interface KnowledgeBuildWarning {
  code: 'REBUILDING_PUBLISHED_UNIT'
  message: string
  doc_id: string
  unit_id: string
}

export interface KnowledgeBuildPreflight {
  selected_count: number
  buildable_count: number
  blocking_count: number
  rebuild_count: number
  can_submit: boolean
  semantic_contract_version: string | null
  blockers: KnowledgeBuildBlocker[]
  warnings: KnowledgeBuildWarning[]
}

export interface KnowledgeBuildTaskUnit {
  doc_id: string
  doc_title: string
  unit_id: string
  unit_revision_id: string
  path: string[]
  status: 'PENDING' | 'BUILT' | 'FAILED'
  candidate_result_ids: string[]
  error_code: string | null
  error_message: string | null
}

export interface KnowledgeBuildResultSummary {
  additions: number
  modifications: number
  replacements: number
  expirations: number
  unchanged: number
}

export interface KnowledgeBuildTask {
  task_id: string
  name: string
  status: KnowledgeBuildTaskStatus
  build_mode: 'INITIAL' | 'REBUILD'
  semantic_contract_version: string
  pipeline_version: string
  model_scene: string
  config_hash: string
  rebuild_reason: string | null
  created_by: string
  units: KnowledgeBuildTaskUnit[]
  processed_units: number
  result_change_set_id: string | null
  result_summary: Partial<KnowledgeBuildResultSummary>
  issue_count: number
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ChangeSetItem {
  item_id: string
  change_type: ChangeItemType
  rule_id: string
  unit_id: string
  doc_id: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ai_recommendation: string
  reason: string
  evidence_ids: string[]
  quality_checks: string[]
  risk_level: RiskLevel
  impact_scope: Record<string, unknown>
  needs_human: boolean
  compile_run_id?: string | null
  canonical_rule?: { rule_id: string } | null
}

export type SemanticProposalType = 'metric' | 'value' | 'dimension'
export type SemanticProposalStatus = 'proposed' | 'reviewing' | 'accepted' | 'published' | 'rejected' | 'stale' | 'superseded'
export type SemanticProposalTrigger = 'EXTRACTION_UNKNOWN' | 'DEMAND_GAP' | 'DATA_SCAN' | 'DERIVATION_PATTERN' | 'CONFLICT_PARTITION'
export type DimensionReviewConclusion =
  | 'new_dimension'
  | 'metric_split_required'
  | 'temporal_version'
  | 'value_normalization'
  | 'extraction_incomplete'
  | 'insufficient_evidence'
  | 'rejected'

export interface ConflictPartitionEvidence {
  trigger_source: 'CONFLICT_PARTITION'
  document_id: string
  extraction_snapshot_id: string
  extraction_contract_version: string
  identity_signature: {
    known_values: Record<string, string>
    unknown_fields: string[]
  }
  conflict_values: Array<{
    semantic_type: string
    canonical_value: string
    canonical_unit: string | null
    raw_value: string
  }>
  partition_mappings: Array<{
    canonical_phrase: string
    display_phrase: string
    canonical_value: string
    rule_ids: string[]
    source_entity_ids: string[]
  }>
  coverage: string | number
  exclusivity: string | number
  evidence_grade: 'single_observation' | 'repeated_within_document'
  rule_ids: string[]
  source_clause_ids: string[]
  evidence_texts: string[]
  unknown_identity_fields: string[]
  competing_axis_candidates: string[]
  diagnosis: string
}

export interface DimensionCandidateProposal {
  fingerprint: string
  proposal_kind: 'new_dimension'
  trigger_source: 'CONFLICT_PARTITION'
  suggested_name: string | null
  suggested_code: string | null
  semantic_type: 'Enum'
  metric_role: 'dimension'
  candidate_values: Array<{ code: string | null; label: string; aliases: string[] }>
  evidence: ConflictPartitionEvidence
  evidence_grade: 'single_observation' | 'repeated_within_document'
  naming_status: 'resolved' | 'manual_required'
  status: 'proposed'
}

export interface SemanticProposalEvidence {
  source_ref: string
  excerpt?: string | null
  doc_id?: string | null
  unit_id?: string | null
  extraction_id?: string | null
  occurrence_count: number
  gap_signature?: string | null
  representative_questions?: string[]
  table_name?: string | null
  field_name?: string | null
  sample_values?: string[]
  non_null_rate?: number | null
  distinct_count?: number | null
  base_metric_code?: string | null
  operator?: string | null
  observations?: string[]
  rule_ids?: string[]
}

export interface SemanticProposalMapping {
  metric_code: string
  domain_code: string
  binding_id: string
  source_value: string
  standard_value: string
}

export interface SemanticProposal {
  proposal_id: string
  fingerprint: string
  proposal_type: SemanticProposalType
  trigger_source: SemanticProposalTrigger
  status: SemanticProposalStatus
  concept: string
  object_code: string
  axis_metric_code: string | null
  metric_draft: {
    metric_code: string
    object_code: string
    name: string
    definition: string | null
    metric_type: string
    semantic_type: string | null
    unit: string | null
    value_domain: string | null
    metric_kind: string
    indexed: boolean
    extraction_hint: string | null
    schema_version: number
  } | null
  value_draft: {
    domain_code: string
    standard_value: string
    evidence: string
    source_ref: string
  } | null
  suggested_mappings: SemanticProposalMapping[]
  mapping_only: boolean
  formula: Record<string, unknown> | null
  dimension_candidate?: DimensionCandidateProposal | null
  review_conclusion?: DimensionReviewConclusion | null
  last_observed_at?: string | null
  evidence: SemanticProposalEvidence[]
  confidence: number
  occurrence_count: number
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  created_at: string
  updated_at: string
}

export interface SourceUnitRevision {
  doc_id: string
  doc_title: string
  unit_id: string
  unit_revision_id: string
  path: string[]
}

export interface KnowledgeChangeSet {
  change_set_id: string
  source_document_version_id: string
  doc_id: string
  doc_title: string
  build_task_id: string | null
  source_units: SourceUnitRevision[]
  semantic_contract_version: string | null
  supersedes_candidate_id: string | null
  status: 'DRAFT' | 'NEEDS_DECISION' | 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED' | 'RETURNED' | 'PUBLISHED' | 'FAILED'
  summary: { additions: number; modifications: number; replacements: number; expirations: number; unchanged: number }
  items: ChangeSetItem[]
  quality_report: {
    source_fidelity: number | null
    structural_completeness: number | null
    semantic_consistency: number | null
    rule_consistency: number | null
  }
  risk_summary: Record<string, number>
  blockers: Array<Record<string, unknown>>
  review_decision: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface PublishedSnapshot {
  snapshot_id: string
  doc_id: string | null
  policy_scope: Record<string, unknown>
  semantic_contract_version: string | null
  rules_collection: string
  facts_collection: string
  source_change_set_id: string | null
  immutable: boolean
  published_at: string
  published_by: string
  rollback_of: string | null
  replaced_by: string | null
}

export const listChangeSets = (docId = '') =>
  request<KnowledgeChangeSet[]>(`${WORKBENCH_API}/change-sets${docId ? `?doc_id=${encodeURIComponent(docId)}` : ''}`)

export const getChangeSet = (changeSetId: string) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}`)

export const listEligibleKnowledgeUnits = () =>
  request<EligibleKnowledgeUnit[]>(`${WORKBENCH_API}/knowledge-build/eligible-units`)

export const preflightKnowledgeBuild = (body: CreateKnowledgeBuildTaskRequest) =>
  request<KnowledgeBuildPreflight>(`${WORKBENCH_API}/knowledge-build/preflight`, json('POST', body))

export const listKnowledgeBuildTasks = () =>
  request<KnowledgeBuildTask[]>(`${WORKBENCH_API}/knowledge-build/tasks`)

export const getKnowledgeBuildTask = (taskId: string) =>
  request<KnowledgeBuildTask>(`${WORKBENCH_API}/knowledge-build/tasks/${encodeURIComponent(taskId)}`)

export const createKnowledgeBuildTask = (body: CreateKnowledgeBuildTaskRequest) =>
  request<KnowledgeBuildTask>(`${WORKBENCH_API}/knowledge-build/tasks`, json('POST', body))

/** @deprecated Use createKnowledgeBuildTask() with exact unit revisions instead. */
export const buildChangeSet = (docId: string) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/build-from-doc`, json('POST', { doc_id: docId }))

export const submitChangeSetReview = (changeSetId: string, reviewer: string, note?: string | null) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/submit-review`, json('POST', { reviewer, note }))

export const approveChangeSet = (changeSetId: string, reviewer: string, note?: string | null) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/approve`, json('POST', { reviewer, note }))

export const returnKnowledgeReview = (changeSetId: string, reviewer: string, note?: string | null) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/return`, json('POST', { reviewer, note }))

export const rejectChangeSet = (changeSetId: string, reviewer: string, note?: string | null) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/reject`, json('POST', { reviewer, note }))

export const reprocessChangeSet = (changeSetId: string) =>
  request<KnowledgeChangeSet>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/reprocess`, { method: 'POST' })

// —— 迭代 18：知识审核重新提取（修改提示词 / 换大模型 / 单条·批量）——

export type PromptMode = 'schema' | 'legacy' | 'custom'

export interface ExtractionOverride {
  prompt_mode?: PromptMode
  custom_prompt?: string | null
  model_name?: string | null
  max_tokens?: number | null
  operator?: string | null
}

export interface ExtractionMetricSummary {
  code: string
  name: string
  kind: string
  extraction_hint?: string | null
  value_domain?: string | null
}

export interface ExtractionConfig {
  default_prompt_mode: PromptMode
  default_model: string
  default_max_tokens: number
  schema_version: number
  metrics: ExtractionMetricSummary[]
  note: string
}

export interface ModelOption {
  model_name: string
  display_name: string
  available: boolean
}

export interface PromptPreview {
  prompt: string
  schema_version: number
  field_count: number
}

export interface ReextractItemResult {
  extraction_id: string
  item_ids: string[]
  success: boolean
  error?: string | null
  model_used?: PromptMode | null
  prompt_mode_used?: PromptMode | null
  new_knowledge_count: number
}

export interface ReextractReport {
  change_set_id: string
  total: number
  succeeded: number
  failed: number
  items: ReextractItemResult[]
  override_applied: ExtractionOverride | null
}

export const getExtractionConfig = () =>
  request<ExtractionConfig>(`${WORKBENCH_API}/extraction-config`)

export const listExtractionModels = () =>
  request<ModelOption[]>(`${WORKBENCH_API}/extraction-config/models`)

export const getPromptPreview = (params: { prompt_mode: PromptMode; custom_prompt?: string }) => {
  const search = new URLSearchParams({ prompt_mode: params.prompt_mode })
  if (params.custom_prompt) search.set('custom_prompt', params.custom_prompt)
  return request<PromptPreview>(`${WORKBENCH_API}/extraction-config/prompt-preview?${search.toString()}`)
}

export const reextractChangeSet = (
  changeSetId: string,
  body: { item_ids?: string[]; override?: ExtractionOverride },
) =>
  request<ReextractReport>(
    `${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/reextract`,
    json('POST', body),
  )

export interface TestExtractResult {
  change_set_id: string
  item_id: string
  extraction_id: string
  fact_count: number
  rule_count: number
  fields_extracted: string[]
  facts: Array<{
    fact_text: string
    rules?: Record<string, unknown>[]
  }>
  override_applied: ExtractionOverride | null
}

export const testExtractChangeSetItem = (
  changeSetId: string,
  body: { item_id: string; override?: ExtractionOverride },
) =>
  request<TestExtractResult>(
    `${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/test-extract`,
    json('POST', body),
  )

export interface RuleDetail {
  rule: KnowledgeItem
  unit: { unit_id: string; path: string[]; source_text: string; status: string }
  document: { doc_id: string; doc_title: string; contract_version: string | null }
  change_set_id: string | null
  review_status: string | null
}

export const getRuleDetail = (ruleId: string) =>
  request<RuleDetail>(`${WORKBENCH_API}/rules/${encodeURIComponent(ruleId)}`)

export type CompileStage =
  | 'INPUT_SNAPSHOT'
  | 'LLM_EXTRACTION'
  | 'CANONICALIZE'
  | 'COMPOSE'
  | 'RESOLVE'
  | 'DERIVE'
  | 'VALIDATE'
  | 'PUBLISH'
  | 'LEGACY_IMPORT'

export type CompileStatus = 'RUNNING' | 'PASS' | 'WARN' | 'REVIEW' | 'FAIL'

export interface ValidationIssue {
  issue_id: string
  severity: 'WARN' | 'REVIEW' | 'FAIL'
  code: string
  stage: CompileStage
  fact_id: string | null
  rule_id: string | null
  message: string
  recommended_action: string
}

export interface CompileStep {
  step_id: string
  run_id: string
  sequence_no: number
  stage: CompileStage
  status: CompileStatus
  input_payload: Record<string, unknown>
  output_payload: Record<string, unknown>
  issues: ValidationIssue[]
  error: Record<string, unknown> | null
  duration_ms: number
  started_at: string
  finished_at: string | null
}

export interface RuleCompilationTrace {
  rule_id: string
  rule: {
    rule_id: string
    subject: string
    population: string | null
    conditions: Record<string, unknown>
    result: Record<string, unknown>
    source_type: 'DIRECT' | 'DERIVED'
    evidence: string[]
    dependencies: string[]
    formula: Record<string, unknown> | null
    compiler_version: string
    rule_version: number
    status: CompileStatus
  } | null
  run: {
    run_id: string
    document_id: string
    unit_id: string
    extraction_id: string
    raw_input: Record<string, unknown>
    llm_output: Record<string, unknown>
    model_name?: string | null
    prompt_version?: string | null
    schema_version?: string | null
    compiler_version: string
    status: CompileStatus
    metrics: Record<string, unknown>
    error: Record<string, unknown> | null
    started_at: string
    finished_at: string | null
  }
  raw_input: Record<string, unknown>
  llm_output: Record<string, unknown>
  steps: CompileStep[]
  issues: ValidationIssue[]
  publication: { release_id: string; status: string; published_at: string | null } | null
  history: Array<{
    run_id: string
    rule_version: number | null
    status: CompileStatus
    compiler_version: string
    started_at: string
    finished_at: string | null
  }>
}

export const getRuleCompilationTrace = (ruleId: string, runId?: string | null) =>
  request<RuleCompilationTrace>(
    `${WORKBENCH_API}/rules/${encodeURIComponent(ruleId)}/trace${
      runId ? `?run_id=${encodeURIComponent(runId)}` : ''
    }`,
  )

export interface DecisionTask {
  task_id: string
  task_type: string
  question: string
  recommended_option: Record<string, unknown>
  alternatives: Array<Record<string, unknown>>
  evidence: Record<string, unknown>
  risk_level: RiskLevel
  affected_items: Record<string, unknown>
  blocking_scope: string | null
  status: 'PENDING' | 'RESOLVED' | 'SKIPPED'
  decision: Record<string, unknown> | null
  created_at: string
  resolved_at: string | null
}

export const listDecisionTasks = (status = '', taskType = '', scope = '') => {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (taskType) params.set('task_type', taskType)
  if (scope) params.set('scope', scope)
  const query = params.toString()
  return request<DecisionTask[]>(`${WORKBENCH_API}/decision-tasks${query ? `?${query}` : ''}`)
}

export const generateDecisionTasks = (changeSetId: string) =>
  request<DecisionTask[]>(`${WORKBENCH_API}/change-sets/${encodeURIComponent(changeSetId)}/generate-tasks`, { method: 'POST' })

export const resolveDecisionTask = (taskId: string, decision: Record<string, unknown>) =>
  request<DecisionTask>(`${WORKBENCH_API}/decision-tasks/${encodeURIComponent(taskId)}/resolve`, json('POST', { decision }))

export interface GovernanceDashboard {
  documents_total: number
  change_sets_total: number
  knowledge_total: number
  rules_total: number
  rules_pending_review: number
  rules_approved: number
  compilation_by_status: Record<string, number>
  tasks_pending: number
  tasks_by_type: Record<string, number>
  change_sets_by_status: Record<string, number>
  risk_summary: Record<string, number>
  avg_source_fidelity: number | null
  avg_completeness: number | null
}

export const getGovernanceDashboard = () =>
  request<GovernanceDashboard>(`${WORKBENCH_API}/governance/dashboard`)

// —— 治理概览聚合（概览页专用，见 政策知识治理-概览页丰富设计-V1.0 §6）——

export interface PipelineSummary {
  documents_count: number
  documents_raw: number
  units_count: number
  units_audited: number
  units_pending: number
  extractions_count: number
  extractions_draft: number
  extractions_reviewed: number
  extractions_published: number
}

export const getPipelineSummary = () =>
  request<PipelineSummary>(`${PIPELINE_API}/summary`)

export interface PipelineExtractionItem {
  confidence?: number | null
}

export interface PipelineExtractionPage {
  items: PipelineExtractionItem[]
  total: number
}

export const listPipelineExtractions = (page = 1, pageSize = 100) =>
  request<PipelineExtractionPage>(`${PIPELINE_API}/extractions?page=${page}&page_size=${pageSize}`)

export interface PolicyKnowledgeStats {
  total: number
}

export const getPolicyKnowledgeStats = () =>
  request<PolicyKnowledgeStats>('/api/v1/medical-insurance-ai-agent/policy-knowledge/stats')

export interface SemanticSummary {
  metrics_count: number
  mapped_count: number
  unmapped_count: number
  mapping_rate: number
}

export const getSemanticSummary = () =>
  request<SemanticSummary>('/api/v1/medical-insurance-ai-agent/semantic/summary')

export const listPublishedSnapshots = () =>
  request<PublishedSnapshot[]>(`${WORKBENCH_API}/published`)

export const getActiveSnapshot = () =>
  request<PublishedSnapshot>(`${WORKBENCH_API}/published/active`)

export const bindExistingMetric = (source: MetricDraftSource, metricCode: string) =>
  request(`${ALIGNMENT_API}/bindings`, json('POST', {
    metric_code: metricCode,
    source_type: 'policy_knowledge',
    source_ref: `${source.doc_id}/${source.unit_id}/${source.knowledge_id}`,
    source_field: source.source_field,
    source_version: source.contract_version,
    evidence: source.source_text,
  }))

export const createMetricDraft = (source: MetricDraftSource, metricCode: string, name: string, options: MetricDraftOptions) =>
  request(`${ALIGNMENT_API}/metrics`, json('POST', {
    metric_code: metricCode,
    object_code: 'zcgz',
    name,
    definition: `由政策知识字段“${source.field_name}”提炼，待语义层审核发布。`,
    metric_type: options.metricType,
    semantic_type: options.semanticType,
    unit: options.unit,
    value_domain: options.valueDomain,
    source_binding: {
      metric_code: metricCode,
      source_type: 'policy_knowledge',
      source_ref: `${source.doc_id}/${source.unit_id}/${source.knowledge_id}`,
      source_field: source.source_field,
      source_version: source.contract_version,
      evidence: source.source_text,
    },
  }))

export const proposeStandardValue = (source: MetricDraftSource, domainCode: string, value: string) =>
  request(`${ALIGNMENT_API}/standard-values`, json('POST', {
    domain_code: domainCode,
    standard_value: value,
    evidence: source.source_text,
    source_ref: `${source.doc_id}/${source.unit_id}/${source.knowledge_id}/${source.source_field}`,
  }))

export const listTestCases = () => request<PolicyTestCase[]>(`${WORKBENCH_API}/test-cases`)
export const saveTestCase = (testCase: Partial<PolicyTestCase>) =>
  request<PolicyTestCase>(`${WORKBENCH_API}/test-cases`, json('POST', testCase))
export const createRelease = (body: { release_id: string; contract_version: string; config_hash: string; source_change_set_id?: string | null }) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases`, json('POST', body))
export const listReleases = () => request<KnowledgeRelease[]>(`${WORKBENCH_API}/releases`)
export const buildRelease = (releaseId: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/build`, { method: 'POST' })
export const runQuality = (releaseId: string) =>
  request<QualityRun>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/test`, json('POST', QUALITY_RUN_CONFIG))
export const getActiveRelease = () => request<KnowledgeRelease>(`${WORKBENCH_API}/releases/active`)
/** @deprecated Legacy compatibility for the unchanged policy test page; governed releases must use promoteGovernedRelease(). */
export const promoteRelease = (releaseId: string, reviewedBy: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/promote-legacy`, json('POST', { reviewed_by: reviewedBy }))
export const promoteGovernedRelease = (releaseId: string, reviewedBy: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/promote`, json('POST', { reviewed_by: reviewedBy }))
export const rollbackRelease = (releaseId: string, reviewedBy: string) =>
  request<KnowledgeRelease>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/rollback`, json('POST', { reviewed_by: reviewedBy }))
export const listQualityCaseResults = (runId: string) =>
  request<QualityCaseResult[]>(`${WORKBENCH_API}/quality-runs/${encodeURIComponent(runId)}/case-results`)

export interface QualityCaseResult {
  run_id: string
  target: 'candidate' | 'baseline'
  case_id: string
  repeat_index: number
  result_knowledge_ids: string[]
  score: number
  passed: boolean
  diagnostics: Record<string, unknown>
}

export interface QualityRunReport {
  run: QualityRun
  case_results: QualityCaseResult[]
}

export const getLatestReleaseQuality = (releaseId: string) =>
  request<QualityRunReport>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/quality/latest`)

export const getReleaseGateStatus = (releaseId: string) =>
  request<ReleaseGateStatus>(`${WORKBENCH_API}/releases/${encodeURIComponent(releaseId)}/gate-status`)

export const searchPolicyKnowledge = (body: Record<string, unknown>) =>
  request<{ groups: Array<Record<string, unknown>>; total_groups: number }>(
    `${PIPELINE_API}/rules/search`, json('POST', body)
  )
