'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import { Search, Eye, Trash2, CheckCircle2, XCircle, Send, Loader2, Layers, GitBranch, Network, Scissors, Boxes, FileText, ArrowRight } from 'lucide-react'

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
  entities?: RuleEntity[]
  relations?: RuleRelation[]
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
  status: string
  reviewed_by: string
  reviewed_at: string
  created_at: string
}

/** 事实单元（用于 Step 1 列表/高亮） */
interface FactUnit {
  id: string
  text: string
  rulesCount: number
}

const statusLabel: Record<string, string> = {
  draft: '草稿',
  reviewed: '已审核',
  rejected: '已驳回',
  published: '已入库',
}
const statusColor: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-600',
  reviewed: 'bg-blue-100 text-blue-700',
  rejected: 'bg-red-100 text-red-700',
  published: 'bg-emerald-100 text-emerald-700',
}

const ENTITY_COLORS: Record<string, string> = {
  PERSON: 'bg-amber-100 text-amber-800 border-amber-300',
  ORG: 'bg-blue-100 text-blue-800 border-blue-300',
  SERVICE: 'bg-purple-100 text-purple-800 border-purple-300',
  AMOUNT: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  RATIO: 'bg-rose-100 text-rose-800 border-rose-300',
  DISEASE: 'bg-red-100 text-red-800 border-red-300',
  DRUG: 'bg-cyan-100 text-cyan-800 border-cyan-300',
  DATE: 'bg-slate-100 text-slate-700 border-slate-300',
  CONDITION: 'bg-orange-100 text-orange-800 border-orange-300',
  LOCATION: 'bg-teal-100 text-teal-800 border-teal-300',
}
const ENTITY_LABEL: Record<string, string> = {
  PERSON: '人员', ORG: '机构', SERVICE: '服务', AMOUNT: '金额',
  RATIO: '比例', DISEASE: '病种', DRUG: '药品', DATE: '日期',
  CONDITION: '条件', LOCATION: '地点',
}

/**
 * 结构化字段分组 — 严格对齐 raw/数据模型1.xlsx「政策规则表」。
 * 系统生成字段（rule_id / fact_id / policy_id / clause_id）不展示。
 */
const FIELD_GROUPS: { title: string; tone: string; fields: { key: string; label: string }[] }[] = [
  {
    title: '溯源信息', tone: 'text-slate-500',
    fields: [{ key: 'source_text', label: '原始政策文本' }],
  },
  {
    title: '适用条件', tone: 'text-blue-500',
    fields: [
      { key: 'insu_type', label: '险种类别' },
      { key: 'med_type', label: '医疗类别' },
      { key: 'hosp_lv', label: '医疗机构等级' },
      { key: 'psn_type', label: '人群标签' },
      { key: 'setl_type', label: '结算方式' },
      { key: 'time_period', label: '时间周期' },
      { key: 'admission_order', label: '住院次数' },
    ],
  },
  {
    title: '待遇数值', tone: 'text-emerald-500',
    fields: [
      { key: 'payment_ratio', label: '支付比例' },
      { key: 'deductible_amount', label: '起付金额' },
      { key: 'cap_amount', label: '封顶金额' },
      { key: 'amount_band', label: '金额分段' },
    ],
  },
  {
    title: '规则定义', tone: 'text-purple-500',
    fields: [
      { key: 'rule_type', label: '规则类型' },
      { key: 'rule_value', label: '规则值' },
      { key: 'priority', label: '规则优先级' },
    ],
  },
]

/** 数值型字段 → 实体类型映射（用于 Step 2 把提取值回填到原文高亮） */
const VALUE_HIGHLIGHT_FIELDS: { key: string; type: string }[] = [
  { key: 'payment_ratio', type: 'RATIO' },
  { key: 'deductible_amount', type: 'AMOUNT' },
  { key: 'cap_amount', type: 'AMOUNT' },
  { key: 'amount_band', type: 'AMOUNT' },
]

