'use client'

// 数据探查页（数据治理中心一级模块）——自包含最简设计，围绕治理全流程：
// 探查回答三个问题：源库有什么表 → 表质量如何 → 要不要同步/建模。
// 三区结构：扫描控制条 → 表清单（选表同步）→ 展开字段画像（纳入建模）。
// 不嵌入语义层发现中心（重型运营能力归语义层），本页仅依赖三个只读/写接口：
// discovery results（按数据源隔离）、discovery scan（SSE）、sync-tables。
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import {
  CheckCircle2, ChevronDown, ChevronRight, Database, Loader2, PlusCircle, RefreshCw, ScanSearch,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { NextStepCard } from '@/components/next-step-card'
import {
  listDataSources, listSyncTables, runSyncTables, selectSyncTable, getTimeCandidates,
  type DataSource,
} from '@/lib/data-governance-api'

const API_BASE = '/api/v1/medical-insurance-ai-agent/semantic'

// ── 类型 ──────────────────────────────────────────────────────────

interface ProfiledField {
  field_name: string
  table_name: string
  data_type: string
  non_null_rate: number
  non_null_row_count: number
  is_primary_key: boolean
  mapped: boolean
  sample_value: string | null
  description: string | null
}

interface DiscoveryResults {
  tables_count?: number
  fields_count?: number
  fields?: ProfiledField[]
  table_labels?: Record<string, string>
}

interface HistoryItem {
  scan_id: string
  started_at: string
  status: string
  duration_seconds: number | null
}

interface TableGroup {
  table: string
  fields: ProfiledField[]
  mappedCount: number
  primaryKeys: string[]
  approxRows: number
}

// ── 数据访问 ──────────────────────────────────────────────────────

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`请求失败 (${res.status})`)
  return res.json() as Promise<T>
}

