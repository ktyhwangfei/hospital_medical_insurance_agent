'use client'

import { useState, useRef, useEffect } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import {
  Send,
  Bot,
  User,
  AlertTriangle,
  Loader2,
  AlertCircle,
  HelpCircle,
  ShieldCheck,
  Target,
  BrainCircuit,
  RotateCcw,
  GitBranch,
  Database,
  FileText,
  Workflow,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Zap,
} from 'lucide-react'
import { sendChatStream, confirmTask } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { ApiClientError } from '@/lib/types'
import type { AgentResponse, ChatRequest, Citation, SseEvent, IntentTrace } from '@/lib/types'
import IntentTraceCard from './intent-trace-card'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  kind?: 'normal' | 'clarification' | 'confirmation'
}

interface PendingConfirmation {
  taskId: string
  description: string
}

type StageStatus = 'pending' | 'running' | 'done' | 'blocked'

interface PipelineStage {
  id: string
  label: string
  description: string
  status: StageStatus
}

const streamTextFields = ['token', 'delta', 'content', 'text', 'message'] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasFallbackFlag(value: unknown): boolean {
  return isRecord(value) && value.fallback === true
}

function streamContent(data: unknown): string {
  if (typeof data === 'string' || typeof data === 'number' || typeof data === 'boolean') {
    return String(data)
  }
  if (isRecord(data)) {
    for (const field of streamTextFields) {
      const value = data[field]
      if (typeof value === 'string') return value
    }
  }
  return ''
}

