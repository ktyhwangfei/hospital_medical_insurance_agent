// Skill 草稿与生命周期管理 API 客户端（P7/P8）
// 对接后端 infra_skill_routes 的草稿 CRUD / 复制 / 导入 / 校验 / 包预览 / 物化 / 生命周期端点

import { API_PREFIX, parseError, requestJson } from './api-client'
import { ApiClientError } from './types'
import type {
  SkillDraftResponse,
  SkillDraftListResponse,
  SkillDraftCreateRequest,
  SkillDraftCopyRequest,
  SkillDraftSaveRequest,
  SkillValidationResponse,
  SkillPackagePreviewResponse,
  SkillMaterializeRequest,
  SkillMaterializeResponse,
  SkillDefinitionResponse,
  SkillLifecycleTransitionRequest,
  SkillInputSelectorResponse,
  SkillInputValidationResponse,
  SkillQueryPlanResponse,
  SkillAIGenerateRequest,
  SkillAIGenerationProposal,
  SkillAIAcceptRequest,
  SkillAIOptimizeRequest,
  SkillAIOptimizationProposal,
} from './types'

const DEV_SKILL_CONTROL_TOKEN =
  'test.eyJzdWIiOiJwb3J0YWwtZGV2ZWxvcGVyIiwicm9sZXMiOlsiZGV2ZWxvcGVyIl0sInBlcm1pc3Npb25zIjpbInNraWxsOnJlbGVhc2U6dGVzdCIsInNraWxsOmV2YWx1YXRlIl0sImV4cCI6NDEwMjQ0NDgwMH0.signature'

function skillControlHeaders(idempotencyKey?: string): HeadersInit {
  const headers: Record<string, string> = {}
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
  if (typeof window !== 'undefined') {
    const token =
      window.sessionStorage.getItem('skill-control-token') ??
      (process.env.NODE_ENV !== 'production' ? DEV_SKILL_CONTROL_TOKEN : null)
    if (token) headers.Authorization = `Bearer ${token}`
  }
  return headers
}

// ── 草稿 CRUD ──────────────────────────────────────────────────

export async function generateSkillAIProposal(
  request: SkillAIGenerateRequest,
): Promise<SkillAIGenerationProposal> {
  return requestJson<SkillAIGenerationProposal>('/infra-skills/ai-generate', {
    method: 'POST',
    headers: skillControlHeaders(),
    body: JSON.stringify(request),
  })
}

export async function acceptSkillAIProposal(
  proposal: SkillAIGenerationProposal,
  idempotencyKey: string,
): Promise<SkillDraftResponse> {
  const request: SkillAIAcceptRequest = {
    generation_id: proposal.generation_id,
    proposal_hash: proposal.proposal_hash,
    skill_id: proposal.structured_config.basic.skill_id,
    skill_name: proposal.structured_config.basic.skill_name,
    structured_config: proposal.structured_config,
    raw_files: proposal.raw_files,
    provenance: proposal.provenance,
  }
  return requestJson<SkillDraftResponse>('/infra-skills/drafts/from-ai', {
    method: 'POST',
    headers: skillControlHeaders(idempotencyKey),
    body: JSON.stringify(request),
  })
}

export async function optimizeSkillAIDraft(
  draftId: string,
  request: SkillAIOptimizeRequest,
): Promise<SkillAIOptimizationProposal> {
  return requestJson<SkillAIOptimizationProposal>(
    `/infra-skills/drafts/${encodeURIComponent(draftId)}/ai-optimize`,
    {
      method: 'POST',
      headers: skillControlHeaders(),
      body: JSON.stringify(request),
    },
  )
}

export async function listSkillDrafts(): Promise<SkillDraftListResponse> {
  return requestJson<SkillDraftListResponse>('/infra-skills/drafts')
}

export async function getSkillDraft(draftId: string): Promise<SkillDraftResponse> {
  return requestJson<SkillDraftResponse>(
    `/infra-skills/drafts/${encodeURIComponent(draftId)}`,
  )
}

export async function createSkillDraft(
  request: SkillDraftCreateRequest,
  idempotencyKey: string,
): Promise<SkillDraftResponse> {
  return requestJson<SkillDraftResponse>('/infra-skills/drafts', {
    method: 'POST',
    headers: skillControlHeaders(idempotencyKey),
    body: JSON.stringify(request),
  })
}

export async function saveSkillDraft(
  draftId: string,
  request: SkillDraftSaveRequest,
): Promise<SkillDraftResponse> {
  return requestJson<SkillDraftResponse>(
    `/infra-skills/drafts/${encodeURIComponent(draftId)}`,
    { method: 'PATCH', headers: skillControlHeaders(), body: JSON.stringify(request) },
  )
}

