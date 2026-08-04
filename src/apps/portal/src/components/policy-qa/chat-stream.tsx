'use client'

/**
 * ChatStream —— 政策问答持续对话流（主区）
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §4.2/§七/§八
 * - 对话气泡复用 chat 组件族样式；输入框复用 chat/chat-input（包一层 @ 指令解析）
 * - 结算单号降级为「首帧锚定 + @换结算」，连续追问复用锚点
 * - 首轮 richResult（费用分解）复用 SettlementExplanationPage 渲染
 */

import { useEffect, useRef, useState } from 'react'
import { Bot, User, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import ChatInput from '@/components/chat/chat-input'
import ThinkingChain from '@/components/thinking-chain'
import SettlementExplanationPage from '@/components/settlement-explanation-page'
import ReasoningChainCollapsible from '@/components/policy-qa/reasoning-chain-collapsible'
import {
  extractSettlementId,
  parsePolicyQACommand,
  type PolicyQAChatMessage,
} from '@/lib/policy-qa-session'
import type { UsePolicyQAStreamReturn } from '@/lib/use-policy-qa-stream'

// ── Props ────────────────────────────────────────────────────

interface ChatStreamProps {
  /** usePolicyQAStream 的完整返回值（会话级状态 + 动作） */
  stream: UsePolicyQAStreamReturn
}

// ── 空态示例问题 ─────────────────────────────────────────────

const EXAMPLE_QUESTIONS = [
  '查询住院费用，结算单 1671213',
  '统筹自付为什么是 4962.67 元？',
  '起付线是怎么计算的？',
] as const

// ── Component ────────────────────────────────────────────────

export default function ChatStream({ stream }: ChatStreamProps) {
  const [input, setInput] = useState('')
  const [traceOpen, setTraceOpen] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  const { messages, isStreaming, steps, anchor } = stream

  // 新消息 / 流式更新时自动滚到底部
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  // ── 发送（含 @ 指令解析，§八）────────────────────────────────
  const handleSend = async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')

    const cmd = parsePolicyQACommand(text)

    if (cmd.kind === 'new_session') {
      // @新会话：重置会话（新 sessionId，清空记忆与对话）
      stream.resetSession()
      return
    }

    if (cmd.kind === 'switch_patient') {
      // @换患者：仅更新锚点并提示补结算单号（结算随患者失效）
      stream.updateAnchor({
        patientId: cmd.patientId,
        settlementId: null,
        subjectChanged: true,
        subjectChangeMsg: `已切换患者 ${cmd.patientId}，旧结算上下文已清除，请提供新结算单号`,
      })
      stream.appendLocalMessage({
        role: 'assistant',
        content: `已切换患者主体（${cmd.patientId}）。请提供该患者的结算单号继续提问，例如：查询住院费用，结算单 1671214`,
      })
      return
    }

    if (cmd.kind === 'switch_settlement') {
      // @换结算：切换锚点并提问（无问题时用默认问题）
      const question = cmd.question || '查询该结算单的费用构成'
      await stream.send(question, { settlementId: cmd.settlementId })
      return
    }

    // 普通问题：锚点缺失时尝试从文本提取结算单号（首帧锚定兜底）
    if (!anchor.settlementId) {
      const extracted = extractSettlementId(cmd.question)
      if (extracted) {
        await stream.send(cmd.question, { settlementId: extracted })
      } else {
        stream.appendLocalMessage({
          role: 'assistant',
          content:
            '首次提问请提供结算单号（例如：查询住院费用，结算单 1671213），' +
            '或使用「@换结算 <单号>」切换锚点。',
        })
      }
      return
    }

    await stream.send(cmd.question)
  }

  // ── 渲染 ───────────────────────────────────────────────────

  return (
    <div className="flex min-h-[560px] flex-col rounded-2xl border border-slate-200/70 bg-white/70 shadow-[0_12px_40px_rgba(15,23,42,0.06)] backdrop-blur">
      {/* 消息区 */}
      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {messages.length === 0 && (
          <div className="space-y-3 py-6">
            <div className="text-sm font-semibold text-slate-900">从哪里开始？</div>
            <p className="text-sm leading-relaxed text-slate-600">
              首次提问请带上结算单号（例如「查询住院费用，结算单 1671213」），
              之后可连续追问，无需重复单号。支持指令：
              <span className="font-mono text-xs">@换结算 &lt;单号&gt;</span>、
              <span className="font-mono text-xs">@换患者 &lt;ID&gt;</span>、
              <span className="font-mono text-xs">@新会话</span>。
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setInput(q)}
                  className="rounded-lg border border-slate-200 bg-white/70 px-2.5 py-1 text-xs text-slate-600 hover:bg-white"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble key={idx} message={msg} isStreaming={isStreaming && idx === messages.length - 1} />
        ))}

        {/* 本轮执行链路（流式期间可折叠展示） */}
        {isStreaming && steps.length > 0 && (
          <div className="overflow-hidden rounded-xl border border-slate-200/70 bg-white/80">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:bg-slate-50/60"
              onClick={() => setTraceOpen((v) => !v)}
            >
              {traceOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              本轮执行链路
              <span className="font-mono text-[11px] text-slate-400 animate-pulse">处理中...</span>
            </button>
            {traceOpen && (
              <div className="border-t border-slate-200/70">
                <ThinkingChain steps={steps} isLoading={isStreaming} />
              </div>
            )}
          </div>
        )}

        {isStreaming && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 正在思考…
          </div>
        )}

        <div ref={scrollRef} />
      </div>

      {/* 输入区（复用 chat-input，浅色覆写） */}
      <ChatInput
        input={input}
        setInput={setInput}
        isLoading={isStreaming}
        onSend={handleSend}
        placeholder={
          anchor.settlementId
            ? `继续追问（当前结算单 ${anchor.settlementId}），或用 @换结算 切换…`
            : '首次请提供结算单号，例如：查询住院费用，结算单 1671213'
        }
        containerClassName="border-t border-slate-200/70 bg-white/60 p-3 backdrop-blur-sm rounded-b-2xl"
        inputClassName="h-auto flex-1 rounded-xl border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus:border-blue-400/60 focus:ring-2 focus:ring-blue-400/15 transition-all duration-200"
      />
    </div>
  )
}

