'use client'

import { useState } from 'react'
import { Clock, FlaskConical, History, Loader2, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { testModel, testModelStream } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import type { ModelTestResponse, SseEvent } from '@/lib/types'

const scenes = ['default', 'settlement_exception', 'pre_discharge_qc', 'drg_analysis'] as const
const modes = ['sync', 'stream'] as const
const streamTextFields = ['token', 'delta', 'content', 'text', 'message'] as const

type ModelScene = (typeof scenes)[number]
type TestMode = (typeof modes)[number]

interface HistoryItem {
  id: string
  scene: ModelScene
  message: string
  result: ModelTestResponse
  createdAt: string
}

const sceneLabels: Record<ModelScene, string> = {
  default: '默认场景',
  settlement_exception: '结算异常',
  pre_discharge_qc: '出院前质控',
  drg_analysis: 'DRG 分析',
}

const modeLabels: Record<TestMode, string> = {
  sync: '同步',
  stream: '流式',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isModelScene(value: unknown): value is ModelScene {
  return typeof value === 'string' && scenes.includes(value as ModelScene)
}

function isTestMode(value: unknown): value is TestMode {
  return typeof value === 'string' && modes.includes(value as TestMode)
}

function hasFallbackFlag(value: unknown): boolean {
  return isRecord(value) && value.fallback === true
}

function safeStringify(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }

  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

function streamContent(data: unknown): string {
  if (typeof data === 'string' || typeof data === 'number' || typeof data === 'boolean') {
    return String(data)
  }

  if (isRecord(data)) {
    for (const field of streamTextFields) {
      const value = data[field]
      if (typeof value === 'string') {
        return value
      }
    }
  }

  return ''
}

function numberField(data: unknown, field: string): number | null {
  if (!isRecord(data)) {
    return null
  }

  const value = data[field]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function stringField(data: unknown, field: string): string | null {
  if (!isRecord(data)) {
    return null
  }

  const value = data[field]
  return typeof value === 'string' && value.trim() ? value : null
}

function createStreamResult(content: string, finalData: unknown, startedAt: number, fallback: boolean): ModelTestResponse {
  return {
    content,
    model_name: stringField(finalData, 'model_name') ?? 'streaming-model',
    latency_ms: numberField(finalData, 'latency_ms') ?? Math.max(0, Date.now() - startedAt),
    prompt_tokens: numberField(finalData, 'prompt_tokens') ?? 0,
    completion_tokens: numberField(finalData, 'completion_tokens') ?? 0,
    fallback: fallback || hasFallbackFlag(finalData) || undefined,
  }
}

function errorMessage(data: unknown): string {
  if (isRecord(data) && typeof data.message === 'string') {
    return data.message
  }

  return safeStringify(data)
}

function createHistoryItem(scene: ModelScene, message: string, result: ModelTestResponse): HistoryItem {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    scene,
    message,
    result,
    createdAt: new Date().toLocaleString('zh-CN'),
  }
}

function contentSummary(content: string): string {
  const summary = content.trim().replace(/\s+/g, ' ').slice(0, 120)
  return summary || '无内容摘要'
}

function tokenProgress(result: ModelTestResponse): number {
  return Math.min(result.prompt_tokens + result.completion_tokens, 100)
}

export default function ModelTest() {
  const { setConnected, setFallback } = useApiContext()
  const [message, setMessage] = useState('请解释医保结算失败 ERR_001 的原因')
  const [scene, setScene] = useState<ModelScene>('default')
  const [mode, setMode] = useState<TestMode>('sync')
  const [result, setResult] = useState<ModelTestResponse | null>(null)
  const [streamText, setStreamText] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addHistory = (response: ModelTestResponse, requestMessage: string) => {
    setHistory((current) => [createHistoryItem(scene, requestMessage, response), ...current])
  }

  const runSync = async () => {
    const requestMessage = message.trim()
    if (!requestMessage) {
      return
    }

    setLoading(true)
    setError(null)
    setStreamText('')

    try {
      const response = await testModel({ message: requestMessage, scene })
      setResult(response)
      addHistory(response, requestMessage)

      if (response.fallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '模型测试失败')
    } finally {
      setLoading(false)
    }
  }

  const runStream = async () => {
    const requestMessage = message.trim()
    if (!requestMessage) {
      return
    }

    const streamState: {
      fallbackDetected: boolean
      finalResult: ModelTestResponse | null
      finalData: unknown
      completed: boolean
      errored: boolean
      content: string
    } = {
      fallbackDetected: false,
      finalResult: null,
      finalData: null,
      completed: false,
      errored: false,
      content: '',
    }
    const startedAt = Date.now()

    const appendStreamContent = (chunk: string) => {
      if (!chunk) {
        return
      }

      streamState.content += chunk
      setStreamText(streamState.content)
    }

    const finalizeStream = (finalData: unknown) => {
      if (streamState.errored || streamState.completed) {
        return
      }

      streamState.finalData = finalData
      streamState.finalResult = createStreamResult(
        streamState.content,
        finalData,
        startedAt,
        streamState.fallbackDetected
      )
      streamState.completed = true
      setResult(streamState.finalResult)
    }

    setLoading(true)
    setError(null)
    setResult(null)
    setStreamText('')

    try {
      await testModelStream({ message: requestMessage, scene }, (event: SseEvent) => {
        if (streamState.errored) {
          return
        }

        if (hasFallbackFlag(event.data)) {
          streamState.fallbackDetected = true
        }

        if (event.event === 'start') {
          return
        }

        if (event.event === 'token' || event.event === 'delta') {
          appendStreamContent(streamContent(event.data))
          return
        }

        if (event.event === 'final') {
          appendStreamContent(streamContent(event.data))
          finalizeStream(event.data)
          return
        }

        if (event.event === 'done') {
          finalizeStream(streamState.finalData ?? event.data)
          return
        }

        if (event.event === 'error') {
          streamState.errored = true
          streamState.finalResult = null
          setResult(null)
          setError(errorMessage(event.data))
        }
      })

      if (!streamState.errored && !streamState.completed) {
        finalizeStream(streamState.finalData)
      }

      if (!streamState.errored && streamState.finalResult) {
        addHistory(streamState.finalResult, requestMessage)
      }

      if (streamState.errored || !streamState.finalResult) {
        return
      }

      if (streamState.fallbackDetected || streamState.finalResult.fallback) {
        setFallback()
      } else {
        setConnected()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '流式测试失败')
    } finally {
      setLoading(false)
    }
  }

  const run = () => {
    if (mode === 'sync') {
      void runSync()
      return
    }

    void runStream()
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 min-h-[calc(100vh-220px)]">
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <FlaskConical className="w-5 h-5" />
            模型测试参数
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-xs text-gray-500 mb-2">场景</p>
            <Select
              value={scene}
              onValueChange={(value) => {
                if (isModelScene(value)) {
                  setScene(value)
                }
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {scenes.map((item) => (
                  <SelectItem key={item} value={item}>
                    {sceneLabels[item]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <p className="text-xs text-gray-500 mb-2">模式</p>
            <Select
              value={mode}
              onValueChange={(value) => {
                if (isTestMode(value)) {
                  setMode(value)
                }
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {modes.map((item) => (
                  <SelectItem key={item} value={item}>
                    {modeLabels[item]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            className="min-h-[160px]"
            placeholder="输入模型测试消息"
          />

          <Button onClick={run} disabled={loading || !message.trim()} className="w-full">
            {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />}
            {loading ? '测试中...' : '发送测试'}
          </Button>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </CardContent>
      </Card>

      <Card className="lg:col-span-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="w-5 h-5" />
            测试结果
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {mode === 'sync' && result && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <Metric label="模型" value={result.model_name} />
                <Metric label="延迟" value={`${result.latency_ms}ms`} />
                <Metric label="Prompt Tokens" value={String(result.prompt_tokens)} />
                <Metric label="Completion Tokens" value={String(result.completion_tokens)} />
              </div>
              <pre className="bg-gray-50 rounded-lg p-4 whitespace-pre-wrap text-sm min-h-[180px]">
                {result.content}
              </pre>
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Token 用量</span>
                  <span className="font-medium">{result.prompt_tokens + result.completion_tokens}</span>
                </div>
                <Progress value={tokenProgress(result)} className="h-2" />
              </div>
              {result.fallback && <Badge variant="outline">离线模式 - 演示数据</Badge>}
            </div>
          )}

          {mode === 'sync' && !result && (
            <div className="bg-gray-50 rounded-lg p-4 min-h-[300px] flex items-center justify-center text-sm text-gray-500">
              等待同步测试结果
            </div>
          )}

          {mode === 'stream' && (
            <pre className="bg-slate-900 text-blue-100 rounded-lg p-4 min-h-[300px] whitespace-pre-wrap text-sm overflow-auto">
              {streamText || '等待流式输出'}
            </pre>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-4">
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-2">
              <History className="w-5 h-5" />
              测试历史
            </span>
            <Button variant="outline" size="sm" onClick={() => setHistory([])} disabled={history.length === 0}>
              清除历史
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {history.length === 0 && <p className="text-sm text-gray-500">暂无测试历史</p>}
          {history.map((item) => (
            <Card key={item.id} className="p-4 hover:shadow-lg transition-shadow">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{sceneLabels[item.scene]}</Badge>
                    <span className="text-sm text-gray-500">{item.createdAt}</span>
                    {item.result.fallback && <Badge variant="outline">离线模式</Badge>}
                  </div>
                  <p className="text-sm text-gray-700 mt-2 line-clamp-2">{item.message}</p>
                  <p className="text-sm text-gray-900 mt-1 line-clamp-2">{contentSummary(item.result.content)}</p>
                </div>
                <Badge className="bg-blue-100 text-blue-800 shrink-0">
                  <Clock className="w-3 h-3 mr-1" />
                  {item.result.latency_ms}ms
                </Badge>
              </div>
            </Card>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-4 bg-gray-50 rounded-lg text-center">
      <p className="text-xl font-bold">{value}</p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  )
}
