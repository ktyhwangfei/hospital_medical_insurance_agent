'use client'

import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ClipboardCheck, History, Loader2, TriangleAlert } from 'lucide-react'

import AnswerVerificationResult, { statusLabel } from '@/components/policy-qa/answer-verification-result'
import { Badge } from '@/components/ui/badge'
import { fetchQAHistory } from '@/lib/api-client'
import {
  verifyPolicyQAAnswer,
  type VerifyAnswerResponse,
} from '@/lib/policy-qa-feedback'
import { ApiClientError } from '@/lib/types'

interface HistoryEntry {
  qaTurnId: string
  question: string
  answer: string
  answerStatus: string
  createdAt: string
}

/** 从嵌套的 session → workflow → task 历史中拍平出可验证的问答轮次（task_id 即 qa_turn_id）。 */
function flattenHistory(response: {
  items: Array<{
    workflows: Array<{
      tasks: Array<{
        task_id?: string
        created_at?: string
        input_data?: Record<string, unknown>
        output_data?: Record<string, unknown>
      }>
    }>
  }>
}): HistoryEntry[] {
  const entries: HistoryEntry[] = []
  for (const session of response.items ?? []) {
    for (const workflow of session.workflows ?? []) {
      for (const task of workflow.tasks ?? []) {
        if (!task.task_id) continue
        entries.push({
          qaTurnId: task.task_id,
          question: String(task.input_data?.question_excerpt ?? ''),
          answer: String(task.output_data?.answer_excerpt ?? ''),
          answerStatus: String(task.output_data?.answer_status ?? ''),
          createdAt: task.created_at ?? '',
        })
      }
    }
  }
  return entries
}

export function AnswerVerificationPanel() {
  const [qaTurnId, setQaTurnId] = useState('')
  const [result, setResult] = useState<VerifyAnswerResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setHistoryLoading(true)
    fetchQAHistory({ limit: 20 })
      .then((response) => {
        if (!cancelled) setHistory(flattenHistory(response))
      })
      .catch(() => {
        if (!cancelled) setHistory([])
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function runVerification(id: string) {
    const trimmed = id.trim()
    if (!trimmed || loading) return
    setLoading(true); setError(''); setResult(null)
    try {
      setResult(await verifyPolicyQAAnswer(trimmed))
    } catch (reason) {
      if (reason instanceof ApiClientError && reason.status === 404) {
        setError('该轮次的验证轨迹已失效（可能服务已重启），仅公开信息可降级验证')
      } else {
        setError(reason instanceof Error ? reason.message : '答案验证失败')
      }
    } finally {
      setLoading(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void runVerification(qaTurnId)
  }

  const recent = useMemo(() => history.slice(0, 10), [history])

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="size-4 text-emerald-600" />
        <h3 className="text-sm font-semibold text-slate-900">答案验证</h3>
        <span className="text-[11px] text-slate-400">
          对政策问答回答做引用/结论/计算/覆盖五维交叉验证
        </span>
      </div>

      {/* 最近可验证问答（从历史自动加载，点选即验证，无需手填 ID） */}
      <div className="mt-4">
        <p className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-500">
          <History className="size-3.5" />
          最近问答
        </p>
        {historyLoading ? (
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <Loader2 className="size-3.5 animate-spin" />
            加载历史…
          </div>
        ) : recent.length === 0 ? (
          <p className="mt-2 text-xs text-slate-400">
            暂无历史问答。可在政策问答页先发起一次问答，再回到这里验证。
          </p>
        ) : (
          <ul className="mt-2 max-h-64 space-y-2 overflow-auto">
            {recent.map((entry) => (
              <li key={entry.qaTurnId}>
                <button
                  type="button"
                  onClick={() => void runVerification(entry.qaTurnId)}
                  disabled={loading}
                  className="flex w-full items-start gap-2 rounded-lg border border-slate-100 p-3 text-left transition hover:border-emerald-200 hover:bg-emerald-50/40 disabled:opacity-50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-slate-800">
                      {entry.question || entry.qaTurnId}
                    </p>
                    {entry.answer && (
                      <p className="mt-0.5 line-clamp-2 text-[11px] leading-5 text-slate-500">
                        {entry.answer}
                      </p>
                    )}
                  </div>
                  {entry.answerStatus === 'complete' && (
                    <Badge variant="outline" className="shrink-0 bg-emerald-50 text-emerald-700">
                      已完成
                    </Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 手动输入兜底（高级用法） */}
      <form onSubmit={submit} className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
        <input
          aria-label="qa_turn_id"
          value={qaTurnId}
          onChange={(event) => setQaTurnId(event.target.value)}
          placeholder="或手动输入轮次 ID（qat_…）"
          className="flex-1 min-w-[16rem] rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs"
        />
        <button
          type="submit"
          disabled={loading || !qaTurnId.trim()}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
        >
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <ClipboardCheck className="size-3.5" />}
          验证
        </button>
      </form>

      {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
      {result && <AnswerVerificationResult result={result} className="mt-4" />}
      {!error && !result && !loading && history.length === 0 && !historyLoading && (
        <p className="mt-3 text-xs text-slate-400">点击上方某条问答，或输入轮次 ID 后点击「验证」。</p>
      )}
    </section>
  )
}

export default AnswerVerificationPanel
