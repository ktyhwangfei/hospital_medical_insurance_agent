'use client'

// 可信问题库 /question-library 页 — issue #37：审核流 + 同义表达运营（越问越准）
// + 试问（命中/澄清）+ 冷启动候选。生产运行优先匹配可信问题，不确定必须澄清。
import { useCallback, useEffect, useState } from 'react'
import { BookMarked, Loader2, MessageCircleQuestion, Play, Search, Sparkles } from 'lucide-react'
import {
  addTrustedQuestionSynonym,
  archiveTrustedQuestion,
  createTrustedQuestionDraft,
  executeQuestion,
  getQuestionLibraryStats,
  listColdStartCandidates,
  listQuestionMatchEvents,
  listTrustedQuestions,
  matchQuestion,
  reviewTrustedQuestion,
  type ColdStartCandidateDto,
  type QuestionLibraryStatsDto,
  type QuestionMatchEventDto,
  type QuestionMatchOutcomeDto,
  type TrustedQuestionDto,
  type TrustedQuestionStatusDto,
} from '@/lib/question-library-api'
import { ApiClientError } from '@/lib/types'

const selectCls =
  'rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-400 focus:outline-none'
const inputCls =
  'w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none'
const btnCls =
  'inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50'
const btnGhostCls =
  'inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 hover:border-slate-400 disabled:opacity-50'

const STATUS_LABELS: Record<TrustedQuestionStatusDto, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

const STATUS_BADGES: Record<TrustedQuestionStatusDto, string> = {
  draft: 'border-amber-200 bg-amber-50 text-amber-700',
  published: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  archived: 'border-slate-200 bg-slate-100 text-slate-500',
}

type Tab = 'library' | 'try' | 'loop' | 'coldstart'

