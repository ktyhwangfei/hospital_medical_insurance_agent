'use client'

// 页面顶层使用 useSearchParams → 关闭静态预渲染（Next.js 要求 Suspense 或动态渲染）
export const dynamic = 'force-dynamic'

// 政策知识治理 · 知识模块（原"结构化"tab 改造）。
// 3 子视图：审核（治理心脏）/ 检索（三模式+跨世界）/ 规则库（浏览+溯源）。
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 审核视图接真实接口：GET /extractions + PUT(状态转换) + POST /publish（发布到 Milvus）。
// 生命周期 5 态就绪；当前数据承载 draft/reviewed/published/rejected 4 态，
// superseded/deprecated + evidence/confidence/extractor/knowledge_type 走优雅降级（有则显）。

import { useState, useCallback, useEffect, useMemo, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  Search, Loader2, Database, FileText, Layers, ListTree,
  ShieldCheck, CheckCircle2, XCircle, RefreshCw, Send, Quote, Gauge, Cpu, X,
} from 'lucide-react'

const PIPELINE_API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'
const RULES_API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'

type SubTab = 'audit' | 'retrieval' | 'library'

// ── 生命周期 5 态（V2.1 §3.1）。当前数据承载前 4 态，后 2 态占位待数据 ──
const LIFECYCLE: Record<string, { label: string; cls: string }> = {
  draft: { label: '待审', cls: 'bg-slate-100 text-slate-600' },
  reviewed: { label: '待发布', cls: 'bg-amber-100 text-amber-700' },
  published: { label: '已发布', cls: 'bg-emerald-100 text-emerald-700' },
  rejected: { label: '已驳回', cls: 'bg-red-100 text-red-700' },
  superseded: { label: '已替代', cls: 'bg-violet-100 text-violet-700' },
  deprecated: { label: '已废止', cls: 'bg-zinc-200 text-zinc-600' },
}

// 8 类知识类型（V2.1 §2.3）。当前数据用 rule_type 近似，全 8 类待提取增强。
const KNOWLEDGE_TYPE_LABEL: Record<string, string> = {
  Definition: '定义', Rule: '规则', Formula: '计算', Condition: '条件',
  Constraint: '约束', Exception: '例外', Procedure: '流程', Reference: '引用',
}

interface PolicyRule { [key: string]: any }
interface ExtractedFields {
  fact_text?: string
  rules?: PolicyRule[]
  [key: string]: unknown
}
interface Extraction {
  extraction_id: string
  doc_id: string
  doc_title?: string
  source_text: string
  extracted_fields: ExtractedFields
  confidence: number
  status: string
  reviewed_by?: string
  reviewed_at?: string
  created_at: string
  [key: string]: unknown
}

/** FieldTrace 字段级溯源对象展开：{value, confidence, extracted_at} → value */
function unwrap(raw: any): string {
  if (raw && typeof raw === 'object' && 'value' in raw) return String((raw as any).value ?? '')
  if (raw === null || raw === undefined) return ''
  return String(raw)
}

export default function KnowledgePage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>}>
      <KnowledgeContent />
    </Suspense>
  )
}

