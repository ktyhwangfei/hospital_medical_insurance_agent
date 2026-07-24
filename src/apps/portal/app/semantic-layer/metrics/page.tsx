'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Search, Filter, ArrowUpDown, ExternalLink, Loader2, BarChart3,
  Pencil, Check, X, Plus, Trash2, AlertTriangle, ChevronDown, ChevronUp,
  Settings2, RefreshCw,
} from 'lucide-react'
import ValueDomainConfigModal from '../value-domain-config-modal'
import StandardValuesModal from '../standard-values-modal'

// ── Types ───────────────────────────────────────────────────────

interface ObjectSummary {
  object_code: string; name: string; domain_code: string; status: string
}
interface MetricDetail {
  metric_code: string; name: string; definition: string | null; object_code: string
  metric_type: string; semantic_type: string | null; unit: string | null
  required: boolean; importance: string; value_domain: string | null
  source_object: string | null; source_field: string | null
  source_adapter_port: string | null; usage_count: number; quality_score: number
  version: string; status: string
}
type MappingStatus = 'mapped' | 'unmapped' | 'value-missing'
interface EnrichedMetric extends MetricDetail {
  object_name: string; domain_code: string; mapping_status: MappingStatus
}
type SortField = 'name' | 'object_code' | 'metric_code' | 'semantic_type' | 'mapping_status' | 'usage_count' | 'quality_score'
type SortDir = 'asc' | 'desc'

