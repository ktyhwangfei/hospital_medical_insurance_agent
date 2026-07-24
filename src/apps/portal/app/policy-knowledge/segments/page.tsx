'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'next/navigation'
import { Layers, GitBranch, Network, Eye, Trash2, CheckCircle2, XCircle, Send, Loader2, Scissors } from 'lucide-react'

const API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

interface RuleEntity {
  name: string
  type: string
  highlight: string
}
interface RuleRelation {
  subject: string
  predicate: string
  object: string
}
interface PolicyRule {
  rule_type: string
  insu_type: string; med_type: string; hosp_lv: string; psn_type: string; setl_type: string
  payment_ratio: string; deductible_amount: string; cap_amount: string
  amount_band: string; admission_order: string; time_period: string
  priority: string; rule_value: string; confidence: number
  entities?: RuleEntity[]; relations?: RuleRelation[]
}
interface ExtractedFields {
  fact_text: string; rules: PolicyRule[]; total_rules: number
  [key: string]: unknown
}
interface Segment {
  extraction_id: string; doc_id: string; doc_title: string
  source_text: string; extracted_fields: ExtractedFields
  confidence: number; status: string
  reviewed_by: string; reviewed_at: string; created_at: string
}

const statusLabel: Record<string, string> = { draft: '草稿', reviewed: '已审核', rejected: '已驳回', published: '已入库' }
const statusColor: Record<string, string> = { draft: 'bg-slate-100 text-slate-600', reviewed: 'bg-blue-100 text-blue-700', rejected: 'bg-red-100 text-red-700', published: 'bg-emerald-100 text-emerald-700' }

const RULE_FIELD_LABELS: Record<string, string> = {
  rule_type: '规则类型', insu_type: '险种类型', med_type: '医疗类别', hosp_lv: '医院等级',
  psn_type: '人群标签', setl_type: '结算方式', payment_ratio: '支付比例', deductible_amount: '起付金额',
  cap_amount: '封顶金额', time_period: '时间周期', admission_order: '住院序次', amount_band: '金额区间',
  priority: '优先级', rule_value: '规则值',
}
const ENTITY_COLORS: Record<string, string> = {
  PERSON: 'bg-amber-100 text-amber-800 border-amber-300', ORG: 'bg-blue-100 text-blue-800 border-blue-300',
  SERVICE: 'bg-purple-100 text-purple-800 border-purple-300', AMOUNT: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  RATIO: 'bg-rose-100 text-rose-800 border-rose-300', DISEASE: 'bg-red-100 text-red-800 border-red-300',
  DRUG: 'bg-cyan-100 text-cyan-800 border-cyan-300', DATE: 'bg-slate-100 text-slate-700 border-slate-300',
  CONDITION: 'bg-orange-100 text-orange-800 border-orange-300', LOCATION: 'bg-teal-100 text-teal-800 border-teal-300',
}
const ENTITY_LABEL: Record<string, string> = {
  PERSON: '人员', ORG: '机构', SERVICE: '服务', AMOUNT: '金额', RATIO: '比例',
  DISEASE: '病种', DRUG: '药品', DATE: '日期', CONDITION: '条件', LOCATION: '地点',
}