export default function QuestionLibraryPage() {
  const [tab, setTab] = useState<Tab>('library')
  const [stats, setStats] = useState<QuestionLibraryStatsDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const refreshStats = useCallback(() => {
    getQuestionLibraryStats()
      .then(setStats)
      .catch(() => setStats(null))
  }, [])
  useEffect(() => { refreshStats() }, [refreshStats])

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <header className="flex items-start gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-slate-900 text-white">
          <BookMarked className="size-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-900">可信问题库</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            生产运行优先匹配可信问题（归一化一致才命中，结果 100% 正确）；不确定时降级候选澄清，不猜测执行。
          </p>
        </div>
      </header>

      {stats && (
        <div data-testid="qlib-overview-chips" className="mt-4 flex flex-wrap gap-2 text-xs">
          <Chip label="草稿" value={stats.question_counts.draft ?? 0} />
          <Chip label="已发布" value={stats.question_counts.published ?? 0} />
          <Chip label="已归档" value={stats.question_counts.archived ?? 0} />
          <Chip label="命中" value={stats.match_event_counts.hit ?? 0} />
          <Chip label="澄清" value={stats.match_event_counts.clarify ?? 0} />
        </div>
      )}

      <nav data-testid="qlib-tabs" className="mt-4 flex gap-1 border-b border-slate-200">
        {([
          ['library', '问题库'],
          ['try', '试问'],
          ['loop', '越问越准'],
          ['coldstart', '冷启动'],
        ] as [Tab, string][]).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => { setTab(key); setNote(null); setError(null) }}
            className={`px-3 py-2 text-sm ${tab === key ? 'border-b-2 border-slate-900 font-medium text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
          >
            {label}
          </button>
        ))}
      </nav>

      {error && (
        <div data-testid="qlib-error" className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}
      {note && (
        <div data-testid="qlib-note" className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {note}
        </div>
      )}

      <div className="mt-4">
        {tab === 'library' && (
          <LibraryTab
            onError={setError}
            onNote={setNote}
            refreshStats={refreshStats}
          />
        )}
        {tab === 'try' && <TryTab onError={setError} onNote={setNote} refreshStats={refreshStats} />}
        {tab === 'loop' && <LoopTab onError={setError} onNote={setNote} refreshStats={refreshStats} />}
        {tab === 'coldstart' && <ColdStartTab onError={setError} onNote={setNote} />}
      </div>
    </main>
  )
}

function Chip({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-600">
      {label} <span className="font-semibold text-slate-900">{value}</span>
    </span>
  )
}

// ── 问题库：列表 + 详情展开 + 审核操作 + 新建草稿 ──

function LibraryTab({
  onError,
  onNote,
  refreshStats,
}: {
  onError: (msg: string | null) => void
  onNote: (msg: string | null) => void
  refreshStats: () => void
}) {
  const [status, setStatus] = useState<TrustedQuestionStatusDto | ''>('')
  const [q, setQ] = useState('')
  const [items, setItems] = useState<TrustedQuestionDto[]>([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [prefill, setPrefill] = useState<string>('')

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const page = await listTrustedQuestions({
        status: status || undefined,
        q: q.trim() || undefined,
        page_size: 50,
      })
      setItems(page.items)
      onError(null)
    } catch (e) {
      onError(e instanceof ApiClientError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status, q, onError])

  useEffect(() => {
    const timer = setTimeout(() => { load() }, 250)
    return () => clearTimeout(timer)
  }, [load])

  const act = async (fn: () => Promise<unknown>, successNote: string) => {
    try {
      await fn()
      onNote(successNote)
      await load()
      refreshStats()
    } catch (e) {
      onError(e instanceof ApiClientError ? e.message : String(e))
    }
  }

  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute top-2.5 left-2 size-4 text-slate-400" />
          <input
            data-testid="qlib-search-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索标准问题或同义表达"
            className={`${inputCls} pl-8`}
          />
        </div>
        <select
          aria-label="按状态过滤"
          data-testid="qlib-status-filter"
          value={status}
          onChange={(e) => setStatus(e.target.value as TrustedQuestionStatusDto | '')}
          className={selectCls}
        >
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="published">已发布</option>
          <option value="archived">已归档</option>
        </select>
        <button
          type="button"
          data-testid="qlib-create-button"
          className={btnCls}
          onClick={() => { setPrefill(''); setShowCreate(true) }}
        >
          新建草稿
        </button>
      </div>

      {loading && <div className="mt-6 flex justify-center"><Loader2 className="size-5 animate-spin text-slate-400" /></div>}

      {!loading && items.length === 0 && (
        <div data-testid="qlib-empty" className="mt-6 rounded-md border border-dashed border-slate-200 px-6 py-10 text-center text-sm text-slate-500">
          暂无可信问题——从「冷启动」候选或「新建草稿」开始
        </div>
      )}

      <ul className="mt-4 space-y-2" data-testid="qlib-list">
        {items.map((item) => (
          <li key={item.question_id} className="rounded-lg border border-slate-200 bg-white">
            <button
              type="button"
              data-testid="qlib-row"
              onClick={() => setExpanded(expanded === item.question_id ? null : item.question_id)}
              className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
            >
              <div>
                <div className="text-sm font-medium text-slate-900">{item.standard_question}</div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
                  <span>{item.object_code}</span>
                  <span>指标 {item.metrics.length}</span>
                  {item.synonyms.length > 0 && <span>同义 {item.synonyms.length}</span>}
                  <span>v{item.version}</span>
                  {item.reviewer && <span>审核 {item.reviewer}</span>}
                </div>
              </div>
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${STATUS_BADGES[item.status]}`}>
                {STATUS_LABELS[item.status]}
              </span>
            </button>
            {expanded === item.question_id && (
              <div data-testid="qlib-detail" className="border-t border-slate-100 px-4 py-3">
                <DetailBlock question={item} />
                <div className="mt-3 flex flex-wrap gap-2">
                  {item.status === 'draft' && (
                    <>
                      <button
                        type="button"
                        data-testid="qlib-approve-button"
                        className={btnCls}
                        onClick={() =>
                          act(
                            () => reviewTrustedQuestion(item.question_id, { approve: true, reviewer: 'portal-reviewer', expected_revision: item.revision }),
                            `已发布：${item.standard_question}`,
                          )
                        }
                      >
                        审核通过并发布
                      </button>
                      <button
                        type="button"
                        className={btnGhostCls}
                        onClick={() =>
                          act(
                            () => reviewTrustedQuestion(item.question_id, { approve: false, reviewer: 'portal-reviewer', expected_revision: item.revision }),
                            '已驳回并归档',
                          )
                        }
                      >
                        驳回
                      </button>
                    </>
                  )}
                  {item.status !== 'archived' && (
                    <button
                      type="button"
                      className={btnGhostCls}
                      onClick={() =>
                        act(
                          () => archiveTrustedQuestion(item.question_id, item.revision),
                          '已归档',
                        )
                      }
                    >
                      归档
                    </button>
                  )}
                  <AddSynonymInline
                    question={item}
                    onDone={(msg) => act(async () => {}, msg)}
                    onError={onError}
                    reload={load}
                    refreshStats={refreshStats}
                  />
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      {showCreate && (
        <CreateDraftDialog
          prefill={prefill}
          onClose={() => setShowCreate(false)}
          onCreated={async (msg) => {
            setShowCreate(false)
            onNote(msg)
            await load()
            refreshStats()
          }}
          onError={onError}
        />
      )}
    </section>
  )
}

function DetailBlock({ question }: { question: TrustedQuestionDto }) {
  return (
    <div className="space-y-2 text-xs text-slate-600">
      {question.synonyms.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {question.synonyms.map((synonym) => (
            <span key={synonym} className="rounded border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-sky-700">
              {synonym}
            </span>
          ))}
        </div>
      )}
      {question.roles.length > 0 && <p>适用角色：{question.roles.join('、')}</p>}
      {question.time_scope && <p>时间口径：{question.time_scope}</p>}
      <p className="break-all text-slate-400">
        查询计划 {String(question.query_plan.object_code ?? '')} / {Array.isArray(question.query_plan.metrics) ? (question.query_plan.metrics as string[]).join(', ') : ''}
      </p>
    </div>
  )
}

