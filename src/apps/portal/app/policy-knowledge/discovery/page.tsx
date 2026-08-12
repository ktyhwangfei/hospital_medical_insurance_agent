'use client'

// P9.6 发现 tab —— 多源扫描候选指标 → 人工确认 → 回写语义层。
// 全量扫描走 SSE 流式进度；增量刷新同步；未映射字段=候选 → POST /semantic/metrics/batch 回写。
// [来源: docs/steering/政策知识管线开发计划.md Phase 9.6 / §8.1]

import { useState, useEffect, useCallback } from 'react'
import {
  Compass, Loader2, RefreshCw, Zap, Search, Database, CheckCircle2,
} from 'lucide-react'
import { semanticReviewJson } from '@/lib/policy-knowledge-api'

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'

interface FieldItem {
  field_name: string
  table_name: string
  data_type: string
  non_null_rate: number
  sample_value?: string | null
  is_dictionary: boolean
  is_primary_key?: boolean
  suggested_object?: string | null
  mapped: boolean
  description?: string | null
}

interface Results {
  tables_count?: number
  fields_count?: number
  mapped_fields?: number
  unmapped_fields?: number
  fields: FieldItem[]
}

interface ObjectInfo { object_code: string; name: string }

interface BatchResult { index: number; metric_code: string; name: string; status: string; error?: string | null }

function inferSemanticType(dt: string): string {
  const s = (dt || '').toLowerCase()
  if (s.includes('int') || s.includes('decimal') || s.includes('numeric')) return 'Amount'
  if (s.includes('date') || s.includes('time')) return 'String'
  if (s.includes('bit') || s.includes('char')) return s.includes('bit') ? 'Enum' : 'String'
  return 'String'
}

const fieldKey = (f: FieldItem) => `${f.table_name}.${f.field_name}`

