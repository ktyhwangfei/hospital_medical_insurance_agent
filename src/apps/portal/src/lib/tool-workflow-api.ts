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
  node_type: 'tool' | 'domain' | 'decision' | 'output'
  tool_id?: string | null
  handler_id?: string | null
  handler_version?: string | null
  source_ref?: string | null
  condition_ref?: string | null
  expected_value?: unknown
  match_step_id?: string | null
  default_step_id?: string | null
  description: string
  bound: boolean
  input_mapping: Record<string, string>
}

export interface WorkflowSummaryDto {
  workflow_id: string
  enabled?: boolean
  keyword_source?: string
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

// ── Workflow 治理配置写入（院区个性化落配置层，不改代码重发版）──
// 鉴权与 ops-api / 可信问题库同模式：sessionStorage → dev 环境变量 token。

function workflowToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('workflow-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_WORKFLOW_TOKEN || null
}

export function hasWorkflowWritePermission(): boolean {
  const token = workflowToken()
  if (!token) return process.env.NODE_ENV !== 'production'
  try {
    const payload = token.replace(/^Bearer\s+/i, '').split('.')[1]
    const base64 = payload
      .replace(/-/g, '+')
      .replace(/_/g, '/')
      .padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const permissions = JSON.parse(atob(base64)).permissions
    return Array.isArray(permissions) && permissions.includes('workflow:write')
  } catch {
    return false
  }
}

// intent_keywords 省略 = 保持该行已有词表；null = 清除覆盖回落代码默认。
export interface WorkflowConfigPayload {
  enabled: boolean
  intent_keywords?: string[] | null
}

export interface EffectiveWorkflowConfigDto {
  workflow_id: string
  enabled: boolean
  intent_keywords: string[]
  source: string
}

export function updateWorkflowConfig(
  workflowId: string,
  payload: WorkflowConfigPayload,
): Promise<EffectiveWorkflowConfigDto> {
  const token = workflowToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = token.startsWith('Bearer ') ? token : `Bearer ${token}`
  return requestJson<EffectiveWorkflowConfigDto>(
    `/workflow-catalog/workflows/${encodeURIComponent(workflowId)}/config`,
    { method: 'PUT', headers, body: JSON.stringify(payload) },
  )
}
