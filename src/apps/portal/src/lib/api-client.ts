import {
  mockMcpServers,
  mockMcpStorageHealth,
  mockModelTestResult,
} from './mock-data'

// ── Infra Skills API ──

export interface InfraSkillsFilter {
  business_action?: string
  business_object?: string
}

export async function listInfraSkills(filter?: InfraSkillsFilter): Promise<InfraSkillItem[]> {
  const params = new URLSearchParams()
  if (filter?.business_action) params.set('business_action', filter.business_action)
  if (filter?.business_object) params.set('business_object', filter.business_object)
  const query = params.toString()
  return requestJson<InfraSkillItem[]>(`/infra-skills${query ? `?${query}` : ''}`)
}

export interface InfraSkillCatalogFilter extends InfraSkillsFilter {
  page?: number
  page_size?: number
  artifact_status?: string
  query?: string
}

export async function getInfraSkillDetail(skillId: string): Promise<InfraSkillDetailResponse> {
  return requestJson<InfraSkillDetailResponse>(`/infra-skills/${encodeURIComponent(skillId)}`)
}

export async function listInfraSkillCatalog(
  filter?: InfraSkillCatalogFilter,
): Promise<InfraSkillCatalogResponse> {
  const params = new URLSearchParams()
  if (filter?.page) params.set('page', String(filter.page))
  if (filter?.page_size) params.set('page_size', String(filter.page_size))
  if (filter?.business_action) params.set('business_action', filter.business_action)
  if (filter?.business_object) params.set('business_object', filter.business_object)
  if (filter?.artifact_status) params.set('artifact_status', filter.artifact_status)
  if (filter?.query) params.set('query', filter.query)
  const query = params.toString()
  return requestJson<InfraSkillCatalogResponse>(
    `/infra-skills/catalog${query ? `?${query}` : ''}`,
  )
}

export async function getSkillGovernanceWorkbench(
  filter: SkillWorkbenchFilter = {},
): Promise<SkillWorkbenchResponse> {
  const params = new URLSearchParams()
  if (filter.page) params.set('page', String(filter.page))
  if (filter.page_size) params.set('page_size', String(filter.page_size))
  if (filter.business_action) params.set('business_action', filter.business_action)
  if (filter.business_object) params.set('business_object', filter.business_object)
  if (filter.artifact_status) params.set('artifact_status', filter.artifact_status)
  if (filter.governance_status) params.set('governance_status', filter.governance_status)
  if (filter.priority) params.set('priority', filter.priority)
  if (filter.query) params.set('query', filter.query)
  const query = params.toString()
  return requestJson<SkillWorkbenchResponse>(
    `/infra-skills/workbench${query ? `?${query}` : ''}`,
  )
}

export async function listInfraSkillVersions(skillId: string): Promise<SkillVersionResponse[]> {
  return requestJson<SkillVersionResponse[]>(
    `/infra-skills/${encodeURIComponent(skillId)}/versions`,
  )
}

