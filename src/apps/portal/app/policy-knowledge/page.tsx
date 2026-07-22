'use client'

import { useState, useEffect, useCallback } from 'react'

/* ───────────────────────────────────────────────
   Types
   ─────────────────────────────────────────────── */
interface Rule { [key: string]: string }
interface Stats { collection: string; available: boolean; total: number; distributions: Record<string, Record<string, number>> }

const API = '/api/v1/medical-insurance-ai-agent/policy-knowledge'

const ALL_FIELDS = ['rule_id','fact_id','policy_id','clause_id','source_text','insu_type','med_type','hosp_lv','psn_type','setl_type','payment_ratio','deductible_amount','cap_amount','time_period','admission_order','amount_band','priority','rule_type','rule_value']
const LABELS: Record<string,string> = {rule_id:'规则ID',fact_id:'事实ID',policy_id:'政策ID',clause_id:'条款ID',source_text:'政策原文',insu_type:'险种类型',med_type:'医疗类别',hosp_lv:'医院等级',psn_type:'人群标签',setl_type:'结算方式',payment_ratio:'支付比例',deductible_amount:'起付金额',cap_amount:'封顶金额',time_period:'时间周期',admission_order:'住院序次',amount_band:'金额区间',priority:'优先级',rule_type:'规则类型',rule_value:'规则值'}
const FILTERABLE = ['rule_type','insu_type','med_type','hosp_lv','psn_type','setl_type','admission_order','amount_band','priority']

const typeBadge: Record<string,string> = {'支付比例':'bg-blue-50 text-blue-700 ring-blue-200','计算公式':'bg-amber-50 text-amber-700 ring-amber-200','起付线':'bg-emerald-50 text-emerald-700 ring-emerald-200','封顶线':'bg-purple-50 text-purple-700 ring-purple-200'}
const grad = ['from-blue-500 to-cyan-400','from-emerald-500 to-teal-400','from-amber-500 to-orange-400','from-purple-500 to-violet-400','from-rose-500 to-pink-400','from-sky-500 to-indigo-400']

/* ───────────────────────────────────────────────
   Page
   ─────────────────────────────────────────────── */