function KnowledgeContent() {
  const params = useSearchParams()
  const docId = params.get('doc_id') || ''
  const [sub, setSub] = useState<SubTab>((params.get('sub') as SubTab) || 'audit')

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            知识治理
          </span>
          {docId && <span className="text-xs text-slate-400">筛选自文档: {docId}</span>}
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">知识</h2>
      </div>

      <div className="flex gap-1 rounded-lg bg-slate-100 p-1 w-fit">
        <button onClick={() => setSub('audit')}
          className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-medium transition ${sub === 'audit' ? 'bg-white text-amber-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          <ShieldCheck className="size-3.5" /> 审核
        </button>
        <button onClick={() => setSub('retrieval')}
          className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-medium transition ${sub === 'retrieval' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          <Search className="size-3.5" /> 检索
        </button>
        <button onClick={() => setSub('library')}
          className={`flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-xs font-medium transition ${sub === 'library' ? 'bg-white text-emerald-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          <ListTree className="size-3.5" /> 规则库
        </button>
      </div>

      {sub === 'audit' && <AuditView docId={docId} />}
      {sub === 'retrieval' && <RetrievalView />}
      {sub === 'library' && <LibraryView />}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// 子视图 1：审核（治理心脏）—— 生命周期 + 证据/置信/提取器 + 审核动作
// ════════════════════════════════════════════════════════════

function AuditView({ docId }: { docId: string }) {
  const [extractions, setExtractions] = useState<Extraction[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState('reviewed')
  const [lowConf, setLowConf] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<Extraction | null>(null)
  const [busy, setBusy] = useState('')
  const PAGE = 20

  const fetchList = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(PAGE) })
      if (docId) p.set('doc_id', docId)
      if (status) p.set('status', status)
      const r = await fetch(`${PIPELINE_API}/extractions?${p}`)
      const d = await r.json()
      let items: Extraction[] = d.items || []
      if (lowConf) items = items.filter((e) => (e.confidence ?? 1) < 0.8)
      setExtractions(items)
      setTotal(lowConf ? items.length : (d.total || 0))
    } catch {
      setError('加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, status, docId, lowConf])

  useEffect(() => { fetchList() }, [fetchList])

  async function refreshDetail(id: string) {
    try {
      const r = await fetch(`${PIPELINE_API}/extractions/${id}`)
      if (r.ok) setDetail(await r.json())
    } catch { /* ignore */ }
  }

  async function act(extId: string, fn: () => Promise<Response>, label: string, closeAfter = false) {
    setBusy(extId); setError('')
    try {
      const r = await fn()
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError(d.detail?.message || d.detail || `${label}失败`)
      } else {
        if (detail && detail.extraction_id === extId) {
          if (closeAfter) setDetail(null)
          else await refreshDetail(extId)
        }
        fetchList()
      }
    } catch {
      setError(`${label}失败`)
    } finally {
      setBusy('')
    }
  }

  const approve = (id: string) =>
    act(id, () => fetch(`${PIPELINE_API}/extractions/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'reviewed' }),
    }), '通过')
  const reject = (id: string) =>
    act(id, () => fetch(`${PIPELINE_API}/extractions/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'rejected' }),
    }), '驳回', true)
  const publish = (id: string) => {
    if (!confirm('确认发布到知识库（policy_facts + policy_rules_v2）？仅 Published 进入检索池。')) return
    act(id, () => fetch(`${PIPELINE_API}/extractions/${id}/publish`, { method: 'POST' }), '发布')
  }
  const reextract = (did: string) => {
    if (!confirm('重新抽取该文档？将生成新的提取记录。')) return
    act('__reextract__', async () => fetch(`${PIPELINE_API}/documents/${did}/extract`, { method: 'POST' }), '重新抽取')
  }

  const pageCount = Math.ceil(total / PAGE) || 1

  return (
    <div className="flex flex-col gap-3">
      {/* 治理筛选条 */}
      <div className="flex flex-wrap items-center gap-2">
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}
          className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-600">
          <option value="">全部生命周期</option>
          <option value="draft">待审 (Draft)</option>
          <option value="reviewed">待发布 (Review)</option>
          <option value="published">已发布 (Published)</option>
          <option value="rejected">已驳回</option>
        </select>
        <label className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50/50 px-2.5 py-2 text-xs text-amber-700">
          <input type="checkbox" checked={lowConf} onChange={(e) => { setLowConf(e.target.checked); setPage(1) }} className="size-3" />
          低置信 (&lt;0.8)
        </label>
        <span className="ml-auto text-xs text-slate-400">共 {total} 条</span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
      ) : extractions.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-400">
          暂无待结构化提取的知识。
          <div className="mt-1 text-xs">
            请先在「<a href={`/policy-knowledge/units${docId ? `?doc_id=${docId}` : ''}`} className="text-amber-600 hover:underline">单元</a>」页审核原文，通过后此处进行结构化提取/发布。
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {extractions.map((ext) => {
            const lc = LIFECYCLE[ext.status] || { label: ext.status, cls: 'bg-slate-100 text-slate-600' }
            const rules = (ext.extracted_fields?.rules as PolicyRule[]) || []
            const kt = rules[0]?.rule_type ? String(unwrap(rules[0].rule_type)) : ''
            const ktLabel = KNOWLEDGE_TYPE_LABEL[kt] || kt || '规则'
            const evidence = ext.source_text || ext.extracted_fields?.fact_text || ''
            const conf = ext.confidence ?? 0
            const confLow = conf < 0.8
            return (
              <div key={ext.extraction_id}
                className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm transition hover:shadow-md">
                {/* 行 1：生命周期 + 类型 + 来源 */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${lc.cls}`}>{lc.label}</span>
                  <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 ring-1 ring-indigo-200">{ktLabel}</span>
                  <span className="flex items-center gap-1 text-[11px] text-slate-500 min-w-0">
                    <FileText className="size-3 shrink-0" /><span className="truncate">{ext.doc_title || ext.doc_id}</span>
                  </span>
                  {!!ext.extracted_fields?.unit_no && (
                    <code className="text-[10px] text-slate-400">{String(ext.extracted_fields.unit_no)}</code>
                  )}
                  <span className="ml-auto flex items-center gap-1 text-[11px] text-slate-400">
                    <ListTree className="size-3" />{rules.length} 条
                  </span>
                </div>

                {/* 行 2：证据原文 */}
                <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-slate-50 p-2">
                  <Quote className="mt-0.5 size-3 shrink-0 text-slate-400" />
                  <p className="line-clamp-2 text-xs leading-relaxed text-slate-700">{evidence || '（无证据原文）'}</p>
                </div>

                {/* 行 3：溯源元数据 + 审核动作 */}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <span className={`flex items-center gap-1 text-[10px] ${confLow ? 'text-amber-600' : 'text-slate-400'}`}>
                    <Gauge className="size-3" />置信 {conf.toFixed(2)}
                  </span>
                  <span className="flex items-center gap-1 text-[10px] text-slate-400">
                    <Cpu className="size-3" />{(ext.extracted_fields?.extractor as any)?.name || 'policy_pipeline'}
                  </span>

                  <div className="ml-auto flex items-center gap-1.5">
                    <button onClick={() => setDetail(ext)} disabled={!!busy}
                      className="rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-40">详情</button>
                    {ext.status === 'draft' && (
                      <button onClick={() => approve(ext.extraction_id)} disabled={!!busy}
                        className="flex items-center gap-1 rounded bg-amber-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-amber-700 disabled:opacity-40">
                        {busy === ext.extraction_id ? <Loader2 className="size-3 animate-spin" /> : <CheckCircle2 className="size-3" />}通过
                      </button>
                    )}
                    {ext.status === 'reviewed' && (
                      <button onClick={() => publish(ext.extraction_id)} disabled={!!busy}
                        className="flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-emerald-700 disabled:opacity-40">
                        {busy === ext.extraction_id ? <Loader2 className="size-3 animate-spin" /> : <Send className="size-3" />}发布
                      </button>
                    )}
                    {(ext.status === 'draft' || ext.status === 'reviewed') && (
                      <button onClick={() => reject(ext.extraction_id)} disabled={!!busy}
                        className="flex items-center gap-1 rounded border border-red-200 px-2 py-1 text-[11px] text-red-600 hover:bg-red-50 disabled:opacity-40">
                        <XCircle className="size-3" />驳回
                      </button>
                    )}
                    {(ext.status === 'rejected' || ext.status === 'draft') && ext.doc_id && (
                      <button onClick={() => reextract(ext.doc_id)} disabled={!!busy}
                        className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-40">
                        <RefreshCw className="size-3" />重新抽取
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
            className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">上一页</button>
          <span className="text-xs text-slate-500">{page} / {pageCount}</span>
          <button disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}
            className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">下一页</button>
        </div>
      )}

      {detail && <AuditDetail ext={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}

// ── 审核详情抽屉：完整字段 + 字段级溯源 ──
function AuditDetail({ ext, onClose }: { ext: Extraction; onClose: () => void }) {
  const rules = (ext.extracted_fields?.rules as PolicyRule[]) || []
  const DETAIL: [string, string][] = [
    ['rule_type', '规则类型'], ['insu_type', '险种'], ['med_type', '医疗类别'],
    ['hosp_lv', '医院等级'], ['psn_type', '人群'], ['setl_type', '结算方式'],
    ['payment_ratio', '支付比例'], ['deductible_amount', '起付额'], ['cap_amount', '封顶额'],
    ['amount_band', '金额分段'], ['rule_value', '规则值'], ['time_period', '时间周期'],
  ]
  const lc = LIFECYCLE[ext.status] || { label: ext.status, cls: 'bg-slate-100 text-slate-600' }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm" onClick={onClose}>
      <div className="h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-100 bg-white px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">知识详情</h3>
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${lc.cls}`}>{lc.label}</span>
          <button onClick={onClose} className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none">×</button>
        </div>
        <div className="flex flex-col gap-3 p-5">
          {/* 证据 */}
          <section>
            <div className="flex items-center gap-1 text-[11px] font-medium uppercase text-slate-400"><Quote className="size-3" />证据原文</div>
            <p className="mt-1 rounded-lg border border-amber-100 bg-amber-50/40 p-3 text-sm leading-relaxed text-slate-800">
              {ext.source_text || ext.extracted_fields?.fact_text || '（无）'}
            </p>
          </section>
          {/* 溯源元数据 */}
          <section className="grid grid-cols-3 gap-2 rounded-lg bg-slate-50 p-3 text-center text-[11px]">
            <div><Gauge className="mx-auto mb-0.5 size-3.5 text-slate-400" /><div className="text-slate-400">置信度</div><div className="font-semibold text-slate-700">{(ext.confidence ?? 0).toFixed(2)}</div></div>
            <div><Cpu className="mx-auto mb-0.5 size-3.5 text-slate-400" /><div className="text-slate-400">提取器</div><div className="font-semibold text-slate-700 truncate">{(ext.extracted_fields?.extractor as any)?.name || 'pipeline'}</div></div>
            <div><FileText className="mx-auto mb-0.5 size-3.5 text-slate-400" /><div className="text-slate-400">来源文档</div><div className="truncate font-semibold text-slate-700">{ext.doc_title || ext.doc_id}</div></div>
          </section>
          {/* 结构化规则 */}
          {rules.map((r, i) => (
            <div key={i} className="rounded-lg border border-slate-100 p-3">
              <div className="mb-1.5 text-[11px] font-medium text-slate-500">规则 {i + 1}</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                {DETAIL.map(([k, label]) => {
                  const v = unwrap(r[k])
                  return v ? (
                    <div key={k}><div className="text-[10px] text-slate-400">{label}</div><div className="text-xs text-slate-700">{v}</div></div>
                  ) : null
                })}
              </div>
            </div>
          ))}
          <div className="rounded-lg bg-amber-50/40 p-2.5 text-[10px] text-amber-700">
            字段级溯源：详情字段以 {`{value, confidence, extracted_at}`} 包装（FieldTrace），此处显示 value。
          </div>
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// 子视图 2：检索（三模式 + 跨世界，自原 structured 移植）
// ════════════════════════════════════════════════════════════

type Mode = 'precise' | 'semantic' | 'hybrid'
type Target = 'policy' | 'database' | 'both'
interface Group { fact_id: string; fact_text: string; rules: PolicyRule[] }

const FILTER_FIELDS = [
  { key: 'insu_type', label: '险种' },
  { key: 'med_type', label: '医疗类别' },
  { key: 'hosp_lv', label: '医院等级' },
  { key: 'rule_type', label: '规则类型' },
  { key: 'psn_type', label: '人群' },
]

function RetrievalView() {
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
        body.metric_codes = metricCodes.split(',').map((s) => s.trim()).filter(Boolean)
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
              {(['precise', 'semantic', 'hybrid'] as Mode[]).map((m) => (
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
              {(['policy', 'database', 'both'] as Target[]).map((t) => (
                <button key={t} onClick={() => setTarget(t)}
                  className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition ${target === t ? 'bg-white text-emerald-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
                  {t === 'policy' ? '政策库' : t === 'database' ? '业务库' : '两者'}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[11px] text-slate-400">
              {target === 'policy' ? '查政策知识' : target === 'database' ? '经 source_field 查业务数据' : '政策知识 + 业务数据联查'}
            </p>
          </div>
        </div>

        {mode !== 'precise' && (
          <div className="mt-4">
            <label className="mb-1.5 block text-xs font-semibold text-slate-600">语义查询 (query)</label>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="如：城镇职工住院报销比例"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
          </div>
        )}

        {(mode === 'precise' || mode === 'hybrid') && (
          <div className="mt-4">
            <label className="mb-1.5 block text-xs font-semibold text-slate-600">核心维度过滤 (filters)</label>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              {FILTER_FIELDS.map((f) => (
                <input key={f.key} value={filters[f.key] || ''} onChange={(e) => setFilters((p) => ({ ...p, [f.key]: e.target.value }))}
                  placeholder={f.label}
                  className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none" />
              ))}
            </div>
          </div>
        )}

        {target !== 'policy' && (
          <div className="mt-4 rounded-lg bg-emerald-50/50 p-3">
            <label className="mb-1.5 block text-xs font-semibold text-emerald-700">跨世界：业务指标查询（语义拉齐）</label>
            <div className="grid gap-2 md:grid-cols-2">
              <input value={metricCodes} onChange={(e) => setMetricCodes(e.target.value)}
                placeholder="metric_codes（逗号分隔）"
                className="rounded-lg border border-emerald-200 bg-white px-3 py-1.5 text-xs focus:border-emerald-500 focus:outline-none" />
              <input value={contextDjh} onChange={(e) => setContextDjh(e.target.value)}
                placeholder="登记号 djh（业务库过滤键）"
                className="rounded-lg border border-emerald-200 bg-white px-3 py-1.5 text-xs focus:border-emerald-500 focus:outline-none" />
            </div>
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">top_k</label>
            <input type="number" value={topK} onChange={(e) => setTopK(Number(e.target.value) || 20)}
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
            <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">{result.total_groups} 个单元分组</span>
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
                  <div className="text-[11px] text-slate-400">单元 {g.fact_id}</div>
                  <div className="text-sm font-medium text-slate-700">{g.fact_text}</div>
                </div>
                <span className="ml-auto rounded bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">{g.rules.length} 条知识</span>
              </div>
              <div className="flex flex-col gap-2">
                {g.rules.map((r, j) => (
                  <div key={j} className="rounded-lg bg-slate-50 p-2.5">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      {r.rule_type && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-200">{unwrap(r.rule_type)}</span>}
                      {r.insu_type && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{unwrap(r.insu_type)}</span>}
                      {r.hosp_lv && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{unwrap(r.hosp_lv)}</span>}
                      {typeof r.score === 'number' && <span className="ml-auto text-[10px] text-amber-600">score: {r.score.toFixed(3)}</span>}
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 md:grid-cols-3">
                      {[['payment_ratio', '支付比例'], ['deductible_amount', '起付'], ['cap_amount', '封顶'], ['amount_band', '分段'], ['rule_value', '规则值']].map(([k, label]) => {
                        const val = unwrap(r[k])
                        return val ? (
                          <div key={k} className="text-xs"><span className="text-slate-400">{label}: </span><span className="font-medium text-slate-700">{val}</span></div>
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
              <FileText className="mx-auto mb-2 size-8 opacity-40" />无匹配知识。
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════
// 子视图 3：规则库（已发布知识浏览 + 字段级溯源，自原 structured 移植）
// ════════════════════════════════════════════════════════════

const RULE_LABELS: Record<string, string> = {
  rule_id: '知识ID', fact_id: '单元ID', source_text: '政策原文', doc_id: '来源文档',
  insu_type: '险种', med_type: '医疗类别', hosp_lv: '医院等级', psn_type: '人群',
  setl_type: '结算方式', payment_ratio: '支付比例', deductible_amount: '起付金额',
  cap_amount: '封顶金额', time_period: '时间周期', admission_order: '住院序次',
  amount_band: '金额区间', priority: '优先级', rule_type: '规则类型', rule_value: '规则值',
}
const DETAIL_FIELDS = Object.keys(RULE_LABELS)

function LibraryView() {
  const [rules, setRules] = useState<PolicyRule[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [ruleType, setRuleType] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<PolicyRule | null>(null)
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

  async function openDetail(r: PolicyRule) {
    setDetail(r); setDocTitle('')
    if (r.doc_id && r.doc_id !== 'None') {
      try {
        const res = await fetch(`${PIPELINE_API}/documents/${r.doc_id}`)
        if (res.ok) { const doc = await res.json(); setDocTitle(doc.title || r.doc_id) }
      } catch { /* ignore */ }
    }
  }

  const pageCount = Math.ceil(total / PAGE) || 1

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input value={keyword} onChange={(e) => { setKeyword(e.target.value); setPage(1) }} placeholder="关键词搜索知识/原文"
          className="w-48 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600" />
        <input value={ruleType} onChange={(e) => { setRuleType(e.target.value); setPage(1) }} placeholder="类型过滤"
          className="w-36 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600" />
        <span className="ml-auto text-xs text-slate-400">共 {total} 条已发布</span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
      ) : rules.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-400">
          规则库为空。先在「知识·审核」发布后再浏览。
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {rules.map((r) => (
            <button key={r.rule_id || Math.random()} onClick={() => openDetail(r)}
              className="text-left rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 shadow-sm transition hover:border-emerald-300 hover:shadow-md">
              <div className="flex items-center gap-2">
                {r.rule_type && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-blue-200">{unwrap(r.rule_type)}</span>}
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
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">上一页</button>
          <span className="text-xs text-slate-500">{page} / {pageCount}</span>
          <button disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)} className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">下一页</button>
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm" onClick={() => setDetail(null)}>
          <div className="h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-100 bg-white px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-800">知识详情</h3>
              <code className="text-[11px] text-slate-400">{detail.rule_id}</code>
              <button onClick={() => setDetail(null)} className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none"><X className="size-4" /></button>
            </div>
            <div className="flex flex-col gap-3 p-5">
              <div className="rounded-lg bg-slate-50 p-3 text-[11px]">
                <span className="text-slate-400">来源文档：</span><span className="text-slate-700">{docTitle || detail.doc_id || '—'}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {DETAIL_FIELDS.map((f) => {
                  const val = unwrap(detail[f])
                  if (!val || val === 'None') return null
                  return (
                    <div key={f}><div className="text-[10px] text-slate-400">{RULE_LABELS[f]}</div><div className="break-words text-xs text-slate-700">{val}</div></div>
                  )
                })}
              </div>
              <div className="rounded-lg bg-amber-50/40 p-2.5 text-[10px] text-amber-700">
                字段级溯源：数值/枚举字段以 {`{value, confidence, extracted_at}`} 包装（FieldTrace），此处显示 value。
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
