'use client'

// 政策知识对齐工作台 · 右栏：指标与值域标化
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 治理台设计（迭代13）：仅展示「评审通过」的知识；每条通过的知识独立标化。
// 栏内空间不足时，点击「弹框操作」在模态框内完成绑定/草稿/值域标化。

import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Expand, Link2, Plus, X } from 'lucide-react'

import type {
  KnowledgeItem,
  MetricDraftSource,
  SemanticMetricSummary,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

import { Empty, fieldTier, readableValue, Status, toDraftSource } from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  unitId: string
  knowledgeId: string
  metrics: SemanticMetricSummary[]
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
}

export function StandardizationColumn(props: Props) {
  const { document, unitId, knowledgeId, metrics, onBindExisting, onCreateMetricDrafts, onProposeValue } = props
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  // 仅评审通过的知识进入标化操作空间
  const approved = (unit?.knowledge || []).filter((item) => item.review_status === 'approved')

  if (!unit) return <Empty text="请选择一个单元" />
  if (approved.length === 0) {
    return <Empty text="暂无评审通过的知识；请先在中栏点击「通过并标化」" />
  }

  return (
    <div className="flex flex-col gap-3">
      {approved.map((knowledge) => (
        <StandardizationBlock
          key={knowledge.knowledge_id}
          document={document}
          unit={unit}
          knowledge={knowledge}
          metrics={metrics}
          active={knowledge.knowledge_id === knowledgeId}
          onBindExisting={onBindExisting}
          onCreateMetricDrafts={onCreateMetricDrafts}
          onProposeValue={onProposeValue} />
      ))}
    </div>
  )
}

type StatusTab = 'pending' | 'mapped' | 'other'

const STATUS_TABS: { key: StatusTab; label: string }[] = [
  { key: 'pending', label: '待处理' },
  { key: 'mapped', label: '已映射' },
  { key: 'other', label: '不适用' },
]