export async function syncInfraSkillVersion(
  skillId: string,
  request: SkillVersionSyncRequest,
): Promise<SkillVersionResponse> {
  return requestJson<SkillVersionResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/versions/sync`,
    { method: 'POST', body: JSON.stringify(request) },
  )
}

export async function listSkillEvalCases(): Promise<SkillEvalCaseListResponse> {
  return requestJson<SkillEvalCaseListResponse>('/infra-skills/eval-cases')
}

export async function createSkillEvalCase(
  request: SkillEvalCaseCreateRequest,
): Promise<SkillEvalCaseResponse> {
  return requestJson<SkillEvalCaseResponse>('/infra-skills/eval-cases', {
    method: 'POST',
    headers: skillEvaluationHeaders(),
    body: JSON.stringify(request),
  })
}

export async function deleteSkillEvalCase(caseId: string): Promise<void> {
  await requestJson<void>(
    `/infra-skills/eval-cases/${encodeURIComponent(caseId)}`,
    { method: 'DELETE', headers: skillEvaluationHeaders() },
  )
}

export async function dedupeSkillEvalCases(): Promise<SkillEvalCaseListResponse> {
  return requestJson<SkillEvalCaseListResponse>('/infra-skills/eval-cases/dedupe', {
    method: 'POST',
    headers: skillEvaluationHeaders(),
  })
}

export async function seedGoldenSkillEvalCases(): Promise<SkillEvalCaseListResponse> {
  return requestJson<SkillEvalCaseListResponse>('/infra-skills/eval-cases/seed-golden', {
    method: 'POST',
    headers: skillEvaluationHeaders(),
  })
}

// ── 错误案例池：转换 / 确认 / 拒绝（仅 skill:evaluate）──

export interface EvalCasePoolTransformResponse {
  pool_id: string
  transformed_dimension: string
  case_proposal: Record<string, unknown> | null
  root_cause: string | null
  citations: Record<string, unknown>[]
  uncertainties: string[]
  revision: number
}

export interface EvalCasePoolConfirmRequest {
  expected_revision: number
  error_dimension: string
  target_skill_id: string | null
  case_proposal: Record<string, unknown> | null
}

export interface EvalCasePoolConfirmResponse {
  pool_id: string
  case_type: string
  case_id: string
  revision: number
}

export async function transformEvalCasePoolItem(
  poolId: string,
  expectedRevision: number,
): Promise<EvalCasePoolTransformResponse> {
  return requestJson<EvalCasePoolTransformResponse>(
    `/infra-skills/eval-case-pool/${encodeURIComponent(poolId)}/transform`,
    {
      method: 'POST',
      headers: skillEvaluationHeaders(),
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  )
}

export async function confirmEvalCasePoolItem(
  poolId: string,
  request: EvalCasePoolConfirmRequest,
): Promise<EvalCasePoolConfirmResponse> {
  return requestJson<EvalCasePoolConfirmResponse>(
    `/infra-skills/eval-case-pool/${encodeURIComponent(poolId)}/confirm`,
    {
      method: 'POST',
      headers: skillEvaluationHeaders(),
      body: JSON.stringify(request),
    },
  )
}

export interface EvalCasePoolItemResponse {
  pool_id: string
  tenant_id: string
  source_qa_turn_id: string
  source_user_id: string
  reason_code: string
  error_dimension: string
  initial_dimension: string
  transformed_dimension: string | null
  target_skill_id: string | null
  status: string
  revision: number
  rejection_reason: string | null
  created_at: string
  updated_at: string
}

export async function rejectEvalCasePoolItem(
  poolId: string,
  expectedRevision: number,
  rejectionReason: string,
): Promise<EvalCasePoolItemResponse> {
  return requestJson<EvalCasePoolItemResponse>(
    `/infra-skills/eval-case-pool/${encodeURIComponent(poolId)}/reject`,
    {
      method: 'POST',
      headers: skillEvaluationHeaders(),
      body: JSON.stringify({
        expected_revision: expectedRevision,
        rejection_reason: rejectionReason,
      }),
    },
  )
}

export async function listSkillEvalRuns(skillId: string): Promise<SkillEvalRunListResponse> {
  return requestJson<SkillEvalRunListResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/eval-runs`,
  )
}

export async function listAllSkillEvalRuns(
  filter?: { skillId?: string; limit?: number },
): Promise<SkillEvalRunListResponse> {
  const params = new URLSearchParams()
  if (filter?.skillId) params.set('skill_id', filter.skillId)
  if (filter?.limit) params.set('limit', String(filter.limit))
  const query = params.toString() ? `?${params.toString()}` : ''
  return requestJson<SkillEvalRunListResponse>(`/infra-skills/eval-runs${query}`)
}

export async function createSkillEvalRun(
  skillId: string,
  request: SkillEvalRunCreateRequest,
): Promise<SkillEvalRunResponse> {
  return requestJson<SkillEvalRunResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/eval-runs`,
    {
      method: 'POST',
      headers: skillEvaluationHeaders(),
      body: JSON.stringify(request),
    },
  )
}

export async function listSkillReleases(
  skillId: string,
  environment: 'dev' | 'test' = 'test',
): Promise<SkillReleaseListResponse> {
  return requestJson<SkillReleaseListResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/releases?environment=${environment}`,
  )
}



