import {
  mockAIChatResponses,
  mockMcpServers,
  mockMcpStorageHealth,
  mockModelTestResult,
} from './mock-data'
import type {
  AgentResponse,
  ApiErrorDetail,
  AppealTemplateCreate,
  AppealTemplateItem,
  AssetCreate,
  ChatRequest,
  ChunkCreate,
  ErrorCode,
  ErrorCodeCreate,
  FallbackChain,
  ListResponse,
  McpCapability,
  McpCapabilityCreate,
  McpServer,
  McpStorageHealth,
  ModelConfig,
  ModelParams,
  ModelProviderCreate,
  ModelProviderResponse,
  ModelProviderTestResult,
  ModelRouteCreate,
  ModelRouteResponse,
  ModelTestRequest,
  ModelTestResponse,
  PatientContextResponse,
  PromptTemplateCreate,
  PromptTemplateItem,
  RenderPromptRequest,
  RenderPromptResponse,
  RuleCreate,
  SseEvent,
  SseEventType,
  TaskConfirmRequest,
  TaskConfirmResponse,
  TaskStatusResponse,
  WorkflowStatusResponse,
} from './types'
import { ApiClientError } from './types'

export const API_PREFIX = '/api/v1/medical-insurance-ai-agent'

const SSE_EVENT_TYPES: readonly SseEventType[] = ['start', 'step', 'delta', 'final', 'error', 'done', 'token', 'intent_trace']

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

export function fallbackAgentResponse(message: string): AgentResponse {
  const lines = mockAIChatResponses[message] ?? [
    `我理解您的问题：${message}`,
    '',
    '后端服务当前不可用，已切换到离线演示模式。',
    '请启动 FastAPI 服务后重新尝试真实联调。',
  ]

  return {
    scenario: 'offline_demo',
    status: 'success',
    result: { content: lines.join('\n') },
    citations: [
      {
        source_type: 'mock',
        source_id: 'prototype-mock',
        summary: '前端离线演示数据',
      },
    ],
    tasks: [],
    missing_fields: [],
    uncertainties: ['后端不可达，当前展示 mock 降级结果'],
    blocked_actions: [],
    audit: {
      fallback: true,
      source: 'prototype-api-client',
      generated_at: new Date().toISOString(),
    },
    fallback: true,
  }
}

function fallbackModelTestResponse(): ModelTestResponse {
  return { ...mockModelTestResult, fallback: true }
}

function fallbackPatientContext(
  patientId: string,
  encounterId: string
): PatientContextResponse {
  return {
    patient: { patient_id: patientId, name: '张*' },
    visible_fields: ['encounter_id', 'settlement_status'],
    encounter_id: encounterId,
    settlement_status: 'failed',
    audit_risks: [],
    fallback: true,
  }
}

function emitFallbackChatStream(message: string, onEvent: (event: SseEvent) => void) {
  onEvent({ event: 'final', data: fallbackAgentResponse(message) })
  onEvent({ event: 'done', data: { fallback: true } })
}

function emitFallbackModelStream(onEvent: (event: SseEvent) => void) {
  onEvent({ event: 'final', data: fallbackModelTestResponse() })
  onEvent({ event: 'done', data: { fallback: true } })
}

export async function sendChat(request: ChatRequest): Promise<AgentResponse> {
  try {
    return await requestJson<AgentResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      console.error('[API] /chat 请求失败:', {
        status: error.status,
        error_code: error.detail.error_code,
        message: error.detail.message,
      })
      throw error
    }

    console.warn('[API] 后端不可达，降级到 mock 模式:', { url: '/chat', message: request.message })
    return fallbackAgentResponse(request.message)
  }
}

