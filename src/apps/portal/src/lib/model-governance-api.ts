import { requestJson } from './api-client'

export type PromptSourceKind = 'code' | 'yaml' | 'dynamic'
export type GatewayStatus = 'routed' | 'direct' | 'unknown'
export type ManagementStatus = 'source_managed' | 'needs_migration' | 'needs_verification'
export type ProviderType = 'openai_compatible' | 'development_fixture'
export type CredentialStatus = 'configured' | 'missing' | 'not_applicable'

export interface PromptParameters {
  temperature: number | null
  max_tokens: number | null
}

export interface PromptGovernanceItem {
  prompt_id: string
  name: string
  source_path: string
  related_source_paths: string[]
  source_kind: PromptSourceKind
  scene: string | null
  model_type: string
  gateway_status: GatewayStatus
  management_status: ManagementStatus
  declared_parameters: PromptParameters
  route_defaults: PromptParameters
  call_overrides: PromptParameters
  effective_parameters: PromptParameters
  warnings: string[]
}

export interface ModelGovernanceItem {
  model_name: string
  temperature: number
  max_tokens: number
}

export interface ModelRouteGovernanceItem {
  scene: string
  model_type: string
  effective_model: string | null
  explicit: boolean
  fallbacks: string[]
  warnings: string[]
}

export interface ProviderGovernanceItem {
  provider_id: string
  type: ProviderType
  endpoint: string
  credential_status: CredentialStatus
}

export interface ModelGovernanceSnapshot {
  prompts: PromptGovernanceItem[]
  models: ModelGovernanceItem[]
  routes: ModelRouteGovernanceItem[]
  providers: ProviderGovernanceItem[]
  citations: string[]
  uncertainties: string[]
}

interface ModelGovernanceResponse {
  scenario: 'model_governance'
  status: 'success'
  result: ModelGovernanceSnapshot
  citations: Array<Record<string, unknown>>
  tasks: Array<Record<string, unknown>>
  missing_fields: string[]
  uncertainties: string[]
  blocked_actions: string[]
  audit: Record<string, unknown>
}

const DEV_MODEL_GOVERNANCE_TOKEN = 'test.eyJzdWIiOiJwb3J0YWwtbW9kZWwtZ292ZXJuYW5jZS1yZWFkZXIiLCJyb2xlcyI6WyJpbmZvcm1hdGlvbl9kZXBhcnRtZW50Il0sInBlcm1pc3Npb25zIjpbIm1vZGVsX2dvdmVybmFuY2U6cmVhZCJdLCJleHAiOjQxMDI0NDQ4MDB9.signature'

function modelGovernanceHeaders(): HeadersInit {
  const headers: Record<string, string> = {}
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('model-governance-token')
      ?? (process.env.NODE_ENV !== 'production' ? DEV_MODEL_GOVERNANCE_TOKEN : null)
    if (token) headers.Authorization = `Bearer ${token}`
  }
  return headers
}

export async function getModelGovernanceSnapshot(): Promise<ModelGovernanceSnapshot> {
  const response = await requestJson<ModelGovernanceResponse>('/model-governance/snapshot', {
    headers: modelGovernanceHeaders(),
  })
  return response.result
}
