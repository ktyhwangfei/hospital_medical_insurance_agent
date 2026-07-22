'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Database, Layers, Loader2, CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronRight,
  Pencil, Check, X, Plus, Trash2, Search, Settings2,
} from 'lucide-react'
import ValueDomainConfigModal from '../value-domain-config-modal'

// ── Types ───────────────────────────────────────────────────────

interface ObjectSummary { object_code: string; name: string; domain_code: string; status: string }
interface MetricDetail { metric_code: string; name: string; definition: string | null; object_code: string; metric_type: string; semantic_type: string | null; unit: string | null; required: boolean; importance: string; value_domain: string | null; source_object: string | null; source_field: string | null; source_adapter_port: string | null; usage_count: number; quality_score: number; version: string; status: string }
interface SemanticSummary { domains_count: number; objects_count: number; metrics_count: number; mapped_count: number; unmapped_count: number; value_missing_count: number; mapping_rate: number; skill_references: number }
interface ValueDomainInfo { domain_code: string; name: string; description?: string; mapping_count: number; standard_values?: string[] }
interface ValueMappingItem { status: string; domain_code: string; source_value: string; standard_value: string }
type MappingStatus = 'mapped' | 'unmapped' | 'value-missing'
interface EnrichedMetric extends MetricDetail { object_name: string; domain_code: string; mapping_status: MappingStatus }

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'
const STATUS_LABELS: Record<string, string> = { mapped: '已映射', unmapped: '未映射', 'value-missing': '值域缺失' }
const STATUS_ICONS: Record<string, string> = { mapped: '✓', unmapped: '✗', 'value-missing': '⚠' }
const STATUS_COLORS: Record<string, string> = { mapped: 'text-emerald-600', unmapped: 'text-red-600', 'value-missing': 'text-amber-600' }
const STATUS_BG: Record<string, string> = { mapped: 'bg-emerald-50', unmapped: 'bg-red-50', 'value-missing': 'bg-amber-50' }

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  if (!res.ok) { const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` })); throw new Error(err.detail || `请求失败`) }
  return res.json() as Promise<T>
}
function determineMappingStatus(m: MetricDetail): MappingStatus {
  if (!m.source_field) return 'unmapped'
  if (m.semantic_type === 'Enum' && !m.value_domain) return 'value-missing'
  return 'mapped'
}

interface DiscoveryField { field_name: string; table_name: string; data_type: string; sample_values?: string[] | null }
interface FieldOption { label: string; value: string; table: string }

// ── Field Mapping Row ──────────────────────────────────────────

function FieldMappingRow({ metric, fieldOptions, fieldSamples, onFieldSave, onOpenVD }: { metric: EnrichedMetric; fieldOptions: FieldOption[]; fieldSamples: Map<string, string[]>; onFieldSave: (code: string, field: string | null, table: string | null) => void; onOpenVD: (m: EnrichedMetric) => void }) {
  const [editing, setEditing] = useState(false)
  const [tableSearch, setTableSearch] = useState('')
  const [fieldSearch, setFieldSearch] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [selectedField, setSelectedField] = useState(metric.source_field || '')
  const [saving, setSaving] = useState(false)
  const [aiMatches, setAiMatches] = useState<FieldOption[]>([])
  const [aiLoading, setAiLoading] = useState(false)

  const tables = useMemo(() => {
    const set = [...new Set(fieldOptions.map((f) => f.table))].sort()
    if (!tableSearch) return set
    return set.filter((t) => t.toLowerCase().includes(tableSearch.toLowerCase()))
  }, [fieldOptions, tableSearch])

  const filteredFields = useMemo(() => {
    let list = selectedTable ? fieldOptions.filter((f) => f.table === selectedTable) : fieldOptions
    if (fieldSearch) list = list.filter((f) => f.label.toLowerCase().includes(fieldSearch.toLowerCase()))
    return list.slice(0, 50)
  }, [fieldOptions, selectedTable, fieldSearch])

  // Display: table.field format. Falls back to source_object.source_field if source_field lacks prefix
  const displayText = useMemo(() => {
    if (!metric.source_field) return ''
    if (metric.source_field.includes('.')) return metric.source_field
    if (metric.source_object) return `${metric.source_object}.${metric.source_field}`
    return metric.source_field
  }, [metric])

  const handleSave = useCallback(async () => {
    setSaving(true)
    const val = selectedTable && selectedField ? `${selectedTable}.${selectedField}` : (selectedField || null)
    try {
      await fetchJson(`${SEMANTIC_API}/metrics/${encodeURIComponent(metric.metric_code)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_field: val }) })
      onFieldSave(metric.metric_code, val, selectedTable)
      setEditing(false)
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [selectedField, selectedTable, metric.metric_code, onFieldSave])

  const handleAiMatch = useCallback(async () => {
    setAiLoading(true)
    try {
      const res = await fetchJson<{ matches: { field_name: string; table_name: string; score: number }[] }>(
        `${SEMANTIC_API}/field-match`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: metric.name, definition: metric.definition || '' }) }
      )
      setAiMatches(res.matches.map((m) => ({ label: m.field_name, value: m.field_name, table: m.table_name })))
    } catch {
      // Fallback: fuzzy match by name
      const q = metric.name.toLowerCase()
      setAiMatches(fieldOptions.filter((f) => f.label.toLowerCase().includes(q) || q.includes(f.label.toLowerCase())).slice(0, 5))
    }
    setAiLoading(false)
  }, [metric.name, metric.definition, fieldOptions])

  return (
    <>
      <tr className="group border-b border-slate-200 hover:bg-slate-50">
      <td className="px-3 py-3">
        <span className="font-mono text-[11px] text-slate-700">{metric.object_code}</span>
      </td>
      <td className="px-3 py-3"><span className="text-xs text-slate-600">{metric.object_name}</span></td>
      <td className="px-3 py-3">
        <span className="font-mono text-[11px] text-slate-600">{metric.metric_code.split('.').pop()}</span>
      </td>
      <td className="px-3 py-3">
        <span className="text-sm font-medium text-slate-800">{metric.name}</span>
      </td>
      <td className="px-3 py-3 relative">
        {editing ? (
          <div className="absolute left-0 top-full z-20 mt-1 w-[420px] rounded-lg border border-slate-300 bg-white p-3 shadow-xl">
            {/* Table selector */}
            <div className="mb-2">
              <div className="mb-1 text-[10px] text-slate-400">选择表</div>
              <div className="flex flex-wrap items-center gap-1">
                <Input value={tableSearch} onChange={(e) => { setTableSearch(e.target.value); setSelectedTable(''); setSelectedField('') }} placeholder="搜索表名..." className="h-7 w-32 text-[11px]" autoFocus />
                {tables.slice(0, 6).map((t) => (
                  <button key={t} onClick={() => { setSelectedTable(t); setTableSearch(t); setSelectedField('') }}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${selectedTable === t ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{t}</button>
                ))}
              </div>
            </div>
            {/* Field selector */}
            {selectedTable && (
              <div className="mb-2">
                <div className="mb-1 text-[10px] text-slate-400">选择字段 ({selectedTable})</div>
                <div className="flex items-center gap-1 mb-1">
                  <Input value={fieldSearch} onChange={(e) => setFieldSearch(e.target.value)} placeholder="搜索字段..." className="h-7 w-28 text-[11px] font-mono" />
                  <button onClick={handleAiMatch} disabled={aiLoading} className="rounded bg-purple-50 px-2 py-1 text-[10px] font-medium text-purple-600 hover:bg-purple-100 disabled:opacity-50">
                    {aiLoading ? '匹配中...' : 'AI 匹配'}
                  </button>
                </div>
                <div className="max-h-40 overflow-y-auto space-y-0.5">
                  {aiMatches.length > 0 && (
                    <div className="border-b border-purple-100 pb-1 mb-1">
                      <div className="px-0.5 text-[10px] text-purple-500 font-medium">AI 推荐</div>
                      {aiMatches.map((fo) => (
                        <button key={`ai-${fo.value}`} onClick={() => { setSelectedField(fo.value); setSelectedTable(fo.table); setFieldSearch(fo.label) }}
                          className="block w-full px-1.5 py-0.5 text-left text-[10px] font-mono text-purple-700 hover:bg-purple-50 rounded">
                          {fo.table}.{fo.label}
                        </button>
                      ))}
                    </div>
                  )}
                  {filteredFields.slice(0, 15).map((fo) => (
                    <button key={fo.value} onClick={() => { setSelectedField(fo.value); setFieldSearch(fo.label) }}
                      className="block w-full px-1.5 py-0.5 text-left text-[10px] font-mono text-slate-600 hover:bg-blue-50 rounded">
                      {fo.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* Actions */}
            <div className="flex items-center justify-between pt-1 border-t border-slate-100">
              {selectedField ? (
                <span className="text-xs font-mono text-blue-700">{selectedTable}.{selectedField}</span>
              ) : <span className="text-[10px] text-slate-400">未选择</span>}
              <div className="flex gap-1">
                <button onClick={() => { setEditing(false); setTableSearch(''); setSelectedTable(''); setSelectedField(''); setAiMatches([]) }}
                  className="rounded px-2 py-1 text-[10px] text-slate-500 hover:bg-slate-100">取消</button>
                <button onClick={handleSave} disabled={saving || !selectedField}
                  className="rounded bg-blue-500 px-3 py-1 text-[10px] font-medium text-white hover:bg-blue-600 disabled:opacity-40">
                  {saving ? '保存中...' : '确认'}
                </button>
              </div>
            </div>
          </div>
        ) : null}
        <div className="group flex items-center gap-1 cursor-pointer" onClick={() => { setEditing(true) }}>
          {metric.source_field ? <span className="font-mono text-xs text-slate-700">{displayText}</span> : <span className="text-xs text-slate-400 italic">点击映射</span>}
          <Pencil className="h-3 w-3 shrink-0 opacity-0 group-hover:opacity-100 text-slate-400" />
        </div>
      </td>
      <td className="px-3 py-3">{metric.value_domain ? (
        <button onClick={() => onOpenVD(metric)} className="font-mono text-[10px] text-purple-600 bg-purple-50 hover:bg-purple-100 rounded px-1.5 py-0.5 cursor-pointer inline-flex items-center gap-0.5" title="配置值域映射">
          {metric.value_domain}<Settings2 className="h-2.5 w-2.5 opacity-50" />
        </button>
      ) : <span className="text-xs text-slate-400">-</span>}</td>
      <td className="px-3 py-3"><span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_BG[metric.mapping_status]} ${STATUS_COLORS[metric.mapping_status]}`}><span>{STATUS_ICONS[metric.mapping_status]}</span><span>{STATUS_LABELS[metric.mapping_status]}</span></span></td>
    </tr>
    </>
  )
}

// ── Value Domain Card ───────────────────────────────────────────

function ValueDomainCard({ vd, onDelete, onRefresh }: { vd: ValueDomainInfo; onDelete: (code: string) => void; onRefresh: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [mappings, setMappings] = useState<ValueMappingItem[]>([])
  const [loadingMappings, setLoadingMappings] = useState(false)
  const [newSource, setNewSource] = useState('')
  const [newStandard, setNewStandard] = useState('')
  const [saving, setSaving] = useState(false)

  const loadMappings = useCallback(async () => {
    setLoadingMappings(true)
    try {
      const res = await fetchJson<{ mappings: ValueMappingItem[] }>(`${SEMANTIC_API}/value-domains/${encodeURIComponent(vd.domain_code)}/mappings`)
      setMappings(res.mappings || [])
    } catch { setMappings([]) }
    setLoadingMappings(false)
  }, [vd.domain_code])

  useEffect(() => { if (expanded) loadMappings() }, [expanded, loadMappings])

  const handleAddMapping = useCallback(async () => {
    if (!newSource.trim() || !newStandard.trim()) return
    setSaving(true)
    try {
      await fetchJson(`${SEMANTIC_API}/value-domain/mapping`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ domain_code: vd.domain_code, source_value: newSource.trim(), standard_value: newStandard.trim() }) })
      setNewSource(''); setNewStandard('')
      loadMappings(); onRefresh()
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [newSource, newStandard, vd.domain_code, loadMappings, onRefresh])

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-4 px-5 py-3 cursor-pointer" onClick={() => setExpanded((p) => !p)}>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-purple-50 text-purple-600"><Layers className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1"><span className="text-sm font-medium text-slate-800">{vd.name}</span><span className="ml-2 font-mono text-[10px] text-slate-400">{vd.domain_code}</span><span className="ml-2 text-[10px] text-slate-500">{vd.mapping_count} 条映射</span></div>
        <button onClick={(e) => { e.stopPropagation(); onDelete(vd.domain_code) }} className="rounded p-1 text-slate-400 hover:text-red-500 hover:bg-red-50" title="删除值域"><Trash2 className="h-3.5 w-3.5" /></button>
        {expanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
      </div>
      {expanded && (
        <div className="border-t border-slate-200 px-5 py-3 space-y-3">
          {loadingMappings ? <Loader2 className="mx-auto h-4 w-4 animate-spin text-slate-400" /> :
           mappings.length === 0 ? <p className="text-center text-[11px] text-slate-400">暂无映射，请在下方添加</p> : (
            <table className="w-full text-left text-xs">
              <thead><tr className="border-b border-slate-100 text-[10px] text-slate-400"><th className="py-1 font-medium">源值</th><th className="py-1 font-medium"></th><th className="py-1 font-medium">标准值</th><th className="py-1"></th></tr></thead>
              <tbody>{mappings.map((m) => (
                <tr key={m.source_value} className="border-b border-slate-50"><td className="py-1.5 font-mono text-slate-700">{m.source_value}</td><td className="py-1.5 text-center text-slate-400">→</td><td className="py-1.5 text-slate-700">{m.standard_value}</td><td className="py-1.5 text-right"><button onClick={async () => { try { await fetch(`${SEMANTIC_API}/value-domains/${encodeURIComponent(vd.domain_code)}/mappings/${encodeURIComponent(m.source_value)}`, { method: 'DELETE' }); loadMappings(); onRefresh() } catch (err: any) { alert(err.message) } }} className="text-red-400 hover:text-red-600"><X className="h-3 w-3" /></button></td></tr>
              ))}</tbody>
            </table>
          )}
          {/* Add new mapping */}
          <div className="flex items-center gap-2">
            <Input value={newSource} onChange={(e) => setNewSource(e.target.value)} placeholder="源值" className="h-7 w-32 text-xs font-mono" />
            <span className="text-xs text-slate-400">→</span>
            <Input value={newStandard} onChange={(e) => setNewStandard(e.target.value)} placeholder="标准值" className="h-7 w-32 text-xs font-mono" />
            <button onClick={handleAddMapping} disabled={saving || !newSource.trim() || !newStandard.trim()} className="rounded-md bg-purple-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-purple-600 disabled:opacity-40">{saving ? '...' : '添加'}</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────

export default function MappingCenterPage() {
  const [metrics, setMetrics] = useState<EnrichedMetric[]>([])
  const [summary, setSummary] = useState<SemanticSummary | null>(null)
  const [valueDomains, setValueDomains] = useState<ValueDomainInfo[]>([])
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null)
  const [showUnmappedOnly, setShowUnmappedOnly] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [fieldOptions, setFieldOptions] = useState<FieldOption[]>([])
  const [fieldSamples, setFieldSamples] = useState<Map<string, string[]>>(new Map())
  // Value domain creation
  const [showAddVD, setShowAddVD] = useState(false)
  const [newVDCode, setNewVDCode] = useState(''); const [newVDName, setNewVDName] = useState('')
  const [savingVD, setSavingVD] = useState(false)
  const [vdConfigMetric, setVdConfigMetric] = useState<EnrichedMetric | null>(null)

  const fetchData = useCallback(() => {
    setLoading(true); setError(null)
    Promise.all([
      (async () => {
        const objects = await fetchJson<ObjectSummary[]>(`${SEMANTIC_API}/objects`)
        const objectMap = new Map(objects.map((o) => [o.object_code, o]))
        const metricsArrays = await Promise.all(objects.map((obj) => fetchJson<MetricDetail[]>(`${SEMANTIC_API}/metrics?object_code=${encodeURIComponent(obj.object_code)}`)))
        const allCodes = metricsArrays.flat().map((m) => m.metric_code)
        const details = (await Promise.all(allCodes.map((code) => fetchJson<MetricDetail>(`${SEMANTIC_API}/metrics/${encodeURIComponent(code)}`).catch(() => null)))).filter((d): d is MetricDetail => d !== null)
        return details.map((m) => { const obj = objectMap.get(m.object_code); return { ...m, object_name: obj?.name ?? m.object_code, domain_code: obj?.domain_code ?? '', mapping_status: determineMappingStatus(m) } })
      })(),
      fetchJson<SemanticSummary>(`${SEMANTIC_API}/summary`),
      fetchJson<ValueDomainInfo[]>(`${SEMANTIC_API}/value-domains`).catch(() => [] as ValueDomainInfo[]),
      fetchJson<{ fields: DiscoveryField[] }>(`${SEMANTIC_API}/discovery/results`).catch(() => ({ fields: [] as DiscoveryField[] })),
    ]).then(([mets, sum, vds, disc]) => { setMetrics(mets); setSummary(sum); setValueDomains(vds); setFieldOptions((disc.fields || []).map((f: DiscoveryField) => ({ label: f.field_name, value: f.field_name, table: f.table_name }))); const samples = new Map<string, string[]>(); (disc.fields || []).forEach((f: DiscoveryField) => { if (f.sample_values?.length) samples.set(`${f.table_name}.${f.field_name}`, f.sample_values); }); setFieldSamples(samples); setLoading(false) })
      .catch((err: Error) => { setError(err.message); setLoading(false) })
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const handleFieldSave = useCallback((code: string, field: string | null, _table: string | null) => { setMetrics((prev) => prev.map((m) => m.metric_code === code ? { ...m, source_field: field, mapping_status: determineMappingStatus({ ...m, source_field: field }) } : m)) }, [])
  const handleDeleteVD = useCallback(async (code: string) => { try { await fetchJson(`${SEMANTIC_API}/value-domains/${encodeURIComponent(code)}`, { method: 'DELETE' }); setValueDomains((prev) => prev.filter((v) => v.domain_code !== code)) } catch (err: any) { alert(err.message) } }, [])
  const handleCreateVD = useCallback(async () => { if (!newVDCode.trim() || !newVDName.trim()) return; setSavingVD(true); try { await fetchJson(`${SEMANTIC_API}/value-domains`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ domain_code: newVDCode.trim(), name: newVDName.trim() }) }); setNewVDCode(''); setNewVDName(''); setShowAddVD(false); fetchData() } catch (err: any) { alert(err.message) }; setSavingVD(false) }, [newVDCode, newVDName, fetchData])

  const filteredMetrics = useMemo(() => { let list = metrics; if (showUnmappedOnly) list = list.filter((m) => m.mapping_status !== 'mapped'); if (searchText.trim()) { const q = searchText.trim().toLowerCase(); list = list.filter((m) => m.name.toLowerCase().includes(q) || m.metric_code.toLowerCase().includes(q) || (m.source_field || '').toLowerCase().includes(q)) } return list }, [metrics, showUnmappedOnly, searchText])

  if (loading) return <div className="flex flex-col gap-6"><div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => (<Card key={i}><CardContent className="px-4 py-4"><div className="h-3 w-16 animate-pulse rounded bg-slate-200" /><div className="mt-2 h-6 w-12 animate-pulse rounded bg-slate-200" /></CardContent></Card>))}</div><div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => (<div key={i} className="h-10 w-full animate-pulse rounded bg-slate-200" />))}</div></div>
  if (error) return <Alert variant="destructive"><AlertTitle>加载失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between"><div><p className="text-sm text-slate-500">字段映射 + 值域管理</p></div></div>

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">总指标</div><div className="text-xl font-bold tabular-nums text-blue-600">{metrics.length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">已映射</div><div className="text-xl font-bold tabular-nums text-emerald-600">{metrics.filter((m) => m.mapping_status === 'mapped').length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">未映射</div><div className="text-xl font-bold tabular-nums text-red-600">{metrics.filter((m) => m.mapping_status === 'unmapped').length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">值域数</div><div className="text-xl font-bold tabular-nums text-purple-600">{valueDomains.length}</div></CardContent></Card>
      </div>

      {/* ══════════ Section 1: 字段映射 ══════════ */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-slate-800">字段映射</h3>
          <div className="flex items-center gap-3">
            <div className="relative"><Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-400" /><Input type="text" placeholder="搜索..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="h-7 w-40 rounded-md border border-slate-300 pl-7 text-xs" /></div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600"><input type="checkbox" checked={showUnmappedOnly} onChange={(e) => setShowUnmappedOnly(e.target.checked)} className="h-3.5 w-3.5 rounded border-slate-300" />只看未映射</label>
            <span className="text-xs text-slate-500">共 <span className="font-mono text-slate-600">{filteredMetrics.length}</span> 条</span>
          </div>
        </div>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left" style={{ overflow: 'visible' }}>
            <thead><tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500"><th className="px-3 py-2.5 font-medium">对象英文</th><th className="px-3 py-2.5 font-medium">对象中文</th><th className="px-3 py-2.5 font-medium">指标英文</th><th className="px-3 py-2.5 font-medium">指标中文</th><th className="px-3 py-2.5 font-medium">源字段</th><th className="px-3 py-2.5 font-medium">值域</th><th className="px-3 py-2.5 font-medium">状态</th></tr></thead>
            <tbody>{filteredMetrics.length === 0 ? (<tr><td colSpan={7} className="px-3 py-10 text-center text-sm text-slate-400">无匹配数据</td></tr>) : filteredMetrics.map((m) => <FieldMappingRow key={m.metric_code} metric={m} fieldOptions={fieldOptions} fieldSamples={fieldSamples} onFieldSave={handleFieldSave} onOpenVD={setVdConfigMetric} />)}</tbody>
          </table>
        </div>
      </div>

      {/* ══════════ Section 2: 值域管理 ══════════ */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-slate-800">值域管理</h3>
          <button onClick={() => setShowAddVD((p) => !p)} className="flex items-center gap-1 rounded-md bg-purple-50 px-2.5 py-1.5 text-xs font-medium text-purple-600 hover:bg-purple-100"><Plus className="h-3.5 w-3.5" />新建值域</button>
        </div>
        {showAddVD && (
          <Card className="mb-3 border-2 border-dashed border-purple-300 bg-purple-50/30 shadow-none">
            <CardContent className="flex items-center gap-3 px-5 py-3">
              <Input value={newVDCode} onChange={(e) => setNewVDCode(e.target.value)} placeholder="值域编码 (如 HOSPITAL_LEVEL)" className="h-8 w-48 text-xs font-mono" />
              <Input value={newVDName} onChange={(e) => setNewVDName(e.target.value)} placeholder="值域名称" className="h-8 w-40 text-xs" />
              <button onClick={handleCreateVD} disabled={savingVD || !newVDCode.trim() || !newVDName.trim()} className="rounded-md bg-purple-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:opacity-40">{savingVD ? '创建中...' : '创建'}</button>
              <button onClick={() => setShowAddVD(false)} className="rounded-md px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200">取消</button>
            </CardContent>
          </Card>
        )}
        <div className="flex flex-col gap-2">
          {valueDomains.length === 0 ? <p className="py-8 text-center text-sm text-slate-400">暂无值域</p> : valueDomains.map((vd) => <ValueDomainCard key={vd.domain_code} vd={vd} onDelete={handleDeleteVD} onRefresh={fetchData} />)}
        </div>
      </div>
      {vdConfigMetric?.value_domain && (
        <ValueDomainConfigModal
          valueDomainCode={vdConfigMetric.value_domain}
          sourceValues={vdConfigMetric.source_field ? fieldSamples.get(vdConfigMetric.source_field) || undefined : undefined}
          onClose={() => setVdConfigMetric(null)}
          onSaved={() => {}}
        />
      )}
    </div>
  )
}
