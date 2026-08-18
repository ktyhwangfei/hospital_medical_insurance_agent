'use client'

import { requestJson } from '@/lib/api-client'

// ── 类型 ──────────────────────────────────────────────

export const POLICY_QA_FEEDBACK_REASONS = [
  'wrong_calculation',
  'wrong_policy_content',
  'wrong_citation',
  'wrong_routing',
  'unhelpful',
  'other',
] as const

export type PolicyQAFeedbackReasonCode = (typeof POLICY_QA_FEEDBACK_REASONS)[number]

export interface PolicyQAFeedbackPayload {
  /** 仅提交服务端生成的稳定 ID；客户端不得伪造正文或技能路由 */
  qaTurnId: string
  reasonCode: PolicyQAFeedbackReasonCode
  comment: string | null
}

export interface PolicyQAFeedbackResult {
  poolId: string
  status: string
  errorDimension: string
  sourceSelectedSkillId: string | null
}

interface RawFeedbackResponse {
  pool_id: string
  status: string
  error_dimension: string
  source_selected_skill_id: string | null
}

export interface EvalCasePoolItem {
  poolId: string
  tenantId: string
  sourceQaTurnId: string
  sourceUserId: string
  reasonCode: string
  errorDimension: string
  initialDimension: string
  transformedDimension: string | null
  targetSkillId: string | null
  questionExcerpt: string
  answerExcerpt: string
  comment: string
  status: string
  revision: number
  evalCaseRef: Record<string, unknown> | null
  createdAt: string
  updatedAt: string
}

export interface EvalCasePoolList {
  items: EvalCasePoolItem[]
  total: number
  limit: number
  offset: number
}

interface RawEvalCasePoolItem {
  pool_id: string
  tenant_id: string
  source_qa_turn_id: string
  source_user_id: string
  reason_code: string
  error_dimension: string
  initial_dimension: string
  transformed_dimension: string | null
  target_skill_id: string | null
  question_excerpt: string
  answer_excerpt: string
  comment: string
  status: string
  revision: number
  eval_case_ref: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

interface RawEvalCasePoolList {
  items: RawEvalCasePoolItem[]
  total: number
  limit: number
  offset: number
}

// ── API ───────────────────────────────────────────────

/** 提交「回答有误」反馈：客户端只提交 ID + 原因码，正文由服务端按 ID 读取。 */
export async function submitPolicyQAFeedback(
  payload: PolicyQAFeedbackPayload,
): Promise<PolicyQAFeedbackResult> {
  const raw = await requestJson<RawFeedbackResponse>('/policy-qa/feedback', {
    method: 'POST',
    body: JSON.stringify({
      qa_turn_id: payload.qaTurnId,
      reason_code: payload.reasonCode,
      comment: payload.comment,
    }),
  })
  return {
    poolId: raw.pool_id,
    status: raw.status,
    errorDimension: raw.error_dimension,
    sourceSelectedSkillId: raw.source_selected_skill_id,
  }
}

export interface EvalCasePoolFilter {
  status?: string
  errorDimension?: string
  targetSkillId?: string
  limit?: number
  offset?: number
}

export async function listEvalCasePool(
  filter?: EvalCasePoolFilter,
): Promise<EvalCasePoolList> {
  const params = new URLSearchParams()
  if (filter?.status) params.set('status', filter.status)
  if (filter?.errorDimension) params.set('error_dimension', filter.errorDimension)
  if (filter?.targetSkillId) params.set('target_skill_id', filter.targetSkillId)
  if (filter?.limit) params.set('limit', String(filter.limit))
  if (filter?.offset) params.set('offset', String(filter.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const raw = await requestJson<RawEvalCasePoolList>(
    `/infra-skills/eval-case-pool${query}`,
  )
  return {
    items: raw.items.map((item) => ({
      poolId: item.pool_id,
      tenantId: item.tenant_id,
      sourceQaTurnId: item.source_qa_turn_id,
      sourceUserId: item.source_user_id,
      reasonCode: item.reason_code,
      errorDimension: item.error_dimension,
      initialDimension: item.initial_dimension,
      transformedDimension: item.transformed_dimension,
      targetSkillId: item.target_skill_id,
      questionExcerpt: item.question_excerpt,
      answerExcerpt: item.answer_excerpt,
      comment: item.comment,
      status: item.status,
      revision: item.revision,
      evalCaseRef: item.eval_case_ref,
      createdAt: item.created_at,
      updatedAt: item.updated_at,
    })),
    total: raw.total,
    limit: raw.limit,
    offset: raw.offset,
  }
}
