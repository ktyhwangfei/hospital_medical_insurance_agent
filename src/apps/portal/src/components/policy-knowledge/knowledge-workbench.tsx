'use client'

import { useMemo, useState } from 'react'
import { Check, ChevronRight, CircleAlert, FileCheck2, Link2, Plus, Sparkles } from 'lucide-react'

import type {
  KnowledgeItem,
  MetricDraftSource,
  SemanticMetricSummary,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

interface Props {
  document: WorkbenchDocument
  metrics: SemanticMetricSummary[]
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
}

const pct = (value: number | null) => value === null ? '待验证' : `${Math.round(value * 100)}%`

type MobileStep = 'units' | 'knowledge' | 'standardization'

export function KnowledgeWorkbench({ document, metrics, onBindExisting, onCreateMetricDrafts, onProposeValue }: Props) {
  const [unitId, setUnitId] = useState(document.units[0]?.unit_id || '')
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const [knowledgeId, setKnowledgeId] = useState(unit?.knowledge[0]?.knowledge_id || '')
  const knowledge = unit?.knowledge.find((item) => item.knowledge_id === knowledgeId) || unit?.knowledge[0]
  const [selectedFields, setSelectedFields] = useState<string[]>([])
  const [selectedMetrics, setSelectedMetrics] = useState<Record<string, string>>({})
  const [mobileStep, setMobileStep] = useState<MobileStep>('units')

  const sources = useMemo(() => {
    if (!unit || !knowledge) return []
    return knowledge.standardized_fields
      .filter((field) => field.status === 'unmapped')
      .map((field) => toDraftSource(document, unit.unit_id, knowledge, field))
  }, [document, unit, knowledge])

  function selectUnit(nextUnitId: string) {
    const next = document.units.find((item) => item.unit_id === nextUnitId)
    setUnitId(nextUnitId)
    setKnowledgeId(next?.knowledge[0]?.knowledge_id || '')
    setSelectedFields([])
    setMobileStep('knowledge')
  }

  const selectedSources = sources.filter((source) => selectedFields.includes(source.source_field))

  return (
    <div>
      <div role="tablist" aria-label="移动端工作台阶段" className="mb-3 grid grid-cols-3 rounded-xl bg-slate-100 p-1 lg:hidden">
        {([['units', '单元'], ['knowledge', '知识'], ['standardization', '标准化']] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-label={`${label}阶段`} aria-selected={mobileStep === key} onClick={() => setMobileStep(key)} className={`rounded-lg px-2 py-2 text-xs ${mobileStep === key ? 'bg-white font-semibold text-blue-700 shadow-sm' : 'text-slate-500'}`}>{label}</button>)}
      </div>
      <div className="grid min-h-[620px] gap-3 lg:grid-cols-[0.85fr_1.15fr_1.2fr]">
      <Column className={mobileStep === 'units' ? '' : 'hidden lg:block'} title="审核通过的单元" subtitle={`${document.units.length} 个可用单元`}>
        <div role="listbox" aria-label="审核通过的单元" className="space-y-2">
          {document.units.map((item) => (
            <button key={item.unit_id} id={`policy-unit-${item.unit_id}`} role="option" type="button" aria-selected={item.unit_id === unit?.unit_id} aria-controls="policy-knowledge-column" onClick={() => selectUnit(item.unit_id)}
              className={`w-full rounded-xl border p-3 text-left transition ${item.unit_id === unit?.unit_id ? 'border-blue-400 bg-blue-50 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
              <div className="flex items-center gap-2">
                <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                  <FileCheck2 className="mr-1 inline size-3" />{item.status === 'published' ? '已发布' : '已审核'}
                </span>
                <span className="ml-auto text-[11px] text-slate-400">{item.knowledge_count} 条知识</span>
              </div>
              <p className="mt-2 text-xs font-semibold text-slate-700">{item.path.join(' / ') || '政策正文'}</p>
              <p className="mt-1 line-clamp-4 text-xs leading-5 text-slate-500">{item.source_text}</p>
            </button>
          ))}
          {!document.units.length && <Empty text="单元页暂无审核通过的内容" />}
        </div>
      </Column>

      <Column id="policy-knowledge-column" className={mobileStep === 'knowledge' ? '' : 'hidden lg:block'} title="结构化知识" subtitle={unit ? `当前单元 · ${unit.knowledge_count} 条` : '请选择单元'}>
        <div role="listbox" aria-label="结构化知识" className="space-y-3">
          {unit?.knowledge.map((item, index) => (
            <button key={item.knowledge_id} id={`policy-knowledge-${item.knowledge_id}`} role="option" type="button" aria-selected={item.knowledge_id === knowledge?.knowledge_id} aria-controls="policy-standardization-column" onClick={() => { setKnowledgeId(item.knowledge_id); setSelectedFields([]); setMobileStep('standardization') }}
              className={`w-full rounded-xl border p-3 text-left transition ${item.knowledge_id === knowledge?.knowledge_id ? 'border-indigo-400 bg-indigo-50/60 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
              <div className="flex items-center gap-2 text-[11px] font-semibold text-indigo-700">
                <Sparkles className="size-3.5" />知识 {index + 1}
                {item.relationship_source === 'legacy_match' && <span className="font-normal text-amber-600">历史文本关联</span>}
                <ChevronRight className="ml-auto size-3.5" />
              </div>
              <p className="mt-2 text-sm font-medium leading-6 text-slate-800">{item.business_sentence}</p>
              <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
                <Score label="完整性" value={pct(item.confidence.completeness)} />
                <Score label="准确性" value={pct(item.confidence.accuracy)} pending={item.confidence.accuracy === null} />
                <Score label="原文一致" value={pct(item.confidence.source_fidelity)} />
                <Score label="模型置信" value={pct(item.confidence.model_confidence)} />
                <Score label="值域合规" value={pct(item.confidence.value_domain_compliance)} pending={item.confidence.value_domain_compliance === null} />
              </div>
              {!!item.confidence.uncertainties.length && (
                <p className="mt-2 flex items-start gap-1 text-[11px] leading-4 text-amber-700">
                  <CircleAlert className="mt-0.5 size-3 shrink-0" />{item.confidence.uncertainties.join('；')}
                </p>
              )}
              {!!item.citations.length && <ul aria-label="来源引用" className="mt-2 space-y-1 text-[11px] text-slate-500">{item.citations.map((citation, citationIndex) => <li key={`${citation.title}-${citationIndex}`}><Link2 className="mr-1 inline size-3" />{citation.title}：{citation.evidence}</li>)}</ul>}
            </button>
          ))}
          {unit && !unit.knowledge.length && <Empty text="该单元尚无结构化知识" />}
        </div>
      </Column>

      <Column id="policy-standardization-column" className={mobileStep === 'standardization' ? '' : 'hidden lg:block'} title="指标与值域标化" subtitle={`语义契约 v${document.contract_version || '不可用'}`}>
        {knowledge ? (
          <div className="space-y-3">
            {knowledge.standardized_fields.map((field) => {
              const source = toDraftSource(document, unit.unit_id, knowledge, field)
              const fieldName = knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field
              return (
                <div key={field.source_field} className="rounded-xl border border-slate-200 bg-white p-3">
                  <div className="flex items-center gap-2">
                    {field.status === 'unmapped' && (
                      <input type="checkbox" aria-label={`选择${fieldName}`}
                        checked={selectedFields.includes(field.source_field)}
                        onChange={(event) => setSelectedFields((current) => event.target.checked ? [...current, field.source_field] : current.filter((item) => item !== field.source_field))} />
                    )}
                    <span className="text-xs font-semibold text-slate-700">{fieldName}</span>
                    <Status status={field.status} />
                  </div>
                  <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-xs">
                    <Value label="来源值" value={field.source_value} />
                    <ChevronRight className="size-4 text-slate-300" />
                    <Value label="标准值" value={field.standard_value} empty={field.status !== 'mapped'} />
                  </div>
                  {field.metric_code && (
                    <p className="mt-2 flex items-center gap-1 text-[11px] text-emerald-700"><Link2 className="size-3" />{field.metric_name || field.metric_code} · {field.metric_code}</p>
                  )}
                  {field.status === 'unmapped' && (
                    <div className="mt-2 space-y-2 rounded-lg bg-blue-50/60 p-2">
                      <p className="text-[10px] font-semibold text-blue-800">首选：绑定语义层已有指标</p>
                      <div className="flex gap-2"><select aria-label={`${fieldName}已有指标`} value={selectedMetrics[field.source_field] || ''} onChange={(event) => setSelectedMetrics((current) => ({ ...current, [field.source_field]: event.target.value }))} className="min-w-0 flex-1 rounded-md border border-blue-200 bg-white px-2 py-1 text-[11px]"><option value="">请选择已有指标</option>{metrics.map((metric) => <option key={metric.metric_code} value={metric.metric_code}>{metric.name} · {metric.metric_code}</option>)}</select><button type="button" disabled={!selectedMetrics[field.source_field]} onClick={() => onBindExisting(source, selectedMetrics[field.source_field])} className="rounded-md bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-40">绑定已有指标</button></div>
                      <button type="button" onClick={() => onCreateMetricDrafts([source])} className="flex items-center gap-1 text-[11px] font-medium text-slate-600"><Plus className="size-3" />没有合适指标，人工生成草稿</button>
                    </div>
                  )}
                  {field.status === 'invalid' && (
                    <button type="button" onClick={() => onProposeValue(source, field)}
                      className="mt-2 flex items-center gap-1 rounded-md border border-amber-200 px-2 py-1 text-[11px] font-medium text-amber-700 hover:bg-amber-50">
                      <Plus className="size-3" />新增标准值草稿
                    </button>
                  )}
                </div>
              )
            })}
            {!knowledge.standardized_fields.length && <Empty text="该知识没有适用的标化字段" />}
            {!!selectedSources.length && (
              <button type="button" onClick={() => onCreateMetricDrafts(selectedSources)}
                className="sticky bottom-2 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-lg hover:bg-blue-700">
                <Check className="size-4" />批量生成指标草稿 ({selectedSources.length})
              </button>
            )}
          </div>
        ) : <Empty text="请选择一条结构化知识" />}
      </Column>
      </div>
    </div>
  )
}

function toDraftSource(document: WorkbenchDocument, unitId: string, knowledge: KnowledgeItem, field: StandardizedField): MetricDraftSource {
  return {
    doc_id: document.doc_id, unit_id: unitId, knowledge_id: knowledge.knowledge_id,
    source_field: field.source_field,
    field_name: knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field,
    source_value: field.source_value, source_text: knowledge.source_text,
    contract_version: document.contract_version || 'unknown',
  }
}

function Column({ id, className = '', title, subtitle, children }: { id?: string; className?: string; title: string; subtitle: string; children: React.ReactNode }) {
  return <section id={id} className={`rounded-2xl border border-slate-200 bg-slate-50/70 p-3 ${className}`}>
    <div className="mb-3"><h3 className="text-sm font-semibold text-slate-900">{title}</h3><p className="mt-0.5 text-[11px] text-slate-400">{subtitle}</p></div>
    <div className="max-h-[720px] overflow-y-auto pr-1">{children}</div>
  </section>
}

function Score({ label, value, pending = false }: { label: string; value: string; pending?: boolean }) {
  return <div className={`rounded-md px-2 py-1.5 ${pending ? 'bg-amber-50' : 'bg-white'}`}><p className="text-[9px] text-slate-400">{label}</p><p className={`text-[11px] font-semibold ${pending ? 'text-amber-700' : 'text-slate-700'}`}>{value}</p></div>
}

function Status({ status }: { status: StandardizedField['status'] }) {
  const styles = { mapped: 'bg-emerald-50 text-emerald-700', unmapped: 'bg-blue-50 text-blue-700', invalid: 'bg-amber-50 text-amber-700', not_applicable: 'bg-slate-100 text-slate-500' }
  const labels = { mapped: '已映射', unmapped: '未映射', invalid: '值域未映射', not_applicable: '不适用' }
  return <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold ${styles[status]}`}>{labels[status]}</span>
}

function Value({ label, value, empty = false }: { label: string; value: unknown; empty?: boolean }) {
  return <div className="rounded-lg bg-slate-50 p-2"><p className="text-[9px] text-slate-400">{label}</p><p className="mt-0.5 break-all font-mono text-[11px] text-slate-700">{empty ? '—' : readableValue(value)}</p></div>
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value !== 'object') return String(value)
  const stable = (_key: string, item: unknown) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right)))
    : item
  return JSON.stringify(value, stable)
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-slate-200 bg-white px-3 py-10 text-center text-xs text-slate-400">{text}</div>
}
