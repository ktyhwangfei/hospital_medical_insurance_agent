'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ShieldCheck, Loader2, AlertCircle, RefreshCw, Search, X, Plus, Trash2,
  CheckCircle2, XCircle, Send, Archive, Sparkles, Pencil,
} from 'lucide-react'
import {
  addTrustedQuestionSynonym,
  approveTrustedQuestion,
  createTrustedQuestion,
  listTrustedQuestions,
  matchTrustedQuestion,
  rejectTrustedQuestion,
  removeTrustedQuestionSynonym,
  retireTrustedQuestion,
  submitTrustedQuestionReview,
  updateTrustedQuestion,
} from '@/lib/trusted-questions-api'
import type {
  TrustedQuestion,
  TrustedQuestionMatchResult,
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
  draft: { label: '草稿', cls: 'bg-slate-50 text-slate-600' },
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
  icon: React.ReactNode
  label: string
}) {
  const cls = {
    primary: 'border-emerald-200 text-emerald-700 hover:bg-emerald-50',
    danger: 'border-red-200 text-red-600 hover:bg-red-50',
    neutral: 'border-neutral-200 text-neutral-600 hover:bg-neutral-50',
  }[tone]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 rounded-lg border bg-white px-2.5 py-1 text-xs font-medium shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${cls}`}
    >
      {icon}{label}
    </button>
  )
}

// ── 匹配测试面板 ────────────────────────────────────────────

function MatchTester() {
  const [question, setQuestion] = useState('')
  const [role, setRole] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<TrustedQuestionMatchResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!question.trim()) return
    setRunning(true); setError(null); setResult(null)
    try {
      setResult(await matchTrustedQuestion({ question: question.trim(), role: role.trim() || undefined }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '匹配失败')
    } finally { setRunning(false) }
  }

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="size-4 text-violet-500" />
        <p className="text-sm font-semibold text-neutral-800">匹配测试</p>
        <span className="text-[11px] text-neutral-400">仅 active 可信问题参与；不确定时返回候选，不猜测执行</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          placeholder="输入用户问题，如：统筹自付为什么这么多？"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') run() }}
          className="min-w-[260px] flex-1 rounded-xl border border-neutral-200 bg-white/80 px-3.5 py-2 text-sm shadow-sm outline-none focus:border-violet-300"
        />
        <input
          placeholder="角色（可选）"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="w-32 rounded-xl border border-neutral-200 bg-white/80 px-3.5 py-2 text-sm shadow-sm outline-none focus:border-violet-300"
        />
        <button
          onClick={run}
          disabled={running || !question.trim()}
          className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-violet-700 disabled:opacity-40"
        >
          {running ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
          测试
        </button>
      </div>
      {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
      {result && (
        <div className="mt-3 rounded-xl bg-neutral-50/80 p-3 ring-1 ring-neutral-100">
          {result.outcome === 'matched' && result.question && (
            <p className="text-xs text-emerald-700">
              <span className="font-semibold">命中：</span>
              {result.question.standard_question}
              <span className="ml-2 font-mono text-[10px] text-neutral-400">{result.question.question_id}</span>
            </p>
          )}
          {result.outcome === 'candidates' && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-amber-700">不确定，需澄清（候选 {result.candidates.length}）：</p>
              {result.candidates.map((c) => (
                <p key={c.question_id} className="text-xs text-neutral-600">
                  {c.standard_question}
                  <span className="ml-2 text-[10px] text-neutral-400">
                    得分 {c.score.toFixed(2)} · 命中表达「{c.matched_expression}」
                  </span>
                </p>
              ))}
            </div>
          )}
          {result.outcome === 'no_match' && (
            <p className="text-xs text-neutral-500">无可信候选，交回长尾受控语义生成。</p>
          )}
        </div>
      )}
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
  const onReject = (q: TrustedQuestion) => {
    const op = requireOperator(); if (!op) return
    const note = window.prompt('驳回原因（必填）：')
    if (!note?.trim()) return
    return run(q, () =>
      rejectTrustedQuestion(q.question_id, {
        expected_version: q.version, operator: op, review_note: note.trim(),
      }))
  }
  const onRetire = (q: TrustedQuestion) => {
    const op = requireOperator(); if (!op) return
    if (!window.confirm(`确认退役「${q.standard_question}」？退役后不再参与匹配。`)) return
    return run(q, () =>
      retireTrustedQuestion(q.question_id, { expected_version: q.version, operator: op }))
  }
  const onEdit = (q: TrustedQuestion) => {
    const next = window.prompt('编辑标准问题：', q.standard_question)
    if (!next?.trim() || next.trim() === q.standard_question) return
    return run(q, () =>
      updateTrustedQuestion(q.question_id, {
        standard_question: next.trim(),
        synonyms: q.synonyms.map((s) => s.expression),
        expected_version: q.version,
      }))
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
    <div className="relative mx-auto flex w-full max-w-[1400px] flex-col gap-5 px-6 py-8">
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#fefbf6_0%,#f8f5ee_30%,#f3efe6_100%)]" />
      </div>

      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-neutral-900">可信问题库</h2>
          <p className="mt-1 text-sm text-neutral-500">
            已生效 {counts.active ?? 0} · 待审核 {counts.pending_review ?? 0} · 草稿 {counts.draft ?? 0} · 已退役 {counts.retired ?? 0}
          </p>
        </div>
        <button onClick={load} disabled={loading} className="group inline-flex items-center gap-2 rounded-xl border border-neutral-200 bg-white/80 px-4 py-2 text-sm font-medium text-neutral-600 shadow-sm backdrop-blur hover:border-neutral-300 hover:bg-white hover:shadow-md disabled:opacity-50">
          <RefreshCw className={`size-3.5 transition-transform duration-700 group-hover:rotate-180 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* 操作人 + 新建 */}
      <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <input
            placeholder="操作人 ID（必填）"
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            className="w-48 rounded-xl border border-neutral-200 bg-white/80 px-3.5 py-2 text-sm shadow-sm outline-none focus:border-amber-300"
          />
          <input
            placeholder="新建标准问题，如：门诊报销比例是多少？"
            value={newQuestion}
            onChange={(e) => setNewQuestion(e.target.value)}
            className="min-w-[240px] flex-1 rounded-xl border border-neutral-200 bg-white/80 px-3.5 py-2 text-sm shadow-sm outline-none focus:border-amber-300"
          />
          <input
            placeholder="同义表达（逗号分隔，可选）"
            value={newSynonyms}
            onChange={(e) => setNewSynonyms(e.target.value)}
            className="min-w-[200px] flex-1 rounded-xl border border-neutral-200 bg-white/80 px-3.5 py-2 text-sm shadow-sm outline-none focus:border-amber-300"
          />
          <button
            onClick={onCreate}
            disabled={!newQuestion.trim()}
            className="inline-flex items-center gap-1.5 rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:opacity-40"
          >
            <Plus className="size-3.5" />新建草稿
          </button>
        </div>
        <p className="mt-2 text-[11px] text-neutral-400">新建一律为草稿，须提交审核并生效后才参与匹配。</p>
      </div>

      {actionError && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50/60 px-4 py-2.5 text-xs text-red-700">
          <AlertCircle className="size-3.5" />{actionError}
        </div>
      )}

      <MatchTester />

      {/* Tabs + 搜索 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 rounded-2xl bg-white/80 p-1 shadow-sm ring-1 ring-neutral-200/70 backdrop-blur w-fit">
          {TABS.map((t) => {
            const sel = tab === t.key
            return (
              <button key={t.key} onClick={() => setTab(t.key)} className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all ${sel ? 'bg-amber-100 text-amber-800 shadow-sm' : 'text-neutral-500 hover:text-neutral-700 hover:bg-neutral-50'}`}>
                {t.label}
                <span className={`text-[11px] tabular-nums ${sel ? 'text-amber-600' : 'text-neutral-400'}`}>{counts[t.key] ?? 0}</span>
              </button>
            )
          })}
        </div>
        <div className="relative min-w-[220px] max-w-[320px] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
          <input
            placeholder="搜索标准问题 / 同义表达"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            className="w-full rounded-xl border border-neutral-200 bg-white/80 py-2.5 pl-10 pr-10 text-sm text-neutral-800 placeholder:text-neutral-400 shadow-sm backdrop-blur outline-none focus:border-amber-300 focus:bg-white focus:shadow-md"
          />
          {keyword && <button onClick={() => setKeyword('')} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-neutral-400 hover:text-neutral-600"><X className="size-3.5" /></button>}
        </div>
      </div>

      {/* 列表 */}
      {loading && <div className="flex flex-col items-center gap-5 py-28"><div className="size-12 animate-spin rounded-full border-2 border-neutral-200 border-t-amber-500" /><p className="text-sm font-medium text-neutral-500">加载中...</p></div>}
      {!loading && error && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-red-100 bg-red-50/50 p-12">
          <AlertCircle className="size-8 text-red-400" /><p className="text-sm font-semibold text-red-700">加载失败</p>
          <button onClick={load} className="rounded-xl border border-red-200 bg-white px-5 py-2 text-sm font-medium text-red-600 hover:bg-red-50">重试</button>
        </div>
      )}
      {!loading && !error && visible.length === 0 && (
        <div className="flex flex-col items-center gap-5 rounded-3xl border border-dashed border-neutral-200 bg-white/50 py-20">
          <ShieldCheck className="size-10 text-neutral-200" /><p className="text-sm font-semibold text-neutral-500">暂无可信问题</p>
        </div>
      )}

      {!loading && !error && visible.length > 0 && (
        <div className="flex flex-col gap-3">
          {visible.map((q) => {
            const busy = busyId === q.question_id
            return (
              <div key={q.question_id} className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={q.status} />
                      <span className="text-sm font-semibold text-neutral-900">{q.standard_question}</span>
                      <span className="font-mono text-[10px] text-neutral-400">{q.question_id} · v{q.version}</span>
                    </div>
                    {/* 同义表达 */}
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {q.synonyms.map((s) => (
                        <span key={s.expression} className="group inline-flex items-center gap-1 rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-0.5 text-[11px] text-neutral-600">
                          {s.expression}
                          <span className="text-[9px] text-neutral-400">{s.added_by}</span>
                          <button
                            onClick={() => onRemoveSynonym(q, s.expression)}
                            disabled={busy}
                            className="text-neutral-300 hover:text-red-500 disabled:opacity-40"
                            title="移除该同义表达"
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
                        className="w-28 rounded-full border border-dashed border-neutral-300 bg-transparent px-2.5 py-0.5 text-[11px] outline-none focus:border-amber-400"
                      />
                    </div>
                    <p className="mt-2 text-[11px] text-neutral-400">
                      创建 {q.created_by || '—'} · {fmtTime(q.created_at)}
                      {q.reviewed_by && <> · 审核 {q.reviewed_by} · {q.reviewed_at ? fmtTime(q.reviewed_at) : ''}</>}
                      {q.review_note && <> · 驳回原因：{q.review_note}</>}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                    {busy && <Loader2 className="size-4 animate-spin text-neutral-300" />}
                    {(q.status === 'draft' || q.status === 'pending_review') && (
                      <ActionBtn onClick={() => onEdit(q)} disabled={busy} tone="neutral" icon={<Pencil className="size-3" />} label="编辑" />
                    )}
                    {q.status === 'draft' && (
                      <ActionBtn onClick={() => onSubmitReview(q)} disabled={busy} tone="neutral" icon={<Send className="size-3" />} label="提交审核" />
                    )}
                    {q.status === 'pending_review' && (
                      <>
                        <ActionBtn onClick={() => onApprove(q)} disabled={busy} tone="primary" icon={<CheckCircle2 className="size-3" />} label="通过" />
                        <ActionBtn onClick={() => onReject(q)} disabled={busy} tone="danger" icon={<XCircle className="size-3" />} label="驳回" />
                      </>
                    )}
                    {q.status === 'active' && (
                      <ActionBtn onClick={() => onRetire(q)} disabled={busy} tone="neutral" icon={<Archive className="size-3" />} label="退役" />
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
