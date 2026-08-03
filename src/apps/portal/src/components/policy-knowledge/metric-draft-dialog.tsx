'use client'

import { useState } from 'react'
import { Loader2, X } from 'lucide-react'

import { createMetricDraft, type MetricDraftSource } from '@/lib/policy-knowledge-api'

interface Row extends MetricDraftSource {
  metricCode: string
  name: string
  metricType: string
  semanticType: string
  unit: string
  valueDomain: string
}

const safeCode = (value: string) => value.toLowerCase().replace(/[^a-z0-9_]+/g, '_')
const inferSemanticType = (source: MetricDraftSource) => {
  const hint = `${source.source_field} ${source.field_name}`.toLowerCase()
  if (/ratio|rate|比例|费率/.test(hint) || String(source.source_value).includes('%')) return 'Ratio'
  if (/date|time|日期|时间/.test(hint)) return 'Date'
  if (/count|数量|次数/.test(hint)) return 'Count'
  if (/type|status|level|类别|类型|状态|等级/.test(hint)) return 'Enum'
  if (/amount|fee|price|金额|费用/.test(hint)) return 'Amount'
  return 'Text'
}

export function MetricDraftDialog({ sources, onClose, onCreated }: {
  sources: MetricDraftSource[]
  onClose: () => void
  onCreated: (count: number) => void
}) {
  const [rows, setRows] = useState<Row[]>(() => sources.map((source) => ({
    ...source,
    metricCode: `zcgz.policy.${safeCode(source.source_field)}`,
    name: source.field_name,
    metricType: 'Atomic',
    semanticType: inferSemanticType(source),
    unit: String(source.source_value).includes('%') ? '%' : '',
    valueDomain: '',
  })))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  if (!sources.length) return null

  async function submit() {
    setSaving(true); setError('')
    try {
      for (const row of rows) {
        await createMetricDraft(row, row.metricCode, row.name, {
          metricType: row.metricType,
          semanticType: row.semanticType || null,
          unit: row.unit || null,
          valueDomain: row.valueDomain || null,
        })
      }
      onCreated(rows.length)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '指标草稿创建失败')
    } finally {
      setSaving(false)
    }
  }

  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm">
    <div role="dialog" aria-modal="true" aria-label="生成指标草稿" className="w-full max-w-3xl rounded-2xl bg-white p-5 shadow-2xl">
      <div className="flex items-start gap-3">
        <div><h3 className="text-base font-semibold text-slate-900">生成指标草稿</h3><p className="mt-1 text-xs text-slate-500">政策字段是权威来源之一；这里只创建草稿，仍需在语义层完成人工审核和发布。</p></div>
        <button type="button" onClick={onClose} className="ml-auto rounded-md p-1 text-slate-400 hover:bg-slate-100"><X className="size-4" /></button>
      </div>
      <div className="mt-4 max-h-[55vh] space-y-2 overflow-y-auto">
        {rows.map((row, index) => <div key={`${row.knowledge_id}-${row.source_field}`} className="grid gap-2 rounded-xl border border-slate-200 p-3 md:grid-cols-[1fr_1.2fr]">
          <div><p className="text-[10px] text-slate-400">政策来源字段</p><p className="mt-1 text-xs font-semibold text-slate-700">{row.field_name}</p><p className="mt-1 font-mono text-[10px] text-slate-400">{row.source_field} = {String(row.source_value ?? '')}</p></div>
          <div className="grid grid-cols-2 gap-2">
            <input aria-label={`${row.field_name}指标编码`} value={row.metricCode} onChange={(event) => setRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, metricCode: event.target.value } : item))} className="rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs" />
            <input aria-label={`${row.field_name}指标名称`} value={row.name} onChange={(event) => setRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
            <select aria-label={`${row.field_name}指标类型`} value={row.metricType} onChange={(event) => setRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, metricType: event.target.value } : item))} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option>Atomic</option><option>Derived</option></select>
            <select aria-label={`${row.field_name}语义类型`} value={row.semanticType} onChange={(event) => setRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, semanticType: event.target.value } : item))} className="rounded-lg border border-slate-200 px-3 py-2 text-xs"><option>Text</option><option>Amount</option><option>Ratio</option><option>Enum</option><option>Date</option><option>Count</option></select>
            <input aria-label={`${row.field_name}单位`} value={row.unit} onChange={(event) => setRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, unit: event.target.value } : item))} placeholder="单位（可选）" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
            <input aria-label={`${row.field_name}值域`} value={row.valueDomain} onChange={(event) => setRows((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, valueDomain: event.target.value } : item))} placeholder="值域编码（可选）" className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
          </div>
        </div>)}
      </div>
      {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-xs text-slate-600">取消</button>
        <button type="button" disabled={saving || rows.some((row) => !row.metricCode || !row.name)} onClick={submit} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50">
          {saving && <Loader2 className="size-3.5 animate-spin" />}确认生成 {rows.length} 个草稿
        </button>
      </div>
    </div>
  </div>
}