function highlightEntities(text: string, entities: RuleEntity[] | undefined): string {
  if (!entities || entities.length === 0) return escapeHtml(text)
  const sorted = [...entities].sort((a, b) => (b.highlight || '').length - (a.highlight || '').length)
  let result = escapeHtml(text)
  for (const ent of sorted) {
    const hl = escapeHtml(ent.highlight || ent.name || '')
    if (!hl) continue
    const escaped = escapeHtmlForRegex(hl)
    const colorClass = ENTITY_COLORS[ent.type] || 'bg-gray-100 text-gray-700 border-gray-300'
    result = result.replace(
      new RegExp(escaped, 'g'),
      `<mark class="inline rounded px-0.5 border ${colorClass} text-xs font-medium cursor-help" title="${escapeHtml(ent.type)}: ${escapeHtml(ent.name)}">${hl}</mark>`
    )
  }
  return result
}
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
function escapeHtmlForRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export default function PolicySegmentsPage() {
  const searchParams = useSearchParams()
  const [segments, setSegments] = useState<Segment[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const PAGE = 20

  const [detail, setDetail] = useState<Segment | null>(null)
  const [expandedRules, setExpandedRules] = useState<Record<number, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)

  const docId = searchParams.get('doc_id') || ''

  const fetchSegments = useCallback(async () => {
    setLoading(true)
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(PAGE) })
      if (docId) p.set('doc_id', docId)
      if (status) p.set('status', status)
      const r = await fetch(`${API}/extractions?${p}`)
      const d = await r.json()
      setSegments(d.items || [])
      setTotal(d.total || 0)
    } catch { setError('加载失败') }
    finally { setLoading(false) }
  }, [page, status, docId])

  useEffect(() => { fetchSegments() }, [fetchSegments])

  function openDetail(seg: Segment) { setDetail(seg); setExpandedRules({}) }

  const allEntityTypes = useMemo(() => {
    if (!detail) return []
    const types = new Set<string>()
    for (const rule of (detail.extracted_fields?.rules || [])) {
      for (const ent of (rule.entities || [])) types.add(ent.type)
    }
    return Array.from(types)
  }, [detail])

  async function handleApprove() {
    if (!detail) return; setSaving(true)
    try {
      const r = await fetch(`${API}/extractions/${detail.extraction_id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'reviewed' }),
      })
      setDetail(await r.json()); fetchSegments()
    } catch { setError('审核失败') }
    finally { setSaving(false) }
  }
  async function handleReject() {
    if (!detail) return; setSaving(true)
    try {
      await fetch(`${API}/extractions/${detail.extraction_id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'rejected' }),
      })
      setDetail(null); fetchSegments()
    } catch { setError('驳回失败') }
    finally { setSaving(false) }
  }
  async function handlePublish() {
    if (!detail) return
    if (!confirm('确认将此片段及其所有规则发布到规则库？')) return
    setPublishing(true)
    try {
      const r = await fetch(`${API}/extractions/${detail.extraction_id}/publish`, { method: 'POST' })
      const d = await r.json()
      if (d.success) {
        alert(`入库成功！发布了 ${d.published_count || d.rule_ids?.length || 0} 条规则`)
        setDetail(null); fetchSegments()
      } else setError(d.error || '入库失败')
    } catch { setError('入库请求失败') }
    finally { setPublishing(false) }
  }
  async function handleDelete(extId: string) {
    if (!confirm('确认删除该片段？')) return
    try { await fetch(`${API}/extractions/${extId}`, { method: 'DELETE' }); fetchSegments() }
    catch { setError('删除失败') }
  }

  const rules = detail?.extracted_fields?.rules || []

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">Step 2</span>
          {docId && <span className="text-xs text-slate-400">筛选自: {docId}</span>}
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">政策片段</h2>
        <p className="text-xs text-slate-500 mt-0.5">从政策原文中提取的独立片段，每个片段包含多条规则及实体关系标注</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select className="bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-xs text-slate-600" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="reviewed">已审核</option>
          <option value="rejected">已驳回</option>
          <option value="published">已入库</option>
        </select>
        <span className="text-xs text-slate-400 ml-auto">共 {total} 条片段</span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead><tr className="bg-slate-50/95 border-b border-slate-200">
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">政策片段</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[100px]">规则</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[60px]">置信度</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[70px]">状态</th>
            <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-slate-500 uppercase w-[200px]">操作</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-16 text-center"><Loader2 className="size-5 text-blue-500 animate-spin mx-auto" /></td></tr>
            ) : segments.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-16 text-center text-sm text-slate-400">
                {docId ? '该文档暂无片段' : '暂无片段，请先在政策原文页面对文档执行提取'}
              </td></tr>
            ) : segments.map(seg => {
              const ef = seg.extracted_fields || {} as ExtractedFields
              const rulesArr = ef.rules || []
              const isNew = !ef.fact_text || ef.fact_text === seg.source_text
              return (
              <tr key={seg.extraction_id} className="hover:bg-blue-50/20 transition-colors cursor-pointer" onClick={() => openDetail(seg)}>
                <td className="px-4 py-3 text-xs text-slate-700 max-w-[380px] truncate">{ef.fact_text || seg.source_text}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {isNew ? (
                      <span className="inline-flex rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 ring-1 ring-blue-200">
                        {(ef as Record<string,string>).rule_type || '通用规则'}
                      </span>
                    ) : (
                      rulesArr.slice(0, 3).map((r, i) => (
                        <span key={i} className="inline-flex rounded-md bg-purple-50 px-1.5 py-0.5 text-[10px] font-medium text-purple-700 ring-1 ring-purple-200">{r.rule_type || '规则'}</span>
                      ))
                    )}
                    {!isNew && rulesArr.length > 3 && <span className="text-[10px] text-slate-400">+{rulesArr.length - 3}</span>}
                  </div>
                  {!isNew && <div className="text-[10px] text-slate-400 mt-0.5">{rulesArr.length} 条规则</div>}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{(seg.confidence * 100).toFixed(0)}%</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${statusColor[seg.status] || 'bg-slate-100 text-slate-500'}`}>{statusLabel[seg.status] || seg.status}</span>
                </td>
                <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => openDetail(seg)} className="rounded px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-100"><Eye className="size-3.5" /></button>
                    {seg.status === 'reviewed' && (
                      <button onClick={() => { setDetail(seg); handlePublish() }} className="rounded px-2 py-0.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50"><Send className="size-3.5" /></button>
                    )}
                    <button onClick={() => handleDelete(seg.extraction_id)} className="rounded px-2 py-0.5 text-xs font-medium text-rose-600 hover:bg-rose-50"><Trash2 className="size-3.5" /></button>
                  </div>
                </td>
              </tr>
            )})}
          </tbody>
        </table>
        {total > PAGE && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 bg-slate-50/50">
            <span className="text-xs text-slate-500">共 {total} 条 · 第 {page}/{Math.ceil(total / PAGE)} 页</span>
            <div className="flex gap-1">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">上一页</button>
              <button disabled={page * PAGE >= total} onClick={() => setPage(p => p + 1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">下一页</button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm px-4" onClick={() => setDetail(null)}>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-white/95 backdrop-blur rounded-t-2xl">
              <div className="flex items-center gap-3">
                <span className={`inline-flex h-7 items-center rounded-full px-2.5 text-xs font-semibold ring-1 ${detail.status === 'reviewed' ? 'bg-blue-50 text-blue-700 ring-blue-200' : detail.status === 'published' ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-amber-50 text-amber-700 ring-amber-200'}`}>{statusLabel[detail.status]}</span>
                <code className="text-xs font-mono text-slate-400">{detail.extraction_id}</code>
                <span className="text-xs text-slate-400">· {rules.length} 条规则 · {rules.reduce((s, r) => s + (r.entities?.length || 0), 0)} 个实体</span>
              </div>
              <button onClick={() => setDetail(null)} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100">
                <svg className="size-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="p-6 space-y-6">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Scissors className="size-4 text-blue-500" />
                  <label className="text-[11px] font-semibold text-slate-500 uppercase">政策片段</label>
                  <span className="text-[10px] text-slate-400">来源: {detail.doc_title}</span>
                </div>
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-sm text-slate-700 leading-relaxed"
                  dangerouslySetInnerHTML={{ __html: highlightEntities(detail.extracted_fields?.fact_text || detail.source_text, rules.flatMap(r => r.entities || [])) }} />
              </div>
              {allEntityTypes.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] text-slate-400">实体类型:</span>
                  {allEntityTypes.map(t => <span key={t} className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium border ${ENTITY_COLORS[t] || 'bg-slate-100 text-slate-500 border-slate-300'}`}>{ENTITY_LABEL[t] || t}</span>)}
                </div>
              )}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <GitBranch className="size-4 text-purple-500" />
                  <label className="text-[11px] font-semibold text-slate-500 uppercase">提取的规则 ({rules.length})</label>
                </div>
                <div className="space-y-3">
                  {rules.map((rule, ri) => {
                    const expanded = expandedRules[ri]
                    const filledFields = Object.entries(RULE_FIELD_LABELS).filter(([k]) => rule[k as keyof PolicyRule])
                    return (
                      <div key={ri} className="border border-slate-200 rounded-lg overflow-hidden">
                        <button className="w-full flex items-center justify-between px-4 py-2.5 bg-slate-50/95 hover:bg-slate-100 transition-colors text-left"
                          onClick={() => setExpandedRules(e => ({ ...e, [ri]: !e[ri] }))}>
                          <div className="flex items-center gap-2">
                            <span className="inline-flex rounded-md bg-purple-100 px-2 py-0.5 text-[11px] font-semibold text-purple-700 ring-1 ring-purple-200">{rule.rule_type || '规则'}</span>
                            <span className="text-xs text-slate-500">{filledFields.slice(0, 3).map(([k]) => RULE_FIELD_LABELS[k]).join(' · ')}{filledFields.length > 3 && ` +${filledFields.length - 3}`}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] text-slate-400">置信度 {(rule.confidence * 100).toFixed(0)}%</span>
                            <svg className={`size-4 text-slate-400 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                          </div>
                        </button>
                        {expanded && (
                          <div className="px-4 py-3 space-y-3 border-t border-slate-100">
                            <div className="grid grid-cols-3 gap-2">
                              {Object.entries(RULE_FIELD_LABELS).map(([key, label]) => {
                                const val = rule[key as keyof PolicyRule]
                                if (!val) return null
                                return <div key={key}><span className="text-[10px] text-slate-400">{label}</span><div className="text-xs font-mono text-slate-700">{String(val)}</div></div>
                              })}
                            </div>
                            {(rule.entities && rule.entities.length > 0) && (
                              <div>
                                <div className="flex items-center gap-1.5 mb-1.5"><Network className="size-3 text-amber-500" /><span className="text-[10px] font-medium text-slate-500">实体 ({rule.entities.length})</span></div>
                                <div className="flex flex-wrap gap-1">
                                  {rule.entities.map((ent, ei) => (
                                    <span key={ei} className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium border ${ENTITY_COLORS[ent.type] || 'bg-slate-100 text-slate-500 border-slate-300'}`}>
                                      <span className="text-[9px] opacity-70">{ENTITY_LABEL[ent.type] || ent.type}</span>{ent.name}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                            {(rule.relations && rule.relations.length > 0) && (
                              <div>
                                <div className="flex items-center gap-1.5 mb-1.5"><GitBranch className="size-3 text-indigo-500" /><span className="text-[10px] font-medium text-slate-500">关系 ({rule.relations.length})</span></div>
                                <div className="flex flex-wrap gap-1.5">
                                  {rule.relations.map((rel, rei) => (
                                    <span key={rei} className="inline-flex items-center gap-1 rounded-md bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 text-[10px]">
                                      <span className="font-medium text-indigo-700">{rel.subject}</span><span className="text-indigo-400">→</span><span className="text-indigo-500 font-medium">{rel.predicate}</span><span className="text-indigo-400">→</span><span className="font-medium text-indigo-700">{rel.object}</span>
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs text-slate-500 border-t border-slate-100 pt-4">
                <div>置信度: <span className="font-mono text-slate-700">{(detail.confidence * 100).toFixed(0)}%</span></div>
                <div>来源文档: <span className="text-slate-700">{detail.doc_title}</span></div>
                <div>创建时间: <span className="text-slate-700">{detail.created_at?.slice(0, 10)}</span></div>
              </div>
            </div>
            {detail.status !== 'published' && (
              <div className="sticky bottom-0 flex justify-between px-6 py-4 border-t border-slate-100 bg-white/95">
                <div className="flex gap-2">
                  {detail.status === 'draft' && (<>
                    <button onClick={handleReject} className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50"><XCircle className="size-3.5" /> 驳回</button>
                    <button onClick={handleApprove} className="flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white hover:bg-[#1d4ed8]"><CheckCircle2 className="size-3.5" /> 审核通过</button>
                  </>)}
                  {detail.status === 'reviewed' && (
                    <button onClick={handlePublish} disabled={publishing} className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                      {publishing ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}发布全部 {rules.length} 条规则
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
