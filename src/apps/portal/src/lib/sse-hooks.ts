'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { sendChatStream, readSseStream } from './api-client'
import type {
  SseEvent,
  ChatRequest,
  IntentTrace,
  AgentResponse,
  ToolCallPayload,
  ToolResultPayload,
} from './types'

// ── Shared types ─────────────────────────────────────────────

export type ConnectionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'closed'
  | 'error'

export interface StreamStepDisplay {
  step: string
  message: string
  status: 'pending' | 'running' | 'completed' | 'error'
  timestamp?: string
}

// ── useSSEConnection options & return ────────────────────────

export interface SSEConnectionOptions {
  /** URL of the SSE endpoint (GET-based) */
  url: string
  /** Called for each SSE event received */
  onEvent?: (event: SseEvent) => void
  /** Called on non-retryable errors */
  onError?: (error: Error) => void
  /** Called when connection status changes */
  onStatusChange?: (status: ConnectionStatus) => void
  /** Start connecting when true (default: false) */
  enabled?: boolean
  /** Max retry attempts on network errors (default: 3) */
  maxRetries?: number
}

export interface SSEConnectionReturn {
  status: ConnectionStatus
  cancel: () => void
  error: Error | null
  retryCount: number
}

// ── useChatStream options & return ───────────────────────────

export interface UseChatStreamOptions {
  /** The chat request to send — starts new stream when this changes */
  request: ChatRequest | null
  /** Called with the full accumulated text content */
  onMessage?: (content: string) => void
  /** Called when an intent_trace event is received */
  onIntentTrace?: (trace: IntentTrace) => void
  /** Called when a tool_call event is received */
  onToolCall?: (payload: ToolCallPayload) => void
  /** Called when a tool_result event is received */
  onToolResult?: (payload: ToolResultPayload) => void
  /** Called when a step event is received */
  onStep?: (step: string, message: string) => void
  /** Called on connection status changes */
  onStatusChange?: (status: ConnectionStatus) => void
  /** Called when a final event is received with the full response */
  onFinal?: (response: AgentResponse) => void
  /** Called on stream errors */
  onError?: (error: Error) => void
  /** Start streaming when true (default: false) */
  enabled?: boolean
}

export interface UseChatStreamReturn {
  status: ConnectionStatus
  cancel: () => void
  streamingContent: string
  steps: StreamStepDisplay[]
  error: Error | null
  clear: () => void
}

// ── Internal helpers ─────────────────────────────────────────

/** Extract text content from delta / token SSE event data */
function extractDeltaContent(data: unknown): string {
  if (typeof data === 'string') return data
  if (typeof data === 'number' || typeof data === 'boolean') return String(data)
  if (data !== null && typeof data === 'object') {
    const obj = data as Record<string, unknown>
    // StreamDeltaPayload → { content }
    if (typeof obj.content === 'string') return obj.content
    // Common fallback fields across different backend implementations
    if (typeof obj.text === 'string') return obj.text
    if (typeof obj.message === 'string') return obj.message
    if (typeof obj.delta === 'string') return obj.delta
  }
  return ''
}