export default function PolicyKnowledgePage() {
  const [rules, setRules] = useState<Rule[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const PAGE = 20

  // Column visibility
  const [visible, setVisible] = useState<Set<string>>(() => new Set(['rule_id','rule_type','source_text','insu_type','hosp_lv','psn_type','payment_ratio','deductible_amount']))
  // Filters
  const [filters, setFilters] = useState<Record<string,string>>({})
  // Advanced expression
  const [advExpr, setAdvExpr] = useState('')
  const [advMode, setAdvMode] = useState(false)
  // Detail
  const [detail, setDetail] = useState<Rule | null>(null)
  // Edit
  const [editRule, setEditRule] = useState<Rule | null>(null)
  const [editFields, setEditFields] = useState<Record<string,string>>({})
  const [saving, setSaving] = useState(false)
  // Show column picker
  const [colOpen, setColOpen] = useState(false)

  /* ── Data ── */
  const fetchRules = useCallback(async () => {
    setLoading(true); setError('')
    try {
      if (advMode && advExpr.trim()) {
        const r = await fetch(`${API}/rules/query`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({expr:advExpr.trim(), limit:PAGE, offset:(page-1)*PAGE}) })
        const d = await r.json(); setRules(d.items||[]); setTotal(d.total||0)
      } else {
        const p = new URLSearchParams({page:String(page),page_size:String(PAGE)})
        if (keyword.trim()) p.set('keyword',keyword.trim())
        Object.entries(filters).forEach(([k,v]) => { if(v) p.set(k,v) })
        const r = await fetch(`${API}/rules?${p}`); const d = await r.json()
        setRules(d.items||[]); setTotal(d.total||0)
      }
    } catch { setError('无法连接后端') }
    finally { setLoading(false) }
  }, [page,keyword,filters,advMode,advExpr])

  const fetchStats = useCallback(async () => {
    try { const r = await fetch(`${API}/stats`); setStats(await r.json()) } catch { /* */ }
  }, [])

  useEffect(() => { const t = setTimeout(fetchRules,200); fetchStats(); return () => clearTimeout(t) }, [fetchRules,fetchStats])

  /* ── Actions ── */
  async function handleDelete(ruleId: string) { if(!confirm(`确认删除 ${ruleId}？`)) return; try { await fetch(`${API}/rules/${ruleId}`,{method:'DELETE'}); setRules(p=>p.filter(r=>r.rule_id!==ruleId)); setTotal(p=>p-1); fetchStats() } catch { setError('删除失败') } }

  async function handleSave() { if(!editRule) return; setSaving(true); try { await fetch(`${API}/rules/${editRule.rule_id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(editFields)}); setEditRule(null); fetchRules() } catch { setError('保存失败') } finally { setSaving(false) } }

  function toggleField(f: string) { setVisible(p => { const n = new Set(p); n.has(f) ? n.delete(f) : n.add(f); return n }) }

  function clearFilters() { setFilters({}); setKeyword(''); setAdvExpr(''); setAdvMode(false); setPage(1) }

  /* ── Detail View ── */
  if (detail) return (
    <div className="relative"><div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"><div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.10),transparent_55%),radial-gradient(ellipse_at_bottom,rgba(14,165,233,0.06),transparent_50%)]" /><div className="absolute inset-0 opacity-[0.28] [background-image:linear-gradient(to_right,rgba(15,23,42,0.04)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.04)_1px,transparent_1px)] [background-size:44px_44px]" /></div>
    <div className="mx-auto max-w-[960px] px-4 py-8"><button onClick={()=>setDetail(null)} className="mb-4 flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 transition-colors"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/></svg>返回列表</button>
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden" style={{animation:'fade-in .35s ease-out'}}><div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3"><span className="inline-flex h-7 items-center rounded-full bg-blue-50 px-2.5 text-xs font-semibold text-blue-700 ring-1 ring-blue-200">规则详情</span><code className="text-sm font-mono text-slate-500">{detail.rule_id}</code></div>
    <div className="p-6 grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">{ALL_FIELDS.filter(f=>f!=='rule_id').map(f=>(<div key={f} className={f==='source_text'?'col-span-full':''}><dt className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-0.5">{LABELS[f]||f}</dt><dd className={f==='source_text'?'text-sm text-slate-700 leading-relaxed':'font-mono text-xs bg-slate-100 px-2 py-1 rounded text-slate-700'}>{detail[f]||'—'}</dd></div>))}</div></div></div></div>
  )

  /* ── List View ── */
  return (
    <div className="relative min-h-screen">
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"><div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.12),transparent_55%),radial-gradient(ellipse_at_60%_80%,rgba(14,165,233,0.08),transparent_50%)]" /><div className="absolute inset-0 opacity-[0.32] [background-image:linear-gradient(to_right,rgba(15,23,42,0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.05)_1px,transparent_1px)] [background-size:48px_48px]" /><div className="absolute -left-20 -top-16 size-[280px] rounded-full bg-blue-500/8 blur-3xl" /><div className="absolute right-0 top-32 size-[320px] rounded-full bg-sky-400/6 blur-3xl" /></div>

      <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-5 px-4 py-8">
        {/* Header */}
        <header className="space-y-1.5"><div className="flex items-center gap-2 justify-between"><div className="flex items-center gap-2"><span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">政策·知识库</span><span className="text-xs text-slate-500">Milvus 规则管理</span></div><div className="flex items-center gap-2"><button onClick={()=>setColOpen(!colOpen)} className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${colOpen?'bg-blue-50 text-blue-700':'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`}>列设置</button><button onClick={clearFilters} className="rounded-lg px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors">清除筛选</button></div></div><h2 className="text-xl font-semibold tracking-tight text-slate-900">政策知识管理</h2></header>

        {/* Stats */}
        {stats && stats.available && stats.distributions && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <div className="bg-white border border-slate-200 rounded-xl px-4 py-3.5 hover:shadow-md transition-all duration-200"><div className="text-xs text-slate-400 mb-1">总规则数</div><div className="text-2xl font-bold bg-gradient-to-r from-blue-500 to-cyan-400 bg-clip-text text-transparent">{stats.total}</div></div>
            {Object.entries(stats.distributions.rule_type||{}).slice(0,4).map(([k,v],i)=>(<div key={k} className="bg-white border border-slate-200 rounded-xl px-4 py-3.5 hover:shadow-md transition-all duration-200"><div className="text-xs text-slate-400 mb-1 truncate">{k}</div><div className={`text-xl font-bold bg-gradient-to-r ${grad[i%grad.length]} bg-clip-text text-transparent`}>{v}</div></div>))}
          </div>
        )}

        {/* Column picker */}
        {colOpen && (<div className="bg-white border border-slate-200 rounded-xl p-4" style={{animation:'fade-in .2s ease-out'}}><div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">显示列 ({visible.size}/{ALL_FIELDS.length})</div><div className="flex flex-wrap gap-1.5">{ALL_FIELDS.map(f=>(<button key={f} onClick={()=>toggleField(f)} className={`rounded-md px-2.5 py-1 text-xs transition-colors ${visible.has(f)?'bg-blue-50 text-blue-700 ring-1 ring-blue-200':'bg-slate-50 text-slate-500 ring-1 ring-slate-200 hover:bg-slate-100'}`}>{LABELS[f]||f}</button>))}</div></div>)}

        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px] max-w-[320px]"><svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg><input className="w-full pl-9 pr-4 py-2 bg-white border border-slate-200 rounded-lg text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" placeholder="搜索政策原文..." value={keyword} onChange={e=>setKeyword(e.target.value)} onKeyDown={e=>e.key==='Enter'&&fetchRules()}/></div>
          {FILTERABLE.map(f=>(<select key={f} className="bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-xs text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" value={filters[f]||''} onChange={e=>{setFilters(p=>({...p,[f]:e.target.value}));setPage(1)}}><option value="">{LABELS[f]||f}</option>{(Object.keys(stats?.distributions?.[f] ?? {})).slice(0,20).map(v=>(<option key={v} value={v}>{v} ({stats?.distributions?.[f]?.[v]})</option>))}</select>))}
          <button onClick={fetchRules} className="flex items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] transition-colors shadow-sm"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>查询</button>
          {/* Advanced toggle */}
          <button onClick={()=>{setAdvMode(!advMode);setPage(1)}} className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${advMode?'bg-amber-50 text-amber-700 ring-1 ring-amber-200':'bg-white border border-slate-200 text-slate-500 hover:bg-slate-50'}`}>表达式</button>
          <span className="text-xs text-slate-400 ml-auto hidden sm:inline">共 {total} 条</span>
        </div>

        {/* Advanced expression bar */}
        {advMode && (<div className="flex gap-2"><input className="flex-1 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-500/20 focus:border-amber-400" placeholder='Milvus 表达式, 如: rule_type == "支付比例" and hosp_lv == "三级医院"' value={advExpr} onChange={e=>setAdvExpr(e.target.value)} onKeyDown={e=>e.key==='Enter'&&fetchRules()}/><button onClick={fetchRules} className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-600 transition-colors">执行</button></div>)}

        {error && (<div className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>{error}</div>)}

        {/* Table */}
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden" style={{animation:'fade-in .4s ease-out'}}>
          <div className="overflow-auto max-h-[70vh]">
            <table className="w-full text-sm" style={{minWidth:visible.size*120}}>
              <thead className="sticky top-0 z-10"><tr className="bg-slate-50/95 backdrop-blur border-b border-slate-200">{ALL_FIELDS.filter(f=>visible.has(f)).map(f=>(<th key={f} className="px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">{LABELS[f]||f}</th>))}<th className="px-3 py-2.5 text-right text-[11px] font-semibold text-slate-500 uppercase tracking-wider sticky right-0 bg-slate-50/95 backdrop-blur border-l border-slate-200 w-[70px]">操作</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (<tr><td colSpan={visible.size+1} className="px-4 py-16 text-center"><div className="flex flex-col items-center gap-2"><div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"/><span className="text-sm text-slate-400">加载中...</span></div></td></tr>)
                : rules.length===0 ? (<tr><td colSpan={visible.size+1} className="px-4 py-16 text-center"><span className="text-sm text-slate-400">{keyword||advExpr||Object.values(filters).some(Boolean)?'无匹配结果':'暂无数据'}</span></td></tr>)
                : rules.map(r=>(<tr key={r.rule_id} className="hover:bg-blue-50/30 transition-colors cursor-pointer" onClick={()=>setDetail(r)}>
                  {ALL_FIELDS.filter(f=>visible.has(f)).map(f=>(<td key={f} className="px-3 py-2.5 whitespace-nowrap" title={r[f]||''}>{f==='rule_id'?<code className="text-xs text-slate-600">{r[f]?.replace('rule_','')?.slice(0,14)}</code>:f==='rule_type'?<span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${typeBadge[r[f]]||'bg-slate-50 text-slate-600 ring-slate-200'}`}>{r[f]||'—'}</span>:f==='source_text'?<span className="block max-w-[300px] truncate text-slate-700">{r[f]}</span>:<span className="text-xs text-slate-500">{r[f]||'—'}</span>}</td>))}
                  <td className="px-3 py-2.5 text-right sticky right-0 bg-white border-l border-slate-100" onClick={e=>e.stopPropagation()}><div className="flex items-center justify-end gap-1"><button onClick={()=>{setEditRule(r);setEditFields(Object.fromEntries(ALL_FIELDS.filter(f=>f!=='rule_id').map(f=>[f,r[f]||''])))}} className="rounded px-2 py-0.5 text-xs font-medium text-blue-600 hover:bg-blue-50 transition-colors">编辑</button><button onClick={()=>handleDelete(r.rule_id)} className="rounded px-2 py-0.5 text-xs font-medium text-rose-600 hover:bg-rose-50 transition-colors">删除</button></div></td></tr>))}
              </tbody>
            </table>
          </div>
          {total>PAGE && (<div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 bg-slate-50/50"><span className="text-xs text-slate-500">共 {total} 条 · 第 {page}/{Math.ceil(total/PAGE)} 页</span><div className="flex gap-1"><button disabled={page<=1} onClick={()=>setPage(p=>p-1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">上一页</button><button disabled={page*PAGE>=total} onClick={()=>setPage(p=>p+1)} className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">下一页</button></div></div>)}
        </div>
      </div>

      {/* Edit Modal */}
      {editRule && (<div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm px-4" onClick={()=>setEditRule(null)}><div className="bg-white border border-slate-200 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto" onClick={e=>e.stopPropagation()} style={{animation:'scale-in .2s ease-out'}}><div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-white/95 backdrop-blur rounded-t-2xl"><div className="flex items-center gap-3"><span className="inline-flex h-7 items-center rounded-full bg-amber-50 px-2.5 text-xs font-semibold text-amber-700 ring-1 ring-amber-200">编辑</span><code className="text-sm font-mono text-slate-500">{editRule.rule_id}</code></div><button onClick={()=>setEditRule(null)} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/></svg></button></div><div className="p-6 space-y-3.5">{ALL_FIELDS.filter(f=>f!=='rule_id').map(f=>(<div key={f}><label className="block text-[11px] font-medium text-slate-500 uppercase tracking-wide mb-1">{LABELS[f]||f}</label>{f==='source_text'?<textarea className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 min-h-[80px] resize-y" value={editFields[f]||''} onChange={e=>setEditFields(p=>({...p,[f]:e.target.value}))}/>:<input className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-mono text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" value={editFields[f]||''} onChange={e=>setEditFields(p=>({...p,[f]:e.target.value}))}/>}</div>))}</div><div className="sticky bottom-0 flex justify-end gap-3 px-6 py-4 border-t border-slate-100 bg-white/95 backdrop-blur rounded-b-2xl"><button onClick={()=>setEditRule(null)} className="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 transition-colors">取消</button><button onClick={handleSave} disabled={saving} className="rounded-lg bg-[#2563EB] px-5 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50 transition-colors shadow-sm">{saving?'保存中...':'保存修改'}</button></div></div></div>)}

      <style jsx global>{`@keyframes fade-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}@keyframes scale-in{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}`}</style>
    </div>
  )
}