export async function createSkillRelease(
  skillId: string,
  request: SkillReleaseCreateRequest,
  idempotencyKey: string,
): Promise<SkillReleaseResponse> {
  return requestJson<SkillReleaseResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/releases`,
    {
      method: 'POST',
      headers: skillControlHeaders(idempotencyKey),
      body: JSON.stringify(request),
    },
  )
}

export async function requestSkillReleaseApproval(
  skillId: string,
  releaseId: string,
  request: SkillReleaseTransitionRequest,
  idempotencyKey: string,
): Promise<SkillReleaseResponse> {
  return requestJson<SkillReleaseResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/releases/${encodeURIComponent(releaseId)}/request-approval`,
    {
      method: 'POST',
      headers: skillControlHeaders(idempotencyKey),
      body: JSON.stringify(request),
    },
  )
}

export async function approveSkillRelease(
  skillId: string,
  releaseId: string,
  request: SkillReleaseApproveRequest,
  idempotencyKey: string,
): Promise<SkillReleaseResponse> {
  return requestJson<SkillReleaseResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/releases/${encodeURIComponent(releaseId)}/approve`,
    {
      method: 'POST',
      headers: skillControlHeaders(idempotencyKey, true),
      body: JSON.stringify(request),
    },
  )
}

export async function activateSkillRelease(
  skillId: string,
  releaseId: string,
  request: SkillReleaseTransitionRequest,
  idempotencyKey: string,
): Promise<SkillReleaseResponse> {
  return requestJson<SkillReleaseResponse>(
    `/infra-skills/${encodeURIComponent(skillId)}/releases/${encodeURIComponent(releaseId)}/activate`,
    {
      method: 'POST',
      headers: skillControlHeaders(idempotencyKey),
      body: JSON.stringify(request),
    },
  )
}

export async function testInfraSkillRouting(request: SkillRouteTestRequest): Promise<SkillRouteTestResponse> {
  return requestJson<SkillRouteTestResponse>('/infra-skills/route-test', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function testInfraSkillExecution(skillId: string, request: SkillExecuteTestRequest): Promise<SkillExecuteTestResponse> {
  return requestJson<SkillExecuteTestResponse>(`/infra-skills/${encodeURIComponent(skillId)}/test`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

// ── 语义层（最新）：技能消费的语义指标 ───────────────────────────

export async function getSkillSemanticMetrics(skillId: string): Promise<SkillSemanticMetric[]> {
  return requestJson<SkillSemanticMetric[]>(`/semantic/skills/${encodeURIComponent(skillId)}/metrics`)
}

export async function getSemanticMetricDetail(metricCode: string): Promise<SemanticMetricDetail> {
  return requestJson<SemanticMetricDetail>(`/semantic/metrics/${encodeURIComponent(metricCode)}`)
}

// ── 语义层：技能查询计划与试运行 ───────────────────────────────

export async function getSkillQueryPlan(skillId: string): Promise<SkillQueryPlan> {
  return requestJson<SkillQueryPlan>(`/semantic/skills/${encodeURIComponent(skillId)}/query-plan`)
}

export async function executeSkillQuery(
  skillId: string,
  djh: string | number
): Promise<SkillQueryExecuteResult> {
  return requestJson<SkillQueryExecuteResult>(
    `/semantic/skills/${encodeURIComponent(skillId)}/query-execute`,
    { method: 'POST', body: JSON.stringify({ djh }) }
  )
}

export async function checkSkillConsistency(
  skillId: string,
  djh: string
): Promise<ConsistencyCheckResult> {
  return requestJson<ConsistencyCheckResult>(
    `/semantic/skills/${encodeURIComponent(skillId)}/consistency-check?djh=${encodeURIComponent(djh)}`
  )
}
import type {
  ApiErrorDetail,
  McpServer,
  McpStorageHealth,
  ModelTestRequest,
  ModelTestResponse,
  QAHistoryResponse,
  SseEvent,
  SseEventType,
  InfraSkillItem,
  InfraSkillDetailResponse,
  InfraSkillCatalogResponse,
  SkillVersionResponse,
  SkillVersionSyncRequest,
  SkillEvalCaseCreateRequest,
  SkillEvalCaseListResponse,
  SkillEvalCaseResponse,
  SkillEvalRunCreateRequest,
  SkillEvalRunListResponse,
  SkillEvalRunResponse,
  SkillWorkbenchFilter,
  SkillReleaseApproveRequest,
  SkillReleaseCreateRequest,
  SkillReleaseListResponse,
  SkillReleaseResponse,
  SkillReleaseTransitionRequest,
  SkillWorkbenchResponse,
  SkillRouteTestRequest,
  SkillRouteTestResponse,
  SkillExecuteTestRequest,
  SkillExecuteTestResponse,
  SkillSemanticMetric,
  SemanticMetricDetail,
  SkillQueryPlan,
  SkillQueryExecuteResult,
  ConsistencyCheckResult,
} from './types'
import { skillControlHeaders, skillEvaluationHeaders } from './skill-auth'
import { ApiClientError } from './types'

export const API_PREFIX = '/api/v1/medical-insurance-ai-agent'

const SSE_EVENT_TYPES: readonly SseEventType[] = [
  'start', 'step', 'delta', 'final', 'error', 'done', 'token', 'intent_trace',
  'stream:start', 'stream:step', 'stream:intent_trace',
  'stream:delta', 'stream:tool_call', 'stream:tool_result',
  'stream:final', 'stream:error', 'stream:done',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function toSseEventType(value: string): SseEventType | null {
  const eventType = value.trim()
  return SSE_EVENT_TYPES.includes(eventType as SseEventType) ? (eventType as SseEventType) : null
}

function errorCause(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function textSummary(text: string): string | null {
  const summary = text.trim().slice(0, 200)
  return summary || null
}

function normalizeErrorDetail(detail: unknown): ApiErrorDetail | null {
  if (!isRecord(detail)) {
    return null
  }

  const errorCode = detail.error_code
  const message = detail.message

  if (typeof errorCode !== 'string' || typeof message !== 'string') {
    return null
  }

  return {
    error_code: errorCode,
    message,
    audit_event: isRecord(detail.audit_event) ? detail.audit_event : undefined,
  }
}

export async function parseError(response: Response): Promise<ApiClientError> {
  const text = await response.text()
  const summary = textSummary(text)
  let body: unknown = null

  if (summary) {
    try {
      body = JSON.parse(text) as unknown
    } catch {
      body = null
    }
  }

  let detail: ApiErrorDetail | null = null

  if (isRecord(body)) {
    detail = normalizeErrorDetail(body.detail) ?? normalizeErrorDetail(body)

    if (!detail && typeof body.detail === 'string') {
      detail = {
        error_code: `HTTP_${response.status}`,
        message: body.detail,
      }
    }

    if (!detail && typeof body.message === 'string') {
      detail = {
        error_code: `HTTP_${response.status}`,
        message: body.message,
      }
    }
  }

  return new ApiClientError(
    response.status,
    detail ?? {
      error_code: `HTTP_${response.status}`,
      message: summary ?? (response.statusText || '请求失败'),
    }
  )
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')

  if (init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    throw await parseError(response)
  }

  const text = await response.text()
  if (!text) {
    return undefined as T
  }

  try {
    return JSON.parse(text) as T
  } catch (error) {
    throw new ApiClientError(response.status, {
      error_code: 'INVALID_JSON_RESPONSE',
      message: '后端返回了无效 JSON 响应',
      audit_event: { path, cause: errorCause(error) },
    })
  }
}

function fallbackModelTestResponse(): ModelTestResponse {
  return { ...mockModelTestResult, fallback: true }
}

function emitFallbackModelStream(onEvent: (event: SseEvent) => void) {
  onEvent({ event: 'final', data: fallbackModelTestResponse() })
  onEvent({ event: 'done', data: { fallback: true } })
}

export async function testModel(request: ModelTestRequest): Promise<ModelTestResponse> {
  try {
    return await requestJson<ModelTestResponse>('/model-test', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return fallbackModelTestResponse()
  }
}

export async function testModelStream(
  request: ModelTestRequest,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  let response: Response

  try {
    response = await fetch(`${API_PREFIX}/model-test/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    emitFallbackModelStream(onEvent)
    return
  }

  if (!response.ok) {
    throw await parseError(response)
  }

  if (!response.body) {
    throw new Error('浏览器不支持流式响应')
  }

  await readSseStream(response.body, onEvent)
}

