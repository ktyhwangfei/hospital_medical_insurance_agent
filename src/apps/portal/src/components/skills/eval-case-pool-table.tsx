'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Database, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import CaseProposalEditor from '@/components/skills/case-proposal-editor'
import { useSkillNameMap } from '@/lib/use-skill-name-map'
import { ApiClientError } from '@/lib/types'
import {
  confirmEvalCasePoolItem,
  rejectEvalCasePoolItem,
  transformEvalCasePoolItem,
  type EvalCasePoolConfirmRequest,
} from '@/lib/api-client'
import { listEvalCasePool, type EvalCasePoolItem } from '@/lib/policy-qa-feedback'

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
  triaged: '已分型',
  transformed: '已转换',
  confirmed: '已确认',
  rejected: '已拒绝',
  discarded: '已丢弃',
}

const STATUS_TONE: Record<string, string> = {
  pending_triage: 'bg-amber-50 text-amber-700',
  triaged: 'bg-slate-100 text-slate-600',
  transformed: 'bg-indigo-50 text-indigo-700',
  confirmed: 'bg-emerald-50 text-emerald-700',
  rejected: 'bg-rose-50 text-rose-700',
  discarded: 'bg-rose-50 text-rose-700',
}

interface PendingEdit {
  dimension: string
  proposal: Record<string, unknown>
}

/**
 * Skill 错误案例池表格：浏览（含脱敏摘要，可区分条目）+ 行内编辑确认/拒绝。
 * 复用案例挖掘的 transform/confirm/reject API 与 CaseProposalEditor。
 */
