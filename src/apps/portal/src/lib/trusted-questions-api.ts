import { requestJson } from './api-client'

// ── 可信问题库 API（Issue #37）──
// 对应后端 src/runtime/api/trusted_question_routes.py（裸 Pydantic 响应，非 AgentResponse 包装）

export type TrustedQuestionStatus = 'draft' | 'pending_review' | 'active' | 'retired'

export interface TrustedQuestionSynonym {
  expression: string
  added_by: string
}

export interface TrustedQuestion {
  question_id: string
  standard_question: string
  synonyms: TrustedQuestionSynonym[]
  applicable_roles: string[]
  metric_codes: string[]
  dimensions: string[]
  time_scope: Record<string, unknown>
  filters: Record<string, unknown>[]
  query_plan: Record<string, unknown> | null
  allowed_drilldowns: string[]
  expected_result_traits: Record<string, unknown>
  status: TrustedQuestionStatus
  created_by: string
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface TrustedQuestionListResponse {
  items: TrustedQuestion[]
  limit: number
  offset: number
}

export interface TrustedQuestionCandidate {
  question_id: string
  standard_question: string
  score: number
  matched_expression: string
}

export interface TrustedQuestionMatchResult {
  outcome: 'matched' | 'candidates' | 'no_match'
  question: TrustedQuestion | null
  candidates: TrustedQuestionCandidate[]
}

export interface TrustedQuestionListFilter {
  status?: TrustedQuestionStatus
  keyword?: string
  limit?: number
}

export async function listTrustedQuestions(
  filter: TrustedQuestionListFilter = {},
): Promise<TrustedQuestionListResponse> {
  const params = new URLSearchParams()
  if (filter.status) params.set('status', filter.status)
  if (filter.keyword) params.set('keyword', filter.keyword)
  if (filter.limit) params.set('limit', String(filter.limit))
  const query = params.toString()
  return requestJson<TrustedQuestionListResponse>(
    `/trusted-questions${query ? `?${query}` : ''}`,
  )
}

export async function createTrustedQuestion(input: {
  standard_question: string
  created_by: string
  synonyms?: string[]
}): Promise<TrustedQuestion> {
  return requestJson<TrustedQuestion>('/trusted-questions', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function updateTrustedQuestion(
  questionId: string,
  input: {
    standard_question: string
    synonyms?: string[]
    expected_version: number
  },
): Promise<TrustedQuestion> {
  return requestJson<TrustedQuestion>(
    `/trusted-questions/${encodeURIComponent(questionId)}`,
    { method: 'PUT', body: JSON.stringify(input) },
  )
}

// ── 审核流（统一 transition 请求：expected_version 乐观锁 + operator 记操作人）──

async function transitionTrustedQuestion(
  questionId: string,
  action: 'submit-review' | 'approve' | 'reject' | 'retire',
  input: { expected_version: number; operator: string; review_note?: string },
): Promise<TrustedQuestion> {
  return requestJson<TrustedQuestion>(
    `/trusted-questions/${encodeURIComponent(questionId)}/${action}`,
    { method: 'POST', body: JSON.stringify(input) },
  )
}

export async function submitTrustedQuestionReview(
  questionId: string,
  input: { expected_version: number; operator: string },
): Promise<TrustedQuestion> {
  return transitionTrustedQuestion(questionId, 'submit-review', input)
}

export async function approveTrustedQuestion(
  questionId: string,
  input: { expected_version: number; operator: string },
): Promise<TrustedQuestion> {
  return transitionTrustedQuestion(questionId, 'approve', input)
}

export async function rejectTrustedQuestion(
  questionId: string,
  input: { expected_version: number; operator: string; review_note: string },
): Promise<TrustedQuestion> {
  return transitionTrustedQuestion(questionId, 'reject', input)
}

export async function retireTrustedQuestion(
  questionId: string,
  input: { expected_version: number; operator: string },
): Promise<TrustedQuestion> {
  return transitionTrustedQuestion(questionId, 'retire', input)
}

// ── 同义表达运营 ──

export async function addTrustedQuestionSynonym(
  questionId: string,
  input: { expression: string; added_by: string; expected_version: number },
): Promise<TrustedQuestion> {
  return requestJson<TrustedQuestion>(
    `/trusted-questions/${encodeURIComponent(questionId)}/synonyms`,
    { method: 'POST', body: JSON.stringify(input) },
  )
}

export async function removeTrustedQuestionSynonym(
  questionId: string,
  expression: string,
  expectedVersion: number,
): Promise<TrustedQuestion> {
  return requestJson<TrustedQuestion>(
    `/trusted-questions/${encodeURIComponent(questionId)}/synonyms/${encodeURIComponent(expression)}?expected_version=${expectedVersion}`,
    { method: 'DELETE' },
  )
}

// ── 匹配测试 ──

export async function matchTrustedQuestion(input: {
  question: string
  role?: string
}): Promise<TrustedQuestionMatchResult> {
  return requestJson<TrustedQuestionMatchResult>('/trusted-questions/match', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
