'use client'

// P9.5 结构化 tab —— 合并现 rules（规则库）+ search（三模式混合检索）。
// 双子 tab：「混合检索」（P6 三模式 + 跨世界联查）+「规则库」（已入库规则浏览 + 字段级溯源）。
// [来源: docs/steering/政策知识管线开发计划.md Phase 9.5]

import { useState, useCallback, useEffect } from 'react'
import {
  Search, Loader2, Database, FileText, Layers, ListTree,
  X,
} from 'lucide-react'

const PIPELINE_API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'
const RULES_API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'

type SubTab = 'retrieval' | 'library'

type Mode = 'precise' | 'semantic' | 'hybrid'
type Target = 'policy' | 'database' | 'both'

interface Rule { [key: string]: any }
interface Group { fact_id: string; fact_text: string; rules: Rule[] }

const FILTER_FIELDS = [
  { key: 'insu_type', label: '险种' },
  { key: 'med_type', label: '医疗类别' },
  { key: 'hosp_lv', label: '医院等级' },
  { key: 'rule_type', label: '规则类型' },
  { key: 'psn_type', label: '人群' },
]

const RULE_LABELS: Record<string, string> = {
  rule_id: '规则ID', fact_id: '事实ID', policy_id: '政策ID', clause_id: '条款ID',
  source_text: '政策原文', doc_id: '来源文档', insu_type: '险种', med_type: '医疗类别',
  hosp_lv: '医院等级', psn_type: '人群', setl_type: '结算方式', payment_ratio: '支付比例',
  deductible_amount: '起付金额', cap_amount: '封顶金额', time_period: '时间周期',
  admission_order: '住院序次', amount_band: '金额区间', priority: '优先级',
  rule_type: '规则类型', rule_value: '规则值',
}
const DETAIL_FIELDS = Object.keys(RULE_LABELS)

/** FieldTrace 字段级溯源对象展开：{value, confidence, extracted_at} → value（P2） */
function unwrap(raw: any): string {
  if (raw && typeof raw === 'object' && 'value' in raw) return String(raw.value ?? '')
  if (raw === null || raw === undefined) return ''
  return String(raw)
}

