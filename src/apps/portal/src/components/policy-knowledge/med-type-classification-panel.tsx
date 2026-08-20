'use client'

import { useMemo, useState } from 'react'
import { BadgeCheck, Loader2, Pencil, RotateCcw, Search, Tag, X } from 'lucide-react'

import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import {
  PolicyKnowledgeApiError,
  resetUnitMedType,
  setUnitMedType,
  type EligibleKnowledgeUnit,
} from '@/lib/policy-knowledge-api'

/** 修正下拉的候选：政策标准医疗类别（与后端 MEDICAL_CATEGORY 别名表对齐）+ 通用/购药 */
export const MED_TYPE_OPTIONS = [
  '通用', '住院', '门诊', '门诊特殊病', '门诊慢性病',
  '急诊', '急诊抢救', '急诊留观', '家庭病床', '日间手术', '购药',
]

type MedTypeClassificationPanelProps = {
  units: EligibleKnowledgeUnit[]
  ready: boolean
  /** 执行分类：重新拉取 eligible-units（服务端确定性分类） */
  onClassify: () => void | Promise<void>
  /** 修正生效后刷新（保持与父页数据一致） */
  onChanged: () => void | Promise<void>
}

/**
 * Issue #19：知识构建页的医疗类别分类面板。
 * 执行分类 → 类别数量卡片 → 点击下钻侧边抽屉（模糊搜索 + 类别切换 + 人工修正）。
 */
export function MedTypeClassificationPanel({
  units, ready, onClassify, onChanged,
}: MedTypeClassificationPanelProps) {
  const [classifying, setClassifying] = useState(false)
  const [drawerCategory, setDrawerCategory] = useState('')
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

  const categories = useMemo(
    () => counts.map(([category]) => category),
    [counts],
  )

  async function handleClassify() {
    setClassifying(true)
    setError('')
    try {
      await onClassify()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setClassifying(false)
    }
  }

  function openDrawer(category: string) {
    setDrawerCategory(category)
    setError('')
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
          {classifying ? '分类中…' : '重新分类'}
        </button>
      </div>

      {error && (
        <p role="alert" className="border-b border-slate-100 px-4 py-2 text-xs font-medium text-red-700">{error}</p>
      )}

      {!ready ? (
        <p className="px-4 py-8 text-center text-sm text-slate-400">
          正在加载医疗类别分类…
        </p>
      ) : (
        <div className="px-4 py-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="医疗类别数量">
            {counts.map(([category, { total, manual }]) => (
              <button
                key={category}
                type="button"
                onClick={() => openDrawer(category)}
                title={`查看「${category}」单元明细`}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 transition-colors hover:border-emerald-400 hover:bg-emerald-50/40 hover:text-emerald-800"
              >
                <span>{category}</span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-slate-600">{total}</span>
                {manual > 0 && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-700" title={`${manual} 个人工修正`}>
                    <BadgeCheck className="size-3" />{manual}
                  </span>
                )}
              </button>
            ))}
            {!counts.length && <p className="text-xs text-slate-400">暂无可分类单元。</p>}
          </div>
        </div>
      )}

      {drawerCategory && (
        <MedTypeDetailDrawer
          units={units}
          categories={categories}
          category={drawerCategory}
          onCategoryChange={setDrawerCategory}
          onChanged={onChanged}
          onClose={() => setDrawerCategory('')}
        />
      )}
    </section>
  )
}

/** 类别明细侧边抽屉：模糊搜索 + 类别切换 + 行内人工修正。 */
function MedTypeDetailDrawer({
  units, categories, category, onCategoryChange, onChanged, onClose,
}: {
  units: EligibleKnowledgeUnit[]
  categories: string[]
  category: string
  onCategoryChange: (category: string) => void
  onChanged: () => void | Promise<void>
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<{ docId: string; unitId: string } | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const categoryUnits = useMemo(
    () => units.filter((unit) => (unit.med_type || '通用') === category),
    [units, category],
  )
  // 模糊搜索：文档标题 / 条款路径 / 原文预览 子串匹配（不区分大小写）
  const visibleUnits = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('zh-CN')
    if (!query) return categoryUnits
    return categoryUnits.filter((unit) =>
      `${unit.doc_title} ${unit.path.join(' ')} ${unit.source_preview}`
        .toLocaleLowerCase('zh-CN')
        .includes(query),
    )
  }, [categoryUnits, search])

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
      await setUnitMedType(editing.docId, editing.unitId, editValue)
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
    <Dialog open onOpenChange={(open) => { if (!open && !saving) onClose() }}>
      <DialogContent
        aria-label={`${category}单元明细`}
        showCloseButton={false}
        className="w-full flex-col gap-0 overflow-hidden bg-white p-0 shadow-2xl ring-0"
        style={{
          top: 0, right: 0, bottom: 0, left: 'auto',
          display: 'flex', height: '100dvh', maxWidth: '40rem',
          transform: 'none', translate: 'none', borderRadius: 0,
        }}
      >
        <header className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-emerald-700">医疗类别 · 单元明细</p>
              <DialogTitle className="mt-1 text-lg font-semibold tracking-tight text-slate-900">
                {category}
                <span className="ml-2 font-mono text-sm font-normal text-slate-400">
                  {visibleUnits.length}/{categoryUnits.length}
                </span>
              </DialogTitle>
            </div>
            <button
              type="button"
              aria-label="关闭单元明细抽屉"
              disabled={saving}
              onClick={onClose}
              className="ml-auto rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="mt-3 flex gap-2">
            <label className="relative block flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-slate-400" />
              <input
                autoFocus
                type="search"
                aria-label="搜索单元"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="模糊搜索文档标题、条款或原文"
                className="h-9 w-full rounded-lg border border-slate-200 pl-9 pr-3 text-sm outline-none transition-colors focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100"
              />
            </label>
            <select
              aria-label="切换医疗类别"
              value={category}
              onChange={(event) => {
                setSearch('')
                setEditing(null)
                onCategoryChange(event.target.value)
              }}
              className="h-9 max-w-40 rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition-colors focus:border-emerald-500"
            >
              {categories.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </div>
          {error && <p role="alert" className="mt-2 text-xs font-medium text-red-700">{error}</p>}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {visibleUnits.length ? (
            <div className="space-y-2">
              {visibleUnits.map((unit) => {
                const isEditing = editing?.docId === unit.doc_id && editing?.unitId === unit.unit_id
                return (
                  <article key={`${unit.doc_id}:${unit.unit_id}`} className="rounded-xl border border-slate-200 p-3 transition-colors hover:border-slate-300">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="max-w-72 truncate text-xs font-medium text-slate-900" title={unit.doc_title}>{unit.doc_title}</p>
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            unit.med_type_source === 'manual' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'
                          }`}>
                            {unit.med_type_source === 'manual' ? '人工' : '自动'}
                          </span>
                          {unit.availability === 'CLAIMED' && (
                            <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700">占用中</span>
                          )}
                        </div>
                        <p className="mt-1 text-[11px] text-slate-500">{unit.path.join(' / ') || unit.unit_id}</p>
                        <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-400">{unit.source_preview}</p>
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
                  </article>
                )
              })}
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-200 py-10 text-center text-sm text-slate-400">
              没有匹配的单元
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function errorMessage(error: unknown): string {
  if (error instanceof PolicyKnowledgeApiError) return error.message
  return error instanceof Error ? error.message : '医疗类别分类操作失败'
}
