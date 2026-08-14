import { requestJson } from './api-client'

export type PromptSourceKind = 'code' | 'yaml' | 'dynamic'
export type GatewayStatus = 'routed' | 'direct' | 'unknown'
export type ManagementStatus = 'source_managed' | 'needs_migration' | 'needs_verification'
export type ProviderType = 'openai_compatible'
export type CredentialStatus = 'configured' | 'missing'

export interface PromptGovernanceItem {
  prompt_id: string
  name: string
  source_path: string
  source_kind: PromptSourceKind
  scene: string | null
  model_type: string
  gateway_status: GatewayStatus
  management_status: ManagementStatus
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

export async function getModelGovernanceSnapshot(): Promise<ModelGovernanceSnapshot> {
  return requestJson<ModelGovernanceSnapshot>('/model-governance/snapshot')
}
