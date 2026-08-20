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

export type GovernanceAssetType = 'prompt' | 'model_profile' | 'route_rule'
export type GovernanceDraftStatus = 'editing' | 'validated' | 'review_pending' | 'approved'
export type GovernanceEnvironment = 'dev' | 'test'
export type GovernanceReleaseStatus = 'active' | 'retired'

export interface PromptVariable {
  name: string
  required: boolean
  description: string
}

export interface PromptAssetContent {
  asset_type: 'prompt'
  asset_id: string
  name: string
  scene: string
  model_type: string
  system_prompt: string
  user_prompt_template: string
  variables: PromptVariable[]
  output_mode: 'text' | 'json'
}

export interface ModelProfileAssetContent {
  asset_type: 'model_profile'
  asset_id: string
  name: string
  provider_id: 'openai_compatible'
  base_url: string
  model_name: string
  credential_ref: string
  timeout_seconds: number
  temperature: number
  max_tokens: number
  enabled: boolean
}

export interface RouteRuleAssetContent {
  asset_type: 'route_rule'
  asset_id: string
  name: string
  scene: string
  model_type: string
  profile_id: string
  fallback_profile_ids: string[]
  enabled: boolean
}

export type GovernanceAssetContent =
  | PromptAssetContent
  | ModelProfileAssetContent
  | RouteRuleAssetContent

export type GovernanceBaseline = GovernanceAssetContent & {
  runtime_status: 'fallback_static'
}

export interface ModelCredentialInput {
  credential_id: string
  api_key: string
}

export interface GovernanceValidationIssue {
  code: string
  message: string
  path: string
}

export interface GovernanceDraft {
  draft_id: string
  asset_id: string
  asset_type: GovernanceAssetType
  content: GovernanceAssetContent
  status: GovernanceDraftStatus
  revision: number
  validation_issues: GovernanceValidationIssue[]
  created_by: string
  last_edited_by: string
  created_at: string
  updated_at: string
}

export interface GovernanceAssetPreview {
  asset_type: GovernanceAssetType
  asset_id: string
  rendered_system_prompt: string | null
  rendered_user_prompt: string | null
  profile_id: string | null
  fallback_profile_ids: string[]
  temperature: number | null
  max_tokens: number | null
}

export interface GovernanceRelease {
  release_id: string
  asset_id: string
  asset_type: GovernanceAssetType
  version_id: string
  source_draft_id: string | null
  environment: GovernanceEnvironment
  status: GovernanceReleaseStatus
  previous_release_id: string | null
  created_by: string
  created_at: string
  retired_at: string | null
}

export interface GovernanceVersion {
  version_id: string
  asset_id: string
  asset_type: GovernanceAssetType
  version_number: number
  content: GovernanceAssetContent
  content_hash: string
  approval_id: string
  created_by: string
  created_at: string
}

export interface GovernanceVersionsResult {
  versions: GovernanceVersion[]
  releases: GovernanceRelease[]
}

export interface GovernanceConnectionTest {
  status: 'success' | 'failure'
  latency_ms: number
  safe_message: string
  tested_at: string
  content_hash: string
}

export interface ModelListProbeResult {
  models: string[]
  safe_message: string
}

export interface PublishedGovernanceAsset {
  asset_id: string
  asset_type: GovernanceAssetType
  version_id: string
  release_id: string
  content_hash: string
  content: GovernanceAssetContent
  runtime_status: 'governed_active' | 'fallback_static'
}

export interface GovernanceAssetsResult {
  baselines: GovernanceBaseline[]
  drafts: GovernanceDraft[]
  published: PublishedGovernanceAsset[]
}

export interface GovernanceImportResult {
  drafts: GovernanceDraft[]
  created_count: number
  skipped_count: number
  counts: {
    prompt: number
    model_profile: number
    route_rule: number
  }
}

export interface PublishedGovernanceSnapshot {
  environment: GovernanceEnvironment
  assets: PublishedGovernanceAsset[]
  generated_at: string
}

interface GovernanceEnvelope<T> {
  scenario: 'model_governance'
  status: 'success'
  result: T
}

export const governanceDevIdentities = {
  editor: {
    userId: 'portal-governance-editor',
    permissions: [
      'model_governance:read',
      'model_governance:write',
      'model_governance:publish',
    ],
  },
  reviewer: {
    userId: 'portal-governance-reviewer',
    permissions: ['model_governance:read', 'model_governance:review'],
  },
} as const

export type GovernanceDevIdentity = keyof typeof governanceDevIdentities

function devToken(identity: GovernanceDevIdentity): string {
  const fixture = governanceDevIdentities[identity]
  const payload = window.btoa(JSON.stringify({
    sub: fixture.userId,
    roles: ['information_department'],
    permissions: fixture.permissions,
    exp: 4102444800,
  })).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
  return `test.${payload}.signature`
}

export function selectGovernanceDevIdentity(identity: GovernanceDevIdentity): void {
  window.sessionStorage.setItem('model-governance-token', devToken(identity))
}

