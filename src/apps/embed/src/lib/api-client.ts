import {
  mockAIChatResponses,
  mockMcpServers,
  mockMcpStorageHealth,
  mockModelTestResult,
} from './mock-data'
import type {
  AgentResponse,
  ApiErrorDetail,
  ChatRequest,
  McpServer,
  McpStorageHealth,
  ModelTestRequest,
  ModelTestResponse,
  PatientContextResponse,
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