function extractContent(result: Record<string, unknown>): string {
  const content = result.content
  if (typeof content === 'string') return content

  if (result.skill_name && result.steps_completed) {
    const outputs = result.outputs as Record<string, unknown> | undefined
    let text = `📋 技能执行完成: ${result.skill_name}\n`
    const steps = result.steps_completed as string[]
    text += `✅ 已完成步骤: ${steps.join(' → ')}\n`
    if (outputs && typeof outputs === 'object') {
      for (const [stepId, stepResult] of Object.entries(outputs)) {
        const sr = stepResult as Record<string, unknown>
        const output = sr.output as Record<string, unknown> | undefined
        if (output && typeof output === 'object' && Object.keys(output).length > 0) {
          text += `\n📌 ${stepId}:\n`
          for (const [key, val] of Object.entries(output)) {
            if (val !== null && val !== undefined && val !== '') {
              text += `  - ${key}: ${typeof val === 'string' ? val : JSON.stringify(val)}\n`
            }
          }
        }
      }
    }
    return text
  }

  if (result.exception_type || result.error_code) {
    let text = '🔍 结算异常分析结果\n\n'
    if (result.error_code) text += `❌ 错误码: ${result.error_code}\n`
    if (result.exception_type) text += `⚠️ 异常类型: ${result.exception_type}\n`
    if (result.error_explanation) text += `📝 说明: ${result.error_explanation}\n`
    if (result.responsible_role) text += `👤 责任角色: ${result.responsible_role}\n`
    const steps = result.recommended_steps as string[] | undefined
    if (steps && steps.length > 0) {
      text += '\n📋 处理建议:\n'
      steps.forEach((s, i) => { text += `  ${i + 1}. ${s}\n` })
    }
    return text
  }

  if (result.qc_recommendation || result.risks) {
    let text = '🏥 出院前质控分析结果\n\n'
    const risks = result.risks as Array<Record<string, unknown>> | undefined
    if (risks && risks.length > 0) {
      text += '⚠️ 风险项:\n'
      risks.forEach((r, i) => {
        text += `  ${i + 1}. [${r.risk_level || '中'}] ${r.risk_type || ''} - ${r.recommendation || ''}\n`
        if (r.responsible_role) text += `     责任角色: ${r.responsible_role}\n`
      })
    }
    if (result.qc_recommendation) text += `\n💡 建议: ${result.qc_recommendation}\n`
    return text
  }

  if (result.message && typeof result.message === 'string') {
    return result.message
  }

  if (content === null || content === undefined) {
    const meaningfulKeys = Object.keys(result).filter(
      (k) => result[k] !== null && result[k] !== undefined && result[k] !== ''
    )
    if (meaningfulKeys.length === 0) return '🤔 未能获取到有效信息，请换个方式提问试试。'
    return JSON.stringify(result, null, 2)
  }

  if (typeof content === 'object' && Object.keys(content as object).length === 0) {
    const resultKeys = Object.keys(result).filter((k) => k !== 'content')
    if (resultKeys.length === 0) return '🤔 未能获取到有效信息，请换个方式提问试试。'
    return JSON.stringify(result, null, 2)
  }

  return JSON.stringify(content, null, 2)
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function intentIdToLabel(intentId: string): string {
  const labels: Record<string, string> = {
    settlement_exception_guidance: '医保结算异常导办',
    pre_discharge_quality_control: '出院前联合质控',
    high_risk_action_confirmation: '高风险动作确认',
    mcp_tool_invocation: 'MCP 工具调用',
    denial_appeal_assistant: '拒付申诉助手',
    policy_rule_explanation: '政策规则解释',
    unknown: '待澄清场景',
  }
  return labels[intentId] ?? intentId
}

function intentStatusLabel(status: string): string {
  if (status === 'routed') return '已路由'
  if (status === 'needs_clarification') return '需澄清'
  if (status === 'fallback_keyword') return '关键词降级'
  return status || '等待'
}

function stageStyle(status: StageStatus): string {
  const styles: Record<StageStatus, string> = {
    pending: 'border-slate-200/60 bg-slate-50/50 text-slate-500',
    running: 'border-blue-200/80 bg-blue-50/60 text-blue-700',
    done: 'border-emerald-200/80 bg-emerald-50/60 text-emerald-700',
    blocked: 'border-amber-200/80 bg-amber-50/60 text-amber-700',
  }
  return styles[status]
}

function stageIcon(status: StageStatus) {
  if (status === 'done') return <span className="w-3.5 h-3.5 text-emerald-500">✓</span>
  if (status === 'blocked') return <AlertTriangle className="w-3.5 h-3.5" />
  if (status === 'running') return <Loader2 className="w-3.5 h-3.5 animate-spin" />
  return <span className="w-3.5 h-3.5 text-slate-400">○</span>
}

export default function EmbeddedChat() {
  const { connectionStatus, setConnected, setFallback } = useApiContext()
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content:
        '您好！我是医保AI导办助手 🤖\n\n我可以帮您：\n• 查询医保结算异常原因\n• 解释医保错误码\n• 生成出院前质控清单\n• 分析DRG/DIP盈亏情况\n• 提供处理步骤导办\n\n请告诉我您需要什么帮助？',
    },
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null)
  const [confirmReason, setConfirmReason] = useState('')
  const [isConfirming, setIsConfirming] = useState(false)
  const [intentTrace, setIntentTrace] = useState<IntentTrace | null>(null)
  const [showIntentPanel, setShowIntentPanel] = useState(false)
  const scrollBottomRef = useRef<HTMLDivElement>(null)

  const role = 'cashier'
  const patientId = 'P001'
  const encounterId = 'E001'

  useEffect(() => {
    scrollBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent])

  const handleSend = async (text?: string) => {
    const messageText = text || input
    if (!messageText.trim() || isLoading) return

    setMessages((prev) => [...prev, { role: 'user', content: messageText }])
    setIntentTrace(null)
    setInput('')
    setIsLoading(true)
    setIsStreaming(true)
    setStreamingContent('')

    const request: ChatRequest = {
      message: messageText,
      user_id: 'demo',
      role,
      patient_id: patientId,
      encounter_id: encounterId,
    }

    const streamState = {
      content: '',
      errored: false,
      completed: false,
      fallbackDetected: false,
      finalResult: null as unknown,
    }

    const streamTimeout = setTimeout(() => {
      if (!streamState.completed && !streamState.errored) {
        streamState.errored = true
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: '⏱️ 请求超时\n后端服务响应超时（30秒），请检查后端服务状态或重试。' },
        ])
        setIsLoading(false)
        setIsStreaming(false)
        setStreamingContent('')
      }
    }, 30000)

    try {
      await sendChatStream(request, (event: SseEvent) => {
        if (streamState.errored || streamState.completed) return

        if (hasFallbackFlag(event.data)) {
          streamState.fallbackDetected = true
        }

        if (event.event === 'start') return

        if (event.event === 'intent_trace') {
          const trace = event.data as IntentTrace
          if (trace && trace.intent) {
            setIntentTrace(trace)
            setShowIntentPanel(true)
          }
          return
        }

        if (event.event === 'token' || event.event === 'delta') {
          const chunk = streamContent(event.data)
          streamState.content += chunk
          setStreamingContent(streamState.content)
          return
        }

        if (event.event === 'final') {
          streamState.completed = true
          streamState.finalResult = event.data
          const agentResponse = event.data as AgentResponse
          const result = (agentResponse.result || agentResponse) as Record<string, unknown>
          const content = extractContent(result)
          const kind =
            agentResponse.status === 'needs_clarification'
              ? 'clarification'
              : agentResponse.status === 'waiting_human_confirmation'
                ? 'confirmation'
                : 'normal'
          setMessages((prev) => [
            ...prev,
            {
              role: 'assistant',
              content,
              fallback: streamState.fallbackDetected || undefined,
              kind,
            },
          ])

          if (
            agentResponse.status === 'waiting_human_confirmation' &&
            agentResponse.tasks.length > 0
          ) {
            const task = agentResponse.tasks[0]
            const taskId = task.task_id
            if (taskId) {
              setPendingConfirmation({
                taskId,
                description: task.description || task.action || '高风险操作',
              })
            }
          }

          if (streamState.fallbackDetected || agentResponse.fallback) {
            setFallback()
          } else {
            setConnected()
          }
          return
        }

        if (event.event === 'done') {
          streamState.completed = true
          if (streamState.content && !streamState.finalResult) {
            setMessages((prev) => [
              ...prev,
              {
                role: 'assistant',
                content: streamState.content,
                fallback: streamState.fallbackDetected || undefined,
              },
            ])
          }
          if (streamState.fallbackDetected) {
            setFallback()
          } else {
            setConnected()
          }
          return
        }

        if (event.event === 'error') {
          streamState.errored = true
          const data = event.data as Record<string, unknown>
          let msg: string
          if (typeof data.message === 'string') {
            msg = data.message
          } else if (isRecord(data.detail)) {
            const detail = data.detail as Record<string, unknown>
            const errorCode = typeof detail.error_code === 'string' ? detail.error_code : 'UNKNOWN'
            msg = typeof detail.message === 'string' ? `[${errorCode}] ${detail.message}` : JSON.stringify(data)
          } else {
            msg = isRecord(data) ? JSON.stringify(data) : '流式传输错误'
          }
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: `❌ 请求失败\n${msg}` },
          ])
        }
      })

      if (!streamState.errored && !streamState.completed) {
        if (streamState.content) {
          setMessages((prev) => [
            ...prev,
            {
              role: 'assistant',
              content: streamState.content,
              fallback: streamState.fallbackDetected || undefined,
            },
          ])
        } else {
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: '🤔 未能获取到有效信息，请换个方式提问试试。' },
          ])
        }
      }
    } catch (error) {
      if (error instanceof ApiClientError) {
        const detail = error.detail
        let suggestion = ''
        if (detail.error_code === 'PERMISSION_DENIED') {
          suggestion = '\n💡 请联系医保办获取权限。'
        }
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `❌ 请求失败\n错误码: ${detail.error_code}\n${detail.message}${suggestion}` },
        ])
      } else {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: '🤔 网络请求失败，请检查后端服务是否正常运行，或等待离线模式自动降级。' },
        ])
      }
    } finally {
      clearTimeout(streamTimeout)
      setIsLoading(false)
      setIsStreaming(false)
      setStreamingContent('')
    }
  }

  const handleTaskConfirm = async (action: 'confirm' | 'reject') => {
    if (!pendingConfirmation) return
    setIsConfirming(true)
    try {
      const result = await confirmTask({
        task_id: pendingConfirmation.taskId,
        action,
        user_id: 'demo',
        reason: confirmReason || undefined,
      })
      const label = action === 'confirm' ? '✅ 已确认执行' : '❌ 已拒绝执行'
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `${label}\n任务: ${pendingConfirmation.description}\n任务ID: ${result.task_id}\n状态: ${result.status}` },
      ])
    } catch (error) {
      if (error instanceof ApiClientError) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `❌ 确认操作失败\n错误码: ${error.detail.error_code}\n${error.detail.message}` },
        ])
      }
    } finally {
      setIsConfirming(false)
      setPendingConfirmation(null)
      setConfirmReason('')
    }
  }

  const quickQuestions = [
    { text: '为什么这个患者结算失败', icon: '🔍' },
    { text: '这个患者出院前还有哪些风险', icon: '🏥' },
    { text: '本月哪个科室DRG亏损最多', icon: '📊' },
  ]

  const intentLabelStr = intentTrace ? intentIdToLabel(intentTrace.intent) : '等待识别'
  const intentConfidence = intentTrace ? clampPercent(intentTrace.confidence * 100) : 0
  const intentStatusStr = intentTrace ? intentStatusLabel(intentTrace.status) : '等待'

  const sidebarCandidates = intentTrace
    ? intentTrace.top_candidates.map((c, i) => ({
        id: c.intent_id,
        label: intentIdToLabel(c.intent_id),
        score: clampPercent(c.score * 100),
        status: i === 0 ? '首选' : '候选',
      }))
    : []

  const sidebarStages: PipelineStage[] = intentTrace
    ? [
        { id: 'recall', label: '候选召回', description: '关键词/语义双路召回', status: intentTrace.top_candidates.length > 0 ? 'done' : 'running' },
        { id: 'llm', label: 'LLM判别', description: '结构化意图判别', status: intentTrace.status === 'needs_clarification' ? 'blocked' : intentTrace.top_candidates.length > 0 ? 'done' : 'running' },
        { id: 'verify', label: '结果校验', description: '字段/权限/风险校验', status: intentTrace.status === 'routed' ? 'done' : 'running' },
        { id: 'route', label: '决策路由', description: '路由至业务场景', status: intentTrace.status === 'routed' ? 'done' : 'blocked' },
      ]
    : []

  const statusLabel =
    connectionStatus === 'connected'
      ? '已连接'
      : connectionStatus === 'fallback'
        ? '离线模式'
        : '未检测'

  const hasCitations =
    intentTrace && intentTrace.citations && intentTrace.citations.length > 0

  return (
    <div className="h-full flex flex-col bg-gradient-to-b from-slate-950 to-slate-900 text-white overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-white/[0.06] px-4 py-3 bg-gradient-to-r from-slate-900 via-slate-900 to-slate-800/90">
        <div className="flex items-center gap-3">
          <div className="relative">
            <Avatar className="h-9 w-9 bg-gradient-to-br from-cyan-400 to-blue-500 shadow-lg shadow-cyan-900/30 ring-2 ring-white/20">
              <AvatarFallback>
                <Bot className="h-5 w-5 text-white" />
              </AvatarFallback>
            </Avatar>
            <span className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-slate-900" />
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold tracking-tight text-white">医保 AI 导办中枢</span>
              {isStreaming && (
                <span className="inline-flex items-center gap-1 text-[10px] text-cyan-300/80">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  识别中
                </span>
              )}
            </div>
            <div className="text-[11px] text-slate-400">收费员视图 · 患者 P001 / 就诊 E001</div>
          </div>
          <Badge variant="outline" className="shrink-0 text-[10px] font-medium px-2 py-0.5 border-white/[0.08] bg-white/[0.06] text-white/80">
            <span className="relative flex h-1.5 w-1.5 mr-1">
              <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${
                connectionStatus === 'connected' ? 'bg-emerald-400' :
                connectionStatus === 'fallback' ? 'bg-amber-400' : 'bg-slate-400'
              } opacity-60`} />
              <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${
                connectionStatus === 'connected' ? 'bg-emerald-500' :
                connectionStatus === 'fallback' ? 'bg-amber-400' : 'bg-slate-400'
              }`} />
            </span>
            {statusLabel}
          </Badge>
        </div>
      </div>

      {/* Main content area: chat + intent sidebar */}
      <div className="flex-1 flex min-h-0">
        {/* Chat column */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages */}
          <ScrollArea className="flex-1 px-4 pt-4 pb-2">
            {intentTrace && (
              <div className="mb-3">
                <IntentTraceCard intentTrace={intentTrace} isStreaming={isStreaming && !streamingContent} />
              </div>
            )}

            <div className="space-y-4">
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex items-end gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
                >
                  {msg.role === 'assistant' ? (
                    <Avatar className="h-8 w-8 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 ring-2 ring-white/10">
                      <AvatarFallback>
                        <Bot className="h-4.5 w-4.5 text-white" />
                      </AvatarFallback>
                    </Avatar>
                  ) : (
                    <Avatar className="h-8 w-8 shrink-0 bg-white/[0.08] border border-white/[0.06]">
                      <AvatarFallback>
                        <User className="h-4.5 w-4.5 text-slate-300" />
                      </AvatarFallback>
                    </Avatar>
                  )}
                  <div className={`max-w-[80%] flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                    <div
                      className={`px-4 py-2.5 text-sm leading-relaxed tracking-normal whitespace-pre-wrap ${
                        msg.role === 'user'
                          ? 'bg-gradient-to-br from-cyan-400 to-blue-500 text-white rounded-2xl rounded-tr-md shadow-lg shadow-cyan-900/25'
                          : msg.kind === 'clarification'
                            ? 'bg-gradient-to-br from-amber-50 to-amber-100/80 text-amber-950 border border-amber-200/60 rounded-2xl rounded-tl-md'
                            : msg.kind === 'confirmation'
                              ? 'bg-gradient-to-br from-rose-50 to-rose-100/80 text-rose-950 border border-rose-200/60 rounded-2xl rounded-tl-md'
                              : msg.fallback
                                ? 'bg-gradient-to-br from-amber-50/95 to-amber-100/70 text-slate-800 border border-amber-200/70 rounded-2xl rounded-tl-md'
                                : 'bg-white/95 text-slate-800 border border-white/20 rounded-2xl rounded-tl-md'
                      }`}
                    >
                      {msg.kind === 'clarification' && (
                        <div className="mb-2 flex items-center gap-1.5 rounded-xl bg-white/70 px-2.5 py-1.5 text-[11px] font-semibold text-amber-800 border border-amber-200/40">
                          <HelpCircle className="w-3.5 h-3.5" /> 需要补充业务场景后继续导办
                        </div>
                      )}
                      {msg.kind === 'confirmation' && (
                        <div className="mb-2 flex items-center gap-1.5 rounded-xl bg-white/70 px-2.5 py-1.5 text-[11px] font-semibold text-rose-800 border border-rose-200/40">
                          <ShieldCheck className="w-3.5 h-3.5" /> 命中高风险动作，已转人工确认
                        </div>
                      )}
                      {msg.content}
                      {msg.fallback && (
                        <div className="flex items-center gap-1.5 mt-2.5 pt-2 border-t border-amber-200/40">
                          <AlertCircle className="w-3 h-3 text-amber-500 shrink-0" />
                          <span className="text-[10px] font-medium text-amber-600">离线演示模式</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}

              {isStreaming && streamingContent && (
                <div className="flex items-end gap-2.5 flex-row">
                  <Avatar className="h-8 w-8 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 ring-2 ring-white/10">
                    <AvatarFallback>
                      <Bot className="h-4.5 w-4.5 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="max-w-[80%]">
                    <div className="bg-white/95 text-slate-800 border border-white/20 rounded-2xl rounded-tl-md px-4 py-2.5">
                      <span className="text-sm leading-relaxed whitespace-pre-wrap">{streamingContent}</span>
                      <span className="inline-block w-[2px] h-[1em] bg-blue-500 animate-pulse ml-0.5 align-text-bottom" />
                    </div>
                  </div>
                </div>
              )}

              {isLoading && !isStreaming && (
                <div className="flex items-end gap-2.5 flex-row">
                  <Avatar className="h-8 w-8 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 ring-2 ring-white/10">
                    <AvatarFallback>
                      <Bot className="h-4.5 w-4.5 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="border border-white/20 rounded-2xl rounded-tl-md px-4 py-3 bg-white/95">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-slate-500">识别中</span>
                      <div className="flex gap-1">
                        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '0ms' }} />
                        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
                        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '600ms' }} />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div ref={scrollBottomRef} />
            </div>
          </ScrollArea>

          {/* Quick questions */}
          <div className="shrink-0 px-4 pt-2 pb-1.5 flex gap-1.5 overflow-x-auto">
            {quickQuestions.map((q) => (
              <button
                key={q.text}
                onClick={() => handleSend(q.text)}
                disabled={isLoading}
                className="shrink-0 inline-flex items-center gap-1 rounded-full border border-white/[0.08] bg-white/[0.04] px-2.5 py-1 text-[11px] text-slate-300 hover:bg-white/[0.08] hover:text-white transition-colors disabled:opacity-40"
              >
                <span className="text-xs">{q.icon}</span>
                <span>{q.text}</span>
              </button>
            ))}
          </div>

          {/* Input area */}
          <div className="shrink-0 px-4 pb-3 pt-1.5 bg-slate-900/80">
            <div className="flex gap-2 items-end">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                placeholder="描述您的问题…"
                className="flex-1 h-auto py-2.5 px-3.5 text-sm bg-white/[0.06] text-white/90 placeholder:text-slate-500 border-white/[0.08] rounded-xl focus:bg-white/[0.1] focus:ring-2 focus:ring-blue-400/15 focus:border-blue-400/40"
                disabled={isLoading}
              />
              <Button
                onClick={() => handleSend()}
                disabled={isLoading || !input.trim()}
                size="icon"
                className="h-[42px] w-[42px] shrink-0 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 text-white hover:from-blue-400 hover:to-blue-500 disabled:from-slate-700 disabled:to-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed shadow-lg shadow-blue-900/30 active:scale-95"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </Button>
            </div>
          </div>
        </div>

        {/* Intent/RAG sidebar — visible on xl+ screens */}
        {intentTrace && (
          <aside className="hidden xl:flex flex-col w-[300px] shrink-0 border-l border-white/[0.06] bg-slate-900/60">
            <div className="border-b border-white/[0.06] px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-white/90">
                <Zap className="w-4 h-4 text-cyan-400" />
                意图 / RAG 过程
              </div>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">问题改写、候选召回、LLM 判别与路由校验</p>
            </div>
            <ScrollArea className="flex-1 p-4">
              <div className="space-y-4">
                {/* Query Rewrite */}
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
                    <RotateCcw className="w-3 h-3 text-cyan-400/70" /> Query Rewrite
                  </div>
                  <div className="rounded-lg bg-slate-950/60 p-2.5 text-[11px] leading-relaxed text-slate-500">
                    <div className="mb-1 text-slate-600">原始问题</div>
                    <div className="text-slate-200">{intentTrace.original_message || '（无）'}</div>
                    {intentTrace.rewrite_changes.length > 0 && (
                      <>
                        <div className="mt-2 mb-1 text-slate-600">改写变化</div>
                        {intentTrace.rewrite_changes.map((change, i) => (
                          <div key={i} className="text-cyan-200/90">{change}</div>
                        ))}
                      </>
                    )}
                  </div>
                </div>

                {/* TopN candidates */}
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
                    <GitBranch className="w-3 h-3 text-violet-400/70" /> TopN 候选意图
                  </div>
                  <div className="space-y-2.5">
                    {sidebarCandidates.length > 0 ? sidebarCandidates.map((candidate) => (
                      <div key={candidate.id} className="space-y-1">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span className="truncate font-medium text-slate-200">{candidate.label}</span>
                          <span className="shrink-0 text-slate-500">{candidate.score}%</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-cyan-400/80 to-violet-400/80"
                            style={{ width: `${candidate.score}%` }}
                          />
                        </div>
                        <Badge variant="outline" className="border-white/[0.06] bg-white/[0.04] px-1.5 py-0 text-[10px] text-slate-400">
                          {candidate.status}
                        </Badge>
                      </div>
                    )) : (
                      <div className="text-[11px] text-slate-500">暂无候选意图</div>
                    )}
                  </div>
                </div>

                {/* RAG citations */}
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
                    <Database className="w-3 h-3 text-emerald-400/70" /> RAG 依据召回
                  </div>
                  <div className="space-y-2">
                    {hasCitations ? intentTrace.citations.map((citation, i) => (
                      <div key={i} className="rounded-lg border border-white/[0.06] bg-slate-950/50 p-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-xs font-semibold text-white/80">引用 {i + 1}</span>
                          <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-[10px] text-emerald-300">{90 - i * 5}</span>
                        </div>
                        <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">{citation}</p>
                      </div>
                    )) : (
                      <div className="text-[11px] text-slate-500">暂无引用依据</div>
                    )}
                  </div>
                </div>

                {/* Pipeline stages */}
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
                    <ShieldCheck className="w-3 h-3 text-amber-400/70" /> 处理链路
                  </div>
                  <div className="space-y-2">
                    {sidebarStages.map((stage) => (
                      <div key={stage.id} className={`rounded-lg border px-2.5 py-2 ${stageStyle(stage.status)}`}>
                        <div className="flex items-center gap-1.5 text-xs font-semibold">
                          {stageIcon(stage.status)}
                          {stage.label}
                        </div>
                        <div className="mt-0.5 text-[10px] leading-relaxed opacity-80">{stage.description}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Audit trail */}
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
                    <FileText className="w-3 h-3 text-blue-400/70" /> 审计追踪
                  </div>
                  <div className="rounded-lg bg-slate-950/60 p-2.5 text-[11px] leading-relaxed text-slate-500">
                    <div>workflow_id: <span className="text-slate-200">wf-intent-{intentTrace.intent}</span></div>
                    <div>citations: <span className="text-slate-200">{intentTrace.citations.length}</span></div>
                    <div>guardrail: <span className="text-slate-200">高风险动作统一转人工确认</span></div>
                  </div>
                </div>
              </div>
            </ScrollArea>
          </aside>
        )}
      </div>

      {/* Intent trace toggle for small screens */}
      {intentTrace && (
        <div className="xl:hidden shrink-0 border-t border-white/[0.06]">
          <button
            onClick={() => setShowIntentPanel(!showIntentPanel)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs text-slate-400 hover:text-white transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <Target className="w-3.5 h-3.5 text-cyan-400" />
              意图识别详情
            </span>
            {showIntentPanel ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          </button>
          {showIntentPanel && (
            <div className="max-h-[200px] overflow-y-auto border-t border-white/[0.06] bg-slate-900/80 p-3">
              <div className="flex items-center gap-3 mb-3 text-xs">
                <div className="flex items-center gap-1.5">
                  <Target className="w-3 h-3 text-cyan-400" />
                  <span className="text-slate-300">{intentLabelStr}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <BrainCircuit className="w-3 h-3 text-violet-400" />
                  <span className="text-slate-400">{intentConfidence}%</span>
                </div>
                <Badge variant="outline" className="border-white/[0.06] bg-white/[0.04] text-[10px] text-slate-400">
                  {intentStatusStr}
                </Badge>
              </div>
              {hasCitations && (
                <div className="space-y-1.5">
                  <div className="text-[11px] font-semibold text-slate-400 flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-blue-400/70" />
                    引用依据
                  </div>
                  {intentTrace.citations.map((citation, i) => (
                    <div key={i} className="text-[11px] text-slate-400 leading-relaxed">
                      <span className="text-slate-600">{i + 1}.</span> {citation}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Confirmation dialog */}
      <Dialog
        open={!!pendingConfirmation}
        onOpenChange={(open) => {
          if (!open) {
            setPendingConfirmation(null)
            setConfirmReason('')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-100">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
              </div>
              高风险操作确认
            </DialogTitle>
            <DialogDescription>
              此操作需要人工确认后才能在业务系统中执行。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="rounded-xl bg-gradient-to-br from-amber-50 to-amber-100/50 border border-amber-200/60 p-4">
              <p className="text-sm font-medium text-amber-900">
                {pendingConfirmation?.description}
              </p>
              <p className="text-xs text-amber-600 mt-1.5 font-mono">
                任务ID: {pendingConfirmation?.taskId}
              </p>
            </div>

            <Textarea
              value={confirmReason}
              onChange={(e) => setConfirmReason(e.target.value)}
              placeholder="请输入确认/拒绝原因（可选）"
              className="min-h-[80px] border-slate-200 focus:border-amber-300 focus:ring-amber-200/30"
            />
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => handleTaskConfirm('reject')}
              disabled={isConfirming}
              className="border-slate-200 hover:bg-slate-50"
            >
              拒绝执行
            </Button>
            <Button
              onClick={() => handleTaskConfirm('confirm')}
              disabled={isConfirming}
              className="bg-gradient-to-br from-amber-500 to-amber-600 text-white hover:from-amber-400 hover:to-amber-500 shadow-sm"
            >
              {isConfirming ? '处理中...' : '确认执行'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