export default function DiscoveryPage() {
  const [results, setResults] = useState<Results | null>(null)
  const [objects, setObjects] = useState<ObjectInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [progress, setProgress] = useState<{ table?: string; done?: number; total?: number } | null>(null)
  const [error, setError] = useState('')
  const [onlyCandidates, setOnlyCandidates] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [targetObj, setTargetObj] = useState('')
  const [writing, setWriting] = useState(false)
  const [writeResults, setWriteResults] = useState<BatchResult[] | null>(null)

  const fetchResults = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`${SEMANTIC_API}/discovery/results`)
      if (r.ok) setResults(await r.json())
    } catch {
      setError('加载发现结果失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchObjects = useCallback(async () => {
    try {
      const r = await fetch(`${SEMANTIC_API}/objects`)
      if (r.ok) setObjects(await r.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchResults(); fetchObjects() }, [fetchResults, fetchObjects])

  // 全量扫描：POST /discovery/scan → 流式消费 SSE 状态
  async function handleScan() {
    setScanning(true); setError(''); setProgress({ done: 0, total: 0 })
    try {
      const r = await fetch(`${SEMANTIC_API}/discovery/scan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      })
      const { task_id } = await r.json()
      const sse = await fetch(`${SEMANTIC_API}/discovery/scan/${task_id}/status`)
      const reader = sse.body?.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let tablesScanned = 0
      if (reader) {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n')
          buf = lines.pop() || ''
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const ev = JSON.parse(line.slice(6))
              if (ev.table) {
                tablesScanned++
                setProgress({ table: ev.table, done: tablesScanned })
              }
              if (ev.status === 'completed') {
                setProgress(p => ({ ...p, done: ev.tables_scanned, total: ev.tables_scanned }))
              }
            } catch { /* skip */ }
          }
        }
      }
      await fetchResults()
    } catch (e) {
      setError('扫描失败：' + (e instanceof Error ? e.message : ''))
    } finally {
      setScanning(false)
      setTimeout(() => setProgress(null), 1500)
    }
  }

  // 增量刷新：同步
  async function handleIncremental() {
    setScanning(true); setError('')
    try {
      const r = await fetch(`${SEMANTIC_API}/discovery/incremental-update`, { method: 'POST' })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail?.message || d.detail || `HTTP ${r.status}`)
      }
      await fetchResults()
    } catch (e) {
      setError(e instanceof Error ? e.message : '增量刷新失败')
    } finally {
      setScanning(false)
    }
  }

  function toggleSel(key: string) {
    setSelected(p => { const n = new Set(p); n.has(key) ? n.delete(key) : n.add(key); return n })
  }

  const filtered = (results?.fields || [])
    .filter(f => onlyCandidates ? !f.mapped : true)
    .filter(f => {
      if (!keyword.trim()) return true
      const k = keyword.toLowerCase()
      return f.field_name.toLowerCase().includes(k) || f.table_name.toLowerCase().includes(k)
    })

  const candidates = (results?.fields || []).filter(f => !f.mapped)

  // 回写语义层：选中候选 → POST /metrics/batch
  async function handleWriteBack() {
    if (selected.size === 0) return
    const selFields = candidates.filter(f => selected.has(fieldKey(f)))
    if (selFields.length === 0) return
    const objCode = targetObj || selFields[0]?.suggested_object || objects[0]?.object_code || ''
    if (!objCode) {
      setError('请选择目标业务对象')
      return
    }
    setWriting(true); setError(''); setWriteResults(null)
    try {
      const items = selFields.map(f => ({
        object_code: objCode,
        name: f.field_name,
        semantic_type: inferSemanticType(f.data_type),
        source_table: f.table_name,
        source_field: f.field_name,
        importance: 'optional',
      }))
      const res = await semanticReviewJson<BatchResult[]>(`${SEMANTIC_API}/metrics/batch`, 'POST', { items })
      setWriteResults(res)
      const created = res.filter(x => x.status === 'created').length
      if (created > 0) {
        setSelected(new Set())
        await fetchResults()  // 候选回写后 mapped 更新
      }
      alert(`回写完成：${created} 创建 / ${res.filter(x => x.status === 'skipped').length} 跳过 / ${res.filter(x => x.status === 'error').length} 错误`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '回写失败')
    } finally {
      setWriting(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            发现
          </span>
          <span className="text-xs text-slate-500">多源扫描候选指标 → 确认 → 回写语义层</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">发现</h2>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={handleScan} disabled={scanning}
          className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700 disabled:opacity-50">
          {scanning ? <Loader2 className="size-4 animate-spin" /> : <Compass className="size-4" />}
          全量扫描
        </button>
        <button onClick={handleIncremental} disabled={scanning}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw className="size-4" /> 增量刷新
        </button>
        {progress && (
          <span className="text-xs text-slate-500">
            {progress.table ? `扫描: ${progress.table}` : `已完成 ${progress.done}/${progress.total || ''} 表`}
          </span>
        )}
        <span className="text-xs text-slate-400 ml-auto">
          {candidates.length} 候选 / {results?.fields_count ?? 0} 字段 / {results?.tables_count ?? 0} 表
        </span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {/* Results Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={onlyCandidates} onChange={e => setOnlyCandidates(e.target.checked)} className="accent-cyan-600" />
          仅未映射候选
        </label>
        <div className="relative">
          <Search className="size-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="字段/表名"
            className="w-48 rounded-lg border border-slate-200 py-1.5 pl-8 pr-2 text-xs text-slate-600" />
        </div>
        {selected.size > 0 && (
          <div className="flex items-center gap-2 ml-auto">
            <select value={targetObj} onChange={e => setTargetObj(e.target.value)}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-600">
              <option value="">默认对象（按 suggested_object）</option>
              {objects.map(o => <option key={o.object_code} value={o.object_code}>{o.object_code} · {o.name}</option>)}
            </select>
            <button onClick={handleWriteBack} disabled={writing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
              {writing ? <Loader2 className="size-3.5 animate-spin" /> : <Zap className="size-3.5" />}
              回写 {selected.size} 候选
            </button>
          </div>
        )}
      </div>

      {/* Field Table */}
      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
          <Database className="mx-auto mb-2 size-8 opacity-40" />
          {candidates.length === 0 ? '无未映射候选，全部字段已映射语义层。' : '无匹配字段。'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2 w-8"></th>
                <th className="px-3 py-2">字段</th>
                <th className="px-3 py-2">表</th>
                <th className="px-3 py-2">类型</th>
                <th className="px-3 py-2">非空率</th>
                <th className="px-3 py-2">建议对象</th>
                <th className="px-3 py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(f => {
                const key = fieldKey(f)
                const sel = selected.has(key)
                return (
                  <tr key={key} className="border-b border-slate-50 hover:bg-slate-50/60">
                    <td className="px-3 py-2">
                      {!f.mapped && (
                        <input type="checkbox" checked={sel} onChange={() => toggleSel(key)} className="accent-emerald-600" />
                      )}
                    </td>
                    <td className="px-3 py-2"><code className="text-xs text-slate-700">{f.field_name}</code></td>
                    <td className="px-3 py-2 text-xs text-slate-500">{f.table_name}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{f.data_type}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{(f.non_null_rate * 100).toFixed(0)}%</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{f.suggested_object || '—'}</td>
                    <td className="px-3 py-2">
                      {f.mapped ? (
                        <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">已映射</span>
                      ) : (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">候选</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 回写结果 drawer */}
      {writeResults && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm" onClick={() => setWriteResults(null)}>
          <div className="h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-100 bg-white px-5 py-3">
              <CheckCircle2 className="size-4 text-emerald-600" />
              <h3 className="text-sm font-semibold text-slate-800">回写结果</h3>
              <button onClick={() => setWriteResults(null)} className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none">×</button>
            </div>
            <div className="flex flex-col gap-1.5 p-5">
              {writeResults.map(r => (
                <div key={r.index} className="flex items-center gap-2 rounded-lg border border-slate-100 px-3 py-2">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    r.status === 'created' ? 'bg-emerald-100 text-emerald-700' :
                    r.status === 'skipped' ? 'bg-slate-100 text-slate-600' : 'bg-red-100 text-red-700'
                  }`}>{r.status}</span>
                  <code className="text-xs text-slate-700">{r.metric_code}</code>
                  {r.error && <span className="text-[10px] text-red-500 ml-auto">{r.error}</span>}
                </div>
              ))}
              <p className="mt-2 text-[11px] text-slate-400">已创建指标初始为 draft，可在语义层管理页发布。</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