function AddSynonymInline({
  question,
  onDone,
  onError,
  reload,
}: {
  question: TrustedQuestionDto
  onDone: (msg: string) => void
  onError: (msg: string | null) => void
  reload: () => Promise<void>
  refreshStats: () => void
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="flex items-center gap-1.5">
      <input
        data-testid={`qlib-synonym-input-${question.question_id}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="新增同义表达"
        className="rounded-md border border-slate-200 px-2 py-1 text-xs"
      />
      <button
        type="button"
        disabled={!value.trim() || busy}
        className={btnGhostCls}
        onClick={async () => {
          try {
            setBusy(true)
            await addTrustedQuestionSynonym(question.question_id, { synonym: value.trim(), expected_revision: question.revision })
            setValue('')
            await reload()
            onDone(`已添加同义表达：${value.trim()}`)
          } catch (e) {
            onError(e instanceof ApiClientError ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        添加同义
      </button>
    </div>
  )
}

// ── 新建草稿对话框 ──

const DEFAULT_PLAN = JSON.stringify(
  {
    object_code: 'mzjyxx',
    scope: { query_scope: 'whole_settlement' },
    metrics: ['fund_pay_total'],
    group_by: [],
    filters: [],
    order_by: [],
    limit: 100,
  },
  null,
  2,
)

function CreateDraftDialog({
  prefill,
  onClose,
  onCreated,
  onError,
}: {
  prefill: string
  onClose: () => void
  onCreated: (msg: string) => void
  onError: (msg: string | null) => void
}) {
  const [standard, setStandard] = useState(prefill)
  const [synonyms, setSynonyms] = useState('')
  const [roles, setRoles] = useState('')
  const [planText, setPlanText] = useState(DEFAULT_PLAN)
  const [busy, setBusy] = useState(false)

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4">
      <div data-testid="qlib-create-dialog" className="w-full max-w-xl rounded-lg bg-white p-5 shadow-xl">
        <h2 className="text-sm font-semibold text-slate-900">新建可信问题草稿</h2>
        <div className="mt-3 space-y-3">
          <label className="block text-xs text-slate-600">
            标准问题
            <input data-testid="qlib-create-standard" value={standard} onChange={(e) => setStandard(e.target.value)} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-600">
            同义表达（每行一条）
            <textarea value={synonyms} onChange={(e) => setSynonyms(e.target.value)} rows={2} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-600">
            适用角色（逗号分隔，留空=全角色）
            <input value={roles} onChange={(e) => setRoles(e.target.value)} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-600">
            绑定查询计划（SemanticQuery JSON）
            <textarea
              data-testid="qlib-create-plan"
              value={planText}
              onChange={(e) => setPlanText(e.target.value)}
              rows={8}
              className={`${inputCls} mt-1 font-mono text-xs`}
            />
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className={btnGhostCls} onClick={onClose}>取消</button>
          <button
            type="button"
            data-testid="qlib-create-submit"
            disabled={!standard.trim() || busy}
            className={btnCls}
            onClick={async () => {
              let plan: Record<string, unknown>
              try {
                plan = JSON.parse(planText)
              } catch {
                onError('查询计划不是合法 JSON')
                return
              }
              try {
                setBusy(true)
                await createTrustedQuestionDraft({
                  standard_question: standard.trim(),
                  synonyms: synonyms.split('\n').map((s) => s.trim()).filter(Boolean),
                  roles: roles.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
                  object_code: String(plan.object_code || ''),
                  metrics: (plan.metrics as string[]) || [],
                  dimensions: (plan.group_by as string[]) || [],
                  time_scope: null,
                  filters: [],
                  query_plan: plan,
                  allow_drilldown: false,
                  expected_result: {},
                })
                onCreated(`草稿已创建：${standard.trim()}`)
              } catch (e) {
                onError(e instanceof ApiClientError ? e.message : String(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            创建草稿
          </button>
        </div>
      </div>
    </div>
  )
}

// ── 试问：命中执行 / 澄清候选 ──

function TryTab({
  onError,
  onNote,
  refreshStats,
}: {
  onError: (msg: string | null) => void
  onNote: (msg: string | null) => void
  refreshStats: () => void
}) {
  const [question, setQuestion] = useState('')
  const [outcome, setOutcome] = useState<QuestionMatchOutcomeDto | null>(null)
  const [rows, setRows] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    if (!question.trim()) return
    try {
      setBusy(true)
      setRows(null)
      const data = await matchQuestion(question.trim())
      setOutcome(data)
      onError(null)
      refreshStats()
    } catch (e) {
      onError(e instanceof ApiClientError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const runExecute = async (questionId: string) => {
    try {
      setBusy(true)
      const result = await executeQuestion(questionId)
      setRows(result)
      onNote(null)
      onError(null)
    } catch (e) {
      onError(e instanceof ApiClientError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="flex gap-2">
        <input
          data-testid="qlib-try-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') run() }}
          placeholder="输入问法试试：例如「本年度医保基金支付总额是多少」"
          className={inputCls}
        />
        <button type="button" data-testid="qlib-try-button" disabled={busy || !question.trim()} className={btnCls} onClick={run}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <MessageCircleQuestion className="size-3.5" />}
          试问
        </button>
      </div>

      {outcome && outcome.kind === 'hit' && outcome.question && (
        <div data-testid="qlib-try-hit" className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3">
          <p className="text-xs text-emerald-700">
            命中可信问题（匹配表达：{outcome.matched_text}）
          </p>
          <p className="mt-1 text-sm font-medium text-slate-900">{outcome.question.standard_question}</p>
          <button type="button" data-testid="qlib-try-execute" className={`${btnCls} mt-2`} disabled={busy} onClick={() => runExecute(outcome.question!.question_id)}>
            <Play className="size-3.5" />
            执行查询计划
          </button>
        </div>
      )}

      {outcome && outcome.kind === 'clarify' && (
        <div data-testid="qlib-try-clarify" className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-xs text-amber-700">未唯一命中——不确定时必须澄清，请从候选中选择（不猜测执行）：</p>
          <ul className="mt-2 space-y-1.5">
            {outcome.candidates.map((candidate) => (
              <li key={candidate.question_id} className="flex items-center justify-between gap-2 rounded border border-amber-100 bg-white px-3 py-2">
                <div>
                  <p className="text-sm text-slate-900">{candidate.standard_question}</p>
                  <p className="text-xs text-slate-400">相似度 {(candidate.score * 100).toFixed(0)}% · 匹配表达 {candidate.matched_text}</p>
                </div>
                <button type="button" className={btnGhostCls} disabled={busy} onClick={() => runExecute(candidate.question_id)}>
                  选择并执行
                </button>
              </li>
            ))}
            {outcome.candidates.length === 0 && (
              <li className="text-xs text-slate-500">没有相近候选——可在「冷启动」沉淀为新的可信问题。</li>
            )}
          </ul>
        </div>
      )}

      {rows && (
        <div data-testid="qlib-try-result" className="mt-4 rounded-md border border-slate-200 bg-white px-4 py-3">
          <p className="text-xs font-medium text-slate-600">查询结果（质量 {String(rows.quality_status ?? '—')}）</p>
          <pre className="mt-2 max-h-64 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-700">
            {JSON.stringify(rows.rows ?? rows, null, 2)}
          </pre>
        </div>
      )}
    </section>
  )
}

// ── 越问越准：澄清事件 → 一键采纳为同义表达 ──

function LoopTab({
  onError,
  onNote,
  refreshStats,
}: {
  onError: (msg: string | null) => void
  onNote: (msg: string | null) => void
  refreshStats: () => void
}) {
  const [events, setEvents] = useState<QuestionMatchEventDto[]>([])
  const [published, setPublished] = useState<TrustedQuestionDto[]>([])
  const [target, setTarget] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const [eventPage, questionPage] = await Promise.all([
        listQuestionMatchEvents({ outcome: 'clarify', page_size: 50 }),
        listTrustedQuestions({ status: 'published', page_size: 100 }),
      ])
      setEvents(eventPage.items)
      setPublished(questionPage.items)
      onError(null)
    } catch (e) {
      onError(e instanceof ApiClientError ? e.message : String(e))
    }
  }, [onError])

  useEffect(() => { load() }, [load])

  return (
    <section>
      <p className="text-xs text-slate-500">用户真实问法（未命中留痕）→ 采纳为某条已发布问题的同义表达，下次同样问法即可命中。</p>
      {events.length === 0 ? (
        <div data-testid="qlib-loop-empty" className="mt-4 rounded-md border border-dashed border-slate-200 px-6 py-8 text-center text-sm text-slate-500">
          暂无澄清事件
        </div>
      ) : (
        <ul data-testid="qlib-loop-list" className="mt-4 space-y-2">
          {events.map((event) => (
            <li key={event.event_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3">
              <div>
                <p className="text-sm text-slate-900">{event.asked_text}</p>
                <p className="text-xs text-slate-400">{new Date(event.created_at).toLocaleString('zh-CN')}</p>
              </div>
              <div className="flex items-center gap-1.5">
                <select
                  aria-label={`采纳目标 ${event.event_id}`}
                  data-testid={`qlib-loop-target-${event.event_id}`}
                  value={target[event.event_id] ?? ''}
                  onChange={(e) => setTarget((prev) => ({ ...prev, [event.event_id]: e.target.value }))}
                  className={selectCls}
                >
                  <option value="">选择目标问题…</option>
                  {published.map((question) => (
                    <option key={question.question_id} value={question.question_id}>
                      {question.standard_question}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  data-testid={`qlib-loop-adopt-${event.event_id}`}
                  disabled={!target[event.event_id]}
                  className={btnCls}
                  onClick={async () => {
                    const questionId = target[event.event_id]
                    const question = published.find((item) => item.question_id === questionId)
                    if (!question) return
                    try {
                      await addTrustedQuestionSynonym(questionId, {
                        synonym: event.asked_text,
                        expected_revision: question.revision,
                      })
                      onNote(`已采纳为同义表达：${event.asked_text}`)
                      await load()
                      refreshStats()
                    } catch (e) {
                      onError(e instanceof ApiClientError ? e.message : String(e))
                    }
                  }}
                >
                  <Sparkles className="size-3.5" />
                  采纳为同义
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ── 冷启动：问答历史高频候选 ──

function ColdStartTab({
  onError,
  onNote,
}: {
  onError: (msg: string | null) => void
  onNote: (msg: string | null) => void
}) {
  const [candidates, setCandidates] = useState<ColdStartCandidateDto[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listColdStartCandidates(100)
      .then((items) => setCandidates(items))
      .catch((e) => onError(e instanceof ApiClientError ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [onError])

  const [creating, setCreating] = useState<string | null>(null)
  const [planText, setPlanText] = useState(DEFAULT_PLAN)
  const [busy, setBusy] = useState(false)

  return (
    <section>
      <p className="text-xs text-slate-500">政策问答历史高频问法（未被现有可信问题覆盖），按频次排序；一期建设 50~100 条。</p>
      {loading && <div className="mt-6 flex justify-center"><Loader2 className="size-5 animate-spin text-slate-400" /></div>}
      {!loading && candidates.length === 0 && (
        <div data-testid="qlib-cold-empty" className="mt-4 rounded-md border border-dashed border-slate-200 px-6 py-8 text-center text-sm text-slate-500">
          暂无候选——历史问法都已被现有可信问题覆盖，或问答历史为空
        </div>
      )}
      {candidates.length > 0 && (
        <table data-testid="qlib-cold-table" className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="py-2">历史问法</th>
              <th className="w-20 py-2">频次</th>
              <th className="w-28 py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.question_text} className="border-b border-slate-100">
                <td className="py-2 text-slate-900">{candidate.question_text}</td>
                <td className="py-2 text-slate-600">{candidate.frequency}</td>
                <td className="py-2">
                  <button type="button" className={btnGhostCls} onClick={() => { setCreating(candidate.question_text); setPlanText(DEFAULT_PLAN) }}>
                    创建草稿
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {creating && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4">
          <div data-testid="qlib-cold-create-dialog" className="w-full max-w-xl rounded-lg bg-white p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-slate-900">沉淀为可信问题草稿</h2>
            <p className="mt-1 text-xs text-slate-500">历史问法：{creating}</p>
            <label className="mt-3 block text-xs text-slate-600">
              绑定查询计划（SemanticQuery JSON）
              <textarea
                data-testid="qlib-cold-plan"
                value={planText}
                onChange={(e) => setPlanText(e.target.value)}
                rows={8}
                className={`${inputCls} mt-1 font-mono text-xs`}
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className={btnGhostCls} onClick={() => setCreating(null)}>取消</button>
              <button
                type="button"
                data-testid="qlib-cold-submit"
                disabled={busy}
                className={btnCls}
                onClick={async () => {
                  let plan: Record<string, unknown>
                  try {
                    plan = JSON.parse(planText)
                  } catch {
                    onError('查询计划不是合法 JSON')
                    return
                  }
                  try {
                    setBusy(true)
                    await createTrustedQuestionDraft({
                      standard_question: creating,
                      synonyms: [],
                      roles: [],
                      object_code: String(plan.object_code || ''),
                      metrics: (plan.metrics as string[]) || [],
                      dimensions: (plan.group_by as string[]) || [],
                      time_scope: null,
                      filters: [],
                      query_plan: plan,
                      allow_drilldown: false,
                      expected_result: {},
                    })
                    setCreating(null)
                    onNote('草稿已创建——请到「问题库」完成审核发布')
                  } catch (e) {
                    onError(e instanceof ApiClientError ? e.message : String(e))
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                创建草稿
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