function modelGovernanceHeaders(): HeadersInit {
  const headers: Record<string, string> = {}
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('model-governance-token')
      ?? (process.env.NODE_ENV !== 'production' ? devToken('editor') : null)
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

async function governanceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await requestJson<GovernanceEnvelope<T>>(path, {
    ...init,
    headers: modelGovernanceHeaders(),
  })
  return response.result
}

export function getGovernanceAssets(
  environment: GovernanceEnvironment = 'dev',
  assetType?: GovernanceAssetType,
): Promise<GovernanceAssetsResult> {
  const params = new URLSearchParams({ environment })
  if (assetType) params.set('asset_type', assetType)
  return governanceRequest(`/model-governance/assets?${params}`)
}

export function createGovernanceDraft(
  content: GovernanceAssetContent,
  credential?: ModelCredentialInput,
): Promise<GovernanceDraft> {
  return governanceRequest('/model-governance/drafts', {
    method: 'POST',
    body: JSON.stringify({ content, ...(credential ? { credential } : {}) }),
  })
}

export function importCurrentGovernanceAssets(): Promise<GovernanceImportResult> {
  return governanceRequest('/model-governance/import-current', { method: 'POST' })
}

export function updateGovernanceDraft(
  draftId: string,
  content: GovernanceAssetContent,
  expectedRevision: number,
  credential?: ModelCredentialInput,
): Promise<GovernanceDraft> {
  return governanceRequest(`/model-governance/drafts/${encodeURIComponent(draftId)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      content,
      expected_revision: expectedRevision,
      ...(credential ? { credential } : {}),
    }),
  })
}

export function createGovernanceVersion(
  assetId: string,
  environment: GovernanceEnvironment = 'dev',
): Promise<GovernanceDraft> {
  return governanceRequest(
    `/model-governance/assets/${encodeURIComponent(assetId)}/versions?environment=${environment}`,
    { method: 'POST' },
  )
}

export function getGovernanceVersions(
  assetId: string,
  environment: GovernanceEnvironment = 'dev',
): Promise<GovernanceVersionsResult> {
  return governanceRequest(
    `/model-governance/assets/${encodeURIComponent(assetId)}/versions?environment=${environment}`,
  )
}

export function testGovernanceConnection(draftId: string): Promise<GovernanceConnectionTest> {
  return governanceRequest(
    `/model-governance/drafts/${encodeURIComponent(draftId)}/test-connection`,
    { method: 'POST' },
  )
}

export function probeModelList(
  baseUrl: string,
  apiKey: string,
  timeoutSeconds = 10,
): Promise<ModelListProbeResult> {
  return governanceRequest('/model-governance/models/probe-list', {
    method: 'POST',
    body: JSON.stringify({
      base_url: baseUrl,
      api_key: apiKey,
      timeout_seconds: timeoutSeconds,
    }),
  })
}

export function deleteGovernanceDraft(
  draftId: string,
  expectedRevision: number,
): Promise<GovernanceDraft> {
  return governanceRequest(
    `/model-governance/drafts/${encodeURIComponent(draftId)}?expected_revision=${expectedRevision}`,
    { method: 'DELETE' },
  )
}

export function validateGovernanceDraft(
  draftId: string,
  expectedRevision: number,
): Promise<GovernanceDraft> {
  return governanceRequest(`/model-governance/drafts/${encodeURIComponent(draftId)}/validate`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  })
}

export function previewGovernanceDraft(
  draftId: string,
  variables: Record<string, string>,
): Promise<GovernanceAssetPreview> {
  return governanceRequest(`/model-governance/drafts/${encodeURIComponent(draftId)}/preview`, {
    method: 'POST',
    body: JSON.stringify({ variables }),
  })
}

export function requestGovernanceReview(
  draftId: string,
  expectedRevision: number,
): Promise<GovernanceDraft> {
  return governanceRequest(`/model-governance/drafts/${encodeURIComponent(draftId)}/request-review`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  })
}

export function approveGovernanceDraft(
  draftId: string,
  expectedRevision: number,
  reason: string,
): Promise<GovernanceDraft> {
  return governanceRequest(`/model-governance/drafts/${encodeURIComponent(draftId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision, reason }),
  })
}

export function publishGovernanceDraft(
  draftId: string,
  expectedRevision: number,
  environment: GovernanceEnvironment,
): Promise<GovernanceRelease> {
  return governanceRequest(`/model-governance/drafts/${encodeURIComponent(draftId)}/publish`, {
    method: 'POST',
    body: JSON.stringify({ expected_revision: expectedRevision, environment }),
  })
}

export async function getGovernanceReleases(
  environment: GovernanceEnvironment = 'dev',
): Promise<GovernanceRelease[]> {
  const result = await governanceRequest<{ releases: GovernanceRelease[] }>(
    `/model-governance/releases?environment=${environment}`,
  )
  return result.releases
}

export function rollbackGovernanceRelease(releaseId: string): Promise<GovernanceRelease> {
  return governanceRequest(`/model-governance/releases/${encodeURIComponent(releaseId)}/rollback`, {
    method: 'POST',
  })
}

export function getPublishedGovernanceSnapshot(
  environment: GovernanceEnvironment = 'dev',
): Promise<PublishedGovernanceSnapshot> {
  return governanceRequest(`/model-governance/published-snapshot?environment=${environment}`)
}
