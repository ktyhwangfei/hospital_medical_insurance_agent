'use client'

// P9.4 事实 tab —— 原文→最小事实拆分 + 向量化管理。
// 每条提取记录 = 一个政策事实（fact_text + rules）。聚焦「事实拆分」与「向量化入库」，
// 非富版两步机械（构成化细节见结构化 tab）。后端：policy-pipeline/extractions + publish-v2。
// [来源: docs/steering/政策知识管线开发计划.md Phase 9.4]

import { useState, useEffect, useCallback, useMemo, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import {
  Boxes, CheckCircle2, XCircle, Loader2, Send,
  ArrowRight, FileText, Zap,
} from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

interface PolicyRule {
  rule_type: string
  insu_type: string
  med_type: string
  hosp_lv: string
  psn_type: string
  setl_type: string
  payment_ratio: string
  deductible_amount: string
  cap_amount: string
  amount_band: string
  admission_order: string
  time_period: string
  priority: string
  rule_value: string
  source_text?: string
  confidence: number
  [key: string]: unknown
}

interface ExtractedFields {
  fact_text: string
  rules: PolicyRule[]
  total_rules: number
  [key: string]: unknown
}

interface Extraction {
  extraction_id: string
  doc_id: string
  doc_title: string
  source_text: string
  extracted_fields: ExtractedFields
  confidence: number
  status: string  // draft | reviewed | rejected | published
  reviewed_by: string
  reviewed_at: string
  created_at: string
}

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  draft:     { label: '草稿',   cls: 'bg-slate-100 text-slate-600' },
  reviewed:  { label: '已审核', cls: 'bg-blue-100 text-blue-700' },
  rejected:  { label: '已驳回', cls: 'bg-red-100 text-red-700' },
  published: { label: '已向量化', cls: 'bg-emerald-100 text-emerald-700' },
}

const RULE_KEY_LABELS: [string, string][] = [
  ['rule_type', '规则类型'],
  ['insu_type', '险种'],
  ['med_type', '医疗类别'],
  ['hosp_lv', '医院等级'],
  ['psn_type', '人群'],
  ['setl_type', '结算方式'],
  ['payment_ratio', '支付比例'],
  ['deductible_amount', '起付额'],
  ['cap_amount', '封顶额'],
  ['amount_band', '金额分段'],
  ['time_period', '时间周期'],
  ['priority', '优先级'],
  ['rule_value', '规则值'],
]

function extractRules(f?: ExtractedFields): PolicyRule[] {
  if (!f) return []
  const r = (f.rules as PolicyRule[] | undefined) || []
  return Array.isArray(r) ? r : []
}

export default function FactsPage() {
  // useSearchParams 需 Suspense 边界（Next 16 静态生成要求）。
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>}>
      <FactsContent />
    </Suspense>
  )
}

