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

const SSE_EVENT_TYPES: readonly SseEventType[] = ['step', 'final', 'error', 'done', 'token']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function toSseEventType(value: string): SseEventType | null {
  const eventType = value.trim()
  return SSE_EVENT_TYPES.includes(eventType as SseEventType) ? (eventType as SseEventType) : null
}

async function readJsonSafely(response: Response): Promise<unknown> {
  return response.json().catch(() => null)
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
  const body = await readJsonSafely(response)
  const detail = isRecord(body) ? normalizeErrorDetail(body.detail) : null

  return new ApiClientError(
    response.status,
    detail ?? {
      error_code: `HTTP_${response.status}`,
      message: response.statusText || '请求失败',
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
  return (text ? JSON.parse(text) : undefined) as T
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
      throw error
    }

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
    emitFallbackChatStream(request.message, onEvent)
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

  try {
    while (true) {
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
        }
      }
    }

    const trailingEvent = parseSseChunk(buffer)
    if (trailingEvent) {
      onEvent(trailingEvent)
    }
  } finally {
    reader.releaseLock()
  }
}

export function parseSseChunk(chunk: string): SseEvent | null {
  const lines = chunk.replace(/\r\n/g, '\n').split('\n')
  let event: SseEventType | null = null
  const dataLines: string[] = []

  for (const line of lines) {
    if (!line || line.startsWith(':')) {
      continue
    }

    if (line.startsWith('event:')) {
      event = toSseEventType(line.slice('event:'.length))
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
  } catch {
    return { event, data: rawData }
  }
}