export async function sendChatStream(
  request: ChatRequest,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  let response: Response

  try {
    response = await fetch(`${API_PREFIX}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    console.warn('[API] 后端不可达，降级到 mock 模式:', { url: `${API_PREFIX}/chat/stream`, message: request.message })
    emitFallbackChatStream(request.message, onEvent)
    return
  }

  if (!response.ok) {
    const error = await parseError(response)
    console.error('[API] 后端返回非 2xx 状态:', {
      status: error.status,
      error_code: error.detail.error_code,
      message: error.detail.message,
    })
    throw error
  }

  if (!response.body) {
    const msg = '浏览器不支持流式响应'
    console.error('[API]', msg)
    throw new Error(msg)
  }

  await readSseStream(response.body, onEvent)
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

export async function fetchPatientContext(
  patientId: string,
  encounterId: string,
  userId: string,
  role: string
): Promise<PatientContextResponse> {
  try {
    const query = new URLSearchParams({ user_id: userId, role })
    const encodedPatientId = encodeURIComponent(patientId)
    const encodedEncounterId = encodeURIComponent(encounterId)

    return await requestJson<PatientContextResponse>(
      `/patient-context/${encodedPatientId}/${encodedEncounterId}?${query.toString()}`
    )
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return fallbackPatientContext(patientId, encounterId)
  }
}

export async function confirmTask(request: TaskConfirmRequest): Promise<TaskConfirmResponse> {
  try {
    return await requestJson<TaskConfirmResponse>('/tasks/confirm', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return {
      task_id: request.task_id,
      status: request.action === 'confirm' ? 'confirmed' : 'rejected',
      confirmed_by: request.user_id,
      confirmed_at: new Date().toISOString(),
      reason: request.reason,
      result: request.action === 'confirm' ? {} : { blocked: true, message: '用户拒绝执行该操作' },
      fallback: true,
    }
  }
}

export async function fetchWorkflowStatus(workflowId: string): Promise<WorkflowStatusResponse> {
  try {
    return await requestJson<WorkflowStatusResponse>(`/workflows/${encodeURIComponent(workflowId)}`)
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return { workflow_id: workflowId, status: 'pending', fallback: true }
  }
}

export async function fetchTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  try {
    return await requestJson<TaskStatusResponse>(`/tasks/${encodeURIComponent(taskId)}`)
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error
    }

    return { task_id: taskId, status: 'pending', fallback: true }
  }
}

// --- Model Management API ---

export async function getModelConfig(): Promise<ModelConfig> {
  return requestJson<ModelConfig>('/model-config')
}

export async function updateModelConfig(data: Partial<ModelConfig>): Promise<ModelConfig> {
  return requestJson<ModelConfig>('/model-config', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function listModelRoutes(): Promise<ListResponse<ModelRouteResponse>> {
  return requestJson<ListResponse<ModelRouteResponse>>('/model-routes')
}

export async function createModelRoute(data: ModelRouteCreate): Promise<ModelRouteResponse> {
  return requestJson<ModelRouteResponse>('/model-routes', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getModelRoute(routeId: string): Promise<ModelRouteResponse> {
  return requestJson<ModelRouteResponse>(`/model-routes/${encodeURIComponent(routeId)}`)
}

export async function updateModelRoute(routeId: string, data: Partial<ModelRouteCreate>): Promise<ModelRouteResponse> {
  return requestJson<ModelRouteResponse>(`/model-routes/${encodeURIComponent(routeId)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteModelRoute(routeId: string): Promise<void> {
  await requestJson<void>(`/model-routes/${encodeURIComponent(routeId)}`, { method: 'DELETE' })
}

export async function getModelFallbacks(modelName: string): Promise<FallbackChain> {
  return requestJson<FallbackChain>(`/model-routes/fallbacks/${encodeURIComponent(modelName)}`)
}

export async function updateModelFallbacks(modelName: string, fallbacks: string[]): Promise<FallbackChain> {
  return requestJson<FallbackChain>(`/model-routes/fallbacks/${encodeURIComponent(modelName)}`, {
    method: 'PUT',
    body: JSON.stringify({ fallbacks }),
  })
}

export async function getModelParams(modelName: string): Promise<ModelParams> {
  return requestJson<ModelParams>(`/model-routes/params/${encodeURIComponent(modelName)}`)
}

export async function updateModelParams(modelName: string, params: ModelParams): Promise<ModelParams> {
  return requestJson<ModelParams>(`/model-routes/params/${encodeURIComponent(modelName)}`, {
    method: 'PUT',
    body: JSON.stringify(params),
  })
}

export async function listModelProviders(): Promise<ListResponse<ModelProviderResponse>> {
  return requestJson<ListResponse<ModelProviderResponse>>('/model-providers')
}

export async function createModelProvider(data: ModelProviderCreate): Promise<ModelProviderResponse> {
  return requestJson<ModelProviderResponse>('/model-providers', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getModelProvider(providerId: string): Promise<ModelProviderResponse> {
  return requestJson<ModelProviderResponse>(`/model-providers/${encodeURIComponent(providerId)}`)
}

export async function updateModelProvider(providerId: string, data: Partial<ModelProviderCreate>): Promise<ModelProviderResponse> {
  return requestJson<ModelProviderResponse>(`/model-providers/${encodeURIComponent(providerId)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteModelProvider(providerId: string): Promise<void> {
  await requestJson<void>(`/model-providers/${encodeURIComponent(providerId)}`, { method: 'DELETE' })
}

export async function testModelProvider(providerId: string): Promise<ModelProviderTestResult> {
  return requestJson<ModelProviderTestResult>(`/model-providers/${encodeURIComponent(providerId)}/test`, {
    method: 'POST',
  })
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

// ── MCP Capabilities API ──

export async function listCapabilities(params?: { server_id?: string }): Promise<McpCapability[]> {
  const query = params?.server_id ? `?server_id=${encodeURIComponent(params.server_id)}` : ''
  return requestJson<McpCapability[]>(`/mcp/capabilities${query}`)
}

export async function createCapability(data: McpCapabilityCreate): Promise<McpCapability> {
  return requestJson<McpCapability>('/mcp/capabilities', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function deleteCapability(capabilityId: string): Promise<void> {
  await requestJson<void>(`/mcp/capabilities/${encodeURIComponent(capabilityId)}`, {
    method: 'DELETE',
  })
}

export function initialMcpServers(): McpServer[] {
  return mockMcpServers.map((server) => ({ ...server }))
}

// Knowledge Management - Error Codes
export async function listErrorCodes(params?: { error_code?: string; description?: string }): Promise<ErrorCode[]> {
  const searchParams = new URLSearchParams()
  if (params?.error_code) searchParams.set('error_code', params.error_code)
  if (params?.description) searchParams.set('description', params.description)
  const query = searchParams.toString()
  return requestJson<ErrorCode[]>(`/knowledge/error-codes${query ? `?${query}` : ''}`)
}

export async function createErrorCode(data: ErrorCodeCreate): Promise<ErrorCode> {
  return requestJson<ErrorCode>('/knowledge/error-codes', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getErrorCode(errorCode: string): Promise<ErrorCode> {
  return requestJson<ErrorCode>(`/knowledge/error-codes/${encodeURIComponent(errorCode)}`)
}

export async function updateErrorCode(errorCode: string, data: Partial<ErrorCodeCreate>): Promise<ErrorCode> {
  return requestJson<ErrorCode>(`/knowledge/error-codes/${encodeURIComponent(errorCode)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteErrorCode(errorCode: string): Promise<void> {
  return requestJson<void>(`/knowledge/error-codes/${encodeURIComponent(errorCode)}`, {
    method: 'DELETE',
  })
}

// ── Appeal Template API ──

export async function listAppealTemplates(params?: { type?: string }): Promise<AppealTemplateItem[]> {
  const query = params?.type ? `?type=${encodeURIComponent(params.type)}` : ''
  return requestJson<AppealTemplateItem[]>(`/knowledge/appeal-templates${query}`)
}

export async function createAppealTemplate(data: AppealTemplateCreate): Promise<AppealTemplateItem> {
  return requestJson<AppealTemplateItem>('/knowledge/appeal-templates', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getAppealTemplate(templateId: string): Promise<AppealTemplateItem> {
  return requestJson<AppealTemplateItem>(`/knowledge/appeal-templates/${encodeURIComponent(templateId)}`)
}

export async function updateAppealTemplate(templateId: string, data: Partial<AppealTemplateCreate>): Promise<AppealTemplateItem> {
  return requestJson<AppealTemplateItem>(`/knowledge/appeal-templates/${encodeURIComponent(templateId)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteAppealTemplate(templateId: string): Promise<void> {
  return requestJson<void>(`/knowledge/appeal-templates/${encodeURIComponent(templateId)}`, {
    method: 'DELETE',
  })
}

// ── Prompt Template API ──

export async function listPromptTemplates(params?: { scenario?: string; role?: string }): Promise<PromptTemplateItem[]> {
  const searchParams = new URLSearchParams()
  if (params?.scenario) searchParams.set('scenario', params.scenario)
  if (params?.role) searchParams.set('role', params.role)
  const query = searchParams.toString() ? `?${searchParams.toString()}` : ''
  return requestJson<PromptTemplateItem[]>(`/knowledge/prompt-templates${query}`)
}

export async function createPromptTemplate(data: PromptTemplateCreate): Promise<PromptTemplateItem> {
  return requestJson<PromptTemplateItem>('/knowledge/prompt-templates', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function getPromptTemplate(templateId: string): Promise<PromptTemplateItem> {
  return requestJson<PromptTemplateItem>(`/knowledge/prompt-templates/${encodeURIComponent(templateId)}`)
}

export async function updatePromptTemplate(templateId: string, data: Partial<PromptTemplateCreate>): Promise<PromptTemplateItem> {
  return requestJson<PromptTemplateItem>(`/knowledge/prompt-templates/${encodeURIComponent(templateId)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deletePromptTemplate(templateId: string): Promise<void> {
  return requestJson<void>(`/knowledge/prompt-templates/${encodeURIComponent(templateId)}`, {
    method: 'DELETE',
  })
}

export async function renderPromptTemplate(request: RenderPromptRequest): Promise<RenderPromptResponse> {
  return requestJson<RenderPromptResponse>('/knowledge/prompt-templates/render', {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function readSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: SseEvent) => void
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let shouldStop = false

  try {
    while (!shouldStop) {
      const { done, value } = await reader.read()

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

      if (trailingEvent.event === 'done') {
        shouldStop = true
      }
    }

    if (shouldStop) {
      await reader.cancel().catch(() => undefined)
    }
  } finally {
    reader.releaseLock()
  }
}

// ── Rules (knowledge/rules) ──

export async function listRules(params?: { scenario?: string }): Promise<Record<string, unknown>[]> {
  const query = params?.scenario ? `?scenario=${encodeURIComponent(params.scenario)}` : ''
  return requestJson(`/knowledge/rules${query}`)
}

export async function createRule(data: RuleCreate): Promise<Record<string, unknown>> {
  return requestJson('/knowledge/rules', { method: 'POST', body: JSON.stringify(data) })
}

export async function getRule(ruleId: string): Promise<Record<string, unknown>> {
  return requestJson(`/knowledge/rules/${encodeURIComponent(ruleId)}`)
}

export async function updateRule(ruleId: string, data: Partial<RuleCreate>): Promise<Record<string, unknown>> {
  return requestJson(`/knowledge/rules/${encodeURIComponent(ruleId)}`, { method: 'PUT', body: JSON.stringify(data) })
}

export async function deleteRule(ruleId: string): Promise<void> {
  return requestJson(`/knowledge/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
}

// ── Assets (knowledge/assets) ──

export async function listAssets(params?: { type?: string; status?: string }): Promise<Record<string, unknown>[]> {
  const searchParams = new URLSearchParams()
  if (params?.type) searchParams.set('type', params.type)
  if (params?.status) searchParams.set('status', params.status)
  const query = searchParams.toString()
  return requestJson(`/knowledge/assets${query ? `?${query}` : ''}`)
}

export async function createAsset(data: AssetCreate): Promise<Record<string, unknown>> {
  return requestJson('/knowledge/assets', { method: 'POST', body: JSON.stringify(data) })
}

export async function getAsset(assetId: string): Promise<Record<string, unknown>> {
  return requestJson(`/knowledge/assets/${encodeURIComponent(assetId)}`)
}

export async function updateAsset(assetId: string, data: Partial<AssetCreate>): Promise<Record<string, unknown>> {
  return requestJson(`/knowledge/assets/${encodeURIComponent(assetId)}`, { method: 'PUT', body: JSON.stringify(data) })
}

export async function deleteAsset(assetId: string): Promise<void> {
  return requestJson(`/knowledge/assets/${encodeURIComponent(assetId)}`, { method: 'DELETE' })
}

// ── Chunks (knowledge/assets/{assetId}/chunks) ──

export async function listAssetChunks(assetId: string): Promise<Record<string, unknown>[]> {
  return requestJson(`/knowledge/assets/${encodeURIComponent(assetId)}/chunks`)
}

export async function createAssetChunk(assetId: string, data: ChunkCreate): Promise<Record<string, unknown>> {
  return requestJson(`/knowledge/assets/${encodeURIComponent(assetId)}/chunks`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
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