/** 从提取字段中派生规则列表（兼容新旧格式）。 */
function extractRules(ef: ExtractedFields | undefined): PolicyRule[] {
  if (!ef) return []
  if (ef.rules && ef.rules.length) return ef.rules
  // 旧格式：扁平字段作为单条规则
  if (ef.rule_type || ef.insu_type || ef.rule_value || ef.payment_ratio) {
    return [ef as unknown as PolicyRule]
  }
  return []
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}
function escapeHtmlForRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 在文本中高亮实体（按 highlight 长度降序避免短词破坏长词）。 */
function highlightEntities(text: string, entities: RuleEntity[] | undefined): string {
  if (!entities || entities.length === 0) return escapeHtml(text)
  const seen = new Set<string>()
  const sorted = [...entities]
    .filter(e => { const h = e.highlight || e.name; if (!h || seen.has(h)) return false; seen.add(h); return true })
    .sort((a, b) => (b.highlight || b.name || '').length - (a.highlight || a.name || '').length)
  let result = escapeHtml(text)
  for (const ent of sorted) {
    const hl = escapeHtml(ent.highlight || ent.name || '')
    if (!hl) continue
    const escaped = escapeHtmlForRegex(hl)
    const colorClass = ENTITY_COLORS[ent.type] || 'bg-gray-100 text-gray-700 border-gray-300'
    const label = ENTITY_LABEL[ent.type] || ent.type
    result = result.replace(
      new RegExp(escaped, 'g'),
      `<mark class="inline rounded px-0.5 border ${colorClass} text-xs font-medium cursor-help" title="${escapeHtml(label)}: ${escapeHtml(ent.name)}">${hl}</mark>`
    )
  }
  return result
}

/** 在 nc 中查找首个未被占用区间的子串位置。 */
function firstFree(nc: string, sub: string, used: boolean[]): { idx: number; len: number } {
  let from = 0
  while (from < nc.length) {
    const idx = nc.indexOf(sub, from)
    if (idx < 0) return { idx: -1, len: 0 }
    if (!used.slice(idx, idx + sub.length).some(Boolean)) return { idx, len: sub.length }
    from = idx + 1
  }
  return { idx: -1, len: 0 }
}

/** 最长子串兜底：容忍首尾标记差异（如全角「（一）」）与尾部截断。 */
function longestFreeSubstring(nc: string, nn: string, used: boolean[], minLen: number) {
  const maxLen = Math.min(nn.length, 30)
  for (let L = maxLen; L >= minLen; L--) {
    for (let s = 0; s + L <= nn.length; s++) {
      const hit = firstFree(nc, nn.slice(s, s + L), used)
      if (hit.idx >= 0) return hit
    }
  }
  return { idx: -1, len: 0 }
}

/** 计算每个「最小事实单元」在原文中的区间（去空白归一化匹配）。 */
function locateFactUnits(content: string, units: FactUnit[]): { start: number; end: number; id: string }[] {
  if (!content) return []
  const normChars: string[] = []
  const origIndex: number[] = []
  for (let i = 0; i < content.length; i++) {
    if (!/\s/.test(content[i])) {
      normChars.push(content[i])
      origIndex.push(i)
    }
  }
  const nc = normChars.join('')
  const used = new Array(nc.length).fill(false)
  const ranges: { start: number; end: number; id: string }[] = []
  for (const u of units) {
    const nn = u.text.replace(/\s+/g, '')
    if (!nn) continue
    let hit = firstFree(nc, nn, used)
    if (hit.idx < 0) hit = longestFreeSubstring(nc, nn, used, 6)
    if (hit.idx < 0) continue
    for (let k = hit.idx; k < hit.idx + hit.len; k++) used[k] = true
    ranges.push({ start: origIndex[hit.idx], end: origIndex[hit.idx + hit.len - 1] + 1, id: u.id })
  }
  return ranges
}

/** 将区间渲染为高亮 HTML，当前单元用琥珀色强调。 */
function renderRanges(content: string, ranges: { start: number; end: number; id: string }[], currentId: string): string {
  if (!content) return ''
  const sorted = [...ranges].sort((a, b) => a.start - b.start)
  let html = ''
  let pos = 0
  for (const r of sorted) {
    html += escapeHtml(content.slice(pos, r.start))
    html += r.id === currentId
      ? `<mark data-current="1" class="rounded bg-amber-200/90 border border-amber-400 ring-1 ring-amber-300 px-0.5 font-medium">${escapeHtml(content.slice(r.start, r.end))}</mark>`
      : `<mark class="rounded bg-blue-100/60 border border-blue-200 px-0.5">${escapeHtml(content.slice(r.start, r.end))}</mark>`
    pos = r.end
  }
  html += escapeHtml(content.slice(pos))
  return html
}

