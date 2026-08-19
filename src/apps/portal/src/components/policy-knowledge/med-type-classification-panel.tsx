'use client'

import { useMemo, useState } from 'react'
import { BadgeCheck, Loader2, Pencil, RotateCcw, Tag } from 'lucide-react'

import {
  PolicyKnowledgeApiError,
  resetUnitMedType,
  setUnitMedType,
  type EligibleKnowledgeUnit,
} from '@/lib/policy-knowledge-api'

/** 修正下拉的候选：政策标准医疗类别（与后端 MEDICAL_CATEGORY 别名表对齐）+ 通用 */
export const MED_TYPE_OPTIONS = [
  '通用', '住院', '门诊', '门诊特殊病', '门诊慢性病',
  '急诊', '急诊抢救', '急诊留观', '家庭病床', '日间手术',
]

type MedTypeClassificationPanelProps = {
  units: EligibleKnowledgeUnit[]
  userId: string
  ready: boolean
  /** 执行分类：重新拉取 eligible-units（服务端确定性分类） */
  onClassify: () => void | Promise<void>
  /** 修正生效后刷新（保持与父页数据一致） */
  onChanged: () => void | Promise<void>
}

/**
 * Issue #19：知识构建页的医疗类别分类面板。
 * 执行分类 → 类别数量卡片（可点击下钻）→ 单元明细（可人工修正、可恢复自动）。
 */
