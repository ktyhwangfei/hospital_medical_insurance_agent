'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import CaseProposalEditor from '@/components/skills/case-proposal-editor'
import { useSkillNameMap } from '@/lib/use-skill-name-map'
import { ApiClientError } from '@/lib/types'
import {
  confirmEvalCasePoolItem,
  listEvalCasePool,
  rejectEvalCasePoolItem,
  transformEvalCasePoolItem,
  type EvalCasePoolConfirmRequest,
  type EvalCasePoolItem,
} from '@/lib/policy-qa-feedback'

const DIMENSIONS = [
  'routing',
  'calculation',
  'policy_content',
  'citation',
  'answer_quality',
  'safety',
  'other',
] as const

const DIMENSION_LABELS: Record<string, string> = {
  routing: '路由',
  calculation: '计算',
  policy_content: '政策内容',
  citation: '引用',
  answer_quality: '答案质量',
  safety: '安全',
  other: '未分型',
}

const STATUS_LABELS: Record<string, string> = {
  pending_triage: '待分型',
  transformed: '已转换',
  confirmed: '已确认',
  rejected: '已拒绝',
}

interface PendingEdit {
  dimension: string
  proposal: Record<string, unknown>
}

/**
 * 错误案例池交互列表：AI 转换 → 人工编辑确认/拒绝。
 * 使用服务端判别联合编辑器；409（revision 冲突）保留未提交修改并提示刷新。
 */