export async function deleteSkillDraft(
  draftId: string,
  expectedRevision: number,
): Promise<void> {
  await requestJson<void>(
    `/infra-skills/drafts/${encodeURIComponent(draftId)}?expected_revision=${expectedRevision}`,
    { method: 'DELETE', headers: skillControlHeaders() },
  )
}

export async function copySkill(
  request: SkillDraftCopyRequest,
  idempotencyKey: string,
): Promise<SkillDraftResponse> {
  return requestJson<SkillDraftResponse>(
    `/infra-skills/${encodeURIComponent(request.source_skill_id)}/copy`,
    { method: 'POST', headers: skillControlHeaders(idempotencyKey), body: JSON.stringify(request) },
  )
}

// ── 导入 ───────────────────────────────────────────────────────

export async function importSkillZip(
  file: File,
  idempotencyKey: string,
): Promise<SkillDraftResponse> {
  const buf = await file.arrayBuffer()
  return requestJson<SkillDraftResponse>(
    `/infra-skills/drafts/import?source=zip`,
    {
      method: 'POST',
      headers: {
        ...skillControlHeaders(idempotencyKey),
        'Content-Type': 'application/zip',
        filename: file.name,
      },
      body: buf,
    },
  )
}

// ── 校验 / 包预览 ──────────────────────────────────────────────

export async function validateSkillDraft(draftId: string): Promise<SkillValidationResponse> {
  return requestJson<SkillValidationResponse>(
    `/infra-skills/drafts/${encodeURIComponent(draftId)}/validate`,
    { method: 'POST', headers: skillControlHeaders() },
  )
}

export async function previewSkillPackage(
  draftId: string,
): Promise<SkillPackagePreviewResponse> {
  return requestJson<SkillPackagePreviewResponse>(
    `/infra-skills/drafts/${encodeURIComponent(draftId)}/package-preview`,
    { method: 'POST' },
  )
}

// ── 物化 ───────────────────────────────────────────────────────

export async function materializeSkill(
  request: SkillMaterializeRequest,
  idempotencyKey: string,
): Promise<SkillMaterializeResponse> {
  return requestJson<SkillMaterializeResponse>(
    `/infra-skills/drafts/${encodeURIComponent(request.draft_id)}/materialize`,
    { method: 'POST', headers: skillControlHeaders(idempotencyKey), body: JSON.stringify(request) },
  )
}

// ── 生命周期 ───────────────────────────────────────────────────

export async function getSkillDefinition(
  skillId: string,
): Promise<SkillDefinitionResponse> {
  return requestJson<SkillDefinitionResponse>(
    `/infra-skills/definitions/${encodeURIComponent(skillId)}`,
  )
}

export async function disableSkill(
  skillId: string,
  request: SkillLifecycleTransitionRequest,
): Promise<SkillDefinitionResponse> {
  return requestJson<SkillDefinitionResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/disable`,
    { method: 'POST', headers: skillControlHeaders(), body: JSON.stringify(request) },
  )
}

export async function restoreSkill(
  skillId: string,
  request: SkillLifecycleTransitionRequest,
): Promise<SkillDefinitionResponse> {
  return requestJson<SkillDefinitionResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/restore`,
    { method: 'POST', headers: skillControlHeaders(), body: JSON.stringify(request) },
  )
}

export async function archiveSkill(
  skillId: string,
  request: SkillLifecycleTransitionRequest,
): Promise<SkillDefinitionResponse> {
  return requestJson<SkillDefinitionResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/archive`,
    { method: 'POST', headers: skillControlHeaders(), body: JSON.stringify(request) },
  )
}

// ── 语义层输入指标 ─────────────────────────────────────────────

export async function getSkillInputSelector(): Promise<SkillInputSelectorResponse> {
  return requestJson<SkillInputSelectorResponse>('/semantic/skill-inputs/selector')
}

export async function validateSkillInputs(
  metricCodes: string[],
): Promise<SkillInputValidationResponse> {
  return requestJson<SkillInputValidationResponse>('/semantic/skill-inputs/validate', {
    method: 'POST',
    body: JSON.stringify({ metric_codes: metricCodes }),
  })
}

export async function getSkillInputQueryPlan(
  metricCodes: string[],
): Promise<SkillQueryPlanResponse> {
  return requestJson<SkillQueryPlanResponse>('/semantic/skill-inputs/query-plan', {
    method: 'POST',
    body: JSON.stringify({ metric_codes: metricCodes }),
  })
}

export { ApiClientError, parseError, API_PREFIX }