export async function fetchQAHistory(params?: {
  userId?: string
  limit?: number
  offset?: number
}): Promise<QAHistoryResponse> {
  const searchParams = new URLSearchParams()
  if (params?.userId) searchParams.set('user_id', params.userId)
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit))
  if (params?.offset !== undefined) searchParams.set('offset', String(params.offset))
  const query = searchParams.toString()
  return requestJson<QAHistoryResponse>(`/policy-qa/history${query ? `?${query}` : ''}`)
}

export async function fetchMcpStorageHealth(): Promise<McpStorageHealth> {
  try {
    return await requestJson<McpStorageHealth>('/mcp/storage/health')
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return { ...mockMcpStorageHealth, fallback: true }
  }
}

export async function registerMcpServer(server: McpServer): Promise<McpServer> {
  try {
    return await requestJson<McpServer>('/mcp/servers', {
      method: 'POST',
      body: JSON.stringify(server),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return { ...server, fallback: true }
  }
}

export function initialMcpServers(): McpServer[] {
  return mockMcpServers.map((server) => ({ ...server }))
}

/**
 * readSseStream — Read an SSE stream from a ReadableStream<Uint8Array>.
 *
 * Added keepalive support:
 *  - After 15 seconds of no data, emits a synthetic `stream:step` event
 *    with { step: 'keepalive', message: '等待服务器响应...' }
 *  - The 15s timer resets each time new data arrives
 *  - Timer is cleaned up when the stream ends
 *
 * Signature unchanged for backward compatibility.
 */
export async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let shouldStop = false

  // ── Keepalive timer ──────────────────────────────────────────
  let keepaliveTimer: ReturnType<typeof setTimeout> | null = null

  function startKeepalive(): void {
    clearKeepalive()
    keepaliveTimer = setTimeout(() => {
      // Emit synthetic keepalive event to keep the connection alive
      onEvent({
        event: 'stream:step',
        data: { step: 'keepalive', message: '等待服务器响应...' },
      })
      // Re-arm timer for next keepalive interval
      startKeepalive()
    }, 15000)
  }

  function clearKeepalive(): void {
    if (keepaliveTimer !== null) {
      clearTimeout(keepaliveTimer)
      keepaliveTimer = null
    }
  }

  function resetKeepalive(): void {
    startKeepalive()
  }

  // Start keepalive monitoring
  resetKeepalive()

  try {
    while (!shouldStop) {
      const { done, value } = await reader.read()

      // Data arrived → reset keepalive timer
      resetKeepalive()

      if (done) {
        buffer += decoder.decode()
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split(/\r?\n\r?\n/)
      buffer = chunks.pop() ?? ''

      for (const chunk of chunks) {
        const event = parseSseChunk(chunk)
        if (event) {
          onEvent(event)

          // ★ 出让微任务队列给 React 渲染 ——
          // 不加这步的话，同一次 reader.read() 里的所有事件
          // 都会在同一个同步循环中触发 setState，
          // React 18 会批量合并成一次渲染，思维链看不到逐条更新。
          await new Promise<void>(resolve => setTimeout(resolve, 0))

          if (event.event === 'done') {
            shouldStop = true
            break
          }
        }
      }
    }

    const trailingEvent = shouldStop ? null : parseSseChunk(buffer)
    if (trailingEvent) {
      onEvent(trailingEvent)
      await new Promise<void>(resolve => setTimeout(resolve, 0))

      if (trailingEvent.event === 'done') {
        shouldStop = true
      }
    }

    if (shouldStop) {
      await reader.cancel().catch(() => undefined)
    }
  } finally {
    clearKeepalive()
    reader.releaseLock()
  }
}

export function parseSseChunk(chunk: string): SseEvent | null {
  const lines = chunk.replace(/\r\n/g, '\n').split('\n')
  let event: SseEventType | null = null
  let rawEvent: string | null = null
  const dataLines: string[] = []

  for (const line of lines) {
    if (!line || line.startsWith(':')) {
      continue
    }

    if (line.startsWith('event:')) {
      rawEvent = line.slice('event:'.length).trim()
      event = toSseEventType(rawEvent)
      continue
    }

    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }

  if (!event || dataLines.length === 0) {
    return null
  }

  const rawData = dataLines.join('\n').trim()
  if (!rawData) {
    return { event, data: {} }
  }

  try {
    return { event, data: JSON.parse(rawData) as unknown }
  } catch (error) {
    if (event === 'token') {
      return { event, data: rawData }
    }

    return {
      event: 'error',
      data: {
        error_code: 'INVALID_SSE_EVENT',
        message: '后端返回了无效 SSE JSON 事件',
        raw_event: rawEvent ?? event,
        raw_data: rawData,
        audit_event: { cause: errorCause(error) },
      },
    }
  }
}
