'use client'

import { useState, useEffect, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
  Bot,
  Sparkles,
  AlertTriangle,
  Target,
  Zap,
} from 'lucide-react'
import { confirmTask } from '@/lib/api-client'
import { useApiContext } from '@/lib/api-context'
import { ApiClientError } from '@/lib/types'
import type { AgentResponse, ChatRequest, IntentTrace } from '@/lib/types'
import { useChatStream } from '@/lib/sse-hooks'
import ExecutionTimeline from './chat/execution-timeline'
import ChatMessageList from './chat/message-list'
import ChatInput from './chat/chat-input'
import { extractContent, hasFallbackFlag, clampPercent } from './chat/helpers'
import type { ChatMessage, PendingConfirmation } from './chat/helpers'

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
  const safetyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefilledRef = useRef<string | null>(null)

  // ── useChatStream hook ────────────────────────────────────────
  const {
    status: sseStatus,
    streamingContent,
    steps,
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

  const handleSend = async (text?: string) => {
    const messageText = text || input
    if (!messageText.trim() || isLoading) return

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
            <ChatMessageList
              messages={messages}
              isStreaming={isStreaming}
              streamingContent={streamingContent}
              isLoading={isLoading}
              steps={steps}
              intentTrace={intentTrace}
              intentLabelStr={intentLabelStr}
              intentConfidenceText={intentConfidenceText}
              intentStatusStr={intentStatusStr}
              connectionStatus={connectionStatus}
              statusLabel={statusLabel}
              onConfirm={handleTaskConfirm}
              pendingConfirmation={pendingConfirmation}
            />

            <ChatInput
              input={input}
              setInput={setInput}
              isLoading={isLoading}
              onSend={() => handleSend()}
            />
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