/** 单条通过知识的标化操作块；可在栏内或弹框内渲染。 */
function StandardizationBlock({ document, unit, knowledge, metrics, active, onBindExisting, onCreateMetricDrafts, onProposeValue, inDialog }: {
  document: WorkbenchDocument
  unit: WorkbenchDocument['units'][number]
  knowledge: KnowledgeItem
  metrics: SemanticMetricSummary[]
  active: boolean
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
  inDialog?: boolean
}) {
  const [tab, setTab] = useState<StatusTab>('pending')
  const [showDescriptive, setShowDescriptive] = useState(false)
  const [selectedFields, setSelectedFields] = useState<string[]>([])
  const [selectedMetrics, setSelectedMetrics] = useState<Record<string, string>>({})
  const [dialogOpen, setDialogOpen] = useState(false)

  const grouped = (() => {
    const pending: StandardizedField[] = []
    const mapped: StandardizedField[] = []
    const other: StandardizedField[] = []
    const descriptive: StandardizedField[] = []
    for (const field of knowledge.standardized_fields) {
      if (fieldTier({ field_code: field.source_field, field_name: '', raw_value: field.source_value }) === 'descriptive') {
        descriptive.push(field)
        continue
      }
      if (field.status === 'unmapped') pending.push(field)
      else if (field.status === 'mapped') mapped.push(field)
      else other.push(field)
    }
    return { pending, mapped, other, descriptive }
  })()

  const { pending, mapped, other, descriptive } = grouped
  const counts: Record<StatusTab, number> = { pending: pending.length, mapped: mapped.length, other: other.length }
  const visibleFields = (tab === 'pending' ? pending : tab === 'mapped' ? mapped : other)
  const toggleField = (field: string, checked: boolean) =>
    setSelectedFields((current) => (checked ? [...current, field] : current.filter((item) => item !== field)))
  const selectedSources = pending
    .filter((field) => selectedFields.includes(field.source_field))
    .map((field) => toDraftSource(document, unit.unit_id, knowledge, field))

  return (
    <>
    <section id={`policy-standardization-${knowledge.knowledge_id}`}
      className={`rounded-xl border bg-white ${active ? 'border-emerald-300 shadow-sm' : 'border-slate-200'}`}>
      <header className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-700">
          <Check className="size-3.5" />已通过 · 标化操作
        </span>
        <span className="truncate font-mono text-[10px] text-slate-400" title={knowledge.business_sentence}>
          {knowledge.knowledge_id}
        </span>
        {/* 空间不足时弹框操作 */}
        {!inDialog && (
          <button type="button" onClick={() => setDialogOpen(true)}
            className="ml-auto flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-[10px] font-medium text-slate-600 hover:bg-slate-50">
            <Expand className="size-3" />弹框操作
          </button>
        )}
      </header>

      <div className="p-3">
        {/* 状态分组 Tab */}
        <div className="mb-2 flex items-center gap-1">
          <div className="flex gap-0.5 rounded-md bg-slate-200/60 p-0.5">
            {STATUS_TABS.map(({ key, label }) => (
              <button key={key} type="button" aria-label={`${label}字段`}
                onClick={() => setTab(key)}
                className={`rounded px-2 py-1 text-[10px] font-medium transition ${tab === key ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
                {label} {counts[key] > 0 && <span className="ml-0.5 text-slate-400">({counts[key]})</span>}
              </button>
            ))}
          </div>
          <span className="ml-auto text-[10px] text-slate-500">已选 {selectedFields.length}</span>
        </div>

        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-[10px] text-slate-500">
                <th className="w-8 px-2 py-2 text-center font-medium">选</th>
                <th className="px-2 py-2 font-medium">字段</th>
                <th className="px-2 py-2 font-medium">状态</th>
                <th className="px-2 py-2 font-medium">来源值</th>
                <th className="px-2 py-2 font-medium">标准值</th>
                <th className="px-2 py-2 font-medium">关联指标</th>
                <th className="px-2 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {visibleFields.map((field) => {
                const source = toDraftSource(document, unit.unit_id, knowledge, field)
                const fieldName = knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field
                return (
                  <tr key={field.source_field} className="border-b border-slate-100 align-top last:border-b-0 hover:bg-slate-50/60">
                    <td className="px-2 py-2 text-center">
                      {field.status === 'unmapped' && (
                        <input type="checkbox" aria-label={`选择${fieldName}`}
                          checked={selectedFields.includes(field.source_field)}
                          onChange={(event) => toggleField(field.source_field, event.target.checked)} />
                      )}
                    </td>
                    <td className="max-w-28 px-2 py-2">
                      <span className="font-semibold text-slate-700">{fieldName}</span>
                      <span className="mt-0.5 block font-mono text-[10px] text-slate-400">{field.source_field}</span>
                    </td>
                    <td className="px-2 py-2"><Status status={field.status} /></td>
                    <td className="max-w-24 px-2 py-2 font-mono text-[11px] text-slate-700">
                      <span className="line-clamp-2 break-all">{readableValue(field.source_value)}</span>
                    </td>
                    <td className="max-w-24 px-2 py-2 font-mono text-[11px] text-emerald-700">
                      {field.status === 'mapped' ? readableValue(field.standard_value) : '—'}
                    </td>
                    <td className="max-w-32 px-2 py-2 text-[11px] text-slate-600">
                      {field.metric_code ? (
                        <span className="flex items-center gap-1 text-emerald-700"><Link2 className="size-3 shrink-0" />{field.metric_name || field.metric_code}</span>
                      ) : '—'}
                    </td>
                    <td className="min-w-44 px-2 py-2">
                      {field.status === 'unmapped' && (
                        <div className="flex flex-col gap-1.5 rounded-lg bg-blue-50/60 p-2">
                          <p className="text-[10px] font-semibold text-blue-800">绑定已有指标</p>
                          <div className="flex gap-1.5">
                            <select aria-label={`${fieldName}已有指标`} value={selectedMetrics[field.source_field] || ''}
                              onChange={(event) => setSelectedMetrics((current) => ({ ...current, [field.source_field]: event.target.value }))}
                              className="min-w-0 flex-1 rounded-md border border-blue-200 bg-white px-1.5 py-1 text-[10px]">
                              <option value="">请选择已有指标</option>
                              {metrics.map((metric) => (
                                <option key={metric.metric_code} value={metric.metric_code}>{metric.name} · {metric.metric_code}</option>
                              ))}
                            </select>
                            <button type="button" disabled={!selectedMetrics[field.source_field]}
                              onClick={() => onBindExisting(source, selectedMetrics[field.source_field])}
                              className="rounded-md bg-blue-600 px-2 py-1 text-[10px] font-semibold text-white disabled:opacity-40">
                              绑定已有指标
                            </button>
                          </div>
                          <button type="button" onClick={() => onCreateMetricDrafts([source])}
                            className="flex items-center gap-1 text-[10px] font-medium text-slate-600 hover:text-slate-800">
                            <Plus className="size-3" />没有合适指标，生成草稿
                          </button>
                        </div>
                      )}
                      {field.status === 'invalid' && (
                        <button type="button" onClick={() => onProposeValue(source, field)}
                          className="flex items-center gap-1 rounded-md border border-amber-200 px-2 py-1 text-[10px] font-medium text-amber-700 hover:bg-amber-50">
                          <Plus className="size-3" />新增标准值草稿
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {visibleFields.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-xs text-slate-400">该分组暂无字段</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 描述型字段折叠区 */}
        {descriptive.length > 0 && (
          <div className="mt-2 rounded-xl border border-slate-200 bg-white">
            <button type="button" onClick={() => setShowDescriptive((v) => !v)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-[11px] font-medium text-slate-500 hover:bg-slate-50">
              {showDescriptive ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              描述字段（{descriptive.length}）：entities / relations 等 AI 辅助信息
            </button>
            {showDescriptive && (
              <div className="border-t border-slate-100 px-3 py-2">
                {descriptive.map((field) => {
                  const fieldName = knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field
                  return (
                    <div key={field.source_field} className="flex items-start gap-2 py-1 text-[11px]">
                      <span className="w-24 shrink-0 text-slate-500">{fieldName}</span>
                      <span className="min-w-0 break-all font-mono text-slate-600 line-clamp-2">{readableValue(field.source_value)}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {!knowledge.standardized_fields.length && <Empty text="该知识没有适用的标化字段" />}

        {!!selectedSources.length && (
          <button type="button" onClick={() => onCreateMetricDrafts(selectedSources)}
            className="sticky bottom-2 mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-lg hover:bg-blue-700">
            <Check className="size-4" />批量生成指标草稿 ({selectedSources.length})
          </button>
        )}
      </div>
    </section>
    {!inDialog && (
      <StandardizationDialog
        open={dialogOpen}
        document={document} unit={unit} knowledge={knowledge} metrics={metrics}
        onBindExisting={onBindExisting}
        onCreateMetricDrafts={onCreateMetricDrafts}
        onProposeValue={onProposeValue}
        onClose={() => setDialogOpen(false)} />
    )}
    </>
  )
}

/** 弹框：在空间不足时承载单条知识的标化操作（需求3）。 */
export function StandardizationDialog({ open, document, unit, knowledge, metrics, onBindExisting, onCreateMetricDrafts, onProposeValue, onClose }: {
  open: boolean
  document: WorkbenchDocument
  unit: WorkbenchDocument['units'][number]
  knowledge: KnowledgeItem
  metrics: SemanticMetricSummary[]
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
  onClose: () => void
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="弹框标化操作"
        className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}>
        <header className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
          <Expand className="size-4 text-emerald-600" />
          <h3 className="text-sm font-semibold text-slate-800">弹框标化操作</h3>
          <button type="button" onClick={onClose} aria-label="关闭" className="ml-auto rounded-md p-1 text-slate-400 hover:bg-slate-100"><X className="size-4" /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <StandardizationBlock
            document={document} unit={unit} knowledge={knowledge} metrics={metrics}
            active
            inDialog
            onBindExisting={onBindExisting}
            onCreateMetricDrafts={onCreateMetricDrafts}
            onProposeValue={onProposeValue} />
        </div>
      </div>
    </div>
  )
}
