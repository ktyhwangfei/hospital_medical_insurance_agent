'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ShieldCheck, Loader2, AlertCircle, RefreshCw, Search, X, Plus,
  CheckCircle2, XCircle, Send, Archive, Sparkles, Pencil, FilePlus2, FlaskConical,
} from 'lucide-react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import {
  addTrustedQuestionSynonym,
  approveTrustedQuestion,
  createTrustedQuestion,
  listTrustedQuestions,
  matchAndExecuteTrustedQuestion,
  rejectTrustedQuestion,
  removeTrustedQuestionSynonym,
  retireTrustedQuestion,
  submitTrustedQuestionReview,
  updateTrustedQuestion,
} from '@/lib/trusted-questions-api'
import type {
  TrustedAnswerOutcome,
  TrustedMatchAndExecuteResult,
  TrustedQuestion,
  TrustedQuestionStatus,
} from '@/lib/trusted-questions-api'

// ── 工具 ────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
  } catch { return iso }
}

const STATUS_META: Record<TrustedQuestionStatus, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'bg-slate-100 text-slate-600' },
  pending_review: { label: '待审核', cls: 'bg-amber-50 text-amber-700' },
  active: { label: '已生效', cls: 'bg-emerald-50 text-emerald-700' },
  retired: { label: '已退役', cls: 'bg-neutral-100 text-neutral-500' },
}

const TABS: { key: TrustedQuestionStatus | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending_review', label: '待审核' },
  { key: 'draft', label: '草稿' },
  { key: 'active', label: '已生效' },
  { key: 'retired', label: '已退役' },
]

const HEADER_STATS: { key: TrustedQuestionStatus; label: string; dot: string }[] = [
  { key: 'active', label: '已生效', dot: 'bg-emerald-500' },
  { key: 'pending_review', label: '待审核', dot: 'bg-amber-500' },
  { key: 'draft', label: '草稿', dot: 'bg-slate-400' },
  { key: 'retired', label: '已退役', dot: 'bg-slate-300' },
]

// ── 小组件 ──────────────────────────────────────────────────

function StatusBadge({ status }: { status: TrustedQuestionStatus }) {
  const m = STATUS_META[status]
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-px text-[10px] font-semibold ${m.cls}`}>
      {m.label}
    </span>
  )
}

function ActionBtn({
  onClick, disabled, tone, icon, label,
}: {
  onClick: () => void
  disabled?: boolean
  tone: 'primary' | 'danger' | 'neutral'
  icon: ReactNode
  label: string
}) {
  const cls = {
    primary: 'border-amber-200 text-amber-700 hover:bg-amber-50 focus-visible:ring-amber-300/50',
    danger: 'border-red-200 text-red-600 hover:bg-red-50 focus-visible:ring-red-300/50',
    neutral: 'border-slate-200 text-slate-600 hover:bg-slate-50 focus-visible:ring-slate-300/50',
  }[tone]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 rounded-lg border bg-white px-2.5 py-1 text-xs font-medium shadow-sm transition-all duration-200 outline-none active:scale-[0.98] focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-40 ${cls}`}
    >
      {icon}{label}
    </button>
  )
}

function StatChip({ label, count, dot }: { label: string; count: number; dot: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1.5 text-xs text-slate-600 backdrop-blur">
      <span className={`size-1.5 rounded-full ${dot}`} />
      <span className="tabular-nums font-semibold text-slate-900">{count}</span>
      <span>{label}</span>
    </span>
  )
}

const CTA_CLS =
  'inline-flex items-center justify-center gap-1.5 rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:bg-amber-700 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/70 disabled:pointer-events-none disabled:opacity-40'

// ── 匹配测试面板 ────────────────────────────────────────────

const ANSWER_OUTCOME_META: Record<TrustedAnswerOutcome, { label: string; cls: string }> = {
  executed: { label: '执行成功', cls: 'bg-emerald-50 text-emerald-700' },
  trait_violation: { label: '特征违例', cls: 'bg-amber-50 text-amber-700' },
  execution_failed: { label: '执行失败', cls: 'bg-red-50 text-red-600' },
  no_plan: { label: '无查询计划', cls: 'bg-slate-100 text-slate-500' },
}

