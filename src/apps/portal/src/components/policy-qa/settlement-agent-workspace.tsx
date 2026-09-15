'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  LoaderCircle,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  ShieldQuestion,
} from 'lucide-react'

import PolicyComposer from '@/components/policy-qa/policy-composer'
import PolicyMessageList from '@/components/policy-qa/policy-message-list'
import SettlementResultBlock from '@/components/policy-qa/settlement-result-block'
import SettlementTimeBrowser from '@/components/policy-qa/settlement-time-browser'
import { toPolicyQAResult, type PolicyQAResult } from '@/lib/policy-qa-stream'
import { parsePolicyQACommand } from '@/lib/policy-qa-session'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

/**
 * V4.0 结算解释智能体工作区（设计 §4.2）。
 *
 * 主输入 = 时间选择器（不是结算单搜索框）：选时段 → 时段结算列表 →
 * 点单看费用构成富块 → 可针对此单追问（走 stream，已锚定）。
 */

const EXPLANATION_URL = '/api/v1/medical-insurance-ai-agent/policy-qa/settlement-explanation'

async function fetchSettlementExplanation(settlementId: string): Promise<PolicyQAResult> {
  const params = new URLSearchParams({ settlement_id: settlementId })
  const response = await fetch(`${EXPLANATION_URL}?${params.toString()}`)
  if (!response.ok) {
    throw new Error(`结算解释查询失败（HTTP ${response.status}）`)
  }
  const payload = (await response.json()) as { result?: unknown } & Record<string, unknown>
  // 端点直接返回 PolicyQAPublicResult（非 { result: ... } 包装）
  const raw = payload.result ?? payload
  return toPolicyQAResult(raw)
}

export default function SettlementAgentWorkspace({
  onStreamingChange,
}: {
  onStreamingChange?: (streaming: boolean) => void
}) {
  const stream = usePolicyQAStream({ mode: 'settlement_explain', storageScope: 'settlement' })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [explanation, setExplanation] = useState<PolicyQAResult | null>(null)
  const [explanationLoading, setExplanationLoading] = useState(false)
  const [explanationError, setExplanationError] = useState<string | null>(null)
  const [input, setInput] = useState('')

  useEffect(() => {
    onStreamingChange?.(stream.isStreaming)
  }, [stream.isStreaming, onStreamingChange])

  // 患者定位/换人（临时方案）：换人时清掉上一患者的选中结算单与解释，
  // 避免跨患者串台；定位本身由 SettlementTimeBrowser 内聚管理
  const handlePatientChange = useCallback(() => {
    setSelectedId(null)
    setExplanation(null)
    setExplanationError(null)
  }, [])

  // 点选结算单 → 锚定会话 + 拉取费用构成解释
  const handleSelect = useCallback(
    (settlementId: string) => {
      setSelectedId(settlementId)
      setExplanation(null)
      setExplanationError(null)
      // 锚定当前单（追问走 stream.send 复用该锚点）
      stream.updateAnchor({ settlementId, subjectChanged: false, subjectChangeMsg: null })
      setExplanationLoading(true)
      void (async () => {
        try {
          const result = await fetchSettlementExplanation(settlementId)
          setExplanation(result)
        } catch (e) {
          setExplanationError(e instanceof Error ? e.message : '结算解释查询失败')
        } finally {
          setExplanationLoading(false)
        }
      })()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stream.updateAnchor],
  )

  const sendQuestion = async (question: string) => {
    if (!question.trim() || stream.isStreaming) return
    if (stream.sessionStatus !== 'active' && stream.sessionStatus !== 'unknown') return
    const command = parsePolicyQACommand(question)
    if (command.kind === 'new_session') {
      stream.resetSession()
      return
    }
    if (command.kind === 'switch_settlement') {
      handleSelect(command.settlementId)
      return
    }
    const settlementId =
      command.kind === 'question' ? selectedId ?? stream.anchor.settlementId : null
    if (command.kind === 'question' && settlementId) {
      await stream.send(command.question, { settlementId })
      return
    }
    await stream.send(question)
  }

  const handleSend = () => {
    const question = input.trim()
    if (!question) return
    setInput('')
    void sendQuestion(question)
  }

  const canOperate =
    stream.sessionStatus === 'active' && stream.messages.length > 0 && !stream.isStreaming
  const lastUserQuestion =
    [...stream.messages].reverse().find((m) => m.role === 'user')?.content ?? ''
  const currentPublicMessage = stream.steps.at(-1)?.publicMessage
  const composerSettlementId = selectedId ?? stream.anchor.settlementId

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-slate-950">结算解释</h1>
            <p className="text-sm text-slate-500">
              按时间段浏览结算单，点开单据查看费用构成解释。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5" data-testid="policy-qa-session-actions">
            <button
              type="button"
              onClick={stream.resetSession}
              disabled={stream.isStreaming || stream.restoring}
              aria-label="新会话"
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              新会话
            </button>
            {canOperate ? (
              <>
                <button
                  type="button"
                  onClick={() => void stream.suspendSession()}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50"
                >
                  <PauseCircle className="size-3.5" aria-hidden />
                  挂起
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const question = input.trim() || lastUserQuestion
                    if (question) void stream.escalateSession(question)
                  }}
                  disabled={!input.trim() && !lastUserQuestion}
                  className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                >
                  <ShieldQuestion className="size-3.5" aria-hidden />
                  升级医保办
                </button>
              </>
            ) : null}
          </div>
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
          <p>已升级至医保办人工处理，本会话暂停提问。医保办回复后重新进入本页即可看到答复。</p>
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

      {/* 主输入：患者定位 + 时间选择器 + 时段列表（临时患者定位，正式由登录态取代） */}
      <SettlementTimeBrowser
        selectedId={selectedId}
        onSelect={handleSelect}
        onPatientChange={handlePatientChange}
      />

      {/* 单笔费用构成富块 */}
      {explanationLoading ? (
        <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          正在生成结算单 {selectedId} 的费用构成解释…
        </div>
      ) : null}
      {!explanationLoading && explanationError ? (
        <div
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          {explanationError}
        </div>
      ) : null}
      {!explanationLoading && !explanationError && explanation && selectedId ? (
        <SettlementResultBlock settlementId={selectedId} result={explanation} />
      ) : null}

      {/* 针对此单的追问对话流 */}
      {stream.messages.length > 0 ? <PolicyMessageList messages={stream.messages} /> : null}

      {stream.isStreaming && currentPublicMessage ? (
        <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          <span>{currentPublicMessage}</span>
        </div>
      ) : null}

      <PolicyComposer
        mode="settlement_explain"
        settlementId={composerSettlementId}
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
    </section>
  )
}
