'use client'

import { useState, useEffect, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
  Sparkles,
  AlertTriangle,
  Loader2,
  AlertCircle,
  BrainCircuit,
  GitBranch,
  ShieldCheck,
  FileText,
  RotateCcw,
  CheckCircle2,
  Clock3,
  Database,
  Target,
  Workflow,
  HelpCircle,
  Zap,
} from 'lucide-react'
import { confirmTask } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { ApiClientError } from '@/lib/types'
import type { AgentResponse, ChatRequest, Citation, IntentTrace } from '@/lib/types'
import IntentTraceCard from './intent-trace-card'
import { useChatStream } from '@/lib/sse-hooks'
import type { ConnectionStatus, StreamStepDisplay } from '@/lib/sse-hooks'
import ExecutionTimeline from './chat/execution-timeline'
import type { ExecutionStep } from './chat/execution-timeline'
import { Typewriter } from './chat/typewriter'

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

interface IntentCandidateLocal {
  id: string
  label: string
  score: number
  status: '已实现' | '规划中' | '需澄清'
}

interface RagEvidence {
  title: string
  source: string
  summary: string
  score: number
}

interface GuideTrace {
  originalQuery: string
  rewrittenQuery: string
  intentLabel: string
  confidence: number
  routeStatus: string
  candidates: IntentCandidateLocal[]
  evidences: RagEvidence[]
  stages: PipelineStage[]
  citations: Citation[]
  auditId?: string
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

function roleDisplayName(role: string): string {
  const names: Record<string, string> = {
    cashier: '收费员',
    medical_office: '医保办',
    information_department: '信息科',
    medical_record_staff: '病案室',
    clinician: '临床医生',
  }
  return names[role] ?? '院内用户'
}

function scenarioLabel(scenario?: string | null): string {
  const labels: Record<string, string> = {
    settlement_exception_guidance: '医保结算异常导办',
    pre_discharge_quality_control: '出院前联合质控',
    high_risk_action_confirmation: '高风险动作确认',
    mcp_tool_invocation: 'MCP 工具调用',
    denial_appeal_assistant: '拒付申诉助手',
    policy_rule_explanation: '政策规则解释',
    unknown: '待澄清场景',
  }
  return labels[scenario || 'unknown'] ?? (scenario || '待澄清场景')
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function inferIntentLabel(message: string, response?: AgentResponse): string {
  if (response?.scenario) return scenarioLabel(response.scenario)
  if (/出院|质控|风险/.test(message)) return '出院前联合质控'
  if (/拒付|申诉/.test(message)) return '拒付申诉助手'
  if (/政策|规则|目录|报销/.test(message)) return '政策规则解释'
  if (/画图|流程图|drawio|diagram|导出/.test(message)) return 'MCP 工具调用'
  if (/结算|错误码|报错|收费/.test(message)) return '医保结算异常导办'
  return '待澄清场景'
}

function mockCandidates(message: string, response?: AgentResponse): IntentCandidateLocal[] {
  const primary = inferIntentLabel(message, response)
  const base: IntentCandidateLocal[] = [
    { id: 'settlement_exception_guidance', label: '医保结算异常导办', score: 86, status: '已实现' },
    { id: 'pre_discharge_quality_control', label: '出院前联合质控', score: 73, status: '已实现' },
    { id: 'policy_rule_explanation', label: '政策规则解释', score: 58, status: '规划中' },
  ]
  const selected = base.find((item) => item.label === primary)
  if (selected) {
    return [
      { ...selected, score: response?.status === 'needs_clarification' ? 62 : 91 },
      ...base.filter((item) => item.id !== selected.id).slice(0, 2),
    ]
  }
  return [
    { id: 'unknown', label: '需要补充业务场景', score: 45, status: '需澄清' },
    ...base.slice(0, 2),
  ]
}

function evidenceFromResponse(response?: AgentResponse): RagEvidence[] {
  const citations = response?.citations || []
  if (citations.length > 0) {
    return citations.slice(0, 3).map((citation, index) => ({
      title: citation.source_type || `依据 ${index + 1}`,
      source: citation.source_id || 'runtime-citation',
      summary: citation.summary || '系统返回的业务依据',
      score: 88 - index * 6,
    }))
  }
  return [
    {
      title: '意图知识库 · 医保场景边界',
      source: 'intent-knowledge-base',
      summary: '用于区分结算异常、出院质控、政策解释和拒付申诉等入口场景。',
      score: 84,
    },
    {
      title: '运行时上下文 · 当前患者',
      source: 'runtime-context',
      summary: '结合当前角色、患者 P001、就诊 E001 和页面入口补全导办语义。',
      score: 79,
    },
  ]
}

function buildGuideTrace(message: string, role: string, response?: AgentResponse): GuideTrace {
  const needsClarification = response?.status === 'needs_clarification'
  const waitingConfirmation = response?.status === 'waiting_human_confirmation'
  const blocked = (response?.blocked_actions?.length || 0) > 0
  const intentLabel = inferIntentLabel(message, response)
  const confidence = needsClarification ? 48 : waitingConfirmation ? 89 : response?.status === 'not_implemented' ? 64 : 92

  return {
    originalQuery: message,
    rewrittenQuery: `以${roleDisplayName(role)}身份，围绕当前患者 P001 / E001 处理：${message}`,
    intentLabel,
    confidence,
    routeStatus: needsClarification ? '需要业务澄清' : waitingConfirmation ? '等待人工确认' : response?.status === 'not_implemented' ? '能力未开通' : '已进入导办流程',
    candidates: mockCandidates(message, response),
    evidences: evidenceFromResponse(response),
    stages: [
      { id: 'rewrite', label: 'Query Rewrite', description: '结合角色、患者和页面上下文补全问题', status: 'done' },
      { id: 'retrieval', label: 'RAG 候选召回', description: '召回意图定义、业务术语和场景边界', status: 'done' },
      { id: 'intent', label: 'LLM 意图判别', description: '在候选场景中进行结构化判别', status: needsClarification ? 'blocked' : 'done' },
      { id: 'guardrail', label: '安全与路由校验', description: '检查权限、高风险动作、未开通能力和缺失字段', status: blocked || waitingConfirmation ? 'blocked' : 'done' },
    ],
    citations: response?.citations || [],
    auditId: typeof response?.audit?.workflow_id === 'string' ? response.audit.workflow_id : 'wf-preview-intent',
  }
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
  if (status === 'done') return <CheckCircle2 className="w-3.5 h-3.5" />
  if (status === 'blocked') return <AlertTriangle className="w-3.5 h-3.5" />
  if (status === 'running') return <Loader2 className="w-3.5 h-3.5 animate-spin" />
  return <Clock3 className="w-3.5 h-3.5" />
}

export default function SettlementChat({ currentRole, prefilledMessage, onPrefillConsumed }: { currentRole: string; prefilledMessage?: string; onPrefillConsumed?: () => void }) {
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
  const [isStreaming, setIsStreaming] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null)
  const [confirmReason, setConfirmReason] = useState('')
  const [isConfirming, setIsConfirming] = useState(false)
  const [intentTrace, setIntentTrace] = useState<IntentTrace | null>(null)
  const [streamingRequest, setStreamingRequest] = useState<ChatRequest | null>(null)
  const [streamEnabled, setStreamEnabled] = useState(false)
  const scrollBottomRef = useRef<HTMLDivElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefilledRef = useRef<string | null>(null)

  // ── useChatStream hook ────────────────────────────────────────
  const {
    status: sseStatus,
    cancel: cancelStream,
    streamingContent,
    steps,
    error: streamError,
    clear: clearStream,
  } = useChatStream({
    request: streamingRequest,
    enabled: streamEnabled,
    onIntentTrace: (trace) => {
      setIntentTrace(trace)
    },
    onFinal: (response) => {
      const agentResponse = response as AgentResponse
      const result = (agentResponse.result || agentResponse) as Record<string, unknown>
      const content = extractContent(result)
      const kind = agentResponse.status === 'needs_clarification'
        ? 'clarification'
        : agentResponse.status === 'waiting_human_confirmation'
          ? 'confirmation'
          : 'normal'

      const isFallback = hasFallbackFlag(result) || agentResponse.fallback || false

      setMessages((prev) => [...prev, {
        role: 'assistant',
        content,
        fallback: isFallback || undefined,
        kind,
      }])

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

      if (isFallback) {
        setFallback()
      } else {
        setConnected()
      }
    },
    onError: (error) => {
      console.error('[Chat] Stream error:', error)
      if (error instanceof ApiClientError) {
        const detail = error.detail
        let suggestion = ''
        if (detail.error_code === 'PERMISSION_DENIED') {
          suggestion = '\n💡 请尝试切换到有权限的角色（如医保办）后再提问。'
        }
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `❌ 请求失败\n错误码: ${detail.error_code}\n${detail.message}${suggestion}`,
          },
        ])
      } else {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: '🤔 网络请求失败，请检查后端服务是否正常运行，或等待离线模式自动降级。',
          },
        ])
      }
    },
  })

  useEffect(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTo({
        top: viewportRef.current.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [messages, streamingContent])

    const handleSend = async (text?: string) => {
    const messageText = text || input
    if (!messageText.trim() || isLoading) return

    console.log('[SettlementChat] Sending message:', { message: messageText, role: currentRole, patient_id: 'P001', encounter_id: 'E001' })
    setMessages((prev) => [...prev, { role: 'user', content: messageText }])
    setIntentTrace(null)
    setInput('')
    setIsLoading(true)
    setIsStreaming(true)

    const request: ChatRequest = {
      message: messageText,
      user_id: 'demo',
      role: currentRole,
      patient_id: 'P001',
      encounter_id: 'E001',
    }

    // Trigger the hook to start streaming
    clearStream()
    setStreamingRequest(request)
    setStreamEnabled(true)
  }

  useEffect(() => {
    if (prefilledMessage && prefilledMessage.trim() && prefilledRef.current !== prefilledMessage) {
      prefilledRef.current = prefilledMessage
      handleSend(prefilledMessage)
      onPrefillConsumed?.()
    }
  }, [prefilledMessage])

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
        {
          role: 'assistant',
          content: `${label}\n任务: ${pendingConfirmation.description}\n任务ID: ${result.task_id}\n状态: ${result.status}`,
        },
      ])
    } catch (error) {
      if (error instanceof ApiClientError) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `❌ 确认操作失败\n错误码: ${error.detail.error_code}\n${error.detail.message}`,
          },
        ])
      }
    } finally {
      setIsConfirming(false)
      setPendingConfirmation(null)
      setConfirmReason('')
    }
  }

  // Reset streaming state when connection closes or errors
  useEffect(() => {
    if (!streamEnabled) return
    if (sseStatus === 'closed' || sseStatus === 'error') {
      setIsLoading(false)
      setIsStreaming(false)
      setStreamEnabled(false)
      setStreamingRequest(null)
    }
  }, [sseStatus, streamEnabled])

  // Safety timeout: force-reset streaming state after 30 seconds
  useEffect(() => {
    if (!streamEnabled) return

    safetyTimerRef.current = setTimeout(() => {
      console.warn('[SettlementChat] Safety timeout — force-resetting streaming state')
      setIsLoading(false)
      setIsStreaming(false)
      setStreamEnabled(false)
      setStreamingRequest(null)
    }, 30000)

    return () => {
      if (safetyTimerRef.current) {
        clearTimeout(safetyTimerRef.current)
        safetyTimerRef.current = null
      }
    }
  }, [streamEnabled])

  const quickQuestions = [
    '为什么这个患者结算失败',
    '这个患者出院前还有哪些风险',
    '本月哪个科室DRG亏损最多',
  ]

  const quickQIcons = ['🔍', '🏥', '📊']

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

  const intentLabelStr = intentTrace ? intentIdToLabel(intentTrace.intent) : '等待识别'
  const intentConfidence = intentTrace ? clampPercent(intentTrace.confidence * 100) : 0
  const intentConfidenceText = `${intentConfidence}%`
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

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[calc(100dvh-7.5rem)]" data-testid="chat-grid">
      {/* 左侧：快捷问题 */}
      <Card className="lg:col-span-1 flex flex-col border-slate-200/70 shadow-sm">
        <CardHeader className="pb-3 px-5 pt-5">
          <CardTitle className="text-sm font-semibold tracking-tight text-slate-800 flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-gradient-to-br from-blue-50 to-blue-100">
              <Sparkles className="h-3.5 w-3.5 text-blue-600" />
            </div>
            快捷提问
          </CardTitle>
          <p className="mt-0.5 text-xs text-slate-400">点击问题快速开始对话</p>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col space-y-1.5 px-3 pb-4">
          {quickQuestions.map((q, i) => (
            <Button
              key={q}
              variant="ghost"
              className="w-full justify-start text-left h-auto py-2 px-3 whitespace-normal rounded-xl border border-transparent hover:border-blue-100 hover:bg-blue-50/70 hover:text-blue-700 transition-all duration-200 text-slate-600 group"
              onClick={() => handleSend(q)}
              disabled={isLoading}
            >
              <span className="mr-2.5 shrink-0 text-base leading-none">{quickQIcons[i]}</span>
              <span className="text-sm leading-snug">{q}</span>
            </Button>
          ))}

          <div className="pt-3 border-t border-slate-100 mt-auto">
            <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2.5">当前角色视图</p>
            <div className="rounded-xl bg-gradient-to-r from-blue-50/80 to-indigo-50/80 border border-blue-100/60 px-3.5 py-2.5 text-center">
              <span className="text-sm font-medium text-slate-700">
                {currentRole === 'cashier' && '💰 收费员'}
                {currentRole === 'medical_office' && '🏥 医保办'}
                {currentRole === 'information_department' && '💻 信息科'}
                {currentRole === 'medical_record_staff' && '📋 病案室'}
                {currentRole === 'clinician' && '🩺 临床医生'}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 右侧：AI 导办对话 + 意图/RAG 过程 */}
      <Card className="lg:col-span-3 flex flex-col border-slate-200/70 overflow-hidden shadow-sm bg-gradient-to-b from-slate-950 to-slate-900 text-white">
        <CardHeader className="border-b border-white/[0.06] py-3 px-4 bg-gradient-to-r from-slate-900 via-slate-900 to-slate-800/90">
          <div className="flex items-center gap-3">
            <div className="relative">
              <Avatar className="h-10 w-10 bg-gradient-to-br from-cyan-400 to-blue-500 shadow-lg shadow-cyan-900/30 ring-2 ring-white/20">
                <AvatarFallback>
                  <Bot className="h-5.5 w-5.5 text-white" />
                </AvatarFallback>
              </Avatar>
              <span className="absolute -bottom-0.5 -right-0.5 flex h-3 w-3">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-slate-900" />
              </span>
            </div>
            <div className="min-w-0">
              <CardTitle className="text-[15px] font-semibold tracking-tight text-white">医保 AI 导办中枢</CardTitle>
              <div className="flex items-center gap-1.5 mt-0.5">
                {isStreaming ? (
                  <span className="inline-flex items-center gap-1 text-xs text-cyan-300/90">
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-75" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-cyan-400" />
                    </span>
                    正在识别意图与组织依据
                    <span className="inline-flex">
                      <span className="animate-pulse" style={{ animationDelay: '0ms' }}>.</span>
                      <span className="animate-pulse" style={{ animationDelay: '150ms' }}>.</span>
                      <span className="animate-pulse" style={{ animationDelay: '300ms' }}>.</span>
                    </span>
                  </span>
                ) : (
                  <span className="text-xs text-slate-400">在线 · LLM 意图识别 · RAG 依据追踪</span>
                )}
              </div>
            </div>
            <Badge variant="outline" className={`ml-auto text-[11px] font-medium px-2.5 py-0.5 border-white/[0.08] bg-white/[0.06] backdrop-blur-sm text-white/80`}>
              <span className="relative flex h-1.5 w-1.5 mr-1.5">
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
        </CardHeader>

        <CardContent className="flex-1 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] min-h-0 p-0">
          <div className="flex min-h-0 flex-col border-r border-white/[0.06]">
            <ScrollArea className="flex-1 px-4 pt-3 pb-2" viewportRef={viewportRef}>
              {/* Intent/RAG stat bar */}
              <div className="mb-3 grid grid-cols-3 gap-3">
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-2.5 shadow-sm">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500"><Target className="w-3.5 h-3.5 text-cyan-400/70" /> 当前意图</div>
                  <div className="mt-1 truncate text-sm font-semibold text-white/90">{intentLabelStr}</div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-2.5 shadow-sm">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500"><BrainCircuit className="w-3.5 h-3.5 text-violet-400/70" /> 置信度</div>
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-violet-400" style={{ width: intentConfidenceText }} />
                    </div>
                    <span className="text-sm font-semibold text-white/90">{intentConfidenceText}</span>
                  </div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-2.5 shadow-sm">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500"><Workflow className="w-3.5 h-3.5 text-emerald-400/70" /> 路由状态</div>
                  <div className="mt-1 truncate text-sm font-semibold text-white/90">{intentStatusStr}</div>
                </div>
              </div>

              {intentTrace && (
                <div className="mb-3">
                  <IntentTraceCard intentTrace={intentTrace} isStreaming={isStreaming && !streamingContent} />
                </div>
              )}

              <div className="space-y-3">
                {messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex items-end gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'} ${
                      idx > 1 ? 'animate-slide-in-right' : ''
                    }`}
                    style={{ animationDelay: '0ms' }}
                  >
                    {msg.role === 'assistant' ? (
                      <Avatar className="h-9 w-9 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 shadow-lg shadow-cyan-900/20 ring-2 ring-white/10">
                        <AvatarFallback>
                          <Bot className="h-5 w-5 text-white" />
                        </AvatarFallback>
                      </Avatar>
                    ) : (
                      <Avatar className="h-9 w-9 shrink-0 bg-white/[0.08] border border-white/[0.06]">
                        <AvatarFallback>
                          <User className="h-5 w-5 text-slate-300" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                    <div
                      className={`max-w-[80%] flex flex-col ${
                        msg.role === 'user' ? 'items-end' : 'items-start'
                      }`}
                    >
                      <div
                        className={`px-4 py-2.5 text-sm leading-relaxed tracking-normal whitespace-pre-wrap ${
                          msg.role === 'user'
                            ? 'bg-gradient-to-br from-cyan-400 to-blue-500 text-white rounded-2xl rounded-tr-md shadow-lg shadow-cyan-900/25'
                            : msg.kind === 'clarification'
                              ? 'bg-gradient-to-br from-amber-50 to-amber-100/80 text-amber-950 border border-amber-200/60 rounded-2xl rounded-tl-md shadow-sm'
                              : msg.kind === 'confirmation'
                                ? 'bg-gradient-to-br from-rose-50 to-rose-100/80 text-rose-950 border border-rose-200/60 rounded-2xl rounded-tl-md shadow-sm'
                                : msg.fallback
                                  ? 'bg-gradient-to-br from-amber-50/95 to-amber-100/70 text-slate-800 border border-amber-200/70 rounded-2xl rounded-tl-md shadow-sm'
                                  : 'bg-white/95 text-slate-800 border border-white/20 rounded-2xl rounded-tl-md shadow-sm'
                        }`}
                      >
                        {msg.kind === 'clarification' && (
                          <div className="mb-3 flex items-center gap-2 rounded-xl bg-white/70 px-3 py-2 text-xs font-semibold text-amber-800 border border-amber-200/40">
                            <HelpCircle className="w-3.5 h-3.5" /> 需要补充业务场景后继续导办
                          </div>
                        )}
                        {msg.kind === 'confirmation' && (
                          <div className="mb-3 flex items-center gap-2 rounded-xl bg-white/70 px-3 py-2 text-xs font-semibold text-rose-800 border border-rose-200/40">
                            <ShieldCheck className="w-3.5 h-3.5" /> 命中高风险动作，已转人工确认
                          </div>
                        )}
                        {msg.content}
                        {msg.fallback && (
                          <div className="flex items-center gap-1.5 mt-3 pt-2.5 border-t border-amber-200/40">
                            <AlertCircle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                            <span className="text-[11px] font-medium text-amber-600">离线演示模式</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}

              {intentTrace && (() => {
                const lastMsg = messages[messages.length - 1]
                const showBeforeResponse = lastMsg?.role === 'user' || isStreaming
                return showBeforeResponse ? (
                  <IntentTraceCard intentTrace={intentTrace} isStreaming={isStreaming && !streamingContent} />
                ) : null
              })()}

              {isStreaming && streamingContent && (
                <div className="flex items-end gap-3 flex-row" data-testid="streaming-indicator">
                  <Avatar className="h-9 w-9 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 shadow-lg shadow-cyan-900/20 ring-2 ring-white/10">
                    <AvatarFallback>
                      <Bot className="h-5 w-5 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="max-w-[80%]">
                    <div className="bg-white/95 text-slate-800 border border-white/20 rounded-2xl rounded-tl-md shadow-sm px-4 py-2.5">
                      <Typewriter 
                        text={streamingContent} 
                        isTyping={isStreaming}
                        awaitingToolCall={steps.some(s => s.status === 'running' || s.status === 'pending')}
                      />
                    </div>
                  </div>
                </div>
              )}

              {isLoading && !isStreaming && (
                <div className="flex items-end gap-3 flex-row" data-testid="loading-indicator">
                  <Avatar className="h-9 w-9 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 shadow-lg shadow-cyan-900/20 ring-2 ring-white/10">
                    <AvatarFallback>
                      <Bot className="h-5 w-5 text-white" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="border border-white/20 rounded-2xl rounded-tl-md shadow-sm px-4 py-3 bg-white/95">
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

          <div className="p-3 border-t border-white/[0.06] bg-slate-900/80 backdrop-blur-sm">
            <div className="flex gap-2.5 items-end">
              <Input
                data-testid="chat-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                placeholder="描述您的问题，例如：这个患者为什么结不了，或者这条规则什么意思…"
                className="flex-1 h-auto py-2.5 px-3.5 text-sm bg-white/[0.06] text-white/90 placeholder:text-slate-500 border-white/[0.08] rounded-xl focus:bg-white/[0.1] focus:ring-2 focus:ring-blue-400/15 focus:border-blue-400/40 transition-all duration-200"
                disabled={isLoading}
              />
              <Button
                data-testid="send-button"
                onClick={() => handleSend()}
                disabled={isLoading || !input.trim()}
                size="icon"
                className="h-[42px] w-[42px] rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 text-white hover:from-blue-400 hover:to-blue-500 disabled:from-slate-700 disabled:to-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed transition-all duration-200 shadow-lg shadow-blue-900/30 active:scale-95"
              >
                {isLoading ? (
                  <Loader2 data-testid="loader-icon" className="w-4.5 h-4.5 animate-spin" />
                ) : (
                  <Send className="w-4.5 h-4.5" />
                )}
              </Button>
            </div>
          </div>
          </div>

          <aside className="hidden xl:flex min-h-0 flex-col bg-slate-900/60 backdrop-blur-sm">
            <div className="border-b border-white/[0.06] p-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-white/90">
                <Zap className="w-4 h-4 text-cyan-400" />
                执行步骤
              </div>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                AI 处理过程实时展示
              </p>
            </div>

            <ScrollArea className="flex-1 p-3">
              {isStreaming || steps.length > 0 ? (
                <ExecutionTimeline steps={steps} />
              ) : (
                <div className="flex items-center justify-center py-12">
                  <div className="text-center">
                    <Target className="w-8 h-8 text-slate-600 mx-auto mb-3" />
                    <p className="text-xs text-slate-500">发送消息后将展示执行过程</p>
                  </div>
                </div>
              )}
            </ScrollArea>
          </aside>
        </CardContent>
      </Card>

      {/* 人工确认 Dialog */}
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