export default function EvalCasePoolTable() {
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
      setError(err instanceof ApiClientError ? err.detail.message : '加载案例池失败')
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
        error_dimension:
          edit?.dimension ?? item.transformedDimension ?? item.initialDimension,
        target_skill_id:
          (edit?.proposal.target_skill_id as string | undefined) ?? item.targetSkillId,
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

  return (
    <section data-testid="eval-case-pool-table" className="space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-800">
          <Database className="size-5" aria-hidden />
          <h2 className="text-lg font-semibold">错误案例池</h2>
        </div>
        <span className="text-sm text-slate-500">共 {items.length} 条</span>
      </header>

      {actionError ? (
        <div
          data-testid="eval-case-pool-action-error"
          className="flex items-center justify-between gap-2 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800"
        >
          <span className="flex items-center gap-2">
            <AlertCircle className="size-4" aria-hidden />
            {actionError}
          </span>
          <Button variant="ghost" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-4" aria-hidden />
            重新加载
          </Button>
        </div>
      ) : null}

      {error ? (
        <div className="flex items-center gap-2 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <AlertCircle className="size-4" aria-hidden />
          {error}
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">加载中…</p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">
          暂无案例。用户在政策问答中提交「回答有误」反馈后，案例将在此汇总。
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">问题摘要</th>
                <th className="px-3 py-2">答案摘要</th>
                <th className="px-3 py-2">错误维度</th>
                <th className="px-3 py-2">目标技能</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((item) => {
                const edit = pending[item.poolId]
                const effectiveDimension =
                  edit?.dimension ?? item.transformedDimension ?? item.initialDimension
                const isEditing = editing === item.poolId
                return (
                  <FragmentRow
                    key={item.poolId}
                    item={item}
                    isEditing={isEditing}
                    effectiveDimension={effectiveDimension}
                    busy={busy}
                    displayName={displayName}
                    onTransform={() => void handleTransform(item)}
                    onToggleEdit={() =>
                      setEditing((cur) => (cur === item.poolId ? null : item.poolId))
                    }
                    onConfirm={() => void handleConfirm(item)}
                    onReject={() => void handleReject(item)}
                    onDimensionChange={(dim) =>
                      setPending((prev) => ({
                        ...prev,
                        [item.poolId]: {
                          dimension: dim,
                          proposal: prev[item.poolId]?.proposal ?? {},
                        },
                      }))
                    }
                    onProposalChange={(dim, proposal) =>
                      setPending((prev) => ({
                        ...prev,
                        [item.poolId]: { dimension: dim, proposal },
                      }))
                    }
                    edit={edit}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

interface FragmentRowProps {
  item: EvalCasePoolItem
  isEditing: boolean
  effectiveDimension: string
  busy: string | null
  displayName: (id: string | null | undefined) => string
  edit?: PendingEdit
  onTransform: () => void
  onToggleEdit: () => void
  onConfirm: () => void
  onReject: () => void
  onDimensionChange: (dim: string) => void
  onProposalChange: (dim: string, proposal: Record<string, unknown>) => void
}

function FragmentRow({
  item,
  isEditing,
  effectiveDimension,
  busy,
  displayName,
  edit,
  onTransform,
  onToggleEdit,
  onConfirm,
  onReject,
  onDimensionChange,
  onProposalChange,
}: FragmentRowProps) {
  return (
    <>
      <tr data-testid={`eval-case-pool-row-${item.poolId}`}>
        <td className="max-w-[260px] px-3 py-2 text-slate-700">
          <div className="truncate" title={item.questionExcerpt}>
            {item.questionExcerpt || <span className="text-slate-300">—</span>}
          </div>
        </td>
        <td className="max-w-[220px] px-3 py-2 text-slate-600">
          <div className="truncate" title={item.answerExcerpt}>
            {item.answerExcerpt || <span className="text-slate-300">—</span>}
          </div>
        </td>
        <td className="px-3 py-2">
          <span className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
            {DIMENSION_LABELS[item.errorDimension] ?? item.errorDimension}
          </span>
        </td>
        <td className="px-3 py-2 text-slate-700">{displayName(item.targetSkillId)}</td>
        <td className="px-3 py-2">
          <span
            className={`rounded px-2 py-0.5 text-xs ${
              STATUS_TONE[item.status] ?? 'bg-slate-100 text-slate-600'
            }`}
          >
            {STATUS_LABELS[item.status] ?? item.status}
          </span>
        </td>
        <td className="px-3 py-2">
          <div className="flex justify-end gap-1.5">
            {item.status === 'pending_triage' ? (
              <Button size="sm" disabled={busy === item.poolId} onClick={onTransform}>
                AI 转换
              </Button>
            ) : null}
            {item.status === 'transformed' ? (
              <Button size="sm" variant="outline" onClick={onToggleEdit}>
                {isEditing ? '收起' : '编辑确认'}
              </Button>
            ) : null}
            {item.status !== 'rejected' && item.status !== 'confirmed' ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy === item.poolId}
                onClick={onReject}
              >
                拒绝
              </Button>
            ) : null}
          </div>
        </td>
      </tr>
      {isEditing ? (
        <tr>
          <td colSpan={6} className="bg-slate-50/60 px-4 py-4">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-600">错误维度</label>
                <select
                  className="rounded-md border border-slate-200 px-2 py-1 text-sm"
                  data-testid={`eval-case-pool-dimension-${item.poolId}`}
                  value={effectiveDimension}
                  onChange={(e) => onDimensionChange(e.target.value)}
                >
                  {DIMENSIONS.map((d) => (
                    <option key={d} value={d}>
                      {DIMENSION_LABELS[d]}
                    </option>
                  ))}
                </select>
                <span className="ml-auto text-xs text-slate-400">
                  来源 {item.sourceQaTurnId} · rev {item.revision}
                </span>
              </div>
              <CaseProposalEditor
                dimension={effectiveDimension}
                proposal={edit?.proposal ?? null}
                onChange={onProposalChange}
              />
              <div className="flex gap-2">
                <Button size="sm" disabled={busy === item.poolId} onClick={onConfirm}>
                  确认投影
                </Button>
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  )
}

function describeError(err: unknown): string {
  if (err instanceof ApiClientError && err.status === 409) {
    return `案例已被修改（当前 revision 可能已变），请重新加载后重试。`
  }
  return err instanceof ApiClientError ? err.detail.message : '操作失败'
}
