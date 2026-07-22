'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  AlertCircle, Loader2, CheckCircle2, XCircle, RefreshCw,
  Layers, Box, GitBranch, Calculator, Workflow, FileText,
  Database, Pencil, Check, X, ChevronDown, ChevronRight, Plus, Trash2,
} from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────

interface IndicatorDef {
  indicator_id: string; name: string; description: string
  category: 'dimension' | 'numeric' | 'condition' | 'meta'
  value_type: string; unit: string; dictionary_ref: string | null
  semantic_tags: string[]; used_by_strategies: string[]
  depends_on: string[]; computation: string | null; policy_field: string
}
interface IndResp { indicators: IndicatorDef[]; total: number; categories: Record<string, number> }

interface BizObj { object_id: string; name: string; description: string; fields: string[] }

interface IndicatorLineage {
  dependencies: string; formula: string; sql_template: string; policy_ref: string
}

// ── 初始实体 ───────────────────────────────────────────────────────

const DEFAULT_ENTITIES: BizObj[] = [
  { object_id: 'Patient', name: '参保人', description: '参保人基本信息：人群分类、险种归属、身份标识。', fields: ['psn_type','insu_type'] },
  { object_id: 'Settlement', name: '结算单', description: '一次医保结算的完整记录：费用、支付、自付。', fields: ['setl_type','admission_order','pooling_pay','pooling_self_pay','deductible_line','total_fee','self_fee','first_pay_fee','in_scope_total','payment_ratio'] },
  { object_id: 'Hospital', name: '医疗机构', description: '提供医疗服务的医院信息，含等级。', fields: ['hosp_lv'] },
  { object_id: 'Policy', name: '医保政策', description: '政策规则维度：险种、比例、起付、封顶、分段。', fields: ['insu_type','med_type','payment_ratio','deductible_amount','cap_amount','amount_band','time_period','rule_type','rule_value','source_text'] },
]

const FIELD_ID_MAP: Record<string, string> = { deductible_line: 'deductible_amount' }

// ── Constants ──────────────────────────────────────────────────────

const API = '/api/v1/medical-insurance-ai-agent/semantic-layer'

const CAT_OPTIONS = ['dimension','numeric','condition','meta'] as const
const CAT_COLORS: Record<string, string> = { dimension: 'bg-blue-50 text-blue-700 border-blue-200', numeric: 'bg-orange-50 text-orange-700 border-orange-200', condition: 'bg-purple-50 text-purple-700 border-purple-200', meta: 'bg-slate-100 text-slate-600 border-slate-200' }
const CAT_LABEL: Record<string, string> = { dimension: '维度', numeric: '数值', condition: '条件', meta: '元数据' }
const LINEAGE_LEVELS: { key: keyof IndicatorLineage; label: string; icon: typeof GitBranch; placeholder: string; ml?: boolean }[] = [
  { key: 'dependencies', label: '一级血缘 · 依赖关系', icon: GitBranch, placeholder: '例：起付线、医保目录金额、医院等级、报销比例' },
  { key: 'formula', label: '二级血缘 · 公式血缘', icon: Calculator, placeholder: '例：第一段 + 第二段 + 第三段', ml: true },
  { key: 'sql_template', label: '三级血缘 · SQL 血缘', icon: Database, placeholder: '例：pooling_payment_query.sql' },
  { key: 'policy_ref', label: '四级血缘 · 政策血缘', icon: FileText, placeholder: '例：三级医院住院待遇政策' },
]

async function fj<T>(url: string): Promise<T | null> {
  try { const r = await fetch(url); return r.ok ? await r.json() as T : null } catch { return null }
}

// ── Inline Editable ────────────────────────────────────────────────