export default function EvalCasePoolList() {
  const [items, setItems] = useState<EvalCasePoolItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [pending, setPending] = useState<Record<string, PendingEdit>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const skillNameMap = useSkillNameMap()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listEvalCasePool({ limit: 100 })
      setItems(result.items)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 服务端数据加载的标准模式
    void load()
  }, [load])

  const displayName = (id: string | null | undefined) =>
    id ? (skillNameMap.get(id) ?? id) : '—'

  async function handleTransform(item: EvalCasePoolItem) {
    setBusy(item.poolId)
    setActionError(null)
    try {
      await transformEvalCasePoolItem(item.poolId, item.revision)
      await load()
    } catch (err) {
      setActionError(describeError(err))
    } finally {
      setBusy(null)
    }
  }

  async function handleConfirm(item: EvalCasePoolItem) {
    const edit = pending[item.poolId]
    setBusy(item.poolId)
    setActionError(null)
    try {
      const request: EvalCasePoolConfirmRequest = {
        expected_revision: item.revision,
        error_dimension: edit?.dimension ?? item.transformedDimension ?? item.initialDimension,
        target_skill_id:
          (edit?.proposal.target_skill_id as string | undefined) ??
          item.targetSkillId,
        case_proposal: edit?.proposal ?? null,
      }
      await confirmEvalCasePoolItem(item.poolId, request)
      setEditing(null)
      setPending((prev) => {
        const next = { ...prev }
        delete next[item.poolId]
        return next
      })
      await load()
    } catch (err) {
      // 409：保留未提交修改，提示刷新
      setActionError(describeError(err))
    } finally {
      setBusy(null)
    }
  }

  async function handleReject(item: EvalCasePoolItem) {
    setBusy(item.poolId)
    setActionError(null)
    try {
      await rejectEvalCasePoolItem(item.poolId, item.revision, '评测者拒绝（误报或不可分型）')
      await load()
    } catch (err) {
      setActionError(describeError(err))
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <p className="text-sm text-slate-500">加载中…</p>
  if (error)
    return (
      <div className="flex items-center gap-2 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">
        <AlertCircle className="size-4" aria-hidden />
        {error}
      </div>
    )

  if (items.length === 0)
    return (
      <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">
        暂无案例。
      </p>
    )

  return (
    <div data-testid="eval-case-pool-list" className="space-y-3">
      {actionError ? (
        <div
          data-testid="eval-case-pool-action-error"
          className="flex items-center justify-between gap-2 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800"
        >
          <span>{actionError}</span>
          <Button variant="ghost" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-4" aria-hidden />
            重新加载
          </Button>
        </div>
      ) : null}

      {items.map((item) => {
        const edit = pending[item.poolId]
        const effectiveDimension =
          edit?.dimension ?? item.transformedDimension ?? item.initialDimension
        const isEditing = editing === item.poolId
        return (
          <div
            key={item.poolId}
            data-testid={`eval-case-pool-row-${item.poolId}`}
            className="rounded-xl border border-slate-200 bg-white p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1 text-sm">
                <div className="font-mono text-xs text-slate-500">
                  {item.sourceQaTurnId}
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Tag>初始：{DIMENSION_LABELS[item.initialDimension] ?? item.initialDimension}</Tag>
                  {item.transformedDimension ? (
                    <Tag tone="indigo">
                      AI：{DIMENSION_LABELS[item.transformedDimension] ?? item.transformedDimension}
                    </Tag>
                  ) : null}
                  <Tag tone="emerald">状态：{STATUS_LABELS[item.status] ?? item.status}</Tag>
                  <Tag>rev {item.revision}</Tag>
                </div>
                <div className="text-slate-600">
                  目标 Skill：{displayName(item.targetSkillId)}
                </div>
              </div>
              <div className="flex gap-2">
                {item.status === 'pending_triage' ? (
                  <Button
                    size="sm"
                    disabled={busy === item.poolId}
                    onClick={() => void handleTransform(item)}
                  >
                    AI 转换
                  </Button>
                ) : null}
                {item.status === 'transformed' ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setEditing((cur) => (cur === item.poolId ? null : item.poolId))
                    }
                  >
                    {isEditing ? '收起' : '编辑确认'}
                  </Button>
                ) : null}
                {item.status !== 'rejected' && item.status !== 'confirmed' ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === item.poolId}
                    onClick={() => void handleReject(item)}
                  >
                    拒绝
                  </Button>
                ) : null}
              </div>
            </div>

            {isEditing ? (
              <div className="mt-4 space-y-4 border-t border-slate-100 pt-4">
                <div className="flex items-center gap-2">
                  <label className="text-xs text-slate-600">错误维度</label>
                  <select
                    className="rounded-md border border-slate-200 px-2 py-1 text-sm"
                    data-testid={`eval-case-pool-dimension-${item.poolId}`}
                    value={effectiveDimension}
                    onChange={(e) =>
                      setPending((prev) => ({
                        ...prev,
                        [item.poolId]: {
                          dimension: e.target.value,
                          proposal: prev[item.poolId]?.proposal ?? {},
                        },
                      }))
                    }
                  >
                    {DIMENSIONS.map((d) => (
                      <option key={d} value={d}>
                        {DIMENSION_LABELS[d]}
                      </option>
                    ))}
                  </select>
                </div>
                <CaseProposalEditor
                  dimension={effectiveDimension}
                  proposal={edit?.proposal ?? null}
                  onChange={(dim, proposal) =>
                    setPending((prev) => ({
                      ...prev,
                      [item.poolId]: { dimension: dim, proposal },
                    }))
                  }
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={busy === item.poolId}
                    onClick={() => void handleConfirm(item)}
                  >
                    确认投影
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function Tag({
  children,
  tone = 'slate',
}: {
  children: React.ReactNode
  tone?: 'slate' | 'indigo' | 'emerald'
}) {
  const tones: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-600',
    indigo: 'bg-indigo-50 text-indigo-700',
    emerald: 'bg-emerald-50 text-emerald-700',
  }
  return (
    <span className={`rounded px-1.5 py-0.5 ${tones[tone]}`}>{children}</span>
  )
}

function describeError(err: unknown): string {
  if (err instanceof ApiClientError && err.status === 409) {
    return `案例已被修改（当前 revision 可能已变），请重新加载后重试。`
  }
  return err instanceof ApiClientError ? err.detail.message : '操作失败'
}
