// 可信问题库 API 客户端 — issue #37（匹配/审核流/同义运营/冷启动）。
// DTO 字段与后端 src/runtime/api/question_library_routes.py 逐字段对齐（snake_case 直传）。
import { requestJson } from './api-client'

export type TrustedQuestionStatusDto = 'draft' | 'published' | 'archived'
export type QuestionMatchKindDto = 'hit' | 'clarify'
export type QuestionMatchEventOutcomeDto = 'hit' | 'clarify' | 'selected'

export interface TrustedQuestionDto {
  question_id: string
  standard_question: string
  synonyms: string[]
  roles: string[]
  object_code: string
  metrics: string[]
  dimensions: string[]
  time_scope: string | null
  filters: Array<Record<string, unknown>>
  query_plan: Record<string, unknown>
  allow_drilldown: boolean
  expected_result: Record<string, unknown>
  reviewer: string | null
  version: number
  status: TrustedQuestionStatusDto
  revision: number
  created_at: string
  updated_at: string
}

export interface TrustedQuestionPageDto {
  items: TrustedQuestionDto[]
  total: number
  page: number
  page_size: number
}

export interface QuestionMatchCandidateDto {
  question_id: string
  standard_question: string
  score: number
  matched_text: string
}

export interface QuestionMatchOutcomeDto {
  kind: QuestionMatchKindDto
  asked_text: string
  question: TrustedQuestionDto | null
  matched_text: string | null
  candidates: QuestionMatchCandidateDto[]
}

export interface QuestionMatchEventDto {
  event_id: string
  asked_text: string
  outcome: QuestionMatchEventOutcomeDto
  matched_question_id: string | null
  created_at: string
}

export interface QuestionMatchEventPageDto {
  items: QuestionMatchEventDto[]
  total: number
  page: number
  page_size: number
}

export interface QuestionLibraryStatsDto {
  question_counts: Record<string, number>
  match_event_counts: Record<string, number>
}

export interface ColdStartCandidateDto {
  question_text: string
  frequency: number
}

export interface CreateDraftBody {
  standard_question: string
  synonyms: string[]
  roles: string[]
  object_code: string
  metrics: string[]
  dimensions: string[]
  time_scope?: string | null
  filters: Array<Record<string, unknown>>
  query_plan: Record<string, unknown>
  allow_drilldown: boolean
  expected_result: Record<string, unknown>
}

// ── 鉴权（与 ops-api 同模式：sessionStorage → dev 环境变量 token）──

function questionLibraryToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = window.sessionStorage.getItem('question-library-token')
    if (token) return token
  }
  return process.env.NODE_ENV === 'production'
    ? null
    : process.env.NEXT_PUBLIC_QUESTION_LIBRARY_TOKEN || null
}

export function hasQuestionLibraryPermission(permission: 'read' | 'write'): boolean {
  const token = questionLibraryToken()
  if (!token) return process.env.NODE_ENV !== 'production'
  try {
    const payload = token.replace(/^Bearer\s+/i, '').split('.')[1]
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const permissions = JSON.parse(atob(base64)).permissions
    return Array.isArray(permissions) && permissions.includes(`question_library:${permission}`)
  } catch {
    return false
  }
}

async function qlibRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = questionLibraryToken()
  if (token) headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`)
  return requestJson<T>(`/question-library${path}`, { ...init, headers })
}

// ── 试问（开放端点）──

export function matchQuestion(question: string): Promise<QuestionMatchOutcomeDto> {
  return requestJson<QuestionMatchOutcomeDto>('/question-library/match', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export function executeQuestion(questionId: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`/question-library/questions/${encodeURIComponent(questionId)}/execute`, {
    method: 'POST',
  })
}

// ── 管理（question_library:read / write）──

export function listTrustedQuestions(query: {
  status?: TrustedQuestionStatusDto
  q?: string
  page?: number
  page_size?: number
}): Promise<TrustedQuestionPageDto> {
  const params = new URLSearchParams()
  if (query.status) params.set('status', query.status)
  if (query.q) params.set('q', query.q)
  if (query.page) params.set('page', String(query.page))
  if (query.page_size) params.set('page_size', String(query.page_size))
  const suffix = params.toString()
  return qlibRequest<TrustedQuestionPageDto>(`/questions${suffix ? `?${suffix}` : ''}`)
}

export function getTrustedQuestion(questionId: string): Promise<TrustedQuestionDto> {
  return qlibRequest<TrustedQuestionDto>(`/questions/${encodeURIComponent(questionId)}`)
}

export function createTrustedQuestionDraft(
  body: CreateDraftBody,
): Promise<{ question_id: string; status: string }> {
  return qlibRequest<{ question_id: string; status: string }>('/questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function reviewTrustedQuestion(
  questionId: string,
  body: { approve: boolean; reviewer: string; reason?: string | null; expected_revision: number },
): Promise<{ question_id: string; status: string; version: number }> {
  return qlibRequest<{ question_id: string; status: string; version: number }>(
    `/questions/${encodeURIComponent(questionId)}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
}

export function archiveTrustedQuestion(
  questionId: string,
  expectedRevision: number,
): Promise<{ question_id: string; status: string }> {
  return qlibRequest<{ question_id: string; status: string }>(
    `/questions/${encodeURIComponent(questionId)}/archive?expected_revision=${expectedRevision}`,
    { method: 'POST' },
  )
}

export function addTrustedQuestionSynonym(
  questionId: string,
  body: { synonym: string; expected_revision: number },
): Promise<{ question_id: string; synonyms: string[] }> {
  return qlibRequest<{ question_id: string; synonyms: string[] }>(
    `/questions/${encodeURIComponent(questionId)}/synonyms`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
}

export function listQuestionMatchEvents(query: {
  outcome?: QuestionMatchEventOutcomeDto
  page?: number
  page_size?: number
}): Promise<QuestionMatchEventPageDto> {
  const params = new URLSearchParams()
  if (query.outcome) params.set('outcome', query.outcome)
  if (query.page) params.set('page', String(query.page))
  if (query.page_size) params.set('page_size', String(query.page_size))
  const suffix = params.toString()
  return qlibRequest<QuestionMatchEventPageDto>(`/match-events${suffix ? `?${suffix}` : ''}`)
}

export function getQuestionLibraryStats(): Promise<QuestionLibraryStatsDto> {
  return qlibRequest<QuestionLibraryStatsDto>('/stats')
}

export function listColdStartCandidates(limit = 100): Promise<ColdStartCandidateDto[]> {
  return qlibRequest<ColdStartCandidateDto[]>(`/cold-start?limit=${limit}`)
}
