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
import { semanticReviewJson, updateSemanticMetric } from '@/lib/policy-knowledge-api'

// ── Types ───────────────────────────────────────────────────────

interface ObjectSummary { object_code: string; name: string; domain_code: string; status: string; current_version?: string | null }
interface MetricDetail { metric_code: string; name: string; definition: string | null; object_code: string; metric_type: string; semantic_type: string | null; indexed: boolean; schema_version: number; unit: string | null; required: boolean; importance: string; value_domain: string | null; source_object: string | null; source_field: string | null; source_adapter_port: string | null; usage_count: number; quality_score: number; version: string; status: string }
interface SemanticSummary { domains_count: number; objects_count: number; metrics_count: number; mapped_count: number; unmapped_count: number; value_missing_count: number; mapping_rate: number; skill_references: number }
interface ValueDomainInfo { domain_code: string; name: string; description?: string; mapping_count: number; standard_values?: string[] }
interface ValueMappingItem { status: string; domain_code: string; source_value: string; standard_value: string }
interface QueryModel {
  object_code: string
  datasets: { dataset_code: string; object_code: string; datasource_id: string; name: string; schema_name: string; table_name: string; status: 'draft' | 'published' }[]
  keys: { key_code: string; dataset_code: string; entity_code: string; key_type: string; columns: string[] }[]
  fields: { field_code: string; dataset_code: string; column_name: string; name: string; field_role: string; semantic_type: string; value_domain: string | null; nullable: boolean; status: 'draft' | 'published' }[]
  relations: { relation_code: string; object_code: string; from_dataset: string; from_key: string; to_dataset: string; to_key: string; cardinality: string; status: 'draft' | 'published' }[]
  quality_rules: { rule_code: string; object_code: string; rule_type: string; target_dataset_or_relation: string; severity: string; parameters: Record<string, unknown>; status: 'draft' | 'published' }[]
  preferred_relation_paths: { from_dataset: string; to_dataset: string; relation_codes: string[] }[]
  validation_issues: string[]
  queryable: boolean
}
type ModelSection = 'overview' | 'datasets' | 'keys' | 'fields' | 'relations' | 'quality' | 'json'
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
function queryModelDocument(model: QueryModel) {
  return {
    datasets: model.datasets,
    keys: model.keys,
    fields: model.fields,
    relations: model.relations,
    quality_rules: model.quality_rules,
    preferred_relation_paths: model.preferred_relation_paths,
  }
}
function determineMappingStatus(m: MetricDetail): MappingStatus {
  if (!m.source_field) return 'unmapped'
  if (m.semantic_type === 'Enum' && !m.value_domain) return 'value-missing'
  return 'mapped'
}

interface DiscoveryField { field_name: string; table_name: string; data_type: string; sample_values?: string[] | null }
interface FieldOption { label: string; value: string; table: string }

// ── Field Mapping Row ──────────────────────────────────────────

