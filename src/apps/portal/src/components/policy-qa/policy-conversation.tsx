'use client'

import { useEffect, useRef, useState } from 'react'
import { LoaderCircle, PauseCircle, PlayCircle, ShieldQuestion } from 'lucide-react'

import PolicyComposer from '@/components/policy-qa/policy-composer'
import PolicyMessageList from '@/components/policy-qa/policy-message-list'
import PolicyQAEmptyState from '@/components/policy-qa/policy-qa-empty-state'
import {
  extractSettlementId,
  parsePolicyQACommand,
} from '@/lib/policy-qa-session'
import type { UsePolicyQAStreamReturn } from '@/lib/use-policy-qa-stream'

interface PolicyConversationProps {
  stream: UsePolicyQAStreamReturn
}

export default function PolicyConversation({ stream }: PolicyConversationProps) {
  const [input, setInput] = useState('')
  const conversationEndRef = useRef<HTMLDivElement>(null)
  const currentPublicMessage = stream.steps.at(-1)?.publicMessage

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [stream.messages, currentPublicMessage, stream.isStreaming])

  const appendPromptForSettlement = () => {
    stream.appendLocalMessage({
      role: 'assistant',
      content: '首次提问请提供结算单号，例如：查询住院费用，结算单 1671213。',
    })
  }

  const sendQuestion = async (question: string) => {
    if (!question.trim() || stream.isStreaming) return
    if (stream.sessionStatus !== 'active' && stream.sessionStatus !== 'unknown') return
    const command = parsePolicyQACommand(question)

    if (command.kind === 'new_session') {
      stream.resetSession()
      return
    }
    if (command.kind === 'switch_settlement') {
      await stream.send(command.question || '查询该结算单的费用构成', {
        settlementId: command.settlementId,
      })
      return
    }
    if (command.kind === 'switch_patient') {
      stream.updateAnchor({
        patientId: command.patientId,
        settlementId: null,
        subjectChanged: true,
        subjectChangeMsg: `已切换患者 ${command.patientId}，请提供新结算单号。`,
      })
      appendPromptForSettlement()
      return
    }

    if (stream.anchor.settlementId) {
      await stream.send(command.question)
      return
    }

    const settlementId = extractSettlementId(command.question)
    if (settlementId) {
      await stream.send(command.question, { settlementId })
    } else {
      appendPromptForSettlement()
    }
  }

  const handleSend = () => {
    const question = input.trim()
    if (!question) return
    setInput('')
    void sendQuestion(question)
  }

  const handleFollowUp = (question: string) => {
    void sendQuestion(question)
  }

  // Issue #30：会话生命周期操作（仅 active 且已有对话时显示）
  const canOperate = stream.sessionStatus === 'active' && stream.messages.length > 0 && !stream.isStreaming
  const lastUserQuestion =
    [...stream.messages].reverse().find((m) => m.role === 'user')?.content ?? ''

  const handleSuspend = () => {
    setInput('')
    void stream.suspendSession()
  }

  const handleEscalate = () => {
    // 升级问题：优先取输入框未发送内容，否则取最近一轮用户问题
    const question = input.trim() || lastUserQuestion
    if (!question) return
    setInput('')
    void stream.escalateSession(question)
  }

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-slate-950">政策问答</h1>
            <p className="text-sm text-slate-500">围绕当前结算单持续追问费用构成与政策依据。</p>
          </div>
          {canOperate ? (
            <div className="flex shrink-0 items-center gap-1.5" data-testid="policy-qa-session-actions">
              <button
                type="button"
                onClick={handleSuspend}
                className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
              >
                <PauseCircle className="size-3.5" aria-hidden />
                挂起
              </button>
              <button
                type="button"
                onClick={handleEscalate}
                disabled={!input.trim() && !lastUserQuestion}
                className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700 hover:bg-amber-100 disabled:opacity-50"
              >
                <ShieldQuestion className="size-3.5" aria-hidden />
                升级医保办
              </button>
            </div>
          ) : null}
        </div>
      </header>

      {stream.sessionStatus === 'suspended' ? (
        <div
          role="status"
          data-testid="policy-qa-suspended-banner"
          className="flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"
        >
          <span>
            会话已挂起{stream.statusReason ? `：${stream.statusReason}` : ''}，可稍后恢复继续。
          </span>
          <button
            type="button"
            onClick={() => void stream.resumeSession()}
            className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700"
          >
            <PlayCircle className="size-3.5" aria-hidden />
            恢复对话
          </button>
        </div>
      ) : null}

      {stream.sessionStatus === 'escalated' ? (
        <div
          role="status"
          data-testid="policy-qa-escalated-banner"
          className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          已升级至医保办人工处理，本会话暂停提问。医保办回复后重新进入本页即可看到答复。
        </div>
      ) : null}

      {stream.escalation?.reply ? (
        <div
          data-testid="policy-qa-escalation-reply"
          className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
        >
          <p className="mb-1 font-medium">医保办回复</p>
          <p className="whitespace-pre-wrap">{stream.escalation.reply}</p>
        </div>
      ) : null}

      {stream.restoring ? (
        <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          正在恢复上次会话…
        </div>
      ) : null}

      {stream.messages.length === 0 ? (
        <PolicyQAEmptyState onSelectQuestion={setInput} />
      ) : (
        <PolicyMessageList messages={stream.messages} onFollowUp={handleFollowUp} />
      )}

      {stream.isStreaming && currentPublicMessage ? (
        <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          <span>{currentPublicMessage}</span>
        </div>
      ) : null}

      <PolicyComposer
        settlementId={stream.anchor.settlementId}
        value={input}
        onChange={setInput}
        onSend={handleSend}
        isStreaming={stream.isStreaming}
        disabled={
          stream.sessionStatus === 'suspended' ||
          stream.sessionStatus === 'escalated' ||
          stream.sessionStatus === 'closed'
        }
      />

      <p className="text-center text-xs leading-5 text-slate-400">
        回答仅供解释参考，不作为报销或结算依据。
      </p>

      <div ref={conversationEndRef} aria-hidden />
    </section>
  )
}
