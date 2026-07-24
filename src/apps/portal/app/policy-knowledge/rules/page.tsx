'use client'

import { useState, useEffect, useCallback } from 'react'
import { Search, Eye, Edit3, Trash2, FileText, Loader2 } from 'lucide-react'

interface Rule { [key: string]: string }
interface UnpublishedRule extends Rule {
  extraction_id: string; doc_title: string; segment_status: string
  fact_text: string
}
interface Stats { collection: string; available: boolean; total: number; distributions: Record<string, Record<string, number>> }

const MILVUS_API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'
const PIPELINE_API = '/api/v1/medical-insurance-ai-agent/policy-pipeline'

const ALL_FIELDS = ['rule_id','fact_id','policy_id','clause_id','source_text','doc_id','insu_type','med_type','hosp_lv','psn_type','setl_type','payment_ratio','deductible_amount','cap_amount','time_period','admission_order','amount_band','priority','rule_type','rule_value']
const LABELS: Record<string,string> = {rule_id:'规则ID',fact_id:'事实ID',policy_id:'政策ID',clause_id:'条款ID',source_text:'政策原文',doc_id:'来源文档',insu_type:'险种类型',med_type:'医疗类别',hosp_lv:'医院等级',psn_type:'人群标签',setl_type:'结算方式',payment_ratio:'支付比例',deductible_amount:'起付金额',cap_amount:'封顶金额',time_period:'时间周期',admission_order:'住院序次',amount_band:'金额区间',priority:'优先级',rule_type:'规则类型',rule_value:'规则值'}
const FILTERABLE = ['rule_type','insu_type','med_type','hosp_lv','psn_type','setl_type','admission_order','amount_band','priority']
const typeBadge: Record<string,string> = {'支付比例':'bg-blue-50 text-blue-700 ring-blue-200','计算公式':'bg-amber-50 text-amber-700 ring-amber-200','起付线':'bg-emerald-50 text-emerald-700 ring-emerald-200','封顶线':'bg-purple-50 text-purple-700 ring-purple-200'}

type TabType = 'published' | 'unpublished'

