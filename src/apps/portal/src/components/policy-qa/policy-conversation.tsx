'use client'

import { useEffect, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'

import PolicyComposer from '@/components/policy-qa/policy-composer'
import PolicyMessageList from '@/components/policy-qa/policy-message-list'
import PolicyQAEmptyState from '@/components/policy-qa/policy-qa-empty-state'
import {
  extractSettlementId,
  parsePolicyQACommand,
  resolveAnchoredSwitch,
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
      // 锚定后问题里出现与当前锚不同的结算单号 → 自动按 @换结算 处理，
      // 避免用户直接打新单号被静默忽略、拿到旧单数据。
      const switchTarget = resolveAnchoredSwitch(
        stream.anchor.settlementId,
        command.question,
      )
      if (switchTarget) {
        await stream.send(switchTarget.question || '查询该结算单的费用构成', {
          settlementId: switchTarget.settlementId,
        })
        return
      }
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

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-slate-950">政策问答</h1>
        <p className="text-sm text-slate-500">围绕当前结算单持续追问费用构成与政策依据。</p>
      </header>

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
      />

      <p className="text-center text-xs leading-5 text-slate-400">
        回答仅供解释参考，不作为报销或结算依据。
      </p>

      <div ref={conversationEndRef} aria-hidden />
    </section>
  )
}