// ── 单条消息气泡 ─────────────────────────────────────────────

/** 回答来源徽标文案（answer_mode → 用户可见标识） */
function AnswerModeBadge({ mode }: { mode: string }) {
  if (mode === 'llm') {
    return (
      <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-700">
        ✨ AI 生成 · 请核对
      </span>
    )
  }
  if (mode === 'dummy') {
    return (
      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
        ⚠️ 演示模式 · 金额基于真实结算数据
      </span>
    )
  }
  return (
    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
      基础模式
    </span>
  )
}

function MessageBubble({
  message,
  isStreaming,
}: {
  message: PolicyQAChatMessage
  isStreaming: boolean
}) {
  const isUser = message.role === 'user'
  const showRichResult = !isUser && message.richResult
  // 双视角切换（患者视角 = content，院端视角 = officeView）
  const [view, setView] = useState<'patient' | 'office'>('patient')
  const showDualView = !isUser && Boolean(message.officeView)
  const displayContent =
    !isUser && view === 'office' && message.officeView ? message.officeView : message.content

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* 头像 */}
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          isUser
            ? 'border border-slate-200 bg-slate-100'
            : 'bg-gradient-to-br from-blue-500 to-sky-500 shadow-md shadow-blue-500/20'
        }`}
      >
        {isUser ? <User className="h-4 w-4 text-slate-500" /> : <Bot className="h-4 w-4 text-white" />}
      </div>

      <div className={`flex max-w-[85%] flex-col gap-2 ${isUser ? 'items-end' : 'items-start'}`}>
        {/* 双视角切换（患者/院端） */}
        {showDualView && (
          <div className="flex gap-1 rounded-lg bg-slate-100/80 p-0.5">
            <button
              type="button"
              onClick={() => setView('patient')}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                view === 'patient' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              患者视角
            </button>
            <button
              type="button"
              onClick={() => setView('office')}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                view === 'office' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'
              }`}
            >
              院端视角
            </button>
          </div>
        )}

        {/* 文本气泡 */}
        {(displayContent || isStreaming) && (
          <div
            className={`whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
              isUser
                ? 'rounded-tr-md bg-gradient-to-br from-blue-600 to-sky-500 text-white'
                : 'rounded-tl-md border border-slate-200/80 bg-white text-slate-800'
            }`}
          >
            {displayContent}
            {isStreaming && !isUser && (
              <span className="ml-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-blue-500 align-middle" />
            )}
          </div>
        )}

        {/* 回答来源徽标（真实性标识） */}
        {!isUser && message.answerMode && !isStreaming && (
          <AnswerModeBadge mode={message.answerMode} />
        )}

        {/* 推理链（可折叠，阶段二） */}
        {!isUser && message.reasoning && message.reasoning.length > 0 && (
          <div className="w-full">
            <ReasoningChainCollapsible steps={message.reasoning} />
          </div>
        )}

        {/* 本轮引用记忆标识 */}
        {!isUser && message.citedMemoryIds && message.citedMemoryIds.length > 0 && (
          <div className="text-[11px] text-slate-400">
            💭 引用记忆 {message.citedMemoryIds.length} 条
          </div>
        )}

        {/* 结构化结果（首轮费用分解，复用 SettlementExplanationPage） */}
        {showRichResult && (
          <div className="w-full">
            <SettlementExplanationPage data={message.richResult!} />
          </div>
        )}
      </div>
    </div>
  )
}
