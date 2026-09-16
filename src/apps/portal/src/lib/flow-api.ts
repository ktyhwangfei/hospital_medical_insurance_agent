// 治理 Flow API 客户端 — Phase 2 画布对接（Phase 0 §3.1 十二端点全集）。
// DTO 字段与后端 src/domain/governed_flow/models.py 逐字段对齐（snake_case 直传）；
// 画布 XYFlow camelCase 映射见 src/components/flow/canvas-dto.ts（契约 §3.3）。
import { requestJson } from './api-client'
import { governanceToken } from './data-governance-api'

// ── 枚举白名单（与后端冻结值一致，勿单侧扩充）──

export type FlowNodeType =
  | 'source' | 'filter' | 'join' | 'aggregate'
  | 'derived_metric' | 'dimension' | 'quality_gate' | 'consumer'

export type FlowStatus = 'draft' | 'validating' | 'pending_review' | 'published' | 'deprecated'

export type AggregateOperator = 'count' | 'count_distinct' | 'sum' | 'avg'

export type FilterOperator =
  | 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte'
  | 'in' | 'not_in' | 'in_or_null' | 'is_null' | 'is_not_null'

export type NullPolicy = 'ignore' | 'fail' | 'zero'
export type ReversalPolicy = 'excluded_by_filter' | 'net'
export type JoinType = 'inner' | 'left'

export type ConsumerKind =
  | 'query_planner' | 'skill' | 'dashboard_card' | 'weekly_report' | 'assistant'

export type QualityCheckType =
  | 'caliber_signoff' | 'identity_assertion' | 'row_count'
  | 'null_rate' | 'freshness' | 'permission'

export type PermissionLevel = 'summary' | 'detail'
export type MaterializationStrategy = 'view'
export type ValidationSeverity = 'blocking' | 'warning'

// ── 值对象 ──

export interface FlowNodePosition { x: number; y: number }

export interface FlowFilterCondition {
  field_code: string
  operator: FilterOperator
  value?: string | number | (string | number)[] | null
  value_domain?: string | null
}

export interface PolicyCarrier {
  doc_number?: string | null
  region_scope?: string | null
  effective_start?: string | null
  effective_end?: string | null
  policy_rule_ref?: string | null
}

export interface AggregateMeasure {
  output_code: string
  source_field: string
  operator: AggregateOperator
  distinct_key?: string | null
  null_policy?: NullPolicy
  reversal_policy?: ReversalPolicy
}

export interface DerivedMetricSpec {
  output_code: string
  expression: string
  dependencies?: string[]
}

export interface DimensionBinding {
  field_code: string
  value_domain?: string | null
  permission_level?: PermissionLevel
}

export interface QualityCheck {
  check_type: QualityCheckType
  params?: Record<string, string | number | (string | number)[]>
  severity?: ValidationSeverity
}

export interface MetricOutputBinding {
  metric_code: string
  name: string
  node_id: string
  policy_definition: string
  policy_carrier?: PolicyCarrier | null
}

export interface SourceContract {
  dataset_code: string
  object_code: string
  fields: string[]
}

// ── 节点判别联合（discriminated on node_type）──

interface FlowNodeBaseDto {
  node_id: string
  name: string
  position?: FlowNodePosition | null
}

export interface SourceNodeDto extends FlowNodeBaseDto {
  node_type: 'source'
  dataset_code: string
  object_code: string
  fields: string[]
}

export interface FilterNodeDto extends FlowNodeBaseDto {
  node_type: 'filter'
  conditions: FlowFilterCondition[]
}

export interface JoinNodeDto extends FlowNodeBaseDto {
  node_type: 'join'
  relation_code: string
  join_type?: JoinType
}

export interface AggregateNodeDto extends FlowNodeBaseDto {
  node_type: 'aggregate'
  group_by?: string[]
  measures: AggregateMeasure[]
}

export interface DerivedMetricNodeDto extends FlowNodeBaseDto {
  node_type: 'derived_metric'
  metrics: DerivedMetricSpec[]
}

export interface DimensionNodeDto extends FlowNodeBaseDto {
  node_type: 'dimension'
  dimensions: DimensionBinding[]
}

export interface QualityGateNodeDto extends FlowNodeBaseDto {
  node_type: 'quality_gate'
  checks: QualityCheck[]
}