export default function PolicyExtractionsPage() {
  const searchParams = useSearchParams()
  const [extractions, setExtractions] = useState<Extraction[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const PAGE = 20

  // Detail modal
  const [detail, setDetail] = useState<Extraction | null>(null)
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)

  // 两步流程状态
  const [step, setStep] = useState<1 | 2>(1)
  const [docContent, setDocContent] = useState('')
  const [siblingUnits, setSiblingUnits] = useState<FactUnit[]>([])
  const [loadingDoc, setLoadingDoc] = useState(false)
  const docViewRef = useRef<HTMLDivElement>(null)

  const docId = searchParams.get('doc_id') || ''

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

  /** 打开提取详情：进入 Step 1，并加载所属文档原文 + 同文档全部事实单元 */
  async function openDetail(ext: Extraction) {
    setDetail(ext)
    setStep(1)
    setError('')
    setLoadingDoc(true)
    try {
      const [docRes, sibRes] = await Promise.all([
        fetch(`${API}/documents/${ext.doc_id}`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/extractions?doc_id=${ext.doc_id}&page=1&page_size=100`).then(r => r.ok ? r.json() : null).catch(() => null),
      ])
      setDocContent(docRes?.content_text || '')
      const items: Extraction[] = sibRes?.items || []
      setSiblingUnits(items.map(it => ({
        id: it.extraction_id,
        text: it.extracted_fields?.fact_text || it.source_text || '',
        rulesCount: extractRules(it.extracted_fields).length,
      })))
    } finally {
      setLoadingDoc(false)
    }
  }

  /** Step 1 列表中点击其它事实单元：切换当前查看对象（同一文档，原文/单元列表不变） */
  async function openSibling(extId: string) {
    try {
      const r = await fetch(`${API}/extractions/${extId}`)
      if (!r.ok) return
      const ext = await r.json()
      setDetail(ext)
    } catch { setError('切换事实单元失败') }
  }

  // 打开后自动滚动到当前事实单元
  useEffect(() => {
    if (step !== 1 || loadingDoc) return
    const t = setTimeout(() => {
      const el = docViewRef.current?.querySelector('mark[data-current="1"]') as HTMLElement | null
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }, 60)
    return () => clearTimeout(t)
  }, [step, loadingDoc, detail?.extraction_id])

  const rules = useMemo(() => extractRules(detail?.extracted_fields), [detail])
  const factText = detail?.extracted_fields?.fact_text || detail?.source_text || ''

  // Step 1 · 文档原文中各事实单元的定位区间（仅在原文/单元列表变化时重算）
  const factRanges = useMemo(() => locateFactUnits(docContent, siblingUnits), [docContent, siblingUnits])
  const docHtml = useMemo(
    () => renderRanges(docContent, factRanges, detail?.extraction_id || ''),
    [docContent, factRanges, detail?.extraction_id],
  )

  // 所有实体类型（图例）
  const allEntityTypes = useMemo(() => {
    const types = new Set<string>()
    for (const rule of rules) for (const ent of (rule.entities || [])) types.add(ent.type)
    return Array.from(types)
  }, [rules])

  // Step 2 原文高亮：真实实体 + 数值型字段值（回填到原文，体现「提取结果」）
  const structureHighlights = useMemo(() => {
    const list: RuleEntity[] = []
    for (const rule of rules) {
      if (rule.entities) list.push(...rule.entities)
      for (const { key, type } of VALUE_HIGHLIGHT_FIELDS) {
        const v = String((rule as Record<string, unknown>)[key] || '')
        if (v && v.length <= 12) list.push({ name: v, type, highlight: v })
      }
    }
    return list
  }, [rules])

  async function handleApprove() {
    if (!detail) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/extractions/${detail.extraction_id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'reviewed' }),
      })
      const updated = await r.json()
      setDetail(updated)
      fetchExtractions()
    } catch { setError('审核失败') }
    finally { setSaving(false) }
  }

  async function handleReject() {
    if (!detail) return
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

  async function handlePublish() {
    if (!detail) return
    if (!confirm('确认将此事实及其所有规则发布到 Milvus 规则库？')) return
    setPublishing(true)
    try {
      const r = await fetch(`${API}/extractions/${detail.extraction_id}/publish`, { method: 'POST' })
      const d = await r.json()
      if (d.success) {
        alert(`入库成功！发布了 ${d.published_count || d.rule_ids?.length || 0} 条规则`)
        setDetail(null)
        fetchExtractions()
      } else {
        setError(d.error || '入库失败')
      }
    } catch { setError('入库请求失败') }
    finally { setPublishing(false) }
  }

  async function handlePublishV2() {
    if (!detail) return
    if (!confirm('确认发布到新集合 policy_facts + policy_rules_v2（字段级溯源，P3）？')) return
    setPublishing(true)
    try {
      const r = await fetch(`${API}/extractions/${detail.extraction_id}/publish-v2`, { method: 'POST' })
      const d = await r.json()
      if (d.success) {
        alert(`入库成功！已写入 policy_facts + policy_rules_v2（${d.count || ''} 条规则）`)
        setDetail(null)
        fetchExtractions()
      } else {
        setError(d.error || '入库失败')
      }
    } catch { setError('入库请求失败') }
    finally { setPublishing(false) }
  }

  async function handleDelete(extId: string) {
    if (!confirm('确认删除该提取记录？')) return
    try {
      await fetch(`${API}/extractions/${extId}`, { method: 'DELETE' })
      fetchExtractions()
    } catch { setError('删除失败') }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">Step 2</span>
          {docId && <span className="text-xs text-slate-400">筛选自: {docId}</span>}
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">规则提取结果</h2>
        <p className="text-xs text-slate-500 mt-0.5">每条记录 = 一个政策事实，详情中按「最小事实单元拆分 → 结构化提取」两步查看</p>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <select className="bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-xs text-slate-600" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}>
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="reviewed">已审核</option>
          <option value="rejected">已驳回</option>
          <option value="published">已入库</option>
        </select>
        <span className="text-xs text-slate-400 ml-auto">共 {total} 条</span>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead><tr className="bg-slate-50/95 border-b border-slate-200">
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">政策事实</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[100px]">规则</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[60px]">置信度</th>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase w-[70px]">状态</th>
            <th className="px-4 py-2.5 text-right text-[11px] font-semibold text-slate-500 uppercase w-[200px]">操作</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-16 text-center"><Loader2 className="size-5 text-blue-500 animate-spin mx-auto" /></td></tr>
            ) : extractions.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-16 text-center text-sm text-slate-400">
                {docId ? '该文档暂无提取结果' : '暂无提取结果，请先在政策原文页面对文档执行提取'}
              </td></tr>
            ) : extractions.map(ext => {
              const ef = ext.extracted_fields || {} as ExtractedFields
              const rs = extractRules(ef)
              return (
              <tr key={ext.extraction_id} className="hover:bg-blue-50/20 transition-colors cursor-pointer" onClick={() => openDetail(ext)}>
                <td className="px-4 py-3 text-xs text-slate-700 max-w-[380px] truncate">
                  {ef.fact_text || ext.source_text}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {rs.slice(0, 3).map((r, i) => (
                      <span key={i} className="inline-flex rounded-md bg-purple-50 px-1.5 py-0.5 text-[10px] font-medium text-purple-700 ring-1 ring-purple-200">
                        {r.rule_type || '规则'}
                      </span>
                    ))}
                    {!rs.length && (
                      <span className="inline-flex rounded-md bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-400 ring-1 ring-slate-200">未结构化</span>
                    )}
                  </div>
                  <div className="text-[10px] text-slate-400 mt-0.5">{rs.length} 条规则</div>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{(ext.confidence * 100).toFixed(0)}%</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${statusColor[ext.status] || 'bg-slate-100 text-slate-500'}`}>
                    {statusLabel[ext.status] || ext.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => openDetail(ext)} className="rounded px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-100"><Eye className="size-3.5" /></button>
                    {ext.status === 'reviewed' && (
                      <button onClick={() => { setDetail(ext); handlePublish() }} title="入库旧集合 policy_rules" className="rounded px-2 py-0.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50"><Send className="size-3.5" /></button>
                      <button onClick={() => { setDetail(ext); handlePublishV2() }} title="入库 v2（policy_rules_v2 字段级溯源）" className="rounded px-2 py-0.5 text-[10px] font-bold text-purple-600 hover:bg-purple-50">v2</button>
                    )}
                    <button onClick={() => handleDelete(ext.extraction_id)} className="rounded px-2 py-0.5 text-xs font-medium text-rose-600 hover:bg-rose-50"><Trash2 className="size-3.5" /></button>
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

      {/* ── 提取详情：两步流程 ── */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm px-4" onClick={() => setDetail(null)}>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col" onClick={e => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-3.5 border-b border-slate-100 shrink-0">
              <div className="flex items-center gap-3">
                <span className={`inline-flex h-7 items-center rounded-full px-2.5 text-xs font-semibold ring-1 ${detail.status === 'reviewed' ? 'bg-blue-50 text-blue-700 ring-blue-200' : detail.status === 'published' ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-amber-50 text-amber-700 ring-amber-200'}`}>
                  {statusLabel[detail.status]}
                </span>
                <code className="text-xs font-mono text-slate-400">{detail.extraction_id}</code>
                <span className="text-xs text-slate-400">· {rules.length} 条规则 · {rules.reduce((s, r) => s + (r.entities?.length || 0), 0)} 个实体</span>
              </div>
              <button onClick={() => setDetail(null)} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100">
                <svg className="size-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            {/* Step Tabs */}
            <div className="flex items-center gap-1 px-6 border-b border-slate-100 shrink-0">
              <button
                onClick={() => setStep(1)}
                className={`flex items-center gap-1.5 -mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${step === 1 ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}
              >
                <span className={`inline-flex size-5 items-center justify-center rounded-full text-[11px] ${step === 1 ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-500'}`}>1</span>
                最小事实单元拆分
                <Scissors className="size-3.5" />
              </button>
              <ArrowRight className="size-3.5 text-slate-300 mx-1" />
              <button
                onClick={() => setStep(2)}
                className={`flex items-center gap-1.5 -mb-px border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${step === 2 ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}
              >
                <span className={`inline-flex size-5 items-center justify-center rounded-full text-[11px] ${step === 2 ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-500'}`}>2</span>
                结构化提取
                <Boxes className="size-3.5" />
              </button>
              <span className="ml-auto text-[11px] text-slate-400">来源：{detail.doc_title}</span>
            </div>

            {/* Body — 两列：原文 | 提取结果 */}
            <div className="flex-1 overflow-hidden">
              {step === 1 ? (
                <div className="grid grid-cols-2 gap-0 h-full">
                  {/* Step 1 · 原文（事实单元高亮） */}
                  <div className="flex flex-col border-r border-slate-100 min-h-0">
                    <div className="flex items-center gap-2 px-5 py-2.5 bg-slate-50/60 border-b border-slate-100 shrink-0">
                      <FileText className="size-4 text-blue-500" />
                      <span className="text-[11px] font-semibold text-slate-600 uppercase">政策原文 · 高亮最小事实单元</span>
                      {loadingDoc && <Loader2 className="size-3.5 text-blue-500 animate-spin ml-auto" />}
                    </div>
                    <div ref={docViewRef} className="flex-1 overflow-y-auto px-5 py-3 text-[13px] text-slate-700 leading-[1.9] whitespace-pre-wrap break-words">
                      {docContent ? (
                        <div dangerouslySetInnerHTML={{
                          __html: docHtml,
                        }} />
                      ) : (
                        <span className="text-xs text-slate-400">{loadingDoc ? '加载原文…' : '原文不可用'}</span>
                      )}
                    </div>
                  </div>
                  {/* Step 1 · 提取结果（事实单元列表） */}
                  <div className="flex flex-col min-h-0">
                    <div className="flex items-center gap-2 px-5 py-2.5 bg-slate-50/60 border-b border-slate-100 shrink-0">
                      <Layers className="size-4 text-amber-500" />
                      <span className="text-[11px] font-semibold text-slate-600 uppercase">拆分结果 · 最小事实单元</span>
                      <span className="ml-auto inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200">{siblingUnits.length} 个单元</span>
                    </div>
                    <div className="flex-1 overflow-y-auto p-3 space-y-1">
                      <p className="px-1 pb-1 text-[11px] text-slate-400">每个单元为可独立理解的政策规定；点击切换查看对象，当前单元已在左侧原文中以琥珀色高亮。</p>
                      {siblingUnits.map((u, i) => {
                        const current = u.id === detail.extraction_id
                        return (
                          <button
                            key={u.id}
                            onClick={() => openSibling(u.id)}
                            className={`flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors ${current ? 'border-amber-300 bg-amber-50 ring-1 ring-amber-200' : 'border-slate-200 hover:bg-slate-50'}`}
                          >
                            <span className={`mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-md text-[10px] font-semibold ${current ? 'bg-amber-400 text-white' : 'bg-slate-100 text-slate-500'}`}>{i + 1}</span>
                            <span className="flex-1 text-xs leading-relaxed text-slate-700 line-clamp-3">{u.text}</span>
                            {u.rulesCount > 0 && (
                              <span className="shrink-0 rounded bg-purple-50 px-1 py-0.5 text-[9px] font-medium text-purple-700 ring-1 ring-purple-200">{u.rulesCount}规则</span>
                            )}
                          </button>
                        )
                      })}
                      {siblingUnits.length === 0 && !loadingDoc && (
                        <div className="px-2 py-8 text-center text-xs text-slate-400">暂无事实单元</div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-0 h-full">
                  {/* Step 2 · 原文（实体/数值高亮） */}
                  <div className="flex flex-col border-r border-slate-100 min-h-0">
                    <div className="flex items-center gap-2 px-5 py-2.5 bg-slate-50/60 border-b border-slate-100 shrink-0">
                      <FileText className="size-4 text-blue-500" />
                      <span className="text-[11px] font-semibold text-slate-600 uppercase">事实原文 · 高亮提取结果</span>
                    </div>
                    <div className="flex-1 overflow-y-auto px-5 py-3">
                      <div
                        className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-[13px] text-slate-700 leading-relaxed whitespace-pre-wrap break-words"
                        dangerouslySetInnerHTML={{ __html: highlightEntities(factText, structureHighlights) }}
                      />
                      {allEntityTypes.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap mt-3">
                          <span className="text-[10px] text-slate-400">图例：</span>
                          {allEntityTypes.map(t => (
                            <span key={t} className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium border ${ENTITY_COLORS[t] || 'bg-slate-100 text-slate-500 border-slate-300'}`}>
                              {ENTITY_LABEL[t] || t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  {/* Step 2 · 提取结果（结构化字段 + 实体 + 关系） */}
                  <div className="flex flex-col min-h-0">
                    <div className="flex items-center gap-2 px-5 py-2.5 bg-slate-50/60 border-b border-slate-100 shrink-0">
                      <Boxes className="size-4 text-purple-500" />
                      <span className="text-[11px] font-semibold text-slate-600 uppercase">结构化结果</span>
                      <span className="text-[10px] text-slate-400">· 字段对齐 数据模型1.xlsx 政策规则表</span>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4 space-y-4">
                      {rules.length === 0 && (
                        <div className="text-center text-xs text-slate-400 py-8">该事实尚未结构化</div>
                      )}
                      {rules.map((rule, ri) => {
                        const filledCount = FIELD_GROUPS.reduce(
                          (n, g) => n + g.fields.filter(f => String((rule as Record<string, unknown>)[f.key] || '').trim()).length, 0,
                        )
                        return (
                          <div key={ri} className="border border-slate-200 rounded-lg overflow-hidden">
                            <div className="flex items-center gap-2 px-3 py-2 bg-slate-50/95 border-b border-slate-100">
                              <span className="inline-flex rounded-md bg-purple-100 px-2 py-0.5 text-[11px] font-semibold text-purple-700 ring-1 ring-purple-200">
                                {rule.rule_type || '规则'}
                              </span>
                              <span className="text-[10px] text-slate-400">{filledCount} 个字段已填充</span>
                              <span className="ml-auto text-[10px] text-slate-400">置信度 {(((rule.confidence ?? detail?.confidence ?? 0)) * 100).toFixed(0)}%</span>
                            </div>

                            <div className="p-3 space-y-3">
                              {FIELD_GROUPS.map(group => {
                                const items = group.fields
                                  .map(f => ({ ...f, val: String((rule as Record<string, unknown>)[f.key] || '').trim() }))
                                  .filter(f => f.val)
                                if (!items.length) return null
                                return (
                                  <div key={group.title}>
                                    <div className={`flex items-center gap-1 mb-1.5 text-[10px] font-semibold uppercase ${group.tone}`}>
                                      <span className="inline-block size-1.5 rounded-full bg-current opacity-60" />
                                      {group.title}
                                    </div>
                                    <div className={group.fields.some(f => f.key === 'source_text') ? 'space-y-1' : 'grid grid-cols-2 gap-x-3 gap-y-1.5'}>
                                      {items.map(f => (
                                        <div key={f.key}>
                                          <div className="text-[10px] text-slate-400">{f.label}</div>
                                          <div className={`text-xs text-slate-700 ${f.key === 'source_text' ? 'leading-relaxed' : 'font-mono'}`}>{f.val}</div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )
                              })}

                              {/* 实体 */}
                              {(rule.entities && rule.entities.length > 0) && (
                                <div>
                                  <div className="flex items-center gap-1.5 mb-1.5">
                                    <Network className="size-3 text-amber-500" />
                                    <span className="text-[10px] font-medium text-slate-500">实体 ({rule.entities.length})</span>
                                  </div>
                                  <div className="flex flex-wrap gap-1">
                                    {rule.entities.map((ent, ei) => (
                                      <span key={ei} className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium border ${ENTITY_COLORS[ent.type] || 'bg-slate-100 text-slate-500 border-slate-300'}`}>
                                        <span className="text-[9px] opacity-70">{ENTITY_LABEL[ent.type] || ent.type}</span>
                                        {ent.name}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* 关系 */}
                              {(rule.relations && rule.relations.length > 0) && (
                                <div>
                                  <div className="flex items-center gap-1.5 mb-1.5">
                                    <GitBranch className="size-3 text-indigo-500" />
                                    <span className="text-[10px] font-medium text-slate-500">关系 ({rule.relations.length})</span>
                                  </div>
                                  <div className="flex flex-col gap-1">
                                    {rule.relations.map((rel, rei) => (
                                      <span key={rei} className="inline-flex items-center gap-1 rounded-md bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 text-[10px] w-fit">
                                        <span className="font-medium text-indigo-700">{rel.subject}</span>
                                        <span className="text-indigo-400">—</span>
                                        <span className="text-indigo-500 font-medium">{rel.predicate}</span>
                                        <span className="text-indigo-400">—</span>
                                        <span className="font-medium text-indigo-700">{rel.object}</span>
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Footer Actions */}
            {detail.status !== 'published' && (
              <div className="flex justify-between px-6 py-3 border-t border-slate-100 shrink-0">
                <div className="flex gap-2">
                  {detail.status === 'draft' && (
                    <>
                      <button onClick={handleReject} className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50">
                        <XCircle className="size-3.5" /> 驳回
                      </button>
                      <button onClick={handleApprove} disabled={saving} className="flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">
                        {saving ? <Loader2 className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />} 审核通过
                      </button>
                    </>
                  )}
                  {detail.status === 'reviewed' && (
                    <button onClick={handlePublish} disabled={publishing}
                      className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                      {publishing ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
                      发布全部 {rules.length} 条规则到 Milvus
                    </button>
                  )}
                </div>
                <div className="text-[11px] text-slate-400 self-center">创建于 {detail.created_at?.slice(0, 10)}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