const SEMANTIC_API = '/api/v1/medical-insurance-ai-agent/semantic'
const SEMANTIC_TYPE_OPTIONS = ['全部', 'Amount', 'Ratio', 'Enum', 'Date', 'Count', 'String'] as const
const STATUS_OPTIONS = ['全部', 'mapped', 'unmapped', 'value-missing'] as const
const STATUS_LABELS: Record<string, string> = { mapped: '已映射', unmapped: '未映射', 'value-missing': '值域缺失' }
const STATUS_ICONS: Record<string, string> = { mapped: '✓', unmapped: '✗', 'value-missing': '⚠' }
const STATUS_COLORS: Record<string, string> = { mapped: 'text-emerald-600', unmapped: 'text-red-600', 'value-missing': 'text-amber-600' }
const STATUS_BG: Record<string, string> = { mapped: 'bg-emerald-50', unmapped: 'bg-red-50', 'value-missing': 'bg-amber-50' }

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  if (!res.ok) { const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` })); throw new Error(err.detail || `请求失败 (${res.status})`) }
  return res.json() as Promise<T>
}
function determineMappingStatus(metric: MetricDetail): MappingStatus {
  if (!metric.source_field) return 'unmapped'
  if (metric.semantic_type === 'Enum' && !metric.value_domain) return 'value-missing'
  return 'mapped'
}
async function fetchAllMetrics(): Promise<{ metrics: EnrichedMetric[]; objects: ObjectSummary[] }> {
  const objects = await fetchJson<ObjectSummary[]>(`${SEMANTIC_API}/objects`)
  const objectMap = new Map(objects.map((o) => [o.object_code, o]))
  const metricsArrays = await Promise.all(objects.map((obj) => fetchJson<MetricDetail[]>(`${SEMANTIC_API}/metrics?object_code=${encodeURIComponent(obj.object_code)}`)))
  const allMetricCodes = metricsArrays.flat().map((m) => m.metric_code)
  const details = (await Promise.all(allMetricCodes.map((code) => fetchJson<MetricDetail>(`${SEMANTIC_API}/metrics/${encodeURIComponent(code)}`).catch(() => null)))).filter((d): d is MetricDetail => d !== null)
  return { metrics: details.map((m) => { const obj = objectMap.get(m.object_code); return { ...m, object_name: obj?.name ?? m.object_code, domain_code: obj?.domain_code ?? '', mapping_status: determineMappingStatus(m) } }), objects }
}

function SortHeader({ field, label, currentField, currentDir, onToggle }: { field: SortField; label: string; currentField: SortField; currentDir: SortDir; onToggle: (f: SortField) => void }) {
  const active = currentField === field
  return <button type="button" onClick={() => onToggle(field)} className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700">{label}<ArrowUpDown className={`h-3 w-3 ${active ? 'text-blue-600' : 'text-slate-400'}`} /></button>
}

// ── Metric Row (expandable edit) ────────────────────────────────

function MetricRow({ metric, objects, onSave, onDelete, onOpenVD }: {
  metric: EnrichedMetric; objects: ObjectSummary[]; onSave: (m: EnrichedMetric) => void; onDelete: (m: EnrichedMetric) => void
  onOpenVD: (m: EnrichedMetric) => void
}) {
  const [editDraft, setEditDraft] = useState<Record<string, any> | null>(null)
  const [saving, setSaving] = useState(false)

  const startEdit = useCallback(() => {
    setEditDraft({
      metric_code: metric.metric_code, object_code: metric.object_code, name: metric.name,
      definition: metric.definition || '', metric_type: metric.metric_type,
      semantic_type: metric.semantic_type || 'Amount', unit: metric.unit || '',
      value_domain: metric.value_domain || '', importance: metric.importance || 'optional',
      required: metric.required,
    })
  }, [metric])

  const handleSave = useCallback(async () => {
    if (!editDraft) return
    setSaving(true)
    const body: Record<string, any> = {}
    if (editDraft.metric_code !== metric.metric_code) body.metric_code = editDraft.metric_code
    if (editDraft.object_code !== metric.object_code) body.object_code = editDraft.object_code
    if (editDraft.name !== metric.name) body.name = editDraft.name
    if (editDraft.definition !== (metric.definition || '')) body.definition = editDraft.definition
    if (editDraft.metric_type !== metric.metric_type) body.metric_type = editDraft.metric_type
    if (editDraft.semantic_type !== (metric.semantic_type || '')) body.semantic_type = editDraft.semantic_type
    if (editDraft.unit !== (metric.unit || '')) body.unit = editDraft.unit
    if (editDraft.value_domain !== (metric.value_domain || '')) body.value_domain = editDraft.value_domain
    if (editDraft.importance !== (metric.importance || '')) body.importance = editDraft.importance
    if (editDraft.required !== metric.required) body.required = editDraft.required
    try {
      await fetchJson(`${SEMANTIC_API}/metrics/${encodeURIComponent(metric.metric_code)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      onSave({ ...metric, ...editDraft })
      setEditDraft(null)
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [editDraft, metric, onSave])

  return (
    <>
      <tr className="group border-b border-slate-200 transition-colors hover:bg-slate-50">
        <td className="px-3 py-3">
          <span className="font-mono text-[11px] text-slate-700">{metric.object_code}</span>
        </td>
        <td className="px-3 py-3">
          <Link href={`/semantic-layer/object?object_code=${metric.object_code}`} className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-blue-600">
            {metric.object_name}<ExternalLink className="h-3 w-3" />
          </Link>
        </td>
        <td className="px-3 py-3">
          <span className="font-mono text-[11px] text-slate-600">{metric.metric_code.split('.').pop()}</span>
        </td>
        <td className="px-3 py-3">
          <span className="text-sm font-medium text-slate-800">{metric.name}</span>
        </td>
        <td className="px-3 py-3"><Badge variant="outline" className="border-slate-300 text-[10px] text-slate-600">{metric.semantic_type || '-'}</Badge></td>
        <td className="px-3 py-3 max-w-[100px]">
          {metric.value_domain ? (
            <button onClick={() => onOpenVD(metric)} className="font-mono text-[10px] text-purple-600 bg-purple-50 hover:bg-purple-100 rounded px-1.5 py-0.5 cursor-pointer inline-flex items-center gap-0.5" title="配置值域标准值">
              {metric.value_domain}<Settings2 className="h-2.5 w-2.5 opacity-50" />
            </button>
          ) : (
            <span className="text-[10px] text-slate-400">-</span>
          )}
        </td>
        <td className="px-3 py-3">
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_BG[metric.mapping_status]} ${STATUS_COLORS[metric.mapping_status]}`}>
            <span>{STATUS_ICONS[metric.mapping_status]}</span><span>{STATUS_LABELS[metric.mapping_status]}</span>
          </span>
        </td>
        <td className="px-3 py-3"><span className="font-mono text-xs tabular-nums text-slate-600">{metric.usage_count}</span></td>
        <td className="px-3 py-3">
          <div className="flex items-center gap-2" title={metric.source_field ? `来源: ${metric.source_field} | 基于五维价值评估（非空率×50 + 描述+示例+活跃度+使用度）` : '未映射，无数据来源'}>
            <div className="h-1.5 w-12 overflow-hidden rounded-full bg-slate-200">
              <div className="h-full rounded-full" style={{ width: `${Math.min(metric.quality_score * 10, 100)}%`, backgroundColor: metric.quality_score >= 8 ? '#10b981' : metric.quality_score >= 5 ? '#eab308' : metric.quality_score > 0 ? '#f97316' : '#64748b' }} />
            </div>
            <span className="font-mono text-xs tabular-nums text-slate-600">{metric.quality_score.toFixed(1)}</span>
          </div>
        </td>
        <td className="px-3 py-3">
          <div className="flex items-center gap-1">
            <button onClick={startEdit} className="rounded p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50" title="编辑"><Pencil className="h-3.5 w-3.5" /></button>
            <button onClick={() => onDelete(metric)} className="rounded p-1 text-slate-400 hover:text-red-500 hover:bg-red-50" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
            <button onClick={() => editDraft ? setEditDraft(null) : startEdit()} className="rounded p-1 text-slate-400 hover:text-slate-600" title={editDraft ? '收起' : '展开'}>
              {editDraft ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>
        </td>
      </tr>
      {editDraft && (
        <tr>
          <td colSpan={10} className="border-b border-slate-200 bg-slate-50/50 px-5 py-4">
            <div className="grid grid-cols-2 gap-3">
              <div><label className="mb-1 block text-[11px] text-slate-500">英文编码</label><Input value={editDraft.metric_code} onChange={(e) => setEditDraft((p) => p ? { ...p, metric_code: e.target.value } : p)} className="h-8 text-xs font-mono" /></div>
              <div><label className="mb-1 block text-[11px] text-slate-500">所属对象</label><select value={editDraft.object_code} onChange={(e) => setEditDraft((p) => p ? { ...p, object_code: e.target.value } : p)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs">{objects.map((o) => <option key={o.object_code} value={o.object_code}>{o.name} ({o.object_code})</option>)}</select></div>
              <div><label className="mb-1 block text-[11px] text-slate-500">中文名称</label><Input value={editDraft.name} onChange={(e) => setEditDraft((p) => p ? { ...p, name: e.target.value } : p)} className="h-8 text-xs" /></div>
              <div className="col-span-2"><label className="mb-1 block text-[11px] text-slate-500">指标描述</label><Input value={editDraft.definition} onChange={(e) => setEditDraft((p) => p ? { ...p, definition: e.target.value } : p)} placeholder="标准业务定义" className="h-8 text-xs" /></div>
              <div><label className="mb-1 block text-[11px] text-slate-500">指标类型</label><select value={editDraft.metric_type} onChange={(e) => setEditDraft((p) => p ? { ...p, metric_type: e.target.value } : p)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs"><option value="Atomic">Atomic（原子）</option><option value="Derived">Derived（派生）</option></select></div>
              <div><label className="mb-1 block text-[11px] text-slate-500">语义类型</label><select value={editDraft.semantic_type} onChange={(e) => setEditDraft((p) => p ? { ...p, semantic_type: e.target.value } : p)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs"><option value="Amount">Amount（金额）</option><option value="Ratio">Ratio（比率）</option><option value="Enum">Enum（枚举）</option><option value="Date">Date（日期）</option><option value="Count">Count（计数）</option><option value="String">String（字符串）</option></select></div>
              {editDraft.semantic_type === 'Amount' && <div><label className="mb-1 block text-[11px] text-slate-500">单位</label><Input value={editDraft.unit} onChange={(e) => setEditDraft((p) => p ? { ...p, unit: e.target.value } : p)} placeholder="如：元" className="h-8 text-xs" /></div>}
              {editDraft.semantic_type === 'Enum' && <div><label className="mb-1 block text-[11px] text-slate-500">值域编码</label><Input value={editDraft.value_domain} onChange={(e) => setEditDraft((p) => p ? { ...p, value_domain: e.target.value } : p)} placeholder="如：HOSPITAL_LEVEL" className="h-8 text-xs font-mono" /></div>}
              {(editDraft.semantic_type !== 'Amount' && editDraft.semantic_type !== 'Enum') && <div />}
              <div><label className="mb-1 block text-[11px] text-slate-500">重要性</label><select value={editDraft.importance} onChange={(e) => setEditDraft((p) => p ? { ...p, importance: e.target.value } : p)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs"><option value="core">core（核心）</option><option value="optional">optional（可选）</option></select></div>
              <div className="flex items-end pb-1"><label className="flex items-center gap-1.5 cursor-pointer text-xs text-slate-600"><input type="checkbox" checked={editDraft.required} onChange={(e) => setEditDraft((p) => p ? { ...p, required: e.target.checked } : p)} className="h-3.5 w-3.5 rounded border-slate-300" />必填指标</label></div>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setEditDraft(null)} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50">取消</button>
              <button onClick={handleSave} disabled={saving} className="rounded-md bg-blue-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-40">{saving ? '保存中...' : '保存'}</button>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Add Metric Form ──────────────────────────────────────────────

function AddMetricForm({ objects, onAdded, onCancel }: { objects: ObjectSummary[]; onAdded: () => void; onCancel: () => void }) {
  const [name, setName] = useState(''); const [metricCode, setMetricCode] = useState(''); const [objectCode, setObjectCode] = useState(objects[0]?.object_code ?? '')
  const [definition, setDefinition] = useState(''); const [metricType, setMetricType] = useState<'Atomic' | 'Derived'>('Atomic')
  const [semanticType, setSemanticType] = useState<'Amount' | 'Ratio' | 'Enum' | 'Date' | 'Count'>('Amount')
  const [unit, setUnit] = useState(''); const [valueDomain, setValueDomain] = useState('')
  const [importance, setImportance] = useState<'core' | 'optional'>('optional'); const [required, setRequired] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleNameChange = useCallback((val: string) => {
    setName(val)
    setMetricCode(val.trim().replace(/\s+/g, '_'))
  }, [])

  const handleSubmit = useCallback(async () => {
    if (!name.trim() || !objectCode || !metricCode.trim()) return; setSaving(true)
    try {
      await fetchJson(`${SEMANTIC_API}/metrics`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ object_code: objectCode, name: name.trim(), metric_type: metricType, semantic_type: semanticType, definition: definition.trim() || null, unit: unit.trim() || null, importance, value_domain: valueDomain.trim() || null, required }) })
      onAdded()
    } catch (err: any) { alert(err.message) }
    setSaving(false)
  }, [name, metricCode, objectCode, definition, metricType, semanticType, unit, valueDomain, importance, required, onAdded])

  const preview = metricCode.trim() ? `${objectCode}.${metricCode.trim()}` : ''
  return (
    <Card className="border-2 border-dashed border-purple-300 bg-purple-50/30 shadow-none">
      <CardContent className="flex flex-col gap-3 px-5 py-4">
        <h4 className="text-xs font-medium text-purple-700">新建业务指标</h4>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="mb-1 block text-[11px] text-slate-500">英文编码 *</label><Input value={metricCode} onChange={(e) => setMetricCode(e.target.value)} placeholder="如: total_fee" className="h-8 text-xs font-mono" /></div>
          <div><label className="mb-1 block text-[11px] text-slate-500">所属对象 *</label><select value={objectCode} onChange={(e) => setObjectCode(e.target.value)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs">{objects.map((o) => <option key={o.object_code} value={o.object_code}>{o.name} ({o.object_code})</option>)}</select></div>
          <div><label className="mb-1 block text-[11px] text-slate-500">中文名称 *</label><Input value={name} onChange={(e) => handleNameChange(e.target.value)} placeholder="如：总费用" className="h-8 text-xs" /></div>
          <div className="col-span-2"><label className="mb-1 block text-[11px] text-slate-500">指标描述</label><Input value={definition} onChange={(e) => setDefinition(e.target.value)} placeholder="标准业务定义" className="h-8 text-xs" /></div>
          <div><label className="mb-1 block text-[11px] text-slate-500">指标类型</label><select value={metricType} onChange={(e) => setMetricType(e.target.value as 'Atomic' | 'Derived')} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs"><option value="Atomic">Atomic（原子指标）</option><option value="Derived">Derived（派生指标）</option></select></div>
          <div><label className="mb-1 block text-[11px] text-slate-500">语义类型</label><select value={semanticType} onChange={(e) => setSemanticType(e.target.value as any)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs"><option value="Amount">Amount（金额）</option><option value="Ratio">Ratio（比率）</option><option value="Enum">Enum（枚举）</option><option value="Date">Date（日期）</option><option value="Count">Count（计数）</option><option value="String">String（字符串）</option></select></div>
          {semanticType === 'Amount' && <div><label className="mb-1 block text-[11px] text-slate-500">单位</label><Input value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="如：元" className="h-8 text-xs" /></div>}
          {semanticType === 'Enum' && <div><label className="mb-1 block text-[11px] text-slate-500">值域编码</label><Input value={valueDomain} onChange={(e) => setValueDomain(e.target.value)} placeholder="如：HOSPITAL_LEVEL" className="h-8 text-xs font-mono" /></div>}
          {(semanticType !== 'Amount' && semanticType !== 'Enum') && <div />}
          <div><label className="mb-1 block text-[11px] text-slate-500">重要性</label><select value={importance} onChange={(e) => setImportance(e.target.value as any)} className="h-8 w-full rounded-md border border-slate-300 bg-white px-2 text-xs"><option value="core">core（核心）</option><option value="optional">optional（可选）</option></select></div>
          <div className="flex items-end pb-1"><label className="flex items-center gap-1.5 cursor-pointer text-xs text-slate-600"><input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} className="h-3.5 w-3.5 rounded border-slate-300" />必填指标</label></div>
        </div>
        {preview && <div className="rounded-md bg-slate-100 px-3 py-1.5 font-mono text-[11px] text-slate-500">编码预览: <span className="text-slate-700">{preview}</span></div>}
        <div className="flex justify-end gap-2"><button onClick={onCancel} className="rounded-md px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200">取消</button><button onClick={handleSubmit} disabled={!name.trim() || !objectCode || !metricCode.trim() || saving} className="rounded-md bg-purple-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:opacity-40">{saving ? '创建中...' : '创建指标'}</button></div>
      </CardContent>
    </Card>
  )
}

// ── Delete Confirm ───────────────────────────────────────────────

function DeleteConfirmDialog({ metric, onConfirm, onCancel }: { metric: EnrichedMetric; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3"><div className="shrink-0 rounded-full bg-amber-50 p-2"><AlertTriangle className="h-5 w-5 text-amber-500" /></div><div className="flex-1"><h3 className="text-sm font-semibold text-slate-800">确认删除</h3><p className="mt-1 text-xs text-slate-600">确定要删除指标 <strong>{metric.name}</strong>？</p></div></div>
        <div className="mt-5 flex justify-end gap-2"><button onClick={onCancel} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">取消</button><button onClick={onConfirm} className="rounded-md bg-red-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600">确认删除</button></div>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────

export default function MetricsCenterPage() {
  const [metrics, setMetrics] = useState<EnrichedMetric[]>([])
  const [objects, setObjects] = useState<ObjectSummary[]>([])
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null)
  const [objectFilter, setObjectFilter] = useState('全部对象'); const [typeFilter, setTypeFilter] = useState('全部')
  const [statusFilter, setStatusFilter] = useState('全部'); const [searchText, setSearchText] = useState('')
  const [sortField, setSortField] = useState<SortField>('object_code'); const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [showAddForm, setShowAddForm] = useState(false); const [deleteTarget, setDeleteTarget] = useState<EnrichedMetric | null>(null)
  const [vdConfigMetric, setVdConfigMetric] = useState<EnrichedMetric | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(() => { setLoading(true); setError(null); return fetchAllMetrics().then(({ metrics: m, objects: o }) => { setMetrics(m); setObjects(o); setLoading(false) }).catch((err: Error) => { setError(err.message); setLoading(false) }) }, [])
  useEffect(() => { fetchData() }, [fetchData])

  const stats = useMemo(() => {
    const total = metrics.length; const mapped = metrics.filter((m) => m.mapping_status === 'mapped').length
    const unmapped = metrics.filter((m) => m.mapping_status === 'unmapped').length
    const valueMissing = metrics.filter((m) => m.mapping_status === 'value-missing').length
    let topMetric = ''; let topUsage = -1
    for (const m of metrics) { if (m.usage_count > topUsage) { topUsage = m.usage_count; topMetric = m.name } }
    return { total, mapped, unmapped, valueMissing, mappedPct: total > 0 ? ((mapped / total) * 100).toFixed(1) : '0.0', unmappedPct: total > 0 ? ((unmapped / total) * 100).toFixed(1) : '0.0', topMetric, topUsage }
  }, [metrics])

  const toggleSort = useCallback((field: SortField) => { if (sortField === field) setSortDir((d) => d === 'asc' ? 'desc' : 'asc'); else { setSortField(field); setSortDir('asc') } }, [sortField])
  const filteredMetrics = useMemo(() => {
    let list = [...metrics]
    if (objectFilter !== '全部对象') list = list.filter((m) => m.object_code === objectFilter)
    if (typeFilter !== '全部') list = list.filter((m) => m.semantic_type === typeFilter)
    if (statusFilter !== '全部') list = list.filter((m) => m.mapping_status === statusFilter)
    if (searchText.trim()) { const q = searchText.trim().toLowerCase(); list = list.filter((m) => m.name.toLowerCase().includes(q) || m.metric_code.toLowerCase().includes(q)) }
    list.sort((a, b) => { let cmp = 0; switch (sortField) { case 'name': cmp = a.name.localeCompare(b.name); break; case 'object_code': cmp = a.object_code.localeCompare(b.object_code) || a.metric_code.localeCompare(b.metric_code); break; case 'metric_code': cmp = a.metric_code.localeCompare(b.metric_code); break; case 'semantic_type': cmp = (a.semantic_type ?? '').localeCompare(b.semantic_type ?? ''); break; case 'mapping_status': cmp = a.mapping_status.localeCompare(b.mapping_status); break; case 'usage_count': cmp = a.usage_count - b.usage_count; break; case 'quality_score': cmp = a.quality_score - b.quality_score; break; } return sortDir === 'asc' ? cmp : -cmp })
    return list
  }, [metrics, objectFilter, typeFilter, statusFilter, searchText, sortField, sortDir])
  const objectOptions = useMemo(() => { const codes = new Set(metrics.map((m) => m.object_code)); return Array.from(codes).sort() }, [metrics])

  const handleMetricSave = useCallback((updated: EnrichedMetric) => {
    setMetrics((prev) => {
      // Handle metric_code rename: replace by old code, or add if not found
      const exists = prev.some((m) => m.metric_code === updated.metric_code)
      if (!exists) {
        // rename: old key was different
        return prev.map((m) => m.metric_code === updated.metric_code ? updated : m)
      }
      return prev.map((m) => (m.metric_code === updated.metric_code ? updated : m))
    })
    // Re-fetch to get fresh data
    fetchData()
  }, [fetchData])
  const handleAdd = useCallback(() => { setShowAddForm(false); fetchData() }, [fetchData])
  const handleRefreshQuality = useCallback(async () => {
    setRefreshing(true)
    try {
      const res = await fetchJson<{ updated: number }>(`${SEMANTIC_API}/metrics/refresh-quality-scores`, { method: 'POST' })
      await fetchData()
      alert(`已按最新发现扫描刷新 ${res.updated} 个指标的质量分`)
    } catch (err: any) { alert(err.message) }
    setRefreshing(false)
  }, [fetchData])
  const handleDeleteConfirm = useCallback(async () => { if (!deleteTarget) return; try { await fetch(`${SEMANTIC_API}/metrics/${encodeURIComponent(deleteTarget.metric_code)}`, { method: 'DELETE' }) } catch (err: any) { alert(err.message) }; setDeleteTarget(null); setMetrics((prev) => prev.filter((m) => m.metric_code !== deleteTarget.metric_code)) }, [deleteTarget])

  if (loading) return <div className="flex flex-col gap-6"><div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => (<Card key={i}><CardHeader className="pb-2"><div className="h-3 w-16 animate-pulse rounded bg-slate-200" /></CardHeader><CardContent><div className="h-8 w-20 animate-pulse rounded bg-slate-200" /></CardContent></Card>))}</div><div className="flex flex-wrap gap-3">{Array.from({ length: 4 }).map((_, i) => (<div key={i} className="h-8 w-28 animate-pulse rounded-md bg-slate-200" />))}</div><div className="rounded-lg border border-slate-200"><div className="border-b border-slate-200 bg-slate-50 px-3 py-2.5"><div className="h-3 w-48 animate-pulse rounded bg-slate-200" /></div><div className="divide-y divide-slate-200">{Array.from({ length: 8 }).map((_, i) => (<div key={i} className="flex items-center gap-4 px-3 py-3"><div className="h-4 w-32 animate-pulse rounded bg-slate-200" /><div className="h-3 w-20 animate-pulse rounded bg-slate-200" /><div className="h-3 w-16 animate-pulse rounded bg-slate-200" /><div className="h-5 w-14 animate-pulse rounded-full bg-slate-200" /><div className="h-3 w-10 animate-pulse rounded bg-slate-200" /><div className="h-4 w-12 animate-pulse rounded bg-slate-200" /></div>))}</div></div></div>
  if (error) return <Alert variant="destructive" className="border-red-200 bg-red-50"><AlertTitle className="text-red-600">数据加载失败</AlertTitle><AlertDescription className="text-red-500">{error}</AlertDescription></Alert>

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between"><div><p className="text-sm text-slate-500">全局浏览与筛选所有指标，支持增删改查</p></div><div className="flex items-center gap-2"><button type="button" onClick={handleRefreshQuality} disabled={refreshing} className="flex items-center gap-1 rounded-md bg-blue-50 px-2.5 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-100 disabled:opacity-40"><RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />{refreshing ? '刷新中...' : '刷新质量分'}</button><button type="button" onClick={() => setShowAddForm(true)} className="flex items-center gap-1 rounded-md bg-purple-50 px-2.5 py-1.5 text-xs font-medium text-purple-600 hover:bg-purple-100"><Plus className="h-3.5 w-3.5" />新建指标</button></div></div>
      {showAddForm && <AddMetricForm objects={objects} onAdded={handleAdd} onCancel={() => setShowAddForm(false)} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card className="border-slate-200/70 bg-white/80 shadow-sm"><CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-slate-600">指标总数</CardTitle></CardHeader><CardContent><div className="text-3xl font-bold tracking-tight text-blue-600">{stats.total}</div></CardContent></Card>
        <Card className="border-slate-200/70 bg-white/80 shadow-sm"><CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-slate-600">已映射</CardTitle></CardHeader><CardContent><div className="text-3xl font-bold tracking-tight text-emerald-600">{stats.mappedPct}%</div><p className="mt-0.5 text-xs text-slate-400">{stats.mapped} / {stats.total}</p></CardContent></Card>
        <Card className="border-slate-200/70 bg-white/80 shadow-sm"><CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-slate-600">未映射</CardTitle></CardHeader><CardContent><div className="text-3xl font-bold tracking-tight text-red-600">{stats.unmappedPct}%</div><p className="mt-0.5 text-xs text-slate-400">{stats.unmapped} + {stats.valueMissing} 值域缺失</p></CardContent></Card>
        <Card className="border-slate-200/70 bg-white/80 shadow-sm"><CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-slate-600">最高引用</CardTitle></CardHeader><CardContent><div className="truncate text-sm font-semibold text-amber-600">{stats.topMetric || '-'}</div><p className="mt-0.5 text-xs text-slate-400">引用 {stats.topUsage} 次</p></CardContent></Card>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5"><Filter className="h-3.5 w-3.5 text-slate-500" /><select value={objectFilter} onChange={(e) => setObjectFilter(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"><option value="全部对象">全部对象</option>{objectOptions.map((code) => <option key={code} value={code}>{code}</option>)}</select></div>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-blue-500 focus:outline-none">{SEMANTIC_TYPE_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt === '全部' ? '全部类型' : opt}</option>)}</select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs focus:border-blue-500 focus:outline-none">{STATUS_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt === '全部' ? '全部状态' : STATUS_LABELS[opt]}</option>)}</select>
        <div className="relative flex-1 max-w-[260px]"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" /><Input type="text" placeholder="搜索指标名称或编码..." value={searchText} onChange={(e) => setSearchText(e.target.value)} className="h-8 rounded-md border border-slate-300 bg-white pl-8 text-xs" /></div>
        <div className="text-xs text-slate-500">共 <span className="font-mono text-slate-600">{filteredMetrics.length}</span> 条</div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left">
          <thead><tr className="border-b border-slate-200 bg-slate-50"><th className="px-3 py-2.5"><SortHeader field="object_code" label="对象英文" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="px-3 py-2.5 text-xs font-medium text-slate-500">对象中文</th><th className="px-3 py-2.5"><SortHeader field="metric_code" label="指标英文" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="px-3 py-2.5"><SortHeader field="name" label="指标中文" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="px-3 py-2.5"><SortHeader field="semantic_type" label="语义类型" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="px-3 py-2.5 text-xs font-medium text-slate-500">值域</th><th className="px-3 py-2.5"><SortHeader field="mapping_status" label="映射状态" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="px-3 py-2.5"><SortHeader field="usage_count" label="引用数" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="px-3 py-2.5"><SortHeader field="quality_score" label="质量分" currentField={sortField} currentDir={sortDir} onToggle={toggleSort} /></th><th className="w-24 px-3 py-2.5 text-xs font-medium text-slate-500">操作</th></tr></thead>
          <tbody>
            {filteredMetrics.length === 0 ? (<tr><td colSpan={10} className="px-3 py-10 text-center text-sm text-slate-400">{metrics.length === 0 ? '暂无指标数据' : '无匹配的指标'}</td></tr>) : (
              filteredMetrics.map((metric) => <MetricRow key={metric.metric_code} metric={metric} objects={objects} onSave={handleMetricSave} onDelete={setDeleteTarget} onOpenVD={setVdConfigMetric} />)
            )}
          </tbody>
        </table>
      </div>
      {deleteTarget && <DeleteConfirmDialog metric={deleteTarget} onConfirm={handleDeleteConfirm} onCancel={() => setDeleteTarget(null)} />}
      {vdConfigMetric?.value_domain && (
        <StandardValuesModal
          valueDomainCode={vdConfigMetric.value_domain}
          onClose={() => setVdConfigMetric(null)}
          onSaved={() => {}}
        />
      )}
    </div>
  )
}