function FieldMappingRow({ metric, fieldOptions, fieldSamples, onFieldSave, onOpenVD }: { metric: EnrichedMetric; fieldOptions: FieldOption[]; fieldSamples: Map<string, string[]>; onFieldSave: (code: string, field: string | null, table: string | null, schemaVersion: number) => void; onOpenVD: (m: EnrichedMetric) => void }) {
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
      const response = await updateSemanticMetric(metric.metric_code, metric, { source_field: val })
      onFieldSave(metric.metric_code, val, selectedTable, response.schema_version)
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
      await semanticReviewJson(`${SEMANTIC_API}/value-domain/mapping`, 'POST', { domain_code: vd.domain_code, source_value: newSource.trim(), standard_value: newStandard.trim() })
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
                <tr key={m.source_value} className="border-b border-slate-50"><td className="py-1.5 font-mono text-slate-700">{m.source_value}</td><td className="py-1.5 text-center text-slate-400">→</td><td className="py-1.5 text-slate-700">{m.standard_value}</td><td className="py-1.5 text-right"><button onClick={async () => { try { await semanticReviewJson(`${SEMANTIC_API}/value-domains/${encodeURIComponent(vd.domain_code)}/mappings/${encodeURIComponent(m.source_value)}`, 'DELETE'); loadMappings(); onRefresh() } catch (err: any) { alert(err.message) } }} className="text-red-400 hover:text-red-600"><X className="h-3 w-3" /></button></td></tr>
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
  const [objects, setObjects] = useState<ObjectSummary[]>([])
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
  const [selectedObject, setSelectedObject] = useState('')
  const [queryModel, setQueryModel] = useState<QueryModel | null>(null)
  const [queryModelText, setQueryModelText] = useState('')
  const [modelSection, setModelSection] = useState<ModelSection>('overview')
  const [modelDirty, setModelDirty] = useState(false)
  const [savingModel, setSavingModel] = useState(false)

  const loadQueryModel = useCallback(async (objectCode: string) => {
    if (!objectCode) return
    try {
      const model = await fetchJson<QueryModel>(`${SEMANTIC_API}/objects/${encodeURIComponent(objectCode)}/query-model`)
      setQueryModel(model)
      setQueryModelText(JSON.stringify({ datasets: model.datasets, keys: model.keys, fields: model.fields, relations: model.relations, quality_rules: model.quality_rules, preferred_relation_paths: model.preferred_relation_paths }, null, 2))
      setModelDirty(false)
      setModelSection('overview')
    } catch (err: any) { setError(err.message) }
  }, [])

  const fetchData = useCallback(() => {
    setLoading(true); setError(null)
    Promise.all([
      (async () => {
        const objectList = await fetchJson<ObjectSummary[]>(`${SEMANTIC_API}/objects`)
        setObjects(objectList)
        const modelEntries = await Promise.all(objectList.map(async (object) => [
          object.object_code,
          await fetchJson<QueryModel>(`${SEMANTIC_API}/objects/${encodeURIComponent(object.object_code)}/query-model`).catch(() => null),
        ] as const))
        const firstQueryable = modelEntries.find(([code, model]) => (
          model?.queryable && objectList.find((object) => object.object_code === code)?.current_version
        ))?.[0]
        setSelectedObject((current) => (
          current && objectList.some((object) => object.object_code === current)
            ? current
            : firstQueryable || objectList[0]?.object_code || ''
        ))
        const objectMap = new Map(objectList.map((o) => [o.object_code, o]))
        const metricsArrays = await Promise.all(objectList.map((obj) => fetchJson<MetricDetail[]>(`${SEMANTIC_API}/metrics?object_code=${encodeURIComponent(obj.object_code)}`)))
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
  useEffect(() => { loadQueryModel(selectedObject) }, [selectedObject, loadQueryModel])

  const handleFieldSave = useCallback((code: string, field: string | null, _table: string | null, schemaVersion: number) => { setMetrics((prev) => prev.map((m) => m.metric_code === code ? { ...m, source_field: field, schema_version: schemaVersion, mapping_status: determineMappingStatus({ ...m, source_field: field }) } : m)) }, [])
  const handleDeleteVD = useCallback(async (code: string) => { try { await semanticReviewJson(`${SEMANTIC_API}/value-domains/${encodeURIComponent(code)}`, 'DELETE'); setValueDomains((prev) => prev.filter((v) => v.domain_code !== code)) } catch (err: any) { alert(err.message) } }, [])
  const handleCreateVD = useCallback(async () => { if (!newVDCode.trim() || !newVDName.trim()) return; setSavingVD(true); try { await semanticReviewJson(`${SEMANTIC_API}/value-domains`, 'POST', { domain_code: newVDCode.trim(), name: newVDName.trim() }); setNewVDCode(''); setNewVDName(''); setShowAddVD(false); fetchData() } catch (err: any) { alert(err.message) }; setSavingVD(false) }, [newVDCode, newVDName, fetchData])
  const updateQueryModel = useCallback((update: (current: QueryModel) => QueryModel) => {
    setQueryModel((current) => current ? update(current) : current)
    setModelDirty(true)
  }, [])
  const changeSelectedObject = useCallback((next: string) => {
    if (modelDirty && !window.confirm('当前查询模型有未保存修改，确定放弃并切换吗？')) return
    setModelDirty(false)
    setSelectedObject(next)
  }, [modelDirty])
  const changeModelSection = useCallback((section: ModelSection) => {
    if (section === 'json' && queryModel) setQueryModelText(JSON.stringify(queryModelDocument(queryModel), null, 2))
    setModelSection(section)
  }, [queryModel])
  const handleSaveQueryModel = useCallback(async () => {
    if (!selectedObject || !queryModel) return
    setSavingModel(true)
    try {
      const document = modelSection === 'json' ? JSON.parse(queryModelText) : queryModelDocument(queryModel)
      const saved = await semanticReviewJson<QueryModel>(`${SEMANTIC_API}/objects/${encodeURIComponent(selectedObject)}/query-model`, 'PUT', document)
      setQueryModel(saved)
      setModelDirty(false)
      setQueryModelText(JSON.stringify(queryModelDocument(saved), null, 2))
    } catch (err: any) { alert(err.message) }
    setSavingModel(false)
  }, [modelSection, queryModel, queryModelText, selectedObject])

  const objectMetrics = useMemo(() => metrics.filter((metric) => metric.object_code === selectedObject), [metrics, selectedObject])
  const filteredMetrics = useMemo(() => { let list = objectMetrics; if (showUnmappedOnly) list = list.filter((m) => m.mapping_status !== 'mapped'); if (searchText.trim()) { const q = searchText.trim().toLowerCase(); list = list.filter((m) => m.name.toLowerCase().includes(q) || m.metric_code.toLowerCase().includes(q) || (m.source_field || '').toLowerCase().includes(q)) } return list }, [objectMetrics, showUnmappedOnly, searchText])

  if (loading) return <div className="flex flex-col gap-6"><div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => (<Card key={i}><CardContent className="px-4 py-4"><div className="h-3 w-16 animate-pulse rounded bg-slate-200" /><div className="mt-2 h-6 w-12 animate-pulse rounded bg-slate-200" /></CardContent></Card>))}</div><div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => (<div key={i} className="h-10 w-full animate-pulse rounded bg-slate-200" />))}</div></div>
  if (error) return <Alert variant="destructive"><AlertTitle>加载失败</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between"><div><p className="text-sm text-slate-500">查询模型 + 字段映射 + 值域管理</p></div></div>

      <Card className="border-slate-200 bg-white shadow-sm">
        <CardHeader className="pb-3"><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle className="text-base">查询模型工作台</CardTitle><p className="mt-1 text-xs text-slate-500">数据集绑定物理表或稳定视图，主键定义每行所代表的业务实体。</p></div><div className="flex items-center gap-2"><label htmlFor="query-model-object" className="sr-only">业务对象</label><select id="query-model-object" aria-label="业务对象" value={selectedObject} onChange={(event) => changeSelectedObject(event.target.value)} className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs">{objects.map((item) => <option key={item.object_code} value={item.object_code}>{item.name} ({item.object_code})</option>)}</select><button type="button" onClick={handleSaveQueryModel} disabled={savingModel || !modelDirty} className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40">{savingModel ? '保存中...' : '校验并保存'}</button></div></div></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">{([['overview', '概览'], ['datasets', '数据集'], ['keys', '键与行粒度'], ['fields', '语义字段'], ['relations', '关系'], ['quality', '质量规则'], ['json', '高级 JSON']] as [ModelSection, string][]).map(([section, label]) => <button type="button" key={section} onClick={() => changeModelSection(section)} className={`rounded-md px-3 py-1.5 text-xs ${modelSection === section ? 'bg-white font-medium text-blue-700 shadow-sm' : 'text-slate-600 hover:bg-white/70'}`}>{label}</button>)}</div>
          {modelSection === 'overview' && queryModel && <><div className="grid grid-cols-2 gap-3 sm:grid-cols-5"><div><p className="text-[11px] text-slate-500">数据集</p><p className="font-bold text-blue-600">{queryModel.datasets.length}</p></div><div><p className="text-[11px] text-slate-500">键</p><p className="font-bold text-cyan-600">{queryModel.keys.length}</p></div><div><p className="text-[11px] text-slate-500">语义字段</p><p className="font-bold text-purple-600">{queryModel.fields.length}</p></div><div><p className="text-[11px] text-slate-500">关系</p><p className="font-bold text-emerald-600">{queryModel.relations.length}</p></div><div><p className="text-[11px] text-slate-500">模型健康</p><p className={queryModel.queryable ? 'font-medium text-emerald-600' : 'font-medium text-red-600'}>{queryModel.queryable ? '可查询' : '不可查询'}</p></div></div>{queryModel.validation_issues.length > 0 && queryModel.datasets.length > 0 && <Alert variant="destructive"><AlertTitle>模型校验未通过</AlertTitle><AlertDescription><ul className="list-disc pl-4">{queryModel.validation_issues.map((issue) => <li key={issue}>{issue}</li>)}</ul></AlertDescription></Alert>}{queryModel.datasets.length === 0 ? <div className="rounded-lg border border-dashed border-blue-300 bg-blue-50/50 p-6 text-center"><Database className="mx-auto h-8 w-8 text-blue-500" /><h3 className="mt-2 text-sm font-medium text-slate-800">从一个数据集开始</h3><p className="mt-1 text-xs text-slate-500">绑定表或视图 → 定义主键和每行实体 → 登记字段与覆盖规则</p><button type="button" onClick={() => { updateQueryModel((model) => ({ ...model, datasets: [...model.datasets, { dataset_code: `${selectedObject}_dataset`, object_code: selectedObject, datasource_id: 'insurance_db', schema_name: 'dbo', table_name: '', name: '新数据集', status: 'draft' }] })); setModelSection('datasets') }} className="mt-4 rounded-md bg-blue-600 px-3 py-2 text-xs font-medium text-white">添加数据集</button></div> : <div className="overflow-x-auto rounded-md border border-slate-200"><table className="w-full text-left text-xs"><thead><tr className="bg-slate-50 text-slate-500"><th className="px-3 py-2">数据集</th><th className="px-3 py-2">物理来源</th><th className="px-3 py-2">每行代表</th></tr></thead><tbody>{queryModel.datasets.map((dataset) => { const primary = queryModel.keys.find((key) => key.dataset_code === dataset.dataset_code && key.key_type === 'primary'); return <tr key={dataset.dataset_code} className="border-t border-slate-100"><td className="px-3 py-2"><span className="font-medium">{dataset.name}</span><span className="ml-2 font-mono text-[10px] text-slate-400">{dataset.dataset_code}</span></td><td className="px-3 py-2 font-mono text-[11px]">{dataset.datasource_id} / {dataset.schema_name}.{dataset.table_name}</td><td className="px-3 py-2">{primary ? <><span>{primary.entity_code}</span><span className="ml-2 font-mono text-[10px] text-slate-400">{primary.columns.join(' + ')}</span></> : <span className="text-red-500">未定义主键</span>}</td></tr> })}</tbody></table></div>}</>}
          {modelSection === 'datasets' && queryModel && <div className="space-y-3"><div className="flex items-center justify-between"><p className="text-xs text-slate-500">一个数据集对应已登记的物理表或稳定视图。</p><button type="button" onClick={() => updateQueryModel((model) => ({ ...model, datasets: [...model.datasets, { dataset_code: `${selectedObject}_dataset_${model.datasets.length + 1}`, object_code: selectedObject, datasource_id: 'insurance_db', schema_name: 'dbo', table_name: '', name: '新数据集', status: 'draft' }] }))} className="inline-flex items-center gap-1 text-xs font-medium text-blue-600"><Plus className="h-3.5 w-3.5" />添加数据集</button></div>{queryModel.datasets.map((dataset, index) => <div key={dataset.dataset_code} className="grid gap-2 rounded-lg border border-slate-200 p-3 md:grid-cols-3"><label className="text-[11px] text-slate-500">数据集编码<Input aria-label={`数据集编码 ${index + 1}`} className="mt-1 font-mono text-xs" value={dataset.dataset_code} onChange={(event) => updateQueryModel((model) => ({ ...model, datasets: model.datasets.map((item, itemIndex) => itemIndex === index ? { ...item, dataset_code: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">数据集名称<Input aria-label={`数据集名称 ${index + 1}`} className="mt-1" value={dataset.name} onChange={(event) => updateQueryModel((model) => ({ ...model, datasets: model.datasets.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">数据源<Input aria-label={`数据源 ${index + 1}`} className="mt-1 font-mono text-xs" value={dataset.datasource_id} onChange={(event) => updateQueryModel((model) => ({ ...model, datasets: model.datasets.map((item, itemIndex) => itemIndex === index ? { ...item, datasource_id: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">Schema<Input aria-label={`Schema ${index + 1}`} className="mt-1 font-mono text-xs" value={dataset.schema_name} onChange={(event) => updateQueryModel((model) => ({ ...model, datasets: model.datasets.map((item, itemIndex) => itemIndex === index ? { ...item, schema_name: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">表或视图<Input aria-label={`表或视图 ${index + 1}`} className="mt-1 font-mono text-xs" value={dataset.table_name} onChange={(event) => updateQueryModel((model) => ({ ...model, datasets: model.datasets.map((item, itemIndex) => itemIndex === index ? { ...item, table_name: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">状态<select aria-label={`数据集状态 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={dataset.status} onChange={(event) => updateQueryModel((model) => ({ ...model, datasets: model.datasets.map((item, itemIndex) => itemIndex === index ? { ...item, status: event.target.value as 'draft' | 'published' } : item) }))}><option value="draft">草稿</option><option value="published">已发布</option></select></label><div className="md:col-span-3 flex justify-end"><button type="button" onClick={() => updateQueryModel((model) => ({ ...model, datasets: model.datasets.filter((_, itemIndex) => itemIndex !== index), keys: model.keys.filter((item) => item.dataset_code !== dataset.dataset_code), fields: model.fields.filter((item) => item.dataset_code !== dataset.dataset_code), relations: model.relations.filter((item) => item.from_dataset !== dataset.dataset_code && item.to_dataset !== dataset.dataset_code) }))} className="inline-flex items-center gap-1 text-xs text-red-600"><Trash2 className="h-3.5 w-3.5" />删除</button></div></div>)}</div>}
          {modelSection === 'keys' && queryModel && <div className="space-y-3"><div className="flex items-center justify-between"><p className="text-xs text-slate-500">每个数据集必须恰好一个主键；主键的实体和列共同定义每行代表。</p><button type="button" disabled={!queryModel.datasets[0]} onClick={() => updateQueryModel((model) => ({ ...model, keys: [...model.keys, { key_code: `key_${model.keys.length + 1}`, dataset_code: model.datasets[0].dataset_code, entity_code: '', key_type: 'primary', columns: [] }] }))} className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 disabled:opacity-40"><Plus className="h-3.5 w-3.5" />添加键</button></div>{queryModel.keys.map((key, index) => <div key={`${key.key_code}-${index}`} className="grid gap-2 rounded-lg border border-slate-200 p-3 md:grid-cols-5"><label className="text-[11px] text-slate-500">键编码<Input aria-label={`键编码 ${index + 1}`} className="mt-1 font-mono text-xs" value={key.key_code} onChange={(event) => updateQueryModel((model) => ({ ...model, keys: model.keys.map((item, itemIndex) => itemIndex === index ? { ...item, key_code: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">数据集<select aria-label={`键数据集 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={key.dataset_code} onChange={(event) => updateQueryModel((model) => ({ ...model, keys: model.keys.map((item, itemIndex) => itemIndex === index ? { ...item, dataset_code: event.target.value } : item) }))}>{queryModel.datasets.map((dataset) => <option key={dataset.dataset_code} value={dataset.dataset_code}>{dataset.name}</option>)}</select></label><label className="text-[11px] text-slate-500">实体编码<Input aria-label={`实体编码 ${index + 1}`} className="mt-1 font-mono text-xs" value={key.entity_code} onChange={(event) => updateQueryModel((model) => ({ ...model, keys: model.keys.map((item, itemIndex) => itemIndex === index ? { ...item, entity_code: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">键类型<select aria-label={`键类型 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={key.key_type} onChange={(event) => updateQueryModel((model) => ({ ...model, keys: model.keys.map((item, itemIndex) => itemIndex === index ? { ...item, key_type: event.target.value } : item) }))}><option value="primary">主键</option><option value="unique">唯一键</option><option value="foreign">外键</option></select></label><label className="text-[11px] text-slate-500">列（逗号分隔）<Input aria-label={`键列 ${index + 1}`} className="mt-1 font-mono text-xs" value={key.columns.join(',')} onChange={(event) => updateQueryModel((model) => ({ ...model, keys: model.keys.map((item, itemIndex) => itemIndex === index ? { ...item, columns: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) } : item) }))} /></label><div className="md:col-span-5 flex items-center justify-between"><span className="text-xs text-slate-500">{key.key_type === 'primary' ? <>每行代表：<strong className="text-slate-700">{key.entity_code || '待填写实体'}</strong>（{key.columns.join(' + ') || '待填写主键列'}）</> : null}</span><button type="button" aria-label={`删除键 ${index + 1}`} onClick={() => updateQueryModel((model) => ({ ...model, keys: model.keys.filter((_, itemIndex) => itemIndex !== index) }))} className="text-red-600"><Trash2 className="h-3.5 w-3.5" /></button></div></div>)}</div>}
          {modelSection === 'fields' && queryModel && <div className="space-y-3"><div className="flex items-center justify-between"><p className="text-xs text-slate-500">把物理列声明为标识、维度或事实字段。</p><button type="button" disabled={!queryModel.datasets[0]} onClick={() => updateQueryModel((model) => ({ ...model, fields: [...model.fields, { field_code: `field_${model.fields.length + 1}`, dataset_code: model.datasets[0].dataset_code, column_name: '', name: '新字段', field_role: 'dimension', semantic_type: 'String', value_domain: null, nullable: true, status: 'draft' }] }))} className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 disabled:opacity-40"><Plus className="h-3.5 w-3.5" />添加字段</button></div>{queryModel.fields.map((field, index) => <div key={`${field.field_code}-${index}`} className="grid gap-2 rounded-lg border border-slate-200 p-3 md:grid-cols-4"><label className="text-[11px] text-slate-500">字段编码<Input aria-label={`字段编码 ${index + 1}`} className="mt-1 font-mono text-xs" value={field.field_code} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, field_code: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">数据集<select aria-label={`字段数据集 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={field.dataset_code} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, dataset_code: event.target.value } : item) }))}>{queryModel.datasets.map((dataset) => <option key={dataset.dataset_code} value={dataset.dataset_code}>{dataset.name}</option>)}</select></label><label className="text-[11px] text-slate-500">物理列<Input aria-label={`物理列 ${index + 1}`} className="mt-1 font-mono text-xs" value={field.column_name} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, column_name: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">名称<Input aria-label={`字段名称 ${index + 1}`} className="mt-1" value={field.name} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">角色<select aria-label={`字段角色 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={field.field_role} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, field_role: event.target.value } : item) }))}><option value="identifier">标识</option><option value="dimension">维度</option><option value="fact">事实</option></select></label><label className="text-[11px] text-slate-500">语义类型<Input aria-label={`语义类型 ${index + 1}`} className="mt-1" value={field.semantic_type} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, semantic_type: event.target.value } : item) }))} /></label><label className="flex items-end gap-2 pb-2 text-xs text-slate-600"><input type="checkbox" checked={!field.nullable} onChange={(event) => updateQueryModel((model) => ({ ...model, fields: model.fields.map((item, itemIndex) => itemIndex === index ? { ...item, nullable: !event.target.checked } : item) }))} />必填</label><div className="flex items-end justify-end"><button type="button" aria-label={`删除字段 ${index + 1}`} onClick={() => updateQueryModel((model) => ({ ...model, fields: model.fields.filter((_, itemIndex) => itemIndex !== index) }))} className="p-2 text-red-600"><Trash2 className="h-3.5 w-3.5" /></button></div></div>)}</div>}
          {modelSection === 'relations' && queryModel && <div className="space-y-3"><div className="flex items-center justify-between"><p className="text-xs text-slate-500">关系只能通过已登记的两端键连接。</p><button type="button" disabled={queryModel.datasets.length < 2 || queryModel.keys.length < 2} onClick={() => updateQueryModel((model) => ({ ...model, relations: [...model.relations, { relation_code: `relation_${model.relations.length + 1}`, object_code: selectedObject, from_dataset: model.datasets[0].dataset_code, from_key: model.keys.find((key) => key.dataset_code === model.datasets[0].dataset_code)?.key_code || '', to_dataset: model.datasets[1].dataset_code, to_key: model.keys.find((key) => key.dataset_code === model.datasets[1].dataset_code)?.key_code || '', cardinality: 'many_to_one', status: 'draft' }] }))} className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 disabled:opacity-40"><Plus className="h-3.5 w-3.5" />添加关系</button></div>{queryModel.relations.map((relation, index) => <div key={`${relation.relation_code}-${index}`} className="grid gap-2 rounded-lg border border-slate-200 p-3 md:grid-cols-3"><label className="text-[11px] text-slate-500">关系编码<Input aria-label={`关系编码 ${index + 1}`} className="mt-1 font-mono text-xs" value={relation.relation_code} onChange={(event) => updateQueryModel((model) => ({ ...model, relations: model.relations.map((item, itemIndex) => itemIndex === index ? { ...item, relation_code: event.target.value } : item) }))} /></label>{(['from', 'to'] as const).map((side) => <div key={side} className="grid grid-cols-2 gap-2"><label className="text-[11px] text-slate-500">{side === 'from' ? '来源数据集' : '目标数据集'}<select aria-label={`${side === 'from' ? '来源' : '目标'}数据集 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={side === 'from' ? relation.from_dataset : relation.to_dataset} onChange={(event) => updateQueryModel((model) => ({ ...model, relations: model.relations.map((item, itemIndex) => itemIndex === index ? { ...item, [side === 'from' ? 'from_dataset' : 'to_dataset']: event.target.value } : item) }))}>{queryModel.datasets.map((dataset) => <option key={dataset.dataset_code} value={dataset.dataset_code}>{dataset.name}</option>)}</select></label><label className="text-[11px] text-slate-500">键<select aria-label={`${side === 'from' ? '来源' : '目标'}键 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={side === 'from' ? relation.from_key : relation.to_key} onChange={(event) => updateQueryModel((model) => ({ ...model, relations: model.relations.map((item, itemIndex) => itemIndex === index ? { ...item, [side === 'from' ? 'from_key' : 'to_key']: event.target.value } : item) }))}>{queryModel.keys.filter((key) => key.dataset_code === (side === 'from' ? relation.from_dataset : relation.to_dataset)).map((key) => <option key={key.key_code} value={key.key_code}>{key.key_code}</option>)}</select></label></div>)}<label className="text-[11px] text-slate-500">基数<select aria-label={`关系基数 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={relation.cardinality} onChange={(event) => updateQueryModel((model) => ({ ...model, relations: model.relations.map((item, itemIndex) => itemIndex === index ? { ...item, cardinality: event.target.value } : item) }))}><option value="one_to_one">一对一</option><option value="many_to_one">多对一</option><option value="one_to_many">一对多</option></select></label><div className="md:col-span-2 flex justify-end"><button type="button" aria-label={`删除关系 ${index + 1}`} onClick={() => updateQueryModel((model) => ({ ...model, relations: model.relations.filter((_, itemIndex) => itemIndex !== index) }))} className="p-2 text-red-600"><Trash2 className="h-3.5 w-3.5" /></button></div></div>)}</div>}
          {modelSection === 'quality' && queryModel && <div className="space-y-3"><div className="flex items-center justify-between"><p className="text-xs text-slate-500">发布前校验非空、唯一性和分段覆盖。</p><button type="button" disabled={!queryModel.datasets[0]} onClick={() => updateQueryModel((model) => ({ ...model, quality_rules: [...model.quality_rules, { rule_code: `rule_${model.quality_rules.length + 1}`, object_code: selectedObject, rule_type: 'not_null', target_dataset_or_relation: model.datasets[0].dataset_code, severity: 'blocking', parameters: {}, status: 'draft' }] }))} className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 disabled:opacity-40"><Plus className="h-3.5 w-3.5" />添加规则</button></div>{queryModel.quality_rules.map((rule, index) => <div key={`${rule.rule_code}-${index}`} className="grid gap-2 rounded-lg border border-slate-200 p-3 md:grid-cols-4"><label className="text-[11px] text-slate-500">规则编码<Input aria-label={`规则编码 ${index + 1}`} className="mt-1 font-mono text-xs" value={rule.rule_code} onChange={(event) => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.map((item, itemIndex) => itemIndex === index ? { ...item, rule_code: event.target.value } : item) }))} /></label><label className="text-[11px] text-slate-500">规则类型<select aria-label={`规则类型 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={rule.rule_type} onChange={(event) => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.map((item, itemIndex) => itemIndex === index ? { ...item, rule_type: event.target.value, parameters: {} } : item) }))}><option value="not_null">非空</option><option value="uniqueness">唯一性</option><option value="coverage">覆盖</option></select></label><label className="text-[11px] text-slate-500">目标<select aria-label={`规则目标 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={rule.target_dataset_or_relation} onChange={(event) => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.map((item, itemIndex) => itemIndex === index ? { ...item, target_dataset_or_relation: event.target.value } : item) }))}>{[...queryModel.datasets.map((item) => ({ code: item.dataset_code, name: item.name })), ...queryModel.relations.map((item) => ({ code: item.relation_code, name: item.relation_code }))].map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label><label className="text-[11px] text-slate-500">级别<select aria-label={`规则级别 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={rule.severity} onChange={(event) => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.map((item, itemIndex) => itemIndex === index ? { ...item, severity: event.target.value } : item) }))}><option value="blocking">阻断</option><option value="warning">警告</option></select></label>{rule.rule_type === 'coverage' && <label className="text-[11px] text-slate-500 md:col-span-2">覆盖参照数据集<select aria-label={`覆盖参照数据集 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={String(rule.parameters.reference_dataset || '')} onChange={(event) => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.map((item, itemIndex) => itemIndex === index ? { ...item, parameters: { ...item.parameters, reference_dataset: event.target.value } } : item) }))}><option value="">请选择</option>{queryModel.datasets.map((dataset) => <option key={dataset.dataset_code} value={dataset.dataset_code}>{dataset.name}</option>)}</select></label>}{rule.rule_type === 'not_null' && <label className="text-[11px] text-slate-500 md:col-span-2">非空字段<select aria-label={`非空字段 ${index + 1}`} className="mt-1 h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs" value={String(rule.parameters.field_code || '')} onChange={(event) => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.map((item, itemIndex) => itemIndex === index ? { ...item, parameters: { ...item.parameters, field_code: event.target.value } } : item) }))}><option value="">请选择</option>{queryModel.fields.map((field) => <option key={field.field_code} value={field.field_code}>{field.name}</option>)}</select></label>}<div className="flex items-end justify-end md:col-span-2"><button type="button" aria-label={`删除规则 ${index + 1}`} onClick={() => updateQueryModel((model) => ({ ...model, quality_rules: model.quality_rules.filter((_, itemIndex) => itemIndex !== index) }))} className="p-2 text-red-600"><Trash2 className="h-3.5 w-3.5" /></button></div></div>)}</div>}
          {modelSection === 'json' && <div className="space-y-2"><p className="text-xs text-slate-500">高级批量维护入口；保存前仍由服务端校验全部引用。</p><textarea aria-label="查询模型 JSON" className="min-h-[360px] w-full rounded-md border border-slate-300 bg-slate-950 p-3 font-mono text-xs text-slate-100" value={queryModelText} onChange={(event) => { setQueryModelText(event.target.value); setModelDirty(true) }} /></div>}
        </CardContent>
      </Card>

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">当前对象指标</div><div className="text-xl font-bold tabular-nums text-blue-600">{objectMetrics.length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">已映射</div><div className="text-xl font-bold tabular-nums text-emerald-600">{objectMetrics.filter((m) => m.mapping_status === 'mapped').length}</div></CardContent></Card>
        <Card className="border-slate-200 bg-white shadow-sm"><CardContent className="px-4 py-3"><div className="text-[11px] text-slate-500">未映射</div><div className="text-xl font-bold tabular-nums text-red-600">{objectMetrics.filter((m) => m.mapping_status === 'unmapped').length}</div></CardContent></Card>
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