function InlineEdit({ value, onChange, placeholder, multiline, className }: {
  value: string; onChange: (v: string) => void; placeholder: string; multiline?: boolean; className?: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const hasValue = value.trim().length > 0

  if (editing) {
    return (
      <div className="space-y-1">
        {multiline ? (
          <textarea value={draft} onChange={e => setDraft(e.target.value)} placeholder={placeholder}
            className="w-full rounded-lg border border-blue-300 bg-white px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-100 resize-y min-h-[44px]"
            autoFocus rows={2} />
        ) : (
          <input value={draft} onChange={e => setDraft(e.target.value)} placeholder={placeholder}
            className={`w-full rounded-lg border border-blue-300 bg-white px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-100 ${className ?? ''}`}
            autoFocus />
        )}
        <div className="flex gap-1">
          <button onClick={() => { onChange(draft); setEditing(false) }} className="inline-flex items-center gap-1 rounded-md bg-blue-500 px-2 py-0.5 text-[10px] text-white hover:bg-blue-600"><Check className="size-2.5" />保存</button>
          <button onClick={() => { setDraft(value); setEditing(false) }} className="inline-flex items-center gap-1 rounded-md bg-slate-200 px-2 py-0.5 text-[10px] text-slate-600 hover:bg-slate-300"><X className="size-2.5" />取消</button>
        </div>
      </div>
    )
  }
  return (
    <div className="group flex items-start gap-1">
      <span className={hasValue ? 'text-slate-700' : 'text-slate-300 italic'}>{hasValue ? value : placeholder}</span>
      <button onClick={() => { setDraft(value); setEditing(true) }}
        className="shrink-0 opacity-0 group-hover:opacity-100 rounded p-0.5 text-slate-400 hover:text-blue-500 hover:bg-blue-50 transition-opacity">
        <Pencil className="size-3" />
      </button>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────

export default function SemanticLayerPage() {
  // Data state
  const [apiIndicators, setApiIndicators] = useState<IndicatorDef[]>([])
  const [entities, setEntities] = useState<BizObj[]>(DEFAULT_ENTITIES)
  const [localIndicators, setLocalIndicators] = useState<IndicatorDef[]>([])
  const [lineages, setLineages] = useState<Record<string, IndicatorLineage>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // UI state
  const [expandedEntities, setExpandedEntities] = useState<Record<string, boolean>>({})
  const [expandedIndicators, setExpandedIndicators] = useState<Record<string, boolean>>({})
  const [addingEntity, setAddingEntity] = useState(false)
  const [addingIndicatorFor, setAddingIndicatorFor] = useState<string | null>(null)

  // ── Fetch ──
  useEffect(() => {
    let c = false; (async () => {
      setLoading(true); setError(null)
      try { const ind = await fj<IndResp>(`${API}/indicators`); if (!c && ind) setApiIndicators(ind.indicators ?? []) }
      catch { if (!c) setError('后端服务不可用') }
      finally { if (!c) setLoading(false) }
    })(); return () => { c = true }
  }, [])

  const refresh = () => {
    setLoading(true)
    fj<IndResp>(`${API}/indicators`).then(ind => { if (ind) setApiIndicators(ind.indicators ?? []) }).catch(() => setError('刷新失败')).finally(() => setLoading(false))
  }

  // Combine API + local indicators
  const allIndicators = useMemo(() => [...apiIndicators, ...localIndicators], [apiIndicators, localIndicators])
  const byId = useMemo(() => { const m: Record<string, IndicatorDef> = {}; for (const i of allIndicators) m[i.indicator_id] = i; return m }, [allIndicators])
  const status = loading ? 'loading' : error ? 'error' : 'loaded'

  // ── Entity CRUD ──
  const addEntity = (name: string, desc: string, objectId: string) => {
    setEntities(prev => [...prev, { object_id: objectId || `Entity_${Date.now()}`, name, description: desc, fields: [] }])
    setAddingEntity(false)
  }
  const updateEntity = (objectId: string, field: 'name' | 'description' | 'object_id', value: string) => {
    setEntities(prev => prev.map(e => e.object_id === objectId ? { ...e, [field]: value } : e))
  }
  const deleteEntity = (objectId: string) => {
    setEntities(prev => prev.filter(e => e.object_id !== objectId))
  }

  // ── Indicator CRUD ──
  const addIndicatorToEntity = (entityId: string, ind: IndicatorDef) => {
    setLocalIndicators(prev => [...prev, ind])
    setEntities(prev => prev.map(e => e.object_id === entityId ? { ...e, fields: [...e.fields, ind.indicator_id] } : e))
    setAddingIndicatorFor(null)
  }
  const removeIndicatorFromEntity = (entityId: string, indicatorId: string) => {
    setEntities(prev => prev.map(e => e.object_id === entityId ? { ...e, fields: e.fields.filter(f => {
      const resolved = FIELD_ID_MAP[f] ?? f
      return resolved !== indicatorId && f !== indicatorId
    })} : e))
  }
  const updateIndicator = (indicatorId: string, field: keyof IndicatorDef, value: any) => {
    setLocalIndicators(prev => prev.map(i => i.indicator_id === indicatorId ? { ...i, [field]: value } : i))
    setApiIndicators(prev => prev.map(i => i.indicator_id === indicatorId ? { ...i, [field]: value } : i))
  }

  // ── Lineage ──
  const getLineage = useCallback((indicatorId: string): IndicatorLineage => {
    if (lineages[indicatorId]) return lineages[indicatorId]
    const ind = byId[indicatorId]
    const deps = (ind?.depends_on ?? []).map(d => byId[d]?.name ?? d).join('、')
    return { dependencies: deps, formula: ind?.computation ?? '', sql_template: '', policy_ref: '' }
  }, [lineages, byId])

  const updateLineage = (indicatorId: string, field: keyof IndicatorLineage, value: string) => {
    setLineages(prev => ({ ...prev, [indicatorId]: { ...getLineage(indicatorId), [field]: value } }))
  }

  // ── Helpers ──
  const resolveIndicator = (fieldName: string): IndicatorDef | null => {
    const id = FIELD_ID_MAP[fieldName] ?? fieldName
    return byId[id] ?? null
  }
  const entityIndicators = (entity: BizObj): IndicatorDef[] =>
    entity.fields.map(f => resolveIndicator(f)).filter(Boolean) as IndicatorDef[]

  // ── Add Entity Form ──────────────────────────────────────────────

  function AddEntityForm() {
    const [name, setName] = useState(''); const [desc, setDesc] = useState(''); const [oid, setOid] = useState('')
    return (
      <div className="rounded-2xl border-2 border-dashed border-blue-300 bg-blue-50/40 p-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
          <div>
            <label className="text-[10px] font-semibold text-slate-500 uppercase mb-1 block">Object ID</label>
            <input value={oid} onChange={e => setOid(e.target.value)} placeholder="例：Drug" className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-100" />
          </div>
          <div>
            <label className="text-[10px] font-semibold text-slate-500 uppercase mb-1 block">中文名</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="例：药品" className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-100" />
          </div>
          <div className="flex items-end gap-2">
            <button onClick={() => { if (name.trim()) addEntity(name.trim(), desc.trim(), oid.trim()) }} disabled={!name.trim()} className="rounded-lg bg-blue-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-40">创建实体</button>
            <button onClick={() => setAddingEntity(false)} className="rounded-lg bg-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-300">取消</button>
          </div>
        </div>
        <div>
          <label className="text-[10px] font-semibold text-slate-500 uppercase mb-1 block">描述</label>
          <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="实体描述…" className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-100" />
        </div>
      </div>
    )
  }

  // ── Add Indicator Form ───────────────────────────────────────────

  function AddIndicatorForm({ entityId }: { entityId: string }) {
    const [iid, setIid] = useState(''); const [name, setName] = useState('')
    const [desc, setDesc] = useState(''); const [cat, setCat] = useState<IndicatorDef['category']>('numeric')
    const [unit, setUnit] = useState('')
    return (
      <div className="rounded-xl border-2 border-dashed border-orange-300 bg-orange-50/30 p-4 ml-2">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2">
          <div>
            <label className="text-[9px] font-semibold text-slate-500 uppercase block mb-0.5">indicator_id</label>
            <input value={iid} onChange={e => setIid(e.target.value)} placeholder="snake_case" className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-orange-200" />
          </div>
          <div>
            <label className="text-[9px] font-semibold text-slate-500 uppercase block mb-0.5">中文名</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="指标名" className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-orange-200" />
          </div>
          <div>
            <label className="text-[9px] font-semibold text-slate-500 uppercase block mb-0.5">分类</label>
            <select value={cat} onChange={e => setCat(e.target.value as any)} className="w-full rounded border border-slate-200 px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-orange-200">
              {CAT_OPTIONS.map(c => <option key={c} value={c}>{CAT_LABEL[c]}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[9px] font-semibold text-slate-500 uppercase block mb-0.5">单位</label>
            <input value={unit} onChange={e => setUnit(e.target.value)} placeholder="元 / %" className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-orange-200" />
          </div>
        </div>
        <div className="mb-2">
          <label className="text-[9px] font-semibold text-slate-500 uppercase block mb-0.5">描述</label>
          <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="指标描述…" className="w-full rounded border border-slate-200 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-orange-200" />
        </div>
        <div className="flex gap-2">
          <button onClick={() => {
            if (!iid.trim() || !name.trim()) return
            addIndicatorToEntity(entityId, {
              indicator_id: iid.trim(), name: name.trim(), description: desc.trim(),
              category: cat, value_type: cat === 'numeric' ? 'float' : 'string', unit: unit.trim(),
              dictionary_ref: null, semantic_tags: [], used_by_strategies: [],
              depends_on: [], computation: null, policy_field: '',
            })
          }} disabled={!iid.trim() || !name.trim()}
            className="rounded-lg bg-orange-500 px-3 py-1 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-40">添加指标</button>
          <button onClick={() => setAddingIndicatorFor(null)} className="rounded-lg bg-slate-200 px-3 py-1 text-xs text-slate-600 hover:bg-slate-300">取消</button>
        </div>
      </div>
    )
  }

  // ── Lineage Panel ────────────────────────────────────────────────

  function LineagePanel({ indicatorId }: { indicatorId: string }) {
    const lin = getLineage(indicatorId)
    return (
      <div className="mt-2 ml-6 pl-3 border-l-2 border-slate-200 space-y-2">
        {LINEAGE_LEVELS.map(lv => (
          <div key={lv.key} className="rounded-lg bg-slate-50/80 px-3 py-2">
            <div className="flex items-center gap-1.5 mb-1">
              <lv.icon className="size-3 text-slate-400" />
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide">{lv.label}</span>
            </div>
            <InlineEdit value={lin[lv.key]} onChange={v => updateLineage(indicatorId, lv.key, v)} placeholder={lv.placeholder} multiline={lv.ml} />
          </div>
        ))}
      </div>
    )
  }

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div className="relative min-h-screen">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.08),transparent_55%)]" />
        <div className="absolute inset-0 opacity-[0.25] [background-image:linear-gradient(to_right,rgba(15,23,42,0.03)_1px,transparent_1px),linear-gradient(to_bottom,rgba(15,23,42,0.03)_1px,transparent_1px)] [background-size:44px_44px]" />
      </div>

      <div className="mx-auto flex w-full max-w-[1000px] flex-col gap-4 p-6">
        {/* Header */}
        <header className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
              <Layers className="mr-1 size-3" /> 语义层
            </span>
          </div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">语义层管理</h2>
        </header>

        {/* Status */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200/70 bg-white/80 px-5 py-2.5 shadow-sm backdrop-blur">
          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
            {status === 'loading' && <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-500 ring-1 ring-slate-200/60"><Loader2 className="size-3 animate-spin" />加载中</span>}
            {status === 'error' && <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-1 text-[11px] font-medium text-red-600 ring-1 ring-red-200/60"><XCircle className="size-3" />加载失败</span>}
            {status === 'loaded' && <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200/60"><CheckCircle2 className="size-3" />已加载</span>}
            <span><strong className="text-slate-700">{allIndicators.length}</strong> 指标</span>
            <span><strong className="text-slate-700">{entities.length}</strong> 实体</span>
          </div>
          <div className="flex gap-2">
            {!addingEntity && (
              <button onClick={() => setAddingEntity(true)} className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors">
                <Plus className="size-3" />新增实体
              </button>
            )}
            <button onClick={refresh} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50">
              <RefreshCw className={`size-3 ${loading ? 'animate-spin' : ''}`} />刷新
            </button>
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-3 rounded-2xl border border-red-200/70 bg-red-50/80 px-5 py-4">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-500" /><p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {/* Parsing flow reference */}
        <div className="rounded-2xl border border-blue-100 bg-blue-50/30 p-4 shadow-sm">
          <h4 className="text-xs font-semibold text-slate-700 mb-2 flex items-center gap-2"><Workflow className="size-3.5 text-blue-500" />标准解析流程</h4>
          <p className="text-[11px] text-slate-500 mb-2">
            用户提问 → 意图识别 → 技能路由（配置所需指标）→ 指标血缘追溯 → SQL 查询 → 政策查询（SQL 结果拼装 Milvus 条件）→ 答案输出
          </p>
          <div className="flex flex-wrap items-center gap-1 text-[10px]">
            {['Question','Intent','Skill','Metric','Lineage','SQL','Policy','Answer'].map((s,i) => (
              <span key={s} className="flex items-center gap-1">{i>0&&<span className="text-blue-300">→</span>}<span className="rounded-md bg-white border border-blue-200 px-2 py-1 text-blue-700 font-medium">{s}</span></span>
            ))}
          </div>
        </div>

        {/* Add Entity Form */}
        {addingEntity && <AddEntityForm />}

        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="size-8 animate-spin text-slate-300" /></div>
        ) : (
          <div className="space-y-4">
            {entities.map(entity => {
              const inds = entityIndicators(entity)
              const isExpanded = expandedEntities[entity.object_id] ?? true
              return (
                <div key={entity.object_id} className="rounded-2xl border border-slate-200/70 bg-white/80 shadow-sm backdrop-blur overflow-hidden group/entity">
                  {/* Entity Header */}
                  <div className="flex items-start gap-3 px-5 py-4">
                    <button type="button" onClick={() => setExpandedEntities(prev => ({ ...prev, [entity.object_id]: !isExpanded }))}
                      className="mt-0.5 shrink-0">
                      {isExpanded ? <ChevronDown className="size-4 text-slate-400" /> : <ChevronRight className="size-4 text-slate-400" />}
                    </button>
                    <Box className="size-5 text-blue-600 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <InlineEdit value={entity.name} onChange={v => updateEntity(entity.object_id, 'name', v)} placeholder="实体名" className="text-sm font-bold" />
                        <div className="group/editable flex items-center gap-1">
                          <InlineEdit value={entity.object_id} onChange={v => updateEntity(entity.object_id, 'object_id', v)} placeholder="object_id" />
                        </div>
                      </div>
                      <InlineEdit value={entity.description} onChange={v => updateEntity(entity.object_id, 'description', v)} placeholder="实体描述" />
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <span className="text-xs text-slate-400">{inds.length} 指标</span>
                      <button onClick={() => deleteEntity(entity.object_id)}
                        className="opacity-0 group-hover/entity:opacity-100 rounded p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 transition-opacity"
                        title="删除实体">
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Entity Body */}
                  {isExpanded && (
                    <div className="border-t border-slate-100 px-5 pb-4 pt-3 space-y-2">
                      {inds.map(ind => {
                        const key = `${entity.object_id}:${ind.indicator_id}`
                        const indExpanded = expandedIndicators[key] ?? false
                        return (
                          <div key={ind.indicator_id} className="rounded-xl border border-slate-100 bg-white group/indicator">
                            <div className="flex items-center gap-2 px-4 py-2.5">
                              <button type="button" onClick={() => setExpandedIndicators(prev => ({ ...prev, [key]: !indExpanded }))}
                                className="shrink-0">
                                {indExpanded ? <ChevronDown className="size-3.5 text-slate-400" /> : <ChevronRight className="size-3.5 text-slate-400" />}
                              </button>
                              <span className={`inline-block size-2 rounded-full shrink-0 ${ind.category==='dimension'?'bg-blue-500':ind.category==='numeric'?'bg-orange-500':ind.category==='condition'?'bg-purple-500':'bg-slate-400'}`} />
                              <code className="text-[10px] text-slate-400 shrink-0 font-mono">
                                <InlineEdit value={ind.indicator_id} onChange={v => updateIndicator(ind.indicator_id, 'indicator_id', v)} placeholder="id" />
                              </code>
                              <span className="text-sm font-semibold text-slate-800">
                                <InlineEdit value={ind.name} onChange={v => updateIndicator(ind.indicator_id, 'name', v)} placeholder="名称" />
                              </span>
                              <span className={`text-[9px] px-1.5 py-0.5 rounded-full border shrink-0 ${CAT_COLORS[ind.category] ?? CAT_COLORS.meta}`}>{CAT_LABEL[ind.category]}</span>
                              {ind.unit && <span className="text-[10px] text-slate-400 shrink-0">{ind.unit}</span>}
                              <button onClick={() => removeIndicatorFromEntity(entity.object_id, ind.indicator_id)}
                                className="ml-auto opacity-0 group-hover/indicator:opacity-100 rounded p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 transition-opacity shrink-0"
                                title="从实体移除">
                                <Trash2 className="size-3" />
                              </button>
                            </div>

                            {indExpanded && (
                              <div className="border-t border-slate-50 px-4 pb-3 pt-2">
                                <InlineEdit value={ind.description} onChange={v => updateIndicator(ind.indicator_id, 'description', v)} placeholder="描述" />
                                <LineagePanel indicatorId={ind.indicator_id} />
                              </div>
                            )}
                          </div>
                        )
                      })}

                      {/* Add Indicator */}
                      {addingIndicatorFor === entity.object_id ? (
                        <AddIndicatorForm entityId={entity.object_id} />
                      ) : (
                        <button onClick={() => setAddingIndicatorFor(entity.object_id)}
                          className="w-full flex items-center justify-center gap-1 rounded-xl border-2 border-dashed border-slate-200 py-2.5 text-xs text-slate-400 hover:border-orange-300 hover:text-orange-600 hover:bg-orange-50/30 transition-colors">
                          <Plus className="size-3" />新增指标
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

      </div>
    </div>
  )
}
