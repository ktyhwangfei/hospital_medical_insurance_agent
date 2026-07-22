'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  History, Clock, User, Loader2, AlertCircle, RefreshCw,
  Search, X, ChevronLeft, ChevronRight, Brain, Database, Wrench,
  Layers, ArrowRight, Circle, Copy, Check,
} from 'lucide-react'
import { fetchQAHistory } from '@/lib/api-client'
import type { QASession, QATask } from '@/lib/types'

// ── 工具 ────────────────────────────────────────────────────

function fmtTime(iso: string): string {
  try { const d = new Date(iso); return `${d.getMonth()+1}/${d.getDate()} ${d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}` } catch { return iso }
}
function fmtDur(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms/1000).toFixed(1)}s`
}
function fmtJson(obj: Record<string, unknown> | null | undefined): string {
  if (!obj || Object.keys(obj).length === 0) return '—'
  return JSON.stringify(obj, null, 0)
}

// ── 扁平化 ──────────────────────────────────────────────────

interface FlatTask {
  task_id: string; task_type: string; status: string; description: string
  executor_type: string; step_id: string; duration_ms: number | null
  error_message: string; created_at: string
  input_data: Record<string, unknown>; output_data: Record<string, unknown>
  session_user: string; session_role: string; session_time: string
  workflow_status: string; workflow_steps: number
}
interface FlatSession { session_id: string; user_id: string; role: string; created_at: string; last_active: string; wfCount: number; taskCount: number }

function build(sessions: QASession[]): { sessions: FlatSession[]; tasks: FlatTask[] } {
  const ss: FlatSession[] = []; const ts: FlatTask[] = []
  for (const s of sessions) { let tc = 0
    for (const w of s.workflows) { tc += w.tasks.length
      for (const t of w.tasks) ts.push({
        task_id: t.task_id, task_type: t.task_type, status: t.status,
        description: t.description || '', executor_type: t.executor_type || 'internal',
        step_id: t.step_id || '', duration_ms: t.duration_ms ?? null,
        error_message: t.error_message || '', created_at: t.created_at || '',
        input_data: t.input_data || {}, output_data: t.output_data || {},
        session_user: s.user_id, session_role: s.role,
        session_time: fmtTime(s.last_active || s.created_at),
        workflow_status: w.status, workflow_steps: w.steps.length,
      })}
    ss.push({ session_id: s.session_id, user_id: s.user_id, role: s.role, created_at: s.created_at, last_active: s.last_active, wfCount: s.workflows.length, taskCount: tc })
  }
  return { sessions: ss, tasks: ts }
}

// ── Tab 定义 ────────────────────────────────────────────────

const TABS = [
  { key: 'sessions', label: 'Sessions', icon: Layers },
  { key: 'llm',      label: 'LLM',      icon: Brain },
  { key: 'mcp',      label: 'MCP',      icon: Database },
  { key: 'skill',    label: 'Skill',    icon: Wrench },
] as const
type TabKey = typeof TABS[number]['key']
const PG = { sessions: 15, llm: 15, mcp: 15, skill: 15 }

// ── 组件 ────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const m: Record<string,string> = { completed:'bg-emerald-50 text-emerald-700', failed:'bg-red-50 text-red-700', error:'bg-red-50 text-red-700' }
  return <span className={`inline-flex items-center rounded-full px-2 py-px text-[10px] font-semibold ${m[status]??'bg-slate-50 text-slate-600'}`}>{status}</span>
}
function Pag({ page, total, onChange }: { page: number; total: number; onChange: (p:number)=>void }) {
  if (total <= 1) return null
  return <div className="flex items-center justify-center gap-3 pt-3">
    <button onClick={()=>onChange(Math.max(0,page-1))} disabled={page===0} className="inline-flex items-center gap-1 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-600 shadow-sm hover:border-neutral-300 disabled:opacity-30 disabled:cursor-not-allowed"><ChevronLeft className="size-3.5"/>上页</button>
    <span className="text-xs text-neutral-500 tabular-nums">{page+1}/{total}</span>
    <button onClick={()=>onChange(Math.min(total-1,page+1))} disabled={page>=total-1} className="inline-flex items-center gap-1 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-600 shadow-sm hover:border-neutral-300 disabled:opacity-30 disabled:cursor-not-allowed">下页<ChevronRight className="size-3.5"/></button>
  </div>
}
function KvBlock({ data, label }: { data: Record<string, unknown>; label: string }) {
  const entries = Object.entries(data).filter(([,v]) => v !== null && v !== undefined && v !== '')
  if (entries.length === 0) return <p className="text-[11px] text-neutral-400 italic">无{label}数据</p>
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-neutral-400">{label}</p>
      <div className="space-y-0.5 rounded-lg bg-neutral-50/80 p-2.5 ring-1 ring-neutral-100">
        {entries.map(([k, v]) => {
          const s = typeof v === 'object' ? JSON.stringify(v).slice(0, 200) : String(v).slice(0, 200)
          return (
            <div key={k} className="flex items-baseline gap-2 text-[11px]">
              <span className="shrink-0 rounded bg-neutral-200/60 px-1 py-px font-mono text-[10px] font-medium text-neutral-500">{k}</span>
              <span className="break-all text-neutral-600">{s}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ★ SQL 专用展示组件 — 完整的 SQL 文本 + JSON 结果 + 复制按钮
function CopyBtn({ text }: { text: string }) {
  const [ok, setOk] = useState(false)
  return (
    <button
      onClick={async () => { try { await navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 2000) } catch { /* noop */ } }}
      className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 transition-colors"
    >
      {ok ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
      {ok ? '已复制' : '复制'}
    </button>
  )
}

function formatValue(v: unknown): string {
  if (typeof v === 'object' && v !== null) {
    try { return JSON.stringify(v, null, 2) } catch { return String(v) }
  }
  return String(v)
}

function SqlCard({ task }: { task: FlatTask }) {
  const sql = (task.input_data as any)?.['SQL语句'] || (task.input_data as any)?.['sql_text'] || ''
  const params = (task.input_data as any)?.['SQL参数'] || (task.input_data as any)?.['sql_params'] || ''
  const resultSample = (task.output_data as any)?.['返回样例'] || (task.output_data as any)?.['result_sample'] || ''
  const fields = (task.output_data as any)?.['返回字段'] || (task.output_data as any)?.['result_fields'] || []
  const rows = (task.output_data as any)?.['返回行数'] || (task.output_data as any)?.['row_count'] || 0
  const dur = (task.output_data as any)?.['耗时ms'] || task.duration_ms || 0

  const sqlStr = typeof sql === 'object' ? JSON.stringify(sql) : String(sql)
  const paramsStr = typeof params === 'object' ? JSON.stringify(params, null, 2) : String(params)
  const resultStr = typeof resultSample === 'object' ? JSON.stringify(resultSample, null, 2) : String(resultSample)

  return (
    <div className="space-y-4">
      {/* SQL 查询语句 */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-neutral-400">SQL 查询语句</p>
          {sqlStr && <CopyBtn text={sqlStr} />}
        </div>
        <pre className="overflow-x-auto rounded-lg bg-neutral-900 p-3 text-[11px] leading-relaxed text-green-300 font-mono max-h-[400px] overflow-y-auto whitespace-pre-wrap break-all">
          {sqlStr || '—'}
        </pre>
      </div>

      {/* SQL 参数 */}
      {paramsStr && paramsStr !== '{}' && (
        <div>
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-neutral-400">SQL 参数</p>
          <pre className="overflow-x-auto rounded-lg bg-neutral-100 p-3 text-[11px] leading-relaxed text-neutral-700 font-mono max-h-[200px] overflow-y-auto">
            {paramsStr}
          </pre>
        </div>
      )}

      {/* 返回结果 */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-2">
            <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-neutral-400">返回结果</p>
            <span className="text-[10px] text-neutral-400 tabular-nums">行数: {rows} · 字段: {(fields as string[]).length} · {dur}ms</span>
          </div>
          {resultStr && <CopyBtn text={resultStr} />}
        </div>
        <pre className="overflow-x-auto rounded-lg bg-neutral-50 p-3 text-[11px] leading-relaxed text-neutral-700 font-mono max-h-[500px] overflow-y-auto ring-1 ring-neutral-200 whitespace-pre-wrap break-all">
          {resultStr || '—'}
        </pre>
      </div>
    </div>
  )
}

// ── 主页面 ──────────────────────────────────────────────────

export default function QAHistoryPage() {
  const [sessions, setSessions] = useState<QASession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('sessions')
  const [search, setSearch] = useState('')
  const [fu, setFu] = useState('')
  const [page, setPage] = useState(0)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { const r = await fetchQAHistory({ limit: 200 }); setSessions(r.items) }
    catch(e) { setError(e instanceof Error ? e.message : '加载失败') }
    finally { setLoading(false) }
  }, [])
  useEffect(()=>{load()},[load])
  useEffect(()=>{setPage(0)},[search,fu,tab])

  const data = useMemo(() => build(sessions), [sessions])
  const users = useMemo(() => [...new Set(data.sessions.map(s=>s.user_id))].sort(), [data.sessions])
  const hasFilters = !!(search||fu)

  const allTasks = useMemo(() => {
    let r = data.tasks; const q = search.toLowerCase().trim()
    if (q) r = r.filter(t => t.description?.toLowerCase().includes(q) || t.session_user.toLowerCase().includes(q))
    if (fu) r = r.filter(t => t.session_user === fu)
    return r
  }, [data.tasks, search, fu])

  const tabDefs: Record<TabKey, { items: any[]; total: number }> = {
    sessions: {
      items: (() => { let r = data.sessions; const q = search.toLowerCase().trim(); if (q) r = r.filter(s => s.user_id.toLowerCase().includes(q)||s.role.toLowerCase().includes(q)); if (fu) r = r.filter(s => s.user_id===fu); return r })(),
      total: 0, // computed below
    },
    llm:   { items: allTasks.filter(t => t.executor_type==='llm'||t.executor_type==='llm_call'), total: 0 },
    mcp:   { items: allTasks.filter(t => t.executor_type==='mcp'||t.executor_type==='mcp_call'||t.executor_type==='sql'||t.executor_type==='sql_query'), total: 0 },
    skill: { items: allTasks.filter(t => t.executor_type==='skill'||t.executor_type==='skill_execution'), total: 0 },
  }
  tabDefs.sessions.total = tabDefs.sessions.items.length
  tabDefs.llm.total = tabDefs.llm.items.length
  tabDefs.mcp.total = tabDefs.mcp.items.length
  tabDefs.skill.total = tabDefs.skill.items.length

  const cur = tabDefs[tab]
  const ps = PG[tab]
  const tpages = Math.max(1, Math.ceil(cur.total / ps))
  const paged = cur.items.slice(page * ps, (page + 1) * ps)

  const selStyle = { backgroundImage:"url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='none' stroke='%23999' stroke-width='2'%3E%3Cpath d='m2 4 4 4 4-4'/%3E%3C/svg%3E\")",backgroundRepeat:'no-repeat',backgroundPosition:'right 10px center' }

  return (
    <div className="relative mx-auto flex w-full max-w-[1400px] flex-col gap-5 px-6 py-8">
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute inset-0 bg-[linear-gradient(180deg,#fefbf6_0%,#f8f5ee_30%,#f3efe6_100%)]" />
      </div>

      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-neutral-900">问答档案</h2>
          <p className="mt-1 text-sm text-neutral-500">Sessions {data.sessions.length} · LLM {tabDefs.llm.total} · MCP {tabDefs.mcp.total} · Skill {tabDefs.skill.total}</p>
        </div>
        <button onClick={load} disabled={loading} className="group inline-flex items-center gap-2 rounded-xl border border-neutral-200 bg-white/80 px-4 py-2 text-sm font-medium text-neutral-600 shadow-sm backdrop-blur hover:border-neutral-300 hover:bg-white hover:shadow-md disabled:opacity-50">
          <RefreshCw className={`size-3.5 transition-transform duration-700 group-hover:rotate-180 ${loading?'animate-spin':''}`} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 rounded-2xl bg-white/80 p-1 shadow-sm ring-1 ring-neutral-200/70 backdrop-blur w-fit">
        {TABS.map(t => { const Icon = t.icon; const sel = tab === t.key
          return <button key={t.key} onClick={()=>setTab(t.key)} className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all ${sel?'bg-amber-100 text-amber-800 shadow-sm':'text-neutral-500 hover:text-neutral-700 hover:bg-neutral-50'}`}>
            <Icon className="size-4"/>{t.label}<span className={`text-[11px] tabular-nums ${sel?'text-amber-600':'text-neutral-400'}`}>{tabDefs[t.key].total}</span>
          </button>
        })}
      </div>

      {/* 筛选 */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] max-w-[320px] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
          <input placeholder={tab==='sessions'?'搜索用户、角色':'搜索描述、用户'} value={search} onChange={e=>setSearch(e.target.value)} className="w-full rounded-xl border border-neutral-200 bg-white/80 py-2.5 pl-10 pr-10 text-sm text-neutral-800 placeholder:text-neutral-400 shadow-sm backdrop-blur outline-none focus:border-amber-300 focus:bg-white focus:shadow-md" />
          {search&&<button onClick={()=>setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-neutral-400 hover:text-neutral-600"><X className="size-3.5"/></button>}
        </div>
        <select value={fu} onChange={e=>setFu(e.target.value)} style={selStyle} className="cursor-pointer appearance-none rounded-xl border border-neutral-200 bg-white/80 py-2.5 pl-3.5 pr-8 text-sm text-neutral-700 shadow-sm backdrop-blur outline-none focus:border-amber-300"><option value="">全部用户</option>{users.map(u=><option key={u} value={u}>{u}</option>)}</select>
        {hasFilters&&<button onClick={()=>{setSearch('');setFu('')}} className="inline-flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-50"><X className="size-3"/>清除</button>}
      </div>

      {loading&&<div className="flex flex-col items-center gap-5 py-28"><div className="size-12 animate-spin rounded-full border-2 border-neutral-200 border-t-amber-500" /><p className="text-sm font-medium text-neutral-500">加载中...</p></div>}
      {!loading&&error&&<div className="flex flex-col items-center gap-4 rounded-2xl border border-red-100 bg-red-50/50 p-12"><AlertCircle className="size-8 text-red-400" /><p className="text-sm font-semibold text-red-700">加载失败</p><button onClick={load} className="rounded-xl border border-red-200 bg-white px-5 py-2 text-sm font-medium text-red-600 hover:bg-red-50">重试</button></div>}
      {!loading&&!error&&cur.total===0&&!hasFilters&&<div className="flex flex-col items-center gap-5 rounded-3xl border border-dashed border-neutral-200 bg-white/50 py-20"><History className="size-10 text-neutral-200" /><p className="text-sm font-semibold text-neutral-500">暂无数据</p></div>}
      {!loading&&!error&&cur.total===0&&hasFilters&&<div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-amber-200 bg-amber-50/40 py-16"><Search className="size-8 text-amber-300" /><p className="text-sm font-medium text-amber-700">无匹配</p></div>}

      {/* ── Sessions ── */}
      {!loading&&!error&&cur.total>0&&tab==='sessions'&&(
        <div className="flex flex-col gap-3">
          <div className="overflow-x-auto rounded-2xl border border-neutral-200 bg-white shadow-sm">
            <table className="w-full text-left text-xs"><thead><tr className="border-b border-neutral-200 bg-neutral-50/80">
              <th className="py-3 pl-4 pr-2 font-semibold text-neutral-500">Session ID</th><th className="py-3 px-2 font-semibold text-neutral-500">用户</th><th className="py-3 px-2 font-semibold text-neutral-500">角色</th><th className="py-3 px-2 font-semibold text-neutral-500">创建时间</th><th className="py-3 px-2 font-semibold text-neutral-500">最后活跃</th><th className="py-3 px-2 font-semibold text-neutral-500 text-right">WFs</th><th className="py-3 pr-4 pl-2 font-semibold text-neutral-500 text-right">Tasks</th>
            </tr></thead><tbody>{(paged as FlatSession[]).map(s=>
              <tr key={s.session_id} className="border-b border-neutral-100 last:border-0 hover:bg-amber-50/30">
                <td className="py-2.5 pl-4 pr-2 font-mono text-[10px] text-neutral-500 max-w-[180px] truncate" title={s.session_id}>{s.session_id}</td>
                <td className="py-2.5 px-2 font-medium text-neutral-800">{s.user_id}</td>
                <td className="py-2.5 px-2"><span className="rounded border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-[10px] text-neutral-500">{s.role}</span></td>
                <td className="py-2.5 px-2 text-neutral-500 font-mono text-[10px]">{fmtTime(s.created_at)}</td>
                <td className="py-2.5 px-2 text-neutral-500 font-mono text-[10px]">{fmtTime(s.last_active)}</td>
                <td className="py-2.5 px-2 text-right text-neutral-600 tabular-nums">{s.wfCount}</td>
                <td className="py-2.5 pr-4 pl-2 text-right text-neutral-600 tabular-nums">{s.taskCount}</td>
              </tr>)}</tbody>
            </table>
          </div>
          <Pag page={page} total={tpages} onChange={setPage} />
        </div>
      )}

      {/* ── LLM ── */}
      {!loading&&!error&&cur.total>0&&tab==='llm'&&(
        <div className="flex flex-col gap-3">
          {(paged as FlatTask[]).map((t,i) => (
            <div key={t.task_id||i} className="rounded-2xl border border-violet-100 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <span className="flex size-7 items-center justify-center rounded-lg bg-violet-50 ring-1 ring-violet-200"><Brain className="size-3.5 text-violet-600" /></span>
                  <div>
                    <span className="text-xs font-bold text-violet-700">LLM 调用</span>
                    <span className="ml-2 text-[11px] text-neutral-400">{t.description}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={t.status} />
                  <span className="text-[11px] text-neutral-400">{fmtDur(t.duration_ms)}</span>
                  <span className="text-[11px] text-neutral-400">{t.session_user} · {t.session_time}</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <KvBlock data={t.input_data} label="LLM 输入 (Prompt)" />
                <KvBlock data={t.output_data} label="LLM 输出 (Response)" />
              </div>
            </div>
          ))}
          <Pag page={page} total={tpages} onChange={setPage} />
        </div>
      )}

      {/* ── MCP ── */}
      {!loading&&!error&&cur.total>0&&tab==='mcp'&&(
        <div className="flex flex-col gap-3">
          {(paged as FlatTask[]).map((t,i) => {
            const isSql = t.executor_type === 'sql' || t.executor_type === 'sql_query' ||
                          t.task_type === 'infra_sql_query' || t.task_type === 'sql_query'
            return (
            <div key={t.task_id||i} className="rounded-2xl border border-amber-100 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <span className="flex size-7 items-center justify-center rounded-lg bg-amber-50 ring-1 ring-amber-200"><Database className="size-3.5 text-amber-600" /></span>
                  <div>
                    <span className="text-xs font-bold text-amber-700">MCP / SQL 查询</span>
                    <span className="ml-2 text-[11px] text-neutral-400">{t.description}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={t.status} />
                  <span className="text-[11px] text-neutral-400">{fmtDur(t.duration_ms)}</span>
                  <span className="text-[11px] text-neutral-400">{t.session_user} · {t.session_time}</span>
                </div>
              </div>
              {isSql ? (
                <SqlCard task={t} />
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <KvBlock data={t.input_data} label="MCP 查询语句 (Query)" />
                  <KvBlock data={t.output_data} label="MCP 返回结果 (Result)" />
                </div>
              )}
            </div>
          )})}
          <Pag page={page} total={tpages} onChange={setPage} />
        </div>
      )}

      {/* ── Skill ── */}
      {!loading&&!error&&cur.total>0&&tab==='skill'&&(
        <div className="flex flex-col gap-3">
          {(paged as FlatTask[]).map((t,i) => (
            <div key={t.task_id||i} className="rounded-2xl border border-blue-100 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <span className="flex size-7 items-center justify-center rounded-lg bg-blue-50 ring-1 ring-blue-200"><Wrench className="size-3.5 text-blue-600" /></span>
                  <div>
                    <span className="text-xs font-bold text-blue-700">Skill 执行</span>
                    <span className="ml-2 text-[11px] text-neutral-400">settlement_explain_skill</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={t.status} />
                  <span className="text-[11px] text-neutral-400">{fmtDur(t.duration_ms)}</span>
                  <span className="text-[11px] text-neutral-400">{t.session_user} · {t.session_time}</span>
                </div>
              </div>
              {t.description && <p className="mb-3 text-sm italic text-neutral-700">&ldquo;{t.description}&rdquo;</p>}
              <div className="grid grid-cols-2 gap-3">
                <KvBlock data={t.input_data} label="Skill 输入" />
                <KvBlock data={t.output_data} label="Skill 输出" />
              </div>
            </div>
          ))}
          <Pag page={page} total={tpages} onChange={setPage} />
        </div>
      )}
    </div>
  )
}
