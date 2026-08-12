'use client'

import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, PlayCircle } from 'lucide-react'

import {
  ApiClientError,
  evaluateSkillCandidateBehavior,
  evaluateSkillCandidateRoutes,
} from '@/lib/skill-draft-api'
import type {
  SkillCandidateBehaviorEvaluationResponse,
  SkillCandidateEvaluationStatus,
  SkillCandidateRouteEvaluationResponse,
} from '@/lib/types'

const STATUS_LABELS: Record<SkillCandidateEvaluationStatus, string> = {
  completed: '已完成',
  failed: '未通过',
  blocked_by_evaluator: '评测器阻断',
}

function resultLabel(
  name: string,
  result: SkillCandidateRouteEvaluationResponse | SkillCandidateBehaviorEvaluationResponse,
) {
  const reason = result.blocked_reason ? `（${result.blocked_reason}）` : ''
  return `${name}：${STATUS_LABELS[result.status]}${reason}`
}

export function SkillCandidateEvaluationPanel({
  draftId,
  disabled,
}: {
  draftId: string
  disabled: boolean
}) {
  const [busy, setBusy] = useState<'route' | 'behavior' | null>(null)
  const [routeResult, setRouteResult] = useState<SkillCandidateRouteEvaluationResponse | null>(null)
  const [behaviorResult, setBehaviorResult] =
    useState<SkillCandidateBehaviorEvaluationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function runRouteEvaluation() {
    setBusy('route')
    setError(null)
    try {
      setRouteResult(await evaluateSkillCandidateRoutes(draftId))
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '候选路由评测失败')
    } finally {
      setBusy(null)
    }
  }

  async function runBehaviorEvaluation() {
    setBusy('behavior')
    setError(null)
    try {
      setBehaviorResult(await evaluateSkillCandidateBehavior(draftId))
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '候选行为评测失败')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section
      className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/40 p-4"
      data-testid="skill-candidate-evaluation"
    >
      <div>
        <h3 className="text-sm font-semibold text-slate-900">候选版本评测</h3>
        <p className="mt-1 text-xs text-slate-500">
          路由评测使用固定快照；行为评测仅在隔离执行器可用时运行。
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void runRouteEvaluation()}
          disabled={disabled || busy !== null}
          className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-medium text-blue-700 disabled:opacity-50"
        >
          {busy === 'route' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
          运行候选路由评测
        </button>
        <button
          type="button"
          onClick={() => void runBehaviorEvaluation()}
          disabled={disabled || busy !== null}
          className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-medium text-blue-700 disabled:opacity-50"
        >
          {busy === 'behavior' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
          运行候选行为评测
        </button>
      </div>
      {disabled && <p className="text-xs text-amber-700">请先完成草稿校验。</p>}
      {routeResult && (
        <p className="flex items-center gap-2 text-sm text-slate-700">
          <CheckCircle2 className="h-4 w-4 text-blue-600" />
          {resultLabel('路由评测', routeResult)}
        </p>
      )}
      {behaviorResult && (
        <p className="flex items-center gap-2 text-sm text-slate-700">
          {behaviorResult.status === 'blocked_by_evaluator' ? (
            <AlertTriangle className="h-4 w-4 text-amber-600" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-blue-600" />
          )}
          {resultLabel('行为评测', behaviorResult)}
        </p>
      )}
      {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
    </section>
  )
}