/** 简化 SSE 读取：只关心完成/失败，不逐表展示进度（最简可维护） */
async function waitScanDone(taskId: string, signal: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE}/discovery/scan/${encodeURIComponent(taskId)}/status`, { signal })
  if (!res.ok || !res.body) throw new Error('无法连接扫描状态流')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split(/\r?\n\r?\n/)
      buffer = chunks.pop() ?? ''
      for (const chunk of chunks) {
        const eventMatch = chunk.match(/^event:\s*(\w+)/m)
        if (eventMatch?.[1] === 'done') return
        if (eventMatch?.[1] === 'error') {
          const message = chunk.match(/"message"\s*:\s*"([^"]*)"/)?.[1]
          throw new Error(message || '扫描失败')
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ── 展示 helper ───────────────────────────────────────────────────

function nonNullTone(rate: number): string {
  if (rate >= 90) return 'text-emerald-700'
  if (rate >= 50) return 'text-amber-700'
  return 'text-red-700'
}

function formatTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—'
}

/** 相对时间（业务友好）：3 分钟前 / 2 小时前 / 昨天 */
function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return formatTime(iso)
}

/** 源字段名 → 模型字段编码候选（field_code 规则 ^[a-z][a-z0-9_]） */
function suggestFieldCode(name: string): string {
  const snake = name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase().replace(/[^a-z0-9_]/g, '_')
  return /^[a-z]/.test(snake) ? snake : `f_${snake}`
}

/** 按探查画像推荐字段角色：主键→标识，数值→事实，时间→时间，其余→维度 */
function suggestFieldRole(field: ProfiledField): string {
  if (field.is_primary_key) return 'identifier'
  const t = field.data_type.toLowerCase()
  if (['int', 'bigint', 'smallint', 'tinyint', 'numeric', 'decimal', 'money', 'float', 'real'].includes(t)) return 'fact'
  if (['datetime', 'datetime2', 'smalldatetime', 'date'].includes(t)) return 'datetime'
  return 'dimension'
}

// ── 页面 ──────────────────────────────────────────────────────────

export default function DataProfilingPage() {
  return (
    <Suspense fallback={<div className="py-16 text-center text-sm text-slate-400">加载数据探查…</div>}>
      <ProfilingContent />
    </Suspense>
  )
}

function ProfilingContent() {
  const preferredSource = useSearchParams().get('source') ?? ''

  const [sources, setSources] = useState<DataSource[]>([])
  const [sourceId, setSourceId] = useState('')
  const [results, setResults] = useState<DiscoveryResults | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [syncTables, setSyncTables] = useState<Map<string, number | null>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const [scanning, setScanning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'selected' | 'unmapped'>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [busyTable, setBusyTable] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 50
  // 选表配置弹窗（增量字段/模式/回看窗口）
  const [configuring, setConfiguring] = useState<string | null>(null)
  const [timeCandidates, setTimeCandidates] = useState<string[]>([])
  const [syncForm, setSyncForm] = useState({ time_column: '', sync_mode: 'full' as 'full' | 'incremental', lookback_minutes: 5 })

  const load = useCallback(async (datasourceId: string) => {
    const [r, h, tables] = await Promise.all([
      fetchJson<DiscoveryResults>(`${API_BASE}/discovery/results?datasource_id=${encodeURIComponent(datasourceId)}`),
      fetchJson<HistoryItem[]>(`${API_BASE}/discovery/history`).catch(() => [] as HistoryItem[]),
      listSyncTables(datasourceId).catch(() => []),
    ])
    setResults(r)
    setHistory(h)
    setSyncTables(new Map(tables.map((t) => [t.table_name, t.last_row_count])))
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const items = await listDataSources()
        if (cancelled) return
        const healthy = items.filter((s) => s.credentialConfigured && s.connectionStatus === 'healthy')
        setSources(healthy)
        const preferred = healthy.find((s) => s.sourceId === preferredSource) ?? healthy[0]
        if (!preferred) {
          setLoading(false)
          return
        }
        setSourceId(preferred.sourceId)
        await load(preferred.sourceId)
        if (!cancelled) setError(null)
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '探查结果加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [load, preferredSource])

  // ── 表聚合视图 ──
  const groups = useMemo<TableGroup[]>(() => {
    const map = new Map<string, ProfiledField[]>()
    for (const field of results?.fields ?? []) {
      const list = map.get(field.table_name) ?? []
      list.push(field)
      map.set(field.table_name, list)
    }
    return Array.from(map.entries()).map(([table, fields]) => ({
      table,
      fields,
      mappedCount: fields.filter((f) => f.mapped).length,
      primaryKeys: fields.filter((f) => f.is_primary_key).map((f) => f.field_name),
      approxRows: Math.max(0, ...fields.map((f) => f.non_null_row_count || 0)),
    })).sort((a, b) => a.table.localeCompare(b.table))
  }, [results])

  const visibleGroups = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    return groups.filter((group) => {
      if (filter === 'selected' && !syncTables.has(group.table)) return false
      if (filter === 'unmapped' && group.mappedCount === group.fields.length) return false
      if (keyword && !group.table.toLowerCase().includes(keyword)
        && !group.fields.some((f) => f.field_name.toLowerCase().includes(keyword))) return false
      return true
    })
  }, [groups, search, filter, syncTables])

  // 推荐表置顶：运营常用表（门诊/医保核心六表）+ 已选同步表优先，其余在后
  const RECOMMENDED_TABLES = ['o_Trade', 'o_FeeItem', 'o_Diagnose', 'yb_mzjyxx', 'yb_mzfymx', 'yb_brdjxx']
  const recommendedGroups = visibleGroups.filter(
    (g) => RECOMMENDED_TABLES.includes(g.table) || syncTables.has(g.table),
  )
  const restGroups = visibleGroups.filter(
    (g) => !RECOMMENDED_TABLES.includes(g.table) && !syncTables.has(g.table),
  )
  // 分页：每页 50 表
  const totalPages = Math.max(1, Math.ceil(visibleGroups.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pagedGroups = [...recommendedGroups, ...restGroups].slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  useEffect(() => { setPage(1) }, [search, filter])

  // ── 操作 ──
  const startScan = async () => {
    if (!sourceId) return
    setScanning(true)
    setMessage(null)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const res = await fetch(`${API_BASE}/discovery/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ datasource_id: sourceId, scope: '全部已接入表', sample_limit: 10000 }),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`扫描启动失败 (${res.status})`)
      const { task_id: taskId } = (await res.json()) as { task_id: string }
      await waitScanDone(taskId, controller.signal)
      await load(sourceId)
      setMessage('扫描完成，画像已更新')
    } catch (reason) {
      if (!controller.signal.aborted) {
        setMessage(reason instanceof Error ? reason.message : '扫描失败')
      }
    } finally {
      setScanning(false)
    }
  }

  const addToSync = (table: string) => {
    // 打开配置弹窗：加载候选时间字段（datetime/date 列），人工确认增量字段
    setConfiguring(table)
    setSyncForm({ time_column: '', sync_mode: 'full', lookback_minutes: 5 })
    void getTimeCandidates(sourceId, table)
      .then(setTimeCandidates)
      .catch(() => setTimeCandidates([]))
  }

  const confirmSelect = async () => {
    if (!configuring) return
    const table = configuring
    setBusyTable(table)
    setMessage(null)
    try {
      await selectSyncTable(sourceId, table, {
        time_column: syncForm.time_column || null,
        sync_mode: syncForm.time_column ? syncForm.sync_mode : 'full',
        lookback_minutes: syncForm.lookback_minutes,
      })
      setSyncTables((current) => new Map(current).set(table, null))
      setMessage(`已加入同步：${table}（${syncForm.time_column ? `增量，时间字段 ${syncForm.time_column}` : '全量，限频日同步'}）`)
      setConfiguring(null)
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : '加入同步失败')
    } finally {
      setBusyTable(null)
    }
  }

  const runSync = async (table: string) => {
    setBusyTable(`run:${table}`)
    setMessage(null)
    try {
      const runs = await runSyncTables(sourceId)
      const mine = runs.find((r) => r.table_name === table)
      if (mine) setSyncTables((current) => new Map(current).set(table, mine.row_count))
      setMessage(mine ? `同步完成：${table} → ${mine.target_table}，${mine.row_count} 行` : '同步完成')
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : '同步失败')
    } finally {
      setBusyTable(null)
    }
  }

  const toggle = (table: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(table)) next.delete(table)
      else next.add(table)
      return next
    })

  const lastScan = history[0]
  const totalFields = results?.fields?.length ?? 0
  const totalMapped = results?.fields?.filter((f) => f.mapped).length ?? 0

  return <div className="space-y-4" data-testid="data-profiling-page">
    {/* 选表配置弹窗：增量时间字段 + 模式 + 回看窗口 */}
    {configuring && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4" role="presentation">
        <section role="dialog" aria-modal="true" aria-label="选表同步配置" data-testid="select-sync-dialog"
          className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
          <h3 className="font-semibold text-slate-900">加入同步：{configuring}</h3>
          <div className="mt-4 space-y-3">
            <label className="grid gap-1 text-xs font-medium text-slate-600">增量时间字段（可选）
              <select className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs outline-none focus:border-blue-500"
                value={syncForm.time_column}
                onChange={(e) => setSyncForm({ ...syncForm, time_column: e.target.value, sync_mode: e.target.value ? 'incremental' : 'full' })}>
                <option value="">无（全量同步，每日限频）</option>
                {timeCandidates.map((col) => <option key={col} value={col}>{col}</option>)}
              </select>
            </label>
            {syncForm.time_column && (
              <label className="grid gap-1 text-xs font-medium text-slate-600">回看窗口（分钟，防边界漏数）
                <input type="number" min={0} max={1440} value={syncForm.lookback_minutes}
                  onChange={(e) => setSyncForm({ ...syncForm, lookback_minutes: Number(e.target.value) })}
                  className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs outline-none focus:border-blue-500" />
              </label>
            )}
            <p className="text-[11px] text-slate-400">
              {syncForm.time_column
                ? `增量模式：从上次水位线前 ${syncForm.lookback_minutes} 分钟回拉，主键去重覆盖`
                : '全量模式：快照覆盖，每日最多一次'}
            </p>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setConfiguring(null)}>取消</Button>
            <Button size="sm" disabled={busyTable !== null} onClick={() => void confirmSelect()}>
              {busyTable === configuring ? <Loader2 className="size-3.5 animate-spin" /> : null}确认加入
            </Button>
          </div>
        </section>
      </div>
    )}

    <div>
      <h2 className="font-semibold text-slate-900">数据探查</h2>
      <p className="mt-1 text-sm text-slate-600">
        看清源库有什么、质量如何，再决定同步哪些表、哪些字段纳入数据模型。
      </p>
    </div>

    {/* 控制条：数据源 + 扫描 + 统计 */}
    <section className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm" data-testid="profiling-toolbar">
      <label className="flex items-center gap-1.5 text-xs text-slate-600">
        <Database className="size-3.5" />
        <select aria-label="数据源" value={sourceId} disabled={scanning || sources.length === 0}
          onChange={(e) => { setSourceId(e.target.value); setLoading(true); void load(e.target.value).finally(() => setLoading(false)) }}
          className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs outline-none focus:border-blue-500">
          {sources.length === 0 && <option value="">无健康数据源</option>}
          {sources.map((s) => <option key={s.sourceId} value={s.sourceId}>{s.hospitalName} / {s.name}</option>)}
        </select>
      </label>
      <Button size="sm" variant="outline" disabled={scanning || !sourceId} onClick={() => void startScan()}
        data-testid="scan-button">
        {scanning ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
        {scanning ? '扫描中…' : '重新扫描'}
      </Button>
      <span className="text-xs text-slate-500">
        {lastScan ? `上次扫描 ${formatRelative(lastScan.started_at)}` : '尚未扫描'}
      </span>
      <span className="ml-auto text-xs text-slate-600" data-testid="profiling-stats">
        {groups.length} 表 · {totalFields} 字段 · 已映射 <span className="text-emerald-700">{totalMapped}</span>
        {syncTables.size > 0 && <> · 已选同步 <span className="text-blue-700">{syncTables.size}</span> 张</>}
      </span>
    </section>

    {(message || error) && (
      <p role={error ? 'alert' : 'status'}
        className={`rounded-lg border px-4 py-2 text-xs ${error ? 'border-red-200 bg-red-50 text-red-800' : 'border-blue-200 bg-blue-50 text-blue-800'}`}>
        {error ?? message}
      </p>
    )}

    {/* 筛选条 */}
    <div className="flex flex-wrap items-center gap-2">
      <input aria-label="搜索表或字段" value={search} onChange={(e) => setSearch(e.target.value)}
        placeholder="搜索表名 / 字段名…"
        className="h-8 w-56 rounded-md border border-slate-300 bg-white px-2 text-xs outline-none focus:border-blue-500" />
      {([['all', '全部'], ['selected', '已选同步'], ['unmapped', '含未映射字段']] as const).map(([key, label]) => (
        <button key={key} type="button" onClick={() => setFilter(key)}
          className={`rounded-full border px-2.5 py-1 text-xs ${filter === key ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-500 hover:border-slate-400'}`}>
          {label}
        </button>
      ))}
    </div>

    {/* 表清单 */}
    {loading ? (
      <div className="flex items-center gap-2 py-10 text-sm text-slate-500"><Loader2 className="size-4 animate-spin" />正在读取探查结果…</div>
    ) : visibleGroups.length === 0 ? (
      <section className="rounded-xl border border-dashed border-slate-300 bg-white py-12 text-center">
        <ScanSearch className="mx-auto size-8 text-slate-400" />
        <p className="mt-3 font-medium text-slate-800">{groups.length === 0 ? '暂无探查结果' : '没有匹配的表'}</p>
        <p className="mt-1 text-sm text-slate-500">{groups.length === 0 ? '选择数据源后点击「重新扫描」' : '调整搜索或筛选条件'}</p>
      </section>
    ) : (
      <section className="space-y-2" data-testid="table-list">
        {pagedGroups.map((group) => {
          const isOpen = expanded.has(group.table)
          const rowCount = syncTables.get(group.table)
          const isSelected = syncTables.has(group.table)
          return <section key={group.table} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
            data-testid={`table-${group.table}`}>
            <div className="flex w-full items-center gap-2 px-4 py-2.5">
              <button type="button" onClick={() => toggle(group.table)} aria-expanded={isOpen}
                className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-blue-700">
                {isOpen ? <ChevronDown className="size-4 shrink-0 text-slate-400" /> : <ChevronRight className="size-4 shrink-0 text-slate-400" />}
                <span className="min-w-0">
                  <span className="block truncate font-mono text-sm font-medium text-slate-800">{group.table}</span>
                  {results?.table_labels?.[group.table] && (
                    <span className="block truncate text-xs text-slate-500">{results.table_labels[group.table]}</span>
                  )}
                </span>
                <span className="shrink-0 text-xs text-slate-500">
                  {group.fields.length} 字段 · 已映射 {group.mappedCount}
                  {group.primaryKeys.length > 0 && <> · 主键 {group.primaryKeys.join(',')}</>}
                </span>
              </button>
              {isSelected
                ? <span className="inline-flex shrink-0 items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                  <CheckCircle2 className="size-3" />{rowCount === null ? '待同步' : `已同步 ${rowCount} 行`}
                </span>
                : <span className="shrink-0 text-xs text-slate-400">未同步</span>}
              {isSelected ? (
                <Button size="sm" variant="outline" disabled={busyTable !== null}
                  onClick={() => void runSync(group.table)} data-testid={`run-sync-${group.table}`}>
                  {busyTable === `run:${group.table}` ? <Loader2 className="size-3.5 animate-spin" /> : null}立即同步
                </Button>
              ) : (
                <Button size="sm" variant="outline" disabled={busyTable !== null}
                  onClick={() => addToSync(group.table)} data-testid={`select-sync-${group.table}`}>
                  {busyTable === group.table ? <Loader2 className="size-3.5 animate-spin" /> : <PlusCircle className="size-3.5" />}加入同步
                </Button>
              )}
            </div>
            {isOpen && (
              <div className="overflow-x-auto border-t border-slate-100">
                <table className="w-full text-left text-xs" data-testid={`fields-${group.table}`}>
                  <thead className="bg-slate-50 text-slate-500">
                    <tr><th className="px-4 py-2">字段</th><th className="px-4 py-2">中文名</th><th className="px-4 py-2">类型</th><th className="px-4 py-2">非空率</th><th className="px-4 py-2">样本值</th><th className="px-4 py-2">主键</th><th className="px-4 py-2">映射</th><th className="px-4 py-2">操作</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {group.fields.map((field) => <tr key={field.field_name}>
                      <td className="px-4 py-2 font-mono">{field.field_name}</td>
                      <td className="max-w-32 truncate px-4 py-2 text-slate-600" title={field.description ?? ''}>
                        {field.description ?? '—'}
                      </td>
                      <td className="px-4 py-2 font-mono text-slate-500">{field.data_type}</td>
                      <td className={`px-4 py-2 font-mono ${nonNullTone(field.non_null_rate)}`}>{field.non_null_rate.toFixed(1)}%</td>
                      <td className="max-w-40 truncate px-4 py-2 font-mono text-slate-500" title={field.sample_value ?? ''}>
                        {field.sample_value ?? '—'}
                      </td>
                      <td className="px-4 py-2">{field.is_primary_key ? '是' : '—'}</td>
                      <td className="px-4 py-2">
                        {field.mapped
                          ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">已映射</span>
                          : <span className="text-slate-400">未映射</span>}
                      </td>
                      <td className="px-4 py-2">
                        <Link
                          href={`/data-governance/modeling?table=${encodeURIComponent(group.table)}&field=${encodeURIComponent(field.field_name)}&field_code=${encodeURIComponent(suggestFieldCode(field.field_name))}&name=${encodeURIComponent(field.description || field.field_name)}&role=${suggestFieldRole(field)}&data_type=${encodeURIComponent(field.data_type)}`}
                          className="text-blue-600 hover:underline">
                          纳入建模 →
                        </Link>
                      </td>
                    </tr>)}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        })}
      </section>
    )}
    {totalPages > 1 && (
      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs text-slate-500" data-testid="table-pagination">
        <span>第 <span className="font-mono text-slate-700">{safePage}</span> / {totalPages} 页 · 共 {visibleGroups.length} 张表</span>
        <div className="flex gap-1">
          <button type="button" disabled={safePage <= 1} onClick={() => setPage((p) => p - 1)}
            className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40 hover:border-slate-400">上一页</button>
          <button type="button" disabled={safePage >= totalPages} onClick={() => setPage((p) => p + 1)}
            className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40 hover:border-slate-400">下一页</button>
        </div>
      </div>
    )}
  
    <NextStepCard href="C:/Program Files/Git/data-governance/sync-jobs" title="执行选表同步，数据落 PostgreSQL"
      description="同步把数据搬进治理底座" />
</div>
}
