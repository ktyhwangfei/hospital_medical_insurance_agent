// Tool 可视化管理与 Workflow 编排 — 只读 API 客户端（不新增鉴权面）。
// DTO 字段与后端 src/runtime/workflow/catalog_view.py 逐字段对齐（snake_case 直传）。
import { requestJson } from './api-client'

// 单个输入/输出字段的契约信息（与后端 ToolDefinition.input_schema/output_schema 对齐）。
export interface ToolFieldInfoDto {
  type: string
  required?: boolean
  description: string
}

export interface ToolSummaryDto {
  tool_id: string
  name: string
  description: string
  contract_kind: string
  target_ref: string
  risk_level: string
  status: string
  semantic_version: string
  bound: boolean
  tags: string[]
  input_schema: Record<string, ToolFieldInfoDto>
  output_schema: Record<string, ToolFieldInfoDto>
  execution_detail: string
}

export interface ToolCatalogDto {
  items: ToolSummaryDto[]
}

export interface MissingEvidenceRuleSummaryDto {
  field_name: string
  clarify_message: string
}

export interface WorkflowStepSummaryDto {
  step_id: string
  tool_id: string
  description: string
  tool_bound: boolean
  input_mapping: Record<string, string>
}

export interface WorkflowSummaryDto {
  workflow_id: string
  name: string
  description: string
  intent_keywords: string[]
  missing_evidence_rules: MissingEvidenceRuleSummaryDto[]
  steps: WorkflowStepSummaryDto[]
}

export interface WorkflowCatalogDto {
  items: WorkflowSummaryDto[]
}

export function listTools(): Promise<ToolCatalogDto> {
  return requestJson<ToolCatalogDto>('/tool-registry/tools')
}

export function listWorkflows(): Promise<WorkflowCatalogDto> {
  return requestJson<WorkflowCatalogDto>('/workflow-catalog/workflows')
}
