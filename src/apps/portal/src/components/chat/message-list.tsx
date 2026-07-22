'use client'

import { useEffect, useRef, useMemo } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  Bot,
  User,
  HelpCircle,
  ShieldCheck,
  AlertCircle,
  Target,
  BrainCircuit,
  Workflow,
} from 'lucide-react'
import IntentTraceCard from '../intent-trace-card'
import StreamingBubble from './streaming-bubble'
import ThinkingChain from '../thinking-chain'
import type { IntentTrace } from '@/lib/types'
import type { StreamStepDisplay } from '@/lib/sse-hooks'
import type { ChatMessage, PendingConfirmation } from './helpers'

// ── Props ────────────────────────────────────────────────────

interface ChatMessageListProps {
  messages: ChatMessage[]
  isStreaming: boolean
  streamingContent: string
  isLoading: boolean
  steps: StreamStepDisplay[]
  intentTrace: IntentTrace | null
  intentLabelStr: string
  intentConfidenceText: string
  intentStatusStr: string
  connectionStatus?: string
  statusLabel?: string
  onConfirm?: (action: 'confirm' | 'reject') => void
  pendingConfirmation?: PendingConfirmation | null
}

// ── Component ────────────────────────────────────────────────

export default function ChatMessageList({
  messages,
  isStreaming,
  streamingContent,
  isLoading,
  steps,
  intentTrace,
  intentLabelStr,
  intentConfidenceText,
  intentStatusStr,
}: ChatMessageListProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const scrollBottomRef = useRef<HTMLDivElement>(null)

  // Convert StreamStepDisplay[] to ThinkingStep[] for ThinkingChain
  const thinkingSteps = useMemo(() => {
    return steps.map((step, index) => ({
      step: step.step,
      status: step.status === 'completed' ? 'done' as const :
              step.status === 'pending' ? 'pending' as const :
              step.status === 'running' ? 'running' as const :
              step.status as 'running' | 'done' | 'error' | 'streaming' | 'pending',
      startTime: step.timestamp ? new Date(step.timestamp).getTime() : Date.now() - (index * 500),
      publicMessage: step.message || undefined,  // ★ SSE 的 public_message → 思维链详情
      detail: step.message ? { message: step.message } : undefined,
    }))
  }, [steps])

  // Auto-scroll to bottom when messages or streaming content changes
  useEffect(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTo({
        top: viewportRef.current.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [messages, streamingContent, steps])

  return (
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

        {/* Thinking Chain - inline between user message and response */}
        {thinkingSteps.length > 0 && (
          <div className="my-3">
            <ThinkingChain steps={thinkingSteps} isLoading={isLoading} />
          </div>
        )}

        {isStreaming && streamingContent && (
          <StreamingBubble isStreaming={isStreaming} streamingContent={streamingContent} steps={steps} />
        )}

        {isLoading && !isStreaming && thinkingSteps.length === 0 && (
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
  )
}