function MatchTester() {
  const [question, setQuestion] = useState('')
  const [role, setRole] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<TrustedMatchAndExecuteResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!question.trim()) return
    setRunning(true); setError(null); setResult(null)
    try {
      setResult(await matchAndExecuteTrustedQuestion({ question: question.trim(), role: role.trim() || undefined }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '匹配失败')
    } finally { setRunning(false) }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 ring-1 ring-amber-500/15">
          <FlaskConical className="size-4 text-amber-600" />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-800">匹配测试</p>
          <p className="text-[11px] leading-relaxed text-slate-400">仅 active 可信问题参与；命中即回放执行，不确定时返回候选，不猜测执行</p>
        </div>
      </div>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <label htmlFor="tq-match-q" className="text-xs font-medium text-slate-600">用户问题</label>
          <Input
            id="tq-match-q"
            placeholder="统筹自付为什么这么多？"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') run() }}
            className="h-9 rounded-xl bg-white/80 focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="tq-match-role" className="text-xs font-medium text-slate-600">角色（可选）</label>
          <Input
            id="tq-match-role"
            placeholder="如：收费员"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') run() }}
            className="h-9 rounded-xl bg-white/80 focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
          />
        </div>
        <button onClick={run} disabled={running || !question.trim()} className={`${CTA_CLS} w-full`}>
          {running ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
          测试
        </button>
      </div>
      {error && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-red-600">
          <AlertCircle className="size-3.5" />{error}
        </p>
      )}
      {result && (
        <div className="mt-3 space-y-1.5 rounded-xl bg-slate-50/80 p-3 ring-1 ring-slate-100">
          {result.outcome === 'matched' && result.question && (
            <>
              <p className="flex items-start gap-1.5 text-xs text-emerald-700">
                <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  <span className="font-semibold">命中：</span>
                  {result.question.standard_question}
                  <span className="ml-2 font-mono text-[10px] text-slate-400">{result.question.question_id}</span>
                </span>
              </p>
              {result.answer && (
                <div className="space-y-1.5 border-t border-slate-200/70 pt-2">
                  <p className="flex flex-wrap items-center gap-2 text-xs">
                    <span className={`inline-flex items-center rounded-full px-2 py-px text-[10px] font-semibold ${ANSWER_OUTCOME_META[result.answer.outcome].cls}`}>
                      {ANSWER_OUTCOME_META[result.answer.outcome].label}
                    </span>
                    {result.answer.result && (
                      <span className="text-[11px] text-slate-500">
                        质量 {result.answer.result.quality_status} · {result.answer.result.rows.length} 行
                      </span>
                    )}
                  </p>
                  {result.answer.violations.length > 0 && (
                    <ul className="space-y-0.5">
                      {result.answer.violations.map((violation) => (
                        <li key={violation} className="flex items-start gap-1 text-[11px] text-amber-700">
                          <AlertCircle className="mt-0.5 size-3 shrink-0" />{violation}
                        </li>
                      ))}
                    </ul>
                  )}
                  {result.answer.outcome === 'executed' && result.answer.result && result.answer.result.rows.length > 0 && (
                    <details className="rounded-lg border border-slate-200 bg-white p-2">
                      <summary className="cursor-pointer text-[11px] font-medium text-slate-600">结果预览（前 3 行）</summary>
                      <pre className="mt-1.5 max-h-40 overflow-auto rounded-md bg-slate-950 p-2 text-[10px] text-slate-100">
                        {JSON.stringify(result.answer.result.rows.slice(0, 3), null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </>
          )}
          {result.outcome === 'candidates' && (
            <div className="space-y-1">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-700">
                <Sparkles className="size-3.5" />不确定，需澄清（候选 {result.candidates.length}）：
              </p>
              {result.candidates.map((c) => (
                <p key={c.question_id} className="text-xs text-slate-600">
                  {c.standard_question}
                  <span className="ml-2 text-[10px] text-slate-400">
                    得分 {c.score.toFixed(2)} · 命中表达「{c.matched_expression}」
                  </span>
                </p>
              ))}
            </div>
          )}
          {result.outcome === 'no_match' && (
            <p className="text-xs text-slate-500">无可信候选，交回长尾受控语义生成。</p>
          )}
        </div>
      )}
    </section>
  )
}

// ── 骨架屏 ──────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div className="flex items-center justify-between gap-4 p-4">
      <div className="flex-1 space-y-2">
        <div className="h-4 w-2/5 animate-pulse rounded bg-slate-100" />
        <div className="h-3 w-3/5 animate-pulse rounded bg-slate-100/70" />
      </div>
      <div className="h-7 w-36 animate-pulse rounded-lg bg-slate-100" />
    </div>
  )
}

// ── 主页面 ──────────────────────────────────────────────────

export default function TrustedQuestionsPage() {
  const [items, setItems] = useState<TrustedQuestion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TrustedQuestionStatus | 'all'>('all')
  const [keyword, setKeyword] = useState('')
  const [operator, setOperator] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  // 新建表单
  const [newQuestion, setNewQuestion] = useState('')
  const [newSynonyms, setNewSynonyms] = useState('')

  // 同义表达输入（按行）
  const [synonymDraft, setSynonymDraft] = useState<Record<string, string>>({})

  // 行内对话框
  const [editTarget, setEditTarget] = useState<TrustedQuestion | null>(null)
  const [editText, setEditText] = useState('')
  const [rejectTarget, setRejectTarget] = useState<TrustedQuestion | null>(null)
  const [rejectNote, setRejectNote] = useState('')
  const [retireTarget, setRetireTarget] = useState<TrustedQuestion | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await listTrustedQuestions({ limit: 200 })
      setItems(r.items)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length }
    for (const q of items) c[q.status] = (c[q.status] ?? 0) + 1
    return c
  }, [items])

  const visible = useMemo(() => {
    let r = tab === 'all' ? items : items.filter((q) => q.status === tab)
    const kw = keyword.trim()
    if (kw) {
      r = r.filter(
        (q) =>
          q.standard_question.includes(kw) ||
          q.synonyms.some((s) => s.expression.includes(kw)),
      )
    }
    return r
  }, [items, tab, keyword])

  const requireOperator = (): string | null => {
    const op = operator.trim()
    if (!op) {
      setActionError('请先填写操作人 ID（开发期声明式身份）')
      return null
    }
    setActionError(null)
    return op
  }

  const run = async (q: TrustedQuestion, fn: () => Promise<TrustedQuestion>) => {
    setBusyId(q.question_id); setActionError(null)
    try {
      const updated = await fn()
      setItems((prev) => prev.map((p) => (p.question_id === q.question_id ? updated : p)))
    } catch (e) {
      setActionError(e instanceof Error ? e.message : '操作失败')
      await load() // 乐观锁冲突等场景回源刷新
    } finally { setBusyId(null) }
  }

  const onCreate = async () => {
    const op = requireOperator()
    if (!op || !newQuestion.trim()) return
    setActionError(null)
    try {
      await createTrustedQuestion({
        standard_question: newQuestion.trim(),
        created_by: op,
        synonyms: newSynonyms.split(/[,，;；]/).map((s) => s.trim()).filter(Boolean),
      })
      setNewQuestion(''); setNewSynonyms('')
      await load()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : '创建失败')
    }
  }

  const onSubmitReview = (q: TrustedQuestion) => {
    const op = requireOperator(); if (!op) return
    return run(q, () =>
      submitTrustedQuestionReview(q.question_id, { expected_version: q.version, operator: op }))
  }
  const onApprove = (q: TrustedQuestion) => {
    const op = requireOperator(); if (!op) return
    return run(q, () =>
      approveTrustedQuestion(q.question_id, { expected_version: q.version, operator: op }))
  }

  // 编辑 / 驳回 / 退役 走行内对话框（替代 window.prompt / window.confirm）
  const openEdit = (q: TrustedQuestion) => {
    if (!requireOperator()) return
    setEditText(q.standard_question)
    setEditTarget(q)
  }
  const openReject = (q: TrustedQuestion) => {
    if (!requireOperator()) return
    setRejectNote('')
    setRejectTarget(q)
  }
  const openRetire = (q: TrustedQuestion) => {
    if (!requireOperator()) return
    setRetireTarget(q)
  }

  const confirmEdit = async () => {
    if (!editTarget) return
    const op = requireOperator(); if (!op) return
    const next = editText.trim()
    if (!next || next === editTarget.standard_question) { setEditTarget(null); return }
    const target = editTarget
    setEditTarget(null)
    await run(target, () =>
      updateTrustedQuestion(target.question_id, {
        standard_question: next,
        synonyms: target.synonyms.map((s) => s.expression),
        expected_version: target.version,
      }))
  }

  const confirmReject = async () => {
    if (!rejectTarget) return
    const op = requireOperator(); if (!op) return
    const note = rejectNote.trim()
    if (!note) return
    const target = rejectTarget
    setRejectTarget(null); setRejectNote('')
    await run(target, () =>
      rejectTrustedQuestion(target.question_id, {
        expected_version: target.version, operator: op, review_note: note,
      }))
  }

  const confirmRetire = async () => {
    if (!retireTarget) return
    const op = requireOperator(); if (!op) return
    const target = retireTarget
    setRetireTarget(null)
    await run(target, () =>
      retireTrustedQuestion(target.question_id, { expected_version: target.version, operator: op }))
  }

  const onAddSynonym = (q: TrustedQuestion) => {
    const op = requireOperator(); if (!op) return
    const expr = (synonymDraft[q.question_id] ?? '').trim()
    if (!expr) return
    return run(q, async () => {
      const updated = await addTrustedQuestionSynonym(q.question_id, {
        expression: expr, added_by: op, expected_version: q.version,
      })
      setSynonymDraft((prev) => ({ ...prev, [q.question_id]: '' }))
      return updated
    })
  }
  const onRemoveSynonym = (q: TrustedQuestion, expression: string) => {
    return run(q, () => removeTrustedQuestionSynonym(q.question_id, expression, q.version))
  }

  return (
    <div className="relative mx-auto flex w-full max-w-[1400px] flex-col gap-5 px-4 py-6 sm:px-6 sm:py-8">
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#f8fafc_0%,#f1f5f9_100%)]" />
      </div>

      {/* 页头 */}
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-amber-500/10 ring-1 ring-amber-500/20">
            <ShieldCheck className="size-5.5 text-amber-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">可信问题库</h1>
            <p className="mt-1 text-sm text-slate-500">标准问题确定性匹配库 —— 命中即执行，未命中交回长尾受控生成</p>
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="group inline-flex size-9 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 shadow-sm transition-all duration-200 hover:border-slate-300 hover:text-slate-700 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
          aria-label="刷新列表"
          title="刷新列表"
        >
          <RefreshCw className={`size-4 transition-transform duration-700 group-hover:rotate-180 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </header>

      {/* 状态统计 */}
      <div className="flex flex-wrap items-center gap-2">
        {HEADER_STATS.map((s) => (
          <StatChip key={s.key} label={s.label} count={counts[s.key] ?? 0} dot={s.dot} />
        ))}
      </div>

      {actionError && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50/60 px-4 py-2.5 text-xs text-red-700">
          <AlertCircle className="size-3.5 shrink-0" />{actionError}
        </div>
      )}

      {/* 非对称双栏：左=列表，右=操作栏（移动端操作栏置顶） */}
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="order-last space-y-4 xl:order-none">
          {/* Tabs + 搜索 */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex w-fit items-center gap-1 rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200/70">
              {TABS.map((t) => {
                const sel = tab === t.key
                return (
                  <button
                    key={t.key}
                    onClick={() => setTab(t.key)}
                    className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/50 ${sel ? 'bg-amber-100 text-amber-800 shadow-sm' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'}`}
                  >
                    {t.label}
                    <span className={`text-[11px] tabular-nums ${sel ? 'text-amber-600' : 'text-slate-400'}`}>{counts[t.key] ?? 0}</span>
                  </button>
                )
              })}
            </div>
            <div className="relative min-w-[220px] max-w-[320px] flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
              <input
                placeholder="搜索标准问题 / 同义表达"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white/80 py-2.5 pl-10 pr-10 text-sm text-slate-800 shadow-sm backdrop-blur outline-none transition-all duration-200 placeholder:text-slate-400 focus:border-amber-300 focus:bg-white focus:ring-2 focus:ring-amber-200/40"
              />
              {keyword && (
                <button
                  onClick={() => setKeyword('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-slate-400 transition-colors hover:text-slate-600"
                  aria-label="清除搜索"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* 加载骨架 */}
          {loading && (
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="divide-y divide-slate-100">
                {Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)}
              </div>
            </div>
          )}

          {/* 错误态 */}
          {!loading && error && (
            <div className="flex flex-col items-center gap-4 rounded-2xl border border-red-100 bg-red-50/50 p-12">
              <AlertCircle className="size-8 text-red-400" />
              <p className="text-sm font-semibold text-red-700">加载失败</p>
              <p className="max-w-md text-center text-xs text-red-500">{error}</p>
              <button
                onClick={load}
                className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-white px-5 py-2 text-sm font-medium text-red-600 shadow-sm transition-all duration-200 hover:bg-red-50 active:scale-[0.98]"
              >
                <RefreshCw className="size-3.5" />重试
              </button>
            </div>
          )}

          {/* 空态 */}
          {!loading && !error && visible.length === 0 && (
            <div className="flex flex-col items-center gap-4 rounded-3xl border border-dashed border-slate-300/70 bg-white/60 px-6 py-20 text-center">
              <div className="flex size-12 items-center justify-center rounded-2xl bg-slate-100 ring-1 ring-slate-200/60">
                <ShieldCheck className="size-6 text-slate-300" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">暂无可信问题</p>
                <p className="mt-1 text-xs text-slate-400">新建草稿并提交审核，生效后即可参与确定性匹配。</p>
              </div>
            </div>
          )}

          {/* 列表 */}
          {!loading && !error && visible.length > 0 && (
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <ul className="divide-y divide-slate-100">
                {visible.map((q, i) => {
                  const busy = busyId === q.question_id
                  return (
                    <li
                      key={q.question_id}
                      className="group animate-in fade-in-0 slide-in-from-bottom-2 duration-500 ease-out"
                      style={{ animationDelay: `${Math.min(i, 12) * 60}ms`, animationFillMode: 'backwards' }}
                    >
                      <div className="p-4 transition-colors duration-200 hover:bg-slate-50/70">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <StatusBadge status={q.status} />
                              <span className="text-sm font-semibold text-slate-900">{q.standard_question}</span>
                              <span className="font-mono text-[10px] text-slate-400">{q.question_id} · v{q.version}</span>
                            </div>
                            {/* 同义表达 */}
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              {q.synonyms.map((s) => (
                                <span key={s.expression} className="group/syn inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] text-slate-600 transition-colors hover:border-slate-300">
                                  {s.expression}
                                  <span className="text-[9px] text-slate-400">{s.added_by}</span>
                                  <button
                                    onClick={() => onRemoveSynonym(q, s.expression)}
                                    disabled={busy}
                                    className="text-slate-300 transition-colors hover:text-red-500 disabled:pointer-events-none disabled:opacity-40"
                                    title="移除该同义表达"
                                    aria-label={`移除同义表达 ${s.expression}`}
                                  >
                                    <X className="size-3" />
                                  </button>
                                </span>
                              ))}
                              <input
                                placeholder="加同义表达"
                                value={synonymDraft[q.question_id] ?? ''}
                                onChange={(e) => setSynonymDraft((prev) => ({ ...prev, [q.question_id]: e.target.value }))}
                                onKeyDown={(e) => { if (e.key === 'Enter') onAddSynonym(q) }}
                                className="w-28 rounded-full border border-dashed border-slate-300 bg-transparent px-2.5 py-0.5 text-[11px] outline-none transition-colors placeholder:text-slate-400 focus:border-amber-400 focus:ring-2 focus:ring-amber-200/40"
                              />
                            </div>
                            <p className="mt-2 text-[11px] text-slate-400">
                              创建 {q.created_by || '—'} · {fmtTime(q.created_at)}
                              {q.reviewed_by && <> · 审核 {q.reviewed_by} · {q.reviewed_at ? fmtTime(q.reviewed_at) : ''}</>}
                              {q.review_note && <> · 驳回原因：{q.review_note}</>}
                            </p>
                          </div>
                          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                            {busy && <Loader2 className="size-4 animate-spin text-slate-300" />}
                            {(q.status === 'draft' || q.status === 'pending_review') && (
                              <ActionBtn onClick={() => openEdit(q)} disabled={busy} tone="neutral" icon={<Pencil className="size-3" />} label="编辑" />
                            )}
                            {q.status === 'draft' && (
                              <ActionBtn onClick={() => onSubmitReview(q)} disabled={busy} tone="neutral" icon={<Send className="size-3" />} label="提交审核" />
                            )}
                            {q.status === 'pending_review' && (
                              <>
                                <ActionBtn onClick={() => onApprove(q)} disabled={busy} tone="primary" icon={<CheckCircle2 className="size-3" />} label="通过" />
                                <ActionBtn onClick={() => openReject(q)} disabled={busy} tone="danger" icon={<XCircle className="size-3" />} label="驳回" />
                              </>
                            )}
                            {q.status === 'active' && (
                              <ActionBtn onClick={() => openRetire(q)} disabled={busy} tone="neutral" icon={<Archive className="size-3" />} label="退役" />
                            )}
                          </div>
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </section>

        {/* 右栏：新建 + 匹配测试 */}
        <aside className="order-first space-y-4 xl:order-none">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-start gap-2.5">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 ring-1 ring-amber-500/15">
                <FilePlus2 className="size-4 text-amber-600" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-800">新建草稿</p>
                <p className="text-[11px] leading-relaxed text-slate-400">新问题一律为草稿，须提交审核并生效后才参与匹配</p>
              </div>
            </div>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <label htmlFor="tq-op" className="text-xs font-medium text-slate-600">操作人 ID（必填）</label>
                <Input
                  id="tq-op"
                  placeholder="开发期声明式身份"
                  value={operator}
                  onChange={(e) => setOperator(e.target.value)}
                  className="h-9 rounded-xl bg-white/80 focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="tq-new-q" className="text-xs font-medium text-slate-600">标准问题</label>
                <Input
                  id="tq-new-q"
                  placeholder="门诊报销比例是多少？"
                  value={newQuestion}
                  onChange={(e) => setNewQuestion(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') onCreate() }}
                  className="h-9 rounded-xl bg-white/80 focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="tq-new-syn" className="text-xs font-medium text-slate-600">同义表达</label>
                <Input
                  id="tq-new-syn"
                  placeholder="逗号分隔，可选"
                  value={newSynonyms}
                  onChange={(e) => setNewSynonyms(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') onCreate() }}
                  className="h-9 rounded-xl bg-white/80 focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
                />
              </div>
              <button onClick={onCreate} disabled={!newQuestion.trim()} className={`${CTA_CLS} w-full`}>
                <Plus className="size-3.5" />新建草稿
              </button>
            </div>
          </section>

          <MatchTester />
        </aside>
      </div>

      {/* 编辑标准问题 */}
      <Dialog open={editTarget !== null} onOpenChange={(o) => { if (!o) setEditTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑标准问题</DialogTitle>
            <DialogDescription>保存后沿用当前状态；需提交审核并生效后才参与匹配。</DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') confirmEdit() }}
            placeholder="标准问题"
            className="focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTarget(null)}>取消</Button>
            <Button className="bg-amber-600 text-white shadow-xs hover:bg-amber-700" onClick={confirmEdit} disabled={!editText.trim()}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 驳回 */}
      <Dialog open={rejectTarget !== null} onOpenChange={(o) => { if (!o) setRejectTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>驳回「{rejectTarget?.standard_question}」</DialogTitle>
            <DialogDescription>驳回原因将随审核记录保留，供创建人参考修改。</DialogDescription>
          </DialogHeader>
          <Textarea
            autoFocus
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
            placeholder="驳回原因（必填）"
            className="focus-visible:border-amber-300 focus-visible:ring-amber-200/40"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={confirmReject} disabled={!rejectNote.trim()}>
              <XCircle className="size-4" />驳回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 退役确认 */}
      <Dialog open={retireTarget !== null} onOpenChange={(o) => { if (!o) setRetireTarget(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认退役</DialogTitle>
            <DialogDescription>确认退役「{retireTarget?.standard_question}」？退役后不再参与匹配。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRetireTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={confirmRetire}>
              <Archive className="size-4" />确认退役
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}