function FactsContent() {
  const params = useSearchParams()
  const [extractions, setExtractions] = useState<Extraction[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const PAGE = 20

  const [detail, setDetail] = useState<Extraction | null>(null)
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)

  const docId = params.get('doc_id') || ''

  const fetchExtractions = useCallback(async () => {
    setLoading(true)
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(PAGE) })
      if (docId) p.set('doc_id', docId)
      if (status) p.set('status', status)
      const r = await fetch(`${API}/extractions?${p}`)
      const d = await r.json()
      setExtractions(d.items || [])
      setTotal(d.total || 0)
    } catch {
      setError('加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, status, docId])

  useEffect(() => { fetchExtractions() }, [fetchExtractions])

  async function openDetail(ext: Extraction) {
    setError('')
    setDetail(ext)
  }

  async function refreshDetail(extId: string) {
    try {
      const r = await fetch(`${API}/extractions/${extId}`)
      if (r.ok) setDetail(await r.json())
    } catch { /* ignore */ }
  }

  async function handleApprove() {
    if (!detail) return
    setSaving(true)
    try {
      await fetch(`${API}/extractions/${detail.extraction_id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'reviewed' }),
      })
      await refreshDetail(detail.extraction_id)
      fetchExtractions()
    } catch { setError('审核失败') }
    finally { setSaving(false) }
  }

  async function handleReject() {
    if (!detail) return
    if (!confirm('驳回该事实？')) return
    setSaving(true)
    try {
      await fetch(`${API}/extractions/${detail.extraction_id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'rejected' }),
      })
      setDetail(null)
      fetchExtractions()
    } catch { setError('驳回失败') }
    finally { setSaving(false) }
  }

  // 向量化入库：发布到 policy_facts + policy_rules_v2（字段级溯源 + 向量复用）。
  async function handleVectorize() {
    if (!detail) return
    if (!confirm('确认向量化入库到 policy_facts + policy_rules_v2？')) return
    setPublishing(true)
    try {
      const r = await fetch(`${API}/extractions/${detail.extraction_id}/publish-v2`, { method: 'POST' })
      const d = await r.json()
      if (d.success) {
        alert(`向量化入库成功：policy_facts + policy_rules_v2（${d.published_count ?? 0} 条规则）`)
        await refreshDetail(detail.extraction_id)
        fetchExtractions()
      } else {
        setError(d.error || '向量化入库失败')
      }
    } catch { setError('入库请求失败') }
    finally { setPublishing(false) }
  }

  const rules = useMemo(() => extractRules(detail?.extracted_fields), [detail])
  const factText = detail?.extracted_fields?.fact_text || detail?.source_text || ''
  const pageCount = Math.ceil(total / PAGE) || 1

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            事实拆分
          </span>
          {docId && <span className="text-xs text-slate-400">筛选自: {docId}</span>}
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">事实</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          每条记录 = 一个政策事实（fact_text + 结构化规则）。审核后向量化入库到 policy_facts + policy_rules_v2。
        </p>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-xs text-slate-600"
          value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}
        >
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="reviewed">已审核</option>
          <option value="rejected">已驳回</option>
          <option value="published">已向量化</option>
        </select>
        <span className="text-xs text-slate-400 ml-auto">共 {total} 条</span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>
      )}

      {/* List */}
      {loading ? (
        <div className="flex items-center justify-center py-16"><Loader2 className="size-5 animate-spin text-slate-400" /></div>
      ) : extractions.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-16 text-center text-sm text-slate-400">
          暂无事实。先在「政策」tab 上传原文并触发提取。
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {extractions.map(ext => {
            const st = STATUS_LABEL[ext.status] || { label: ext.status, cls: 'bg-slate-100 text-slate-600' }
            const ruleCount = (ext.extracted_fields?.rules?.length) || 0
            const ft = ext.extracted_fields?.fact_text || ext.source_text || ''
            return (
              <button key={ext.extraction_id} onClick={() => openDetail(ext)}
                className="text-left rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm transition-all hover:border-purple-300 hover:shadow-md">
                <div className="flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${st.cls}`}>{st.label}</span>
                  <span className="flex items-center gap-1 text-[11px] text-slate-500">
                    <FileText className="size-3" />{ext.doc_title || ext.doc_id}
                  </span>
                  <span className="ml-auto flex items-center gap-1 text-[11px] text-slate-500">
                    <Boxes className="size-3" />{ruleCount} 规则
                  </span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-slate-700">{ft || '（无事实文本）'}</p>
                {ruleCount > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {extractRules(ext.extracted_fields).slice(0, 3).map((r, i) => (
                      <span key={i} className="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
                        {r.rule_type || '规则'}
                      </span>
                    ))}
                    {ruleCount > 3 && <span className="text-[10px] text-slate-400">+{ruleCount - 3}</span>}
                  </div>
                )}
              </button>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
            className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">上一页</button>
          <span className="text-xs text-slate-500">{page} / {pageCount}</span>
          <button disabled={page >= pageCount} onClick={() => setPage(p => p + 1)}
            className="rounded border border-slate-200 px-2.5 py-1 text-xs text-slate-600 disabled:opacity-40">下一页</button>
        </div>
      )}

      {/* Detail Drawer */}
      {detail && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm" onClick={() => setDetail(null)}>
          <div className="h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-100 bg-white px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-800">事实详情</h3>
              <span className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${(STATUS_LABEL[detail.status] || { cls: '' }).cls}`}>
                {(STATUS_LABEL[detail.status] || { label: detail.status }).label}
              </span>
              <button onClick={() => setDetail(null)} className="ml-auto text-slate-400 hover:text-slate-600 text-xl leading-none">×</button>
            </div>

            <div className="flex flex-col gap-4 p-5">
              {/* 事实文本 */}
              <section>
                <div className="text-[11px] font-medium uppercase text-slate-400">事实文本</div>
                <p className="mt-1 rounded-lg border border-purple-100 bg-purple-50/40 p-3 text-sm leading-relaxed text-slate-800">
                  {factText || '（无）'}
                </p>
                <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-400">
                  <Link href={`/policy-knowledge/documents`} className="hover:text-slate-600">{detail.doc_title || detail.doc_id}</Link>
                  <span>· 置信度 {(detail.confidence * 100).toFixed(0)}%</span>
                </div>
              </section>

              {/* 结构化规则 */}
              <section>
                <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase text-slate-400">
                  <Boxes className="size-3.5" /> 结构化规则 ({rules.length})
                </div>
                {rules.length === 0 ? (
                  <div className="text-xs text-slate-400">无规则（仅事实文本）。</div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {rules.map((r, i) => (
                      <div key={i} className="rounded-lg border border-slate-100 p-2.5">
                        <div className="mb-1 text-xs font-medium text-slate-700">{r.rule_type || '（未分类规则）'}</div>
                        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                          {RULE_KEY_LABELS.filter(([k]) => r[k] && String(r[k]) !== '').map(([k, label]) => (
                            <div key={k}>
                              <span className="text-slate-400">{label}：</span>
                              <span className="text-slate-700">{String(r[k])}</span>
                            </div>
                          ))}
                        </div>
                        {typeof r.confidence === 'number' && (
                          <div className="mt-1 text-[10px] text-slate-400">置信度 {(r.confidence * 100).toFixed(0)}%</div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <Link href={`/policy-knowledge/structured`} className="mt-2 inline-flex items-center gap-1 text-xs text-emerald-600 hover:text-emerald-700">
                  结构化检索 → <ArrowRight className="size-3" />
                </Link>
              </section>

              {/* Actions（向量化管理）*/}
              <section className="sticky bottom-0 flex flex-wrap gap-2 border-t border-slate-100 bg-white pt-3">
                {detail.status === 'draft' && (
                  <button onClick={handleApprove} disabled={saving}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                    {saving ? <Loader2 className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
                    审核通过
                  </button>
                )}
                {detail.status !== 'rejected' && (
                  <button onClick={handleReject} disabled={saving}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                    <XCircle className="size-3.5" /> 驳回
                  </button>
                )}
                <button onClick={handleVectorize} disabled={publishing || detail.status === 'published'}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                  {publishing ? <Loader2 className="size-3.5 animate-spin" /> : <Zap className="size-3.5" />}
                  {detail.status === 'published' ? '已向量化' : '向量化入库'}
                </button>
              </section>

              {detail.status === 'published' && (
                <div className="flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-[11px] text-emerald-700">
                  <Send className="size-3.5" /> 已向量化入库至 policy_facts + policy_rules_v2（字段级溯源 + 向量复用）。
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}