/** Sleep for ms, aborting early if signal fires */
function sleepAbortable(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms)
    if (signal.aborted) {
      clearTimeout(timer)
      resolve()
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      resolve()
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

// ── useSSEConnection ─────────────────────────────────────────

/**
 * Generic SSE connection hook.
 *
 * Connects to a GET-based SSE endpoint using fetch + readSseStream.
 * Manages connection lifecycle, auto-retry on network errors,
 * and proper cleanup on unmount / cancellation.
 *
 * Note: The `url` parameter is the actual endpoint URL.
 * For the chat-specific SSE flow, see `useChatStream`.
 *
 * Key behaviors:
 *  - Starts connecting when `enabled` transitions to true
 *  - Auto-retries up to `maxRetries` times on network errors (TypeError) with exponential backoff
 *  - Returns `cancel()` to abort the connection immediately
 *  - Cleans up on unmount (calls cancel in useEffect cleanup)
 */
export function useSSEConnection(options: SSEConnectionOptions): SSEConnectionReturn {
  const { url, onEvent, onError, onStatusChange, enabled = false, maxRetries = 3 } = options

  const [status, setStatus] = useState<ConnectionStatus>('idle')
  const [error, setError] = useState<Error | null>(null)
  const [retryCount, setRetryCount] = useState(0)

  // Refs for latest callbacks to avoid stale closures
  const onEventRef = useRef(onEvent)
  const onErrorRef = useRef(onError)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  const updateStatus = useCallback(
    (newStatus: ConnectionStatus) => {
      setStatus(newStatus)
      onStatusChange?.(newStatus)
    },
    [onStatusChange],
  )

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  useEffect(() => {
    if (!enabled || !url) return

    let cancelled = false
    let attempts = 0
    const controller = new AbortController()
    controllerRef.current = controller

    updateStatus('connecting')

    const connect = async (): Promise<void> => {
      while (!cancelled && !controller.signal.aborted) {
        try {
          const response = await fetch(url, {
            signal: controller.signal,
            headers: { Accept: 'text/event-stream' },
          })

          // Check cancellation immediately after fetch
          if (cancelled || controller.signal.aborted) return

          if (!response.ok) {
            throw new Error(`服务器返回错误: HTTP ${response.status} ${response.statusText}`)
          }

          if (!response.body) {
            throw new Error('浏览器不支持流式响应')
          }

          updateStatus('connected')
          setError(null)

          // Read the SSE stream — will throw on abort
          await readSseStream(response.body, (event: SseEvent) => {
            if (!cancelled && !controller.signal.aborted) {
              onEventRef.current?.(event)
            }
          })

          // Stream ended normally
          if (!cancelled && !controller.signal.aborted) {
            updateStatus('closed')
          }
          return
        } catch (err: unknown) {
          // Silent exit on cancellation
          if (cancelled || controller.signal.aborted) return

          const connectionError = err instanceof Error ? err : new Error(String(err))

          // Only retry on TypeError (network error), up to maxRetries
          if (err instanceof TypeError && attempts < maxRetries) {
            attempts++
            setRetryCount(attempts)
            updateStatus('reconnecting')

            const delay =
              Math.min(1000 * Math.pow(3, attempts - 1), 10000) *
              (0.8 + Math.random() * 0.4)

            console.warn(
              `[useSSEConnection] 连接失败，第 ${attempts}/${maxRetries} 次重试 (${Math.round(delay)}ms): ${connectionError.message}`,
            )

            await sleepAbortable(delay, controller.signal)
            continue // retry loop
          }

          // Non-retryable error
          setError(connectionError)
          updateStatus('error')
          onErrorRef.current?.(connectionError)
          return
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      controller.abort()
      controllerRef.current = null
    }
  }, [url, enabled, maxRetries, updateStatus])

  return { status, cancel, error, retryCount }
}

// ── useChatStream ────────────────────────────────────────────

/**
 * Chat SSE stream hook.
 *
 * Uses `sendChatStream()` from api-client.ts to connect to the
 * `/chat/stream` SSE endpoint. Parses streaming events with
 * backward compatibility for both old (`delta`, `final`, etc.)
 * and new (`stream:delta`, `stream:final`, etc.) event naming.
 *
 * Key behaviors:
 *  - Starts streaming when `request` is non-null and `enabled` is true
 *  - Restarts the stream when `request` reference changes
 *  - Tracks streaming content, execution steps, and connection status
 *  - Provides `cancel()` to abort the current stream
 *  - Provides `clear()` to reset content and steps
 *  - Cleans up on unmount
 */
export function useChatStream(options: UseChatStreamOptions): UseChatStreamReturn {
  const {
    request,
    onMessage,
    onIntentTrace,
    onToolCall,
    onToolResult,
    onStep,
    onStatusChange,
    onFinal,
    onError,
    enabled = false,
  } = options

  const [status, setStatus] = useState<ConnectionStatus>('idle')
  const [streamingContent, setStreamingContent] = useState('')
  const [steps, setSteps] = useState<StreamStepDisplay[]>([])
  const [error, setError] = useState<Error | null>(null)

  // ── Refs for stable callbacks and tracking ──
  const cancelRef = useRef<(() => void) | null>(null)
  const streamingContentRef = useRef('')
  const stepCallIdsRef = useRef<Map<string, string>>(new Map())
  const lastRequestKeyRef = useRef<string>('')

  // Keep callback refs fresh to avoid stale closures in the event handler
  const onMessageRef = useRef(onMessage)
  const onIntentTraceRef = useRef(onIntentTrace)
  const onToolCallRef = useRef(onToolCall)
  const onToolResultRef = useRef(onToolResult)
  const onStepRef = useRef(onStep)
  const onFinalRef = useRef(onFinal)
  const onErrorRef = useRef(onError)

  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { onIntentTraceRef.current = onIntentTrace }, [onIntentTrace])
  useEffect(() => { onToolCallRef.current = onToolCall }, [onToolCall])
  useEffect(() => { onToolResultRef.current = onToolResult }, [onToolResult])
  useEffect(() => { onStepRef.current = onStep }, [onStep])
  useEffect(() => { onFinalRef.current = onFinal }, [onFinal])
  useEffect(() => { onErrorRef.current = onError }, [onError])

  // ── Status updater ──
  const updateStatus = useCallback(
    (newStatus: ConnectionStatus) => {
      setStatus(newStatus)
      onStatusChange?.(newStatus)
    },
    [onStatusChange],
  )

  // ── Clear: reset content & steps ──
  const clear = useCallback(() => {
    setStreamingContent('')
    setSteps([])
    setError(null)
    streamingContentRef.current = ''
    stepCallIdsRef.current.clear()
  }, [])

  // ── Cancel: abort current stream ──
  const cancel = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
    streamingContentRef.current = ''
    updateStatus('closed')
  }, [updateStatus])

  // ── SSE event handler ──
  const handleSseEvent = useCallback((event: SseEvent): void => {
    const e = event.event

    // ── Content events: delta / stream:delta / token ──
    if (e === 'delta' || e === 'stream:delta' || e === 'token') {
      const delta = extractDeltaContent(event.data)
      if (delta) {
        streamingContentRef.current += delta
        setStreamingContent(streamingContentRef.current)
        onMessageRef.current?.(streamingContentRef.current)
      }
      return
    }

    // Normalize event name for switch (remove 'stream:' prefix)
    const norm = e.startsWith('stream:') ? e.slice(7) : e

    switch (norm) {
      case 'start':
        // Connection established — no action needed
        break

      case 'intent_trace': {
        const trace = event.data as IntentTrace
        if (trace && trace.intent) {
          onIntentTraceRef.current?.(trace)
        }
        break
      }

      case 'tool_call': {
        const payload = event.data as ToolCallPayload
        if (payload?.call_id) {
          onToolCallRef.current?.(payload)
          // Track call_id → step key for correlating with tool_result
          stepCallIdsRef.current.set(payload.call_id, payload.call_id)
          setSteps((prev) => [
            ...prev,
            {
              step: payload.call_id,
              message: `调用工具: ${payload.tool_name}`,
              status: 'running',
              timestamp: payload.event_timestamp,
            },
          ])
        }
        break
      }

      case 'tool_result': {
        const payload = event.data as ToolResultPayload
        if (payload?.call_id) {
          onToolResultRef.current?.(payload)
          const key = stepCallIdsRef.current.get(payload.call_id)
          if (key) {
            setSteps((prev) =>
              prev.map((s) =>
                s.step === key
                  ? { ...s, status: 'completed', timestamp: payload.event_timestamp }
                  : s,
              ),
            )
            stepCallIdsRef.current.delete(payload.call_id)
          }
        }
        break
      }

      case 'step': {
        const data = event.data as Record<string, unknown>
        const stepName = typeof data.step === 'string' ? data.step : undefined
        const stepMsg = typeof data.public_message === 'string'
          ? data.public_message
          : typeof data.message === 'string'
            ? data.message
            : ''
        const stepTs = typeof data.event_timestamp === 'string' ? data.event_timestamp : undefined
        // 后端可能直接带 status 字段（Policy QA 端点），也可能依赖 step_complete 事件
        const stepStatus = typeof data.status === 'string'
          ? (data.status === 'done' ? 'completed' as const
            : data.status === 'running' ? 'running' as const
            : data.status === 'error' ? 'error' as const
            : 'running' as const)
          : 'running' as const

        if (stepName) {
          onStepRef.current?.(stepName, stepMsg)
          setSteps((prev) => {
            const existing = prev.find((s) => s.step === stepName)
            if (existing) {
              return prev.map((s) =>
                s.step === stepName
                  ? { ...s, message: stepMsg || s.message, status: stepStatus, timestamp: stepTs || s.timestamp }
                  : s,
              )
            }
            return [...prev, { step: stepName, message: stepMsg, status: stepStatus, timestamp: stepTs }]
          })
        }
        break
      }

      case 'step_complete': {
        const data = event.data as Record<string, unknown>
        const stepName = typeof data.step === 'string' ? data.step : undefined

        if (stepName) {
          setSteps((prev) =>
            prev.map((s) =>
              s.step === stepName ? { ...s, status: 'completed' } : s,
            ),
          )
        }
        break
      }

      case 'final': {
        // 标记所有剩余 running 步骤为 completed
        setSteps((prev) =>
          prev.map((s) => (s.status === 'running' ? { ...s, status: 'completed' as const } : s)),
        )
        const response = event.data as AgentResponse
        if (response && response.status) {
          onFinalRef.current?.(response)
        }
        break
      }

      case 'error': {
        const data = event.data as Record<string, unknown>
        const errorMsg =
          typeof data.message === 'string' ? data.message : typeof data === 'string' ? data : 'SSE 流式错误'
        const streamError = new Error(errorMsg)
        setError(streamError)
        updateStatus('error')
        onErrorRef.current?.(streamError)
        break
      }

      case 'done':
        // 标记所有剩余 running 步骤为 completed
        setSteps((prev) =>
          prev.map((s) => (s.status === 'running' ? { ...s, status: 'completed' as const } : s)),
        )
        updateStatus('closed')
        break
    }
  }, [updateStatus])

  // ── Main effect: start/restart stream ──
  useEffect(() => {
    // Build a stable key to prevent duplicate starts for the same logical request
    const requestKey = request
      ? `${request.message}|${request.role}|${request.user_id}|${request.patient_id ?? ''}|${request.encounter_id ?? ''}`
      : ''

    if (!request || !enabled) return

    // Skip if this exact request was already started
    if (requestKey === lastRequestKeyRef.current) return
    lastRequestKeyRef.current = requestKey

    // Cancel any previous connection
    cancelRef.current?.()

    // Reset state
    clear()
    updateStatus('connecting')
    setError(null)

    let cancelled = false

    const startStream = async (): Promise<void> => {
      try {
        const { cancel: cancelFn } = await sendChatStream(request, (event: SseEvent) => {
          if (cancelled) return
          handleSseEvent(event)
        })

        // If cancelled during the await, clean up immediately
        if (cancelled) {
          cancelFn()
          return
        }

        cancelRef.current = cancelFn
        // Stream completed — mark as closed (works with or without server 'done' event)
        updateStatus('closed')
      } catch (err: unknown) {
        if (cancelled) return

        // sendChatStream swallows abort errors internally, so this catch
        // only fires for unexpected errors (HTTP 4xx/5xx, etc.)
        const streamError = err instanceof Error ? err : new Error(String(err))
        setError(streamError)
        updateStatus('error')
        onErrorRef.current?.(streamError)
      }
    }

    startStream()

    return () => {
      cancelled = true
      cancelRef.current?.()
      cancelRef.current = null
    }
  }, [
    // Stringify request fields to trigger restart on meaningful changes
    request?.message,
    request?.role,
    request?.user_id,
    request?.patient_id,
    request?.encounter_id,
    enabled,
    updateStatus,
    clear,
    handleSseEvent,
  ])

  return {
    status,
    cancel,
    streamingContent,
    steps,
    error,
    clear,
  }
}