export default function StructuredPage() {
  const [sub, setSub] = useState<SubTab>('retrieval')
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            结构化
          </span>
          <span className="text-xs text-slate-500">规则库 + 三模式混合检索</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">结构化</h2>
      </div>

      {/* 子 tab */}
      <div className="flex gap-1 rounded-lg bg-slate-100 p-1 w-fit">
        <button onClick={() => setSub('retrieval')}
          className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-medium transition ${sub === 'retrieval' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          <Search className="size-3.5" /> 混合检索
        </button>
        <button onClick={() => setSub('library')}
          className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-medium transition ${sub === 'library' ? 'bg-white text-emerald-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          <ListTree className="size-3.5" /> 规则库
        </button>
      </div>

      {sub === 'retrieval' ? <RetrievalPanel /> : <RuleLibrary />}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// 子 tab 1：混合检索（三模式 + 跨世界，自 search 页移植）
// ════════════════════════════════════════════════════════════

function RetrievalPanel() {
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
      const r = await fetch(`${PIPELINE_API}/rules/search`, {
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
    <div className="flex flex-col gap-4">
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

        {mode !== 'precise' && (
          <div className="mt-4">
            <label className="mb-1.5 block text-xs font-semibold text-slate-600">语义查询 (query)</label>
            <input value={query} onChange={e => setQuery(e.target.value)} placeholder="如：城镇职工住院报销比例"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
          </div>
        )}

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

      {result && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3 text-sm text-slate-600">
            <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">{result.total_groups} 个事实分组</span>
            {target !== 'policy' && (
              <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                {Object.keys(result.database_values || {}).length} 个业务指标
              </span>
            )}
          </div>

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
              <div className="flex flex-col gap-2">
                {g.rules.map((r, j) => (
                  <div key={j} className="rounded-lg bg-slate-50 p-2.5">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      {r.rule_type && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-200">{unwrap(r.rule_type)}</span>}
                      {r.insu_type && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{unwrap(r.insu_type)}</span>}
                      {r.hosp_lv && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{unwrap(r.hosp_lv)}</span>}
                      {typeof r.score === 'number' && (
                        <span className="ml-auto text-[10px] text-amber-600">score: {r.score.toFixed(3)}</span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 md:grid-cols-3">
                      {[['payment_ratio', '支付比例'], ['deductible_amount', '起付'], ['cap_amount', '封顶'], ['amount_band', '分段'], ['rule_value', '规则值']].map(([k, label]) => {
                        const val = unwrap(r[k])
                        return val ? (
                          <div key={k} className="text-xs">
                            <span className="text-slate-400">{label}: </span>
                            <span className="font-medium text-slate-700">{val}</span>
                          </div>
                        ) : null
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {result.groups.length === 0 && target === 'policy' && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
              <FileText className="mx-auto mb-2 size-8 opacity-40" />
              policy_rules_v2 无匹配规则。先上传政策 → 提取 → 向量化入库。
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// 子 tab 2：规则库（已入库规则浏览 + 字段级溯源）
// ════════════════════════════════════════════════════════════

function RuleLibrary() {
  const [rules, setRules] = useState<Rule[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [ruleType, setRuleType] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<Rule | null>(null)
  const [docTitle, setDocTitle] = useState('')
  const PAGE = 20

  const fetchRules = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(PAGE) })
      if (keyword.trim()) p.set('keyword', keyword.trim())
      if (ruleType.trim()) p.set('rule_type', ruleType.trim())
      const r = await fetch(`${RULES_API}/rules?${p}`)
      const d = await r.json()
      setRules(d.items || [])
      setTotal(d.total || 0)
    } catch {
      setError('无法连接后端')
    } finally {
      setLoading(false)
    }
  }, [page, keyword, ruleType])

  useEffect(() => { const t = setTimeout(fetchRules, 200); return () => clearTimeout(t) }, [fetchRules])

  async function openDetail(r: Rule) {
    setDetail(r)
    setDocTitle('')
    if (r.doc_id && r.doc_id !== 'None') {
      try {
        const res = await fetch(`${PIPELINE_API}/documents/${r.doc_id}`)
        if (res.ok) {
          const doc = await res.json()
          setDocTitle(doc.title || r.doc_id)
        }
      } catch { /* ignore */ }
    }
  }

  const pageCount = Math.ceil(total / PAGE) || 1

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input value={keyword} onChange={e => { setKeyword(e.target.value); setPage(1) }}
          placeholder="关键词搜索规则/原文"
          className="w-48 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600" />
        <input value={ruleType} onChange={e => { setRuleType(e.target.value); setPage(1) }}
          placeholder="规则类型过滤"
          className="w-36 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600" />
        <span className="text-xs text-slate-400 ml-auto">共 {total} 条</span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
      ) : rules.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-400">
          规则库为空。先在「事实」tab 向量化入库后再浏览。
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {rules.map(r => (
            <button key={r.rule_id || Math.random()} onClick={() => openDetail(r)}
              className="text-left rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 shadow-sm transition hover:border-emerald-300 hover:shadow-md">
              <div className="flex items-center gap-2">
                {r.rule_type && (
                  <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-200">{unwrap(r.rule_type)}</span>
                )}
                {r.insu_type && <span className="text-[11px] text-slate-500">{unwrap(r.insu_type)}</span>}
                {r.hosp_lv && <span className="text-[11px] text-slate-500">· {unwrap(r.hosp_lv)}</span>}
                <code className="ml-auto text-[10px] text-slate-400">{r.rule_id}</code>
              </div>
              <p className="mt-1 line-clamp-1 text-xs text-slate-600">
                {unwrap(r.payment_ratio) || unwrap(r.deductible_amount) || unwrap(r.rule_value) || unwrap(r.source_text) || '（无摘要）'}
              </p>
            </button>
          ))}
        </div>
      )}

      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
            className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">上一页</button>
          <span className="text-xs text-slate-500">{page} / {pageCount}</span>
          <button disabled={page >= pageCount} onClick={() => setPage(p => p + 1)}
            className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">下一页</button>
        </div>
      )}

      {/* 规则详情 drawer */}
      {detail && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm" onClick={() => setDetail(null)}>
          <div className="h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-100 bg-white px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-800">规则详情</h3>
              <code className="text-[11px] text-slate-400">{detail.rule_id}</code>
              <button onClick={() => setDetail(null)} className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none">×</button>
            </div>
            <div className="flex flex-col gap-3 p-5">
              <div className="rounded-lg bg-slate-50 p-3 text-[11px]">
                <span className="text-slate-400">来源文档：</span>
                <span className="text-slate-700">{docTitle || detail.doc_id || '—'}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {DETAIL_FIELDS.map(f => {
                  const val = unwrap(detail[f])
                  if (!val || val === 'None') return null
                  return (
                    <div key={f}>
                      <div className="text-[10px] text-slate-400">{RULE_LABELS[f]}</div>
                      <div className="text-xs text-slate-700 break-words">{val}</div>
                    </div>
                  )
                })}
              </div>
              <div className="rounded-lg bg-amber-50/40 p-2.5 text-[10px] text-amber-700">
                字段级溯源：数值/枚举字段以 {`{value, confidence, extracted_at}`} 包装（P2 FieldTrace），此处显示 value。
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