export interface ConsumerNodeDto extends FlowNodeBaseDto {
  node_type: 'consumer'
  consumer_kind: ConsumerKind
  consumes: string[]
}

export type FlowNodeDto =
  | SourceNodeDto | FilterNodeDto | JoinNodeDto | AggregateNodeDto
  | DerivedMetricNodeDto | DimensionNodeDto | QualityGateNodeDto | ConsumerNodeDto

export interface FlowEdgeDto {
  edge_id: string
  from_node: string
  to_node: string
}

// ── 聚合根与发布证据 ──

export interface FlowDefinitionDto {
  flow_id: string
  name: string
  owner: string
  status: FlowStatus
  nodes: FlowNodeDto[]
  edges: FlowEdgeDto[]
  source_contracts: SourceContract[]
  metric_outputs: MetricOutputBinding[]
  materialization?: MaterializationStrategy
  revision: number
  content_hash?: string
  published_at?: string | null
  published_by?: string | null
  lineage_refs?: string[]
  consumer_refs?: string[]
}

export interface FlowValidationIssue {
  code: string
  message: string
  node_id?: string | null
  severity: ValidationSeverity
}

export interface FlowValidationReportDto {
  issues: FlowValidationIssue[]
  has_blocking: boolean
}

export interface FlowPublishedRevisionDto {
  revision_id: string
  flow_id: string
  flow_revision: number
  content_hash: string
  semantic_revision: string
  artifact_hash: string
  published_at: string
  published_by: string
  definition: FlowDefinitionDto
}

export interface FlowRevisionViewDto {
  revision: FlowPublishedRevisionDto
  is_active: boolean
}

export interface CompileStepDto {
  step_index: number
  node_id: string
  node_type: FlowNodeType
  description: string
}

export interface CompiledFlowArtifactDto {
  view_name: string
  view_sql: string
  query_plan: CompileStepDto[]
  artifact_hash: string
}

// ── 十二端点（Phase 0 §3.1；乐观锁 expected_revision 必填）──

/** 节点数上限（与后端 T13 加固 MAX_FLOW_NODES 一致；画布面板据此禁用添加） */
export const MAX_FLOW_NODES = 50

export function listFlows(): Promise<FlowDefinitionDto[]> {
  return requestJson('/flow')
}

export function getFlow(flowId: string): Promise<FlowDefinitionDto> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}`)
}

export function createFlow(definition: FlowDefinitionDto): Promise<FlowDefinitionDto> {
  return requestJson('/flow', { method: 'POST', body: JSON.stringify(definition) })
}

export function updateFlow(
  flowId: string,
  definition: FlowDefinitionDto,
  expectedRevision: number,
): Promise<FlowDefinitionDto> {
  return requestJson(
    `/flow/${encodeURIComponent(flowId)}?expected_revision=${expectedRevision}`,
    { method: 'PUT', body: JSON.stringify(definition) },
  )
}

export function deleteFlow(flowId: string, expectedRevision: number): Promise<{ deleted: string }> {
  return requestJson(
    `/flow/${encodeURIComponent(flowId)}?expected_revision=${expectedRevision}`,
    { method: 'DELETE' },
  )
}

export function validateFlow(flowId: string): Promise<FlowValidationReportDto> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}/validate`, { method: 'POST' })
}

export function submitFlowReview(flowId: string): Promise<FlowDefinitionDto> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}/submit-review`, { method: 'POST' })
}

export function publishFlow(flowId: string, publishedBy: string): Promise<FlowPublishedRevisionDto> {
  // publishedBy 参数已废弃：后端从认证主体取发布人（V3.0 治理加固），
  // 这里仅带凭据；请求体字段保留仅为向后兼容（服务端忽略）。
  const headers = new Headers({ 'Content-Type': 'application/json' })
  const token = governanceToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson(`/flow/${encodeURIComponent(flowId)}/publish`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ published_by: '' }),
  })
}

export function rollbackFlow(flowId: string, revisionId: string): Promise<FlowRevisionViewDto> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ revision_id: revisionId }),
  })
}

export function deprecateFlow(flowId: string): Promise<FlowDefinitionDto> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}/deprecate`, { method: 'POST' })
}

export function listFlowRevisions(flowId: string): Promise<FlowRevisionViewDto[]> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}/revisions`)
}

export function previewFlow(flowId: string): Promise<CompiledFlowArtifactDto> {
  return requestJson(`/flow/${encodeURIComponent(flowId)}/preview`)
}