export function MedTypeClassificationPanel({
  units, userId, ready, onClassify, onChanged,
}: MedTypeClassificationPanelProps) {
  const [classifying, setClassifying] = useState(false)
  const [done, setDone] = useState(false)
  const [activeCategory, setActiveCategory] = useState('')
  const [editing, setEditing] = useState<{ docId: string; unitId: string } | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const counts = useMemo(() => {
    const byCategory = new Map<string, { total: number; manual: number }>()
    for (const unit of units) {
      const key = unit.med_type || '通用'
      const entry = byCategory.get(key) ?? { total: 0, manual: 0 }
      entry.total += 1
      if (unit.med_type_source === 'manual') entry.manual += 1
      byCategory.set(key, entry)
    }
    return [...byCategory.entries()]
      .sort((a, b) => b[1].total - a[1].total || a[0].localeCompare(b[0], 'zh-CN'))
  }, [units])

  const detailUnits = useMemo(
    () => (activeCategory
      ? units.filter((unit) => (unit.med_type || '通用') === activeCategory)
      : []),
    [units, activeCategory],
  )

  async function handleClassify() {
    setClassifying(true)
    setError('')
    try {
      await onClassify()
      setDone(true)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setClassifying(false)
    }
  }

  function startEdit(unit: EligibleKnowledgeUnit) {
    setEditing({ docId: unit.doc_id, unitId: unit.unit_id })
    setEditValue(unit.med_type || '通用')
    setError('')
  }

  async function saveEdit() {
    if (!editing) return
    setSaving(true)
    setError('')
    try {
      await setUnitMedType(editing.docId, editing.unitId, editValue, userId)
      setEditing(null)
      await onChanged()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setSaving(false)
    }
  }

  async function resetEdit(unit: EligibleKnowledgeUnit) {
    setSaving(true)
    setError('')
    try {
      await resetUnitMedType(unit.doc_id, unit.unit_id)
      await onChanged()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section
      aria-labelledby="med-type-classification-title"
      data-testid="med-type-classification-section"
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <h3 id="med-type-classification-title" className="text-sm font-semibold tracking-tight text-slate-900">
            医疗类别分类
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            自动分类按单元原文就近识别；分类不对可人工修正，新建构建任务时按类别筛选。
          </p>
        </div>
        <button
          type="button"
          disabled={!ready || classifying}
          onClick={() => void handleClassify()}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-emerald-700 px-3 text-xs font-semibold text-white transition-all hover:bg-emerald-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {classifying ? <Loader2 className="size-3.5 animate-spin" /> : <Tag className="size-3.5" />}
          {classifying ? '分类中…' : done ? '重新分类' : '执行分类'}
        </button>
      </div>

      {error && (
        <p role="alert" className="border-b border-slate-100 px-4 py-2 text-xs font-medium text-red-700">{error}</p>
      )}

      {!done ? (
        <p className="px-4 py-8 text-center text-sm text-slate-400">
          点击「执行分类」对可构建单元按医疗类别归类。
        </p>
      ) : (
        <div className="space-y-4 px-4 py-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="医疗类别数量">
            {counts.map(([category, { total, manual }]) => {
              const active = activeCategory === category
              return (
                <button
                  key={category}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setActiveCategory(active ? '' : category)}
                  className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
                    active
                      ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                  }`}
                >
                  <span>{category}</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-slate-600">{total}</span>
                  {manual > 0 && (
                    <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-700" title={`${manual} 个人工修正`}>
                      <BadgeCheck className="size-3" />{manual}
                    </span>
                  )}
                </button>
              )
            })}
            {!counts.length && <p className="text-xs text-slate-400">暂无可分类单元。</p>}
          </div>

          {activeCategory ? (
            <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              <p className="px-3 py-2 text-xs font-semibold text-slate-500">
                「{activeCategory}」{detailUnits.length} 个单元
              </p>
              {detailUnits.map((unit) => {
                const isEditing = editing?.docId === unit.doc_id && editing?.unitId === unit.unit_id
                return (
                  <div key={`${unit.doc_id}:${unit.unit_id}`} className="flex flex-wrap items-start gap-3 px-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="max-w-72 truncate text-xs font-medium text-slate-900" title={unit.doc_title}>{unit.doc_title}</p>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          unit.med_type_source === 'manual'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-slate-100 text-slate-500'
                        }`}>
                          {unit.med_type_source === 'manual' ? '人工' : '自动'}
                        </span>
                        {unit.availability === 'CLAIMED' && (
                          <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700">占用中</span>
                        )}
                      </div>
                      <p className="mt-1 text-[11px] text-slate-500">{unit.path.join(' / ') || unit.unit_id}</p>
                      <p className="mt-1 line-clamp-1 text-[11px] text-slate-400">{unit.source_preview}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {isEditing ? (
                        <>
                          <select
                            aria-label="选择医疗类别"
                            value={editValue}
                            onChange={(event) => setEditValue(event.target.value)}
                            className="h-7 rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus:border-emerald-500"
                          >
                            {MED_TYPE_OPTIONS.map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </select>
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => void saveEdit()}
                            className="h-7 rounded-lg bg-emerald-700 px-2.5 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
                          >
                            保存
                          </button>
                          <button
                            type="button"
                            disabled={saving}
                            onClick={() => setEditing(null)}
                            className="h-7 rounded-lg border border-slate-200 px-2.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                          >
                            取消
                          </button>
                        </>
                      ) : (
                        <>
                          <span className="rounded-md bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-200">
                            {unit.med_type || '通用'}
                          </span>
                          <button
                            type="button"
                            onClick={() => startEdit(unit)}
                            className="inline-flex h-7 items-center gap-1 rounded-lg border border-slate-200 px-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
                          >
                            <Pencil className="size-3" />修改
                          </button>
                          {unit.med_type_source === 'manual' && (
                            <button
                              type="button"
                              disabled={saving}
                              onClick={() => void resetEdit(unit)}
                              className="inline-flex h-7 items-center gap-1 rounded-lg border border-slate-200 px-2 text-xs font-medium text-slate-500 hover:bg-slate-50 disabled:opacity-50"
                              title="清除人工修正，恢复自动分类"
                            >
                              <RotateCcw className="size-3" />恢复自动
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-xs text-slate-400">点击上方类别查看单元明细，可修正分类。</p>
          )}
        </div>
      )}
    </section>
  )
}

function errorMessage(error: unknown): string {
  if (error instanceof PolicyKnowledgeApiError) return error.message
  return error instanceof Error ? error.message : '医疗类别分类操作失败'
}