export default function PolicyRulesPage() {
  const [tab, setTab] = useState<TabType>('published')

  // Published (Milvus)
  const [rules, setRules] = useState<Rule[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const PAGE = 20
  const [visible, setVisible] = useState<Set<string>>(() => new Set(['rule_id','rule_type','source_text','doc_id','insu_type','hosp_lv','psn_type','payment_ratio','deductible_amount']))
  const [filters, setFilters] = useState<Record<string,string>>({})
  const [advExpr, setAdvExpr] = useState('')
  const [advMode, setAdvMode] = useState(false)
  const [detail, setDetail] = useState<Rule | null>(null)
  const [editRule, setEditRule] = useState<Rule | null>(null)
  const [editFields, setEditFields] = useState<Record<string,string>>({})
  const [saving, setSaving] = useState(false)
  const [colOpen, setColOpen] = useState(false)
  const [lineageMap, setLineageMap] = useState<Record<string, {doc_id: string; doc_title: string}>>({})

  // Unpublished (from extractions)
  const [unpubRules, setUnpubRules] = useState<UnpublishedRule[]>([])
  const [unpubTotal, setUnpubTotal] = useState(0)
  const [unpubPage, setUnpubPage] = useState(1)
  const [unpubLoading, setUnpubLoading] = useState(false)
  const UNPUB_PAGE = 50

  /* ── Published ── */
  const fetchRules = useCallback(async () => {
    setLoading(true); setError('')
    try {
      if (advMode && advExpr.trim()) {
        const r = await fetch(`${MILVUS_API}/rules/query`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({expr:advExpr.trim(), limit:PAGE, offset:(page-1)*PAGE}) })
        const d = await r.json(); setRules(d.items||[]); setTotal(d.total||0)
      } else {
        const p = new URLSearchParams({page:String(page),page_size:String(PAGE)})
        if (keyword.trim()) p.set('keyword',keyword.trim())
        Object.entries(filters).forEach(([k,v]) => { if(v) p.set(k,v) })
        const r = await fetch(`${MILVUS_API}/rules?${p}`); const d = await r.json()
        setRules(d.items||[]); setTotal(d.total||0)
      }
    } catch { setError('无法连接后端') }
    finally { setLoading(false) }
  }, [page,keyword,filters,advMode,advExpr])

  const fetchStats = useCallback(async () => {
    try { const r = await fetch(`${MILVUS_API}/stats`); setStats(await r.json()) } catch { /* */ }
  }, [])

  useEffect(() => { const t = setTimeout(fetchRules,200); fetchStats(); return () => clearTimeout(t) }, [fetchRules,fetchStats])
  useEffect(() => { if (rules.length>0) fetchLineage(rules) }, [rules])

  const fetchLineage = useCallback(async (items: Rule[]) => {
    const map: Record<string, {doc_id: string; doc_title: string}> = {}
    for (const r of items) {
      if (r.doc_id && r.doc_id !== 'None' && r.doc_id !== '') {
        try { const res = await fetch(`${PIPELINE_API}/documents/${r.doc_id}`); if (res.ok) { const doc = await res.json(); map[r.rule_id] = { doc_id: r.doc_id, doc_title: doc.title || r.doc_id } } } catch { /* */ }
      }
    }
    setLineageMap(map)
  }, [])

  async function handleDeletePub(ruleId: string) { if(!confirm(`确认删除 ${ruleId}？`)) return; try { await fetch(`${MILVUS_API}/rules/${ruleId}`,{method:'DELETE'}); setRules(p=>p.filter(r=>r.rule_id!==ruleId)); setTotal(p=>p-1); fetchStats() } catch { setError('删除失败') } }
  async function handleSave() { if(!editRule) return; setSaving(true); try { await fetch(`${MILVUS_API}/rules/${editRule.rule_id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(editFields)}); setEditRule(null); fetchRules() } catch { setError('保存失败') } finally { setSaving(false) } }
  function toggleField(f: string) { setVisible(p => { const n = new Set(p); n.has(f) ? n.delete(f) : n.add(f); return n }) }
  function clearFilters() { setFilters({}); setKeyword(''); setAdvExpr(''); setAdvMode(false); setPage(1) }

  /* ── Unpublished ── */
  const fetchUnpublished = useCallback(async () => {
    setUnpubLoading(true)
    try {
      const p = new URLSearchParams({ page: String(unpubPage), page_size: String(UNPUB_PAGE) })
      const r = await fetch(`${PIPELINE_API}/rules/unpublished?${p}`)
      const d = await r.json()
      setUnpubRules(d.items || [])
      setUnpubTotal(d.total || 0)
    } catch { setError('加载待审核规则失败') }
    finally { setUnpubLoading(false) }
  }, [unpubPage])

  useEffect(() => { if (tab === 'unpublished') fetchUnpublished() }, [tab, fetchUnpublished])

  /* ── Detail (shared) ── */
  if (detail) return (
    <div>
      <button onClick={()=>setDetail(null)} className="mb-4 flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 transition-colors">
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/></svg>返回列表
      </button>
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3">
          <span className="inline-flex h-7 items-center rounded-full bg-blue-50 px-2.5 text-xs font-semibold text-blue-700 ring-1 ring-blue-200">规则详情</span>
          <code className="text-sm font-mono text-slate-500">{detail.rule_id}</code>
          {detail.doc_id && detail.doc_id !== 'None' && (
            <a href="/policy-knowledge/documents" className="ml-auto inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"><FileText className="size-3" /> 查看来源文档</a>
          )}
        </div>
        <div className="p-6 grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">
          {ALL_FIELDS.filter(f=>f!=='rule_id').map(f=>(
            <div key={f} className={f==='source_text'?'col-span-full':''}>
              <dt className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-0.5">{LABELS[f]||f}</dt>
              {f === 'doc_id' ? (
                <dd className="text-xs text-slate-500">{detail[f] || '—（无来源文档）'}</dd>
              ) : f === 'source_text' ? (
                <dd className="text-sm text-slate-700 leading-relaxed">{detail[f]||'—'}</dd>
              ) : (
                <dd className="font-mono text-xs bg-slate-100 px-2 py-1 rounded text-slate-700">{detail[f]||'—'}</dd>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )

  /* ── Published tab content ── */
  const pubContent = (
    <>
      {stats && stats.available && stats.distributions && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div className="bg-white border border-slate-200 rounded-xl px-4 py-3.5"><div className="text-xs text-slate-400 mb-1">总规则数</div><div className="text-2xl font-bold text-blue-600">{stats.total}</div></div>
          {Object.entries(stats.distributions.rule_type||{}).slice(0,4).map(([k,v])=>(
            <div key={k} className="bg-white border border-slate-200 rounded-xl px-4 py-3.5"><div className="text-xs text-slate-400 mb-1 truncate">{k}</div><div className="text-xl font-bold text-slate-700">{v}</div></div>
          ))}
        </div>
      )}
      {colOpen && (
        <div className="bg-white border border-slate-200 rounded-xl p-4">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">显示列 ({visible.size}/{ALL_FIELDS.length})</div>
          <div className="flex flex-wrap gap-1.5">
            {ALL_FIELDS.map(f=>(<button key={f} onClick={()=>toggleField(f)} className={`rounded-md px-2.5 py-1 text-xs transition-colors ${visible.has(f)?'bg-blue-50 text-blue-700 ring-1 ring-blue-200':'bg-slate-50 text-slate-500 ring-1 ring-slate-200 hover:bg-slate-100'}`}>{LABELS[f]||f}</button>))}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-[320px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-slate-400 pointer-events-none" />
          <input className="w-full pl-9 pr-4 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
            placeholder="搜索政策原文..." value={keyword} onChange={e=>setKeyword(e.target.value)} onKeyDown={e=>e.key==='Enter'&&fetchRules()}/>
        </div>
        {FILTERABLE.map(f=>(
          <select key={f} className="bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-xs text-slate-600" value={filters[f]||''} onChange={e=>{setFilters(p=>({...p,[f]:e.target.value}));setPage(1)}}>
            <option value="">{LABELS[f]||f}</option>
            {(Object.keys(stats?.distributions?.[f] ?? {})).slice(0,20).map(v=>(<option key={v} value={v}>{v} ({stats?.distributions?.[f]?.[v]})</option>))}
          </select>
        ))}
        <button onClick={fetchRules} className="flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]"><Search className="size-4" /> 查询</button>
        <button onClick={()=>{setAdvMode(!advMode);setPage(1)}} className={`rounded-lg px-3 py-2 text-xs font-medium ${advMode?'bg-amber-50 text-amber-700 ring-1 ring-amber-200':'bg-white border border-slate-200 text-slate-500 hover:bg-slate-50'}`}>表达式</button>
        <button onClick={clearFilters} className="rounded-lg px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50">清除筛选</button>
        <span className="text-xs text-slate-400 ml-auto">共 {total} 条</span>
      </div>
      {advMode && (
        <div className="flex gap-2">
          <input className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono text-slate-700" placeholder='Milvus 表达式, 如: rule_type == "支付比例" and hosp_lv == "三级医院"' value={advExpr} onChange={e=>setAdvExpr(e.target.value)} onKeyDown={e=>e.key==='Enter'&&fetchRules()}/>
          <button onClick={fetchRules} className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-600">执行</button>
        </div>
      )}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-auto max-h-[70vh]">
          <table className="w-full text-sm" style={{minWidth:visible.size*120}}>
            <thead className="sticky top-0 z-10"><tr className="bg-slate-50/95 backdrop-blur border-b border-slate-200">
              {ALL_FIELDS.filter(f=>visible.has(f)).map(f=>(<th key={f} className="px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase whitespace-nowrap">{LABELS[f]||f}</th>))}
              <th className="px-3 py-2.5 text-right text-[11px] font-semibold text-slate-500 uppercase sticky right-0 bg-slate-50/95 border-l border-slate-200 w-[80px]">操作</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? (
                <tr><td colSpan={visible.size+1} className="px-4 py-16 text-center"><Loader2 className="size-5 text-blue-500 animate-spin mx-auto" /></td></tr>
              ) : rules.length===0 ? (
                <tr><td colSpan={visible.size+1} className="px-4 py-16 text-center text-sm text-slate-400">暂无已发布规则</td></tr>
              ) : rules.map(r => {
                const lineage = lineageMap[r.rule_id]
                return (
                  <tr key={r.rule_id} className="hover:bg-blue-50/30 transition-colors cursor-pointer" onClick={()=>setDetail(r)}>
                    {ALL_FIELDS.filter(f=>visible.has(f)).map(f => {
                      if (f === 'rule_id') return <td key={f} className="px-3 py-2.5 whitespace-nowrap"><code className="text-xs text-slate-600">{r[f]?.replace('rule_','')?.slice(0,14)}</code></td>
                      if (f === 'rule_type') return <td key={f} className="px-3 py-2.5"><span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${typeBadge[r[f]]||'bg-slate-50 text-slate-600 ring-slate-200'}`}>{r[f]||'—'}</span></td>
                      if (f === 'source_text') return <td key={f} className="px-3 py-2.5"><span className="block max-w-[300px] truncate text-slate-700">{r[f]}</span></td>
                      if (f === 'doc_id') return <td key={f} className="px-3 py-2.5">{lineage ? <a href="/policy-knowledge/documents" className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline" onClick={e=>e.stopPropagation()}><FileText className="size-3" />{lineage.doc_title}</a> : <span className="text-xs text-slate-400">—</span>}</td>
                      return <td key={f} className="px-3 py-2.5 whitespace-nowrap"><span className="text-xs text-slate-500">{r[f]||'—'}</span></td>
                    })}
                    <td className="px-3 py-2.5 text-right sticky right-0 bg-white border-l border-slate-100" onClick={e=>e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={()=>{setEditRule(r);setEditFields(Object.fromEntries(ALL_FIELDS.filter(f=>f!=='rule_id').map(f=>[f,r[f]||''])))}} className="rounded px-2 py-0.5 text-xs font-medium text-blue-600 hover:bg-blue-50">编辑</button>
                        <button onClick={()=>handleDeletePub(r.rule_id)} className="rounded px-2 py-0.5 text-xs font-medium text-rose-600 hover:bg-rose-50">删除</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {total>PAGE && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 bg-slate-50/50">
            <span className="text-xs text-slate-500">共 {total} 条 · 第 {page}/{Math.ceil(total/PAGE)} 页</span>
            <div className="flex gap-1">
              <button disabled={page<=1} onClick={()=>setPage(p=>p-1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">上一页</button>
              <button disabled={page*PAGE>=total} onClick={()=>setPage(p=>p+1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">下一页</button>
            </div>
          </div>
        )}
      </div>
    </>
  )

  /* ── Unpublished tab content ── */
  const UNPUB_FIELDS = ['rule_type','insu_type','med_type','hosp_lv','psn_type','setl_type','payment_ratio','deductible_amount','cap_amount','amount_band','admission_order','time_period','priority','rule_value','source_text','confidence']
  const UNPUB_LABELS: Record<string,string> = {rule_type:'规则类型',insu_type:'险种',med_type:'医疗类别',hosp_lv:'医院等级',psn_type:'人群',setl_type:'结算方式',payment_ratio:'支付比例',deductible_amount:'起付金额',cap_amount:'封顶金额',amount_band:'金额分段',admission_order:'住院次数',time_period:'时间周期',priority:'优先级',rule_value:'规则值',source_text:'原文',confidence:'置信度'}
  const unpubContent = (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
      <div className="overflow-auto max-h-[70vh]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10"><tr className="bg-slate-50/95 border-b border-slate-200">
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">片段状态</th>
            {UNPUB_FIELDS.map(f => (<th key={f} className="px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase whitespace-nowrap">{UNPUB_LABELS[f]||f}</th>))}
          </tr></thead>
          <tbody className="divide-y divide-slate-100">
            {unpubLoading ? (
              <tr><td colSpan={UNPUB_FIELDS.length+1} className="px-4 py-16 text-center"><Loader2 className="size-5 text-blue-500 animate-spin mx-auto" /></td></tr>
            ) : unpubRules.length === 0 ? (
              <tr><td colSpan={UNPUB_FIELDS.length+1} className="px-4 py-16 text-center text-sm text-slate-400">暂无待审核规则</td></tr>
            ) : unpubRules.map((r, i) => (
              <tr key={r.rule_id || i} className="hover:bg-amber-50/30 transition-colors">
                <td className="px-3 py-2.5">
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${r.segment_status === 'reviewed' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'}`}>
                    {r.segment_status === 'reviewed' ? '已审核' : '草稿'}
                  </span>
                </td>
                {UNPUB_FIELDS.map(f => (
                  <td key={f} className="px-3 py-2.5 text-xs text-slate-500 max-w-[150px] truncate">
                    {f === 'rule_type' ? (
                      <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${typeBadge[r[f]]||'bg-slate-50 text-slate-600 ring-slate-200'}`}>{r[f]||'—'}</span>
                    ) : f === 'source_text' ? (
                      <span className="block max-w-[250px] truncate" title={r[f]}>{r[f]||'—'}</span>
                    ) : f === 'confidence' ? (
                      <span>{r.confidence ? `${(Number(r.confidence)*100).toFixed(0)}%` : '—'}</span>
                    ) : (
                      <span>{r[f]||'—'}</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {unpubTotal > UNPUB_PAGE && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 bg-slate-50/50">
          <span className="text-xs text-slate-500">共 {unpubTotal} 条 · 第 {unpubPage}/{Math.ceil(unpubTotal/UNPUB_PAGE)} 页</span>
          <div className="flex gap-1">
            <button disabled={unpubPage<=1} onClick={()=>setUnpubPage(p=>p-1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">上一页</button>
            <button disabled={unpubPage*UNPUB_PAGE>=unpubTotal} onClick={()=>setUnpubPage(p=>p+1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30">下一页</button>
          </div>
        </div>
      )}
    </div>
  )

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">Step 3</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900 mt-1">规则管理</h2>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit">
        <button onClick={() => setTab('published')} className={`rounded-md px-4 py-2 text-sm font-medium transition-all ${tab === 'published' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          已发布 {stats?.total ? `(${stats.total})` : ''}
        </button>
        <button onClick={() => setTab('unpublished')} className={`rounded-md px-4 py-2 text-sm font-medium transition-all ${tab === 'unpublished' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}>
          待审核 {unpubTotal > 0 ? `(${unpubTotal})` : ''}
        </button>
      </div>

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">{error}</div>}

      {tab === 'published' ? pubContent : unpubContent}

      {/* Edit Modal (published only) */}
      {editRule && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm px-4" onClick={()=>setEditRule(null)}>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto" onClick={e=>e.stopPropagation()}>
            <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-white/95 rounded-t-2xl">
              <div className="flex items-center gap-3"><span className="inline-flex h-7 items-center rounded-full bg-amber-50 px-2.5 text-xs font-semibold text-amber-700 ring-1 ring-amber-200">编辑</span><code className="text-sm font-mono text-slate-500">{editRule.rule_id}</code></div>
              <button onClick={()=>setEditRule(null)} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100"><svg className="size-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/></svg></button>
            </div>
            <div className="p-6 space-y-3.5">
              {ALL_FIELDS.filter(f=>f!=='rule_id').map(f=>(
                <div key={f}><label className="block text-[11px] font-medium text-slate-500 uppercase mb-1">{LABELS[f]||f}</label>
                  {f==='source_text'
                    ? <textarea className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 min-h-[80px] resize-y" value={editFields[f]||''} onChange={e=>setEditFields(p=>({...p,[f]:e.target.value}))}/>
                    : <input className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-mono text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20" value={editFields[f]||''} onChange={e=>setEditFields(p=>({...p,[f]:e.target.value}))}/>
                  }
                </div>
              ))}
            </div>
            <div className="sticky bottom-0 flex justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-white/95 rounded-b-2xl">
              <button onClick={()=>setEditRule(null)} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">取消</button>
              <button onClick={handleSave} disabled={saving} className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">{saving?'保存中...':'保存'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
