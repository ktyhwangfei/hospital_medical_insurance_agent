'use client'

import { useState } from 'react'
import { Search, Loader2, Database, FileText, Layers } from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

type Mode = 'precise' | 'semantic' | 'hybrid'
type Target = 'policy' | 'database' | 'both'

interface Rule { [key: string]: any }
interface Group { fact_id: string; fact_text: string; rules: Rule[] }

const FILTER_FIELDS = [
  { key: 'insu_type', label: '险种类型' },
  { key: 'med_type', label: '医疗类别' },
  { key: 'hosp_lv', label: '医院等级' },
  { key: 'rule_type', label: '规则类型' },
  { key: 'psn_type', label: '人群标签' },
]

export default function RetrievalPage() {
  const [mode, setMode] = useState<Mode>('precise')
  const [target, setTarget] = useState<Target>('policy')
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [metricCodes, setMetricCodes] = useState('djxx.fund_type,djxx.yllb')
  const [contextDjh, setContextDjh] = useState('')
  const [topK, setTopK] = useState(20)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<{ groups: Group[]; database_values: Record<string, any>; total_groups: number } | null>(null)
  const [error, setError] = useState('')

  async function handleSearch() {
    setLoading(true); setError(''); setResult(null)
    try {
      const body: Record<string, any> = { mode, target, top_k: topK }
      if (mode !== 'precise') body.query = query
      if (mode === 'precise' || mode === 'hybrid') {
        body.filters = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
      }
      if (target !== 'policy') {
        body.metric_codes = metricCodes.split(',').map(s => s.trim()).filter(Boolean)
        body.context = contextDjh ? { djh: contextDjh } : {}
      }
      const r = await fetch(`${API}/rules/search`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail?.message || d.detail || `HTTP ${r.status}`)
      }
      setResult(await r.json())
    } catch (e: any) {
      setError(e.message || '检索失败')
    } finally {
      setLoading(false)
    }
  }

  const MODE_DESC: Record<Mode, string> = {
    precise: '精准标量过滤（按核心维度精确匹配）',
    semantic: '语义向量召回（自然语言查询）',
    hybrid: '混合（向量召回 + 标量过滤）',
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-800">
            <Search className="size-7 text-blue-600" /> 政策知识检索
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            三模式检索 + 跨世界联查（基于 policy_rules_v2 + 业务库）。后端 API：<code className="rounded bg-slate-100 px-1">POST /rules/search</code>
          </p>
        </div>

        {/* 检索模式 */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-xs font-semibold text-slate-600">检索模式 (mode)</label>
              <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
                {(['precise', 'semantic', 'hybrid'] as Mode[]).map(m => (
                  <button key={m} onClick={() => setMode(m)}
                    className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition ${mode === m ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
                    {m}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-400">{MODE_DESC[mode]}</p>
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold text-slate-600">查询目标 (target)</label>
              <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
                {(['policy', 'database', 'both'] as Target[]).map(t => (
                  <button key={t} onClick={() => setTarget(t)}
                    className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition ${target === t ? 'bg-white text-emerald-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
                    {t === 'policy' ? '政策库' : t === 'database' ? '业务库' : '两者'}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-400">
                {target === 'policy' ? '查政策规则' : target === 'database' ? '经 source_field 查业务数据' : '政策规则 + 业务数据联查'}
              </p>
            </div>
          </div>

          {/* 语义查询 */}
          {mode !== 'precise' && (
            <div className="mt-4">
              <label className="mb-1.5 block text-xs font-semibold text-slate-600">语义查询 (query)</label>
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="如：城镇职工住院报销比例"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </div>
          )}

          {/* 标量过滤 */}
          {(mode === 'precise' || mode === 'hybrid') && (
            <div className="mt-4">
              <label className="mb-1.5 block text-xs font-semibold text-slate-600">核心维度过滤 (filters)</label>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                {FILTER_FIELDS.map(f => (
                  <input key={f.key} value={filters[f.key] || ''} onChange={e => setFilters(p => ({ ...p, [f.key]: e.target.value }))}
                    placeholder={f.label}
                    className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none" />
                ))}
              </div>
            </div>
          )}

          {/* 跨世界 */}
          {target !== 'policy' && (
            <div className="mt-4 rounded-lg bg-emerald-50/50 p-3">
              <label className="mb-1.5 block text-xs font-semibold text-emerald-700">跨世界：业务指标查询</label>
              <div className="grid gap-2 md:grid-cols-2">
                <input value={metricCodes} onChange={e => setMetricCodes(e.target.value)}
                  placeholder="metric_codes（逗号分隔，如 djxx.fund_type）"
                  className="rounded-lg border border-emerald-200 bg-white px-3 py-1.5 text-xs focus:border-emerald-500 focus:outline-none" />
                <input value={contextDjh} onChange={e => setContextDjh(e.target.value)}
                  placeholder="登记号 djh（业务库过滤键）"
                  className="rounded-lg border border-emerald-200 bg-white px-3 py-1.5 text-xs focus:border-emerald-500 focus:outline-none" />
              </div>
            </div>
          )}

          <div className="mt-4 flex items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-500">top_k</label>
              <input type="number" value={topK} onChange={e => setTopK(Number(e.target.value) || 20)}
                className="w-20 rounded-lg border border-slate-300 px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none" />
            </div>
            <button onClick={handleSearch} disabled={loading}
              className="ml-auto flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50">
              {loading ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />} 检索
            </button>
          </div>
        </div>

        {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        {/* 结果 */}
        {result && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 text-sm text-slate-600">
              <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">{result.total_groups} 个事实分组</span>
              {target !== 'policy' && (
                <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                  {Object.keys(result.database_values || {}).length} 个业务指标
                </span>
              )}
            </div>

            {/* 业务数据 */}
            {target !== 'policy' && result.database_values && Object.keys(result.database_values).length > 0 && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-4">
                <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-emerald-800">
                  <Database className="size-4" /> 业务数据（target=database）
                </h3>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(result.database_values).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-emerald-200 bg-white px-3 py-1.5">
                      <div className="text-[10px] text-slate-400">{k}</div>
                      <div className="text-sm font-medium text-slate-700">{String(v ?? '—')}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 政策规则（按 fact 分组） */}
            {result.groups.map((g, i) => (
              <div key={g.fact_id || i} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-start gap-2 border-b border-slate-100 pb-2">
                  <Layers className="mt-0.5 size-4 shrink-0 text-purple-500" />
                  <div>
                    <div className="text-[11px] text-slate-400">事实 {g.fact_id}</div>
                    <div className="text-sm font-medium text-slate-700">{g.fact_text}</div>
                  </div>
                  <span className="ml-auto rounded bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">
                    {g.rules.length} 条规则
                  </span>
                </div>
                <div className="space-y-2">
                  {g.rules.map((r, j) => (
                    <div key={j} className="rounded-lg bg-slate-50 p-2.5">
                      <div className="mb-1 flex flex-wrap items-center gap-1.5">
                        {r.rule_type && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-200">{r.rule_type}</span>}
                        {r.insu_type && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{r.insu_type}</span>}
                        {r.hosp_lv && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{r.hosp_lv}</span>}
                        {typeof r.score === 'number' && (
                          <span className="ml-auto text-[10px] text-amber-600">score: {r.score.toFixed(3)}</span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 md:grid-cols-3">
                        {[['payment_ratio', '支付比例'], ['deductible_amount', '起付'], ['cap_amount', '封顶'], ['amount_band', '分段'], ['rule_value', '规则值']].map(([k, label]) => (
                          r[k] ? (
                            <div key={k} className="text-xs">
                              <span className="text-slate-400">{label}: </span>
                              <span className="font-medium text-slate-700">{String(r[k])}</span>
                            </div>
                          ) : null
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {result.groups.length === 0 && target === 'policy' && (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
                <FileText className="mx-auto mb-2 size-8 opacity-40" />
                policy_rules_v2 无匹配规则。先上传政策 → 提取 → publish-v2 入库。
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
