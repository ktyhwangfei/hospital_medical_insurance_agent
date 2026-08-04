'use client'

// 政策知识对齐工作台 · 右栏：指标与值域标化
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 表格化展示：字段固定（字段名/状态/来源值/标准值/关联指标/操作），
// 以标准表格呈现（列固定、对齐、可读性强），替代原卡片堆叠。

import { Check, Link2, Plus } from 'lucide-react'

import type {
  MetricDraftSource,
  SemanticMetricSummary,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

import { Empty, readableValue, Status, toDraftSource } from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  unitId: string
  knowledgeId: string
  metrics: SemanticMetricSummary[]
  selectedFields: string[]
  selectedMetrics: Record<string, string>
  onToggleField: (sourceField: string, checked: boolean) => void
  onSelectMetric: (sourceField: string, metricCode: string) => void
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
}

export function StandardizationColumn(props: Props) {
  const {
    document, unitId, knowledgeId, metrics,
    selectedFields, selectedMetrics,
    onToggleField, onSelectMetric, onBindExisting, onCreateMetricDrafts, onProposeValue,
  } = props
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const knowledge = unit?.knowledge.find((item) => item.knowledge_id === knowledgeId) || unit?.knowledge[0]

  if (!knowledge) return <Empty text="请选择一条结构化知识" />

  const fields = knowledge.standardized_fields
  const selectedSources = fields
    .filter((field) => field.status === 'unmapped' && selectedFields.includes(field.source_field))
    .map((field) => toDraftSource(document, unit.unit_id, knowledge, field))

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-[10px] text-slate-500">
              <th className="w-8 px-2 py-2 font-medium text-center">选</th>
              <th className="px-2 py-2 font-medium">字段</th>
              <th className="px-2 py-2 font-medium">状态</th>
              <th className="px-2 py-2 font-medium">来源值</th>
              <th className="px-2 py-2 font-medium">标准值</th>
              <th className="px-2 py-2 font-medium">关联指标</th>
              <th className="px-2 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => {
              const source = toDraftSource(document, unit.unit_id, knowledge, field)
              const fieldName = knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field
              return (
                <tr key={field.source_field} className="border-b border-slate-100 align-top last:border-b-0 hover:bg-slate-50/60">
                  {/* 选择列：仅未映射字段可勾选 */}
                  <td className="px-2 py-2 text-center">
                    {field.status === 'unmapped' ? (
                      <input type="checkbox" aria-label={`选择${fieldName}`}
                        checked={selectedFields.includes(field.source_field)}
                        onChange={(event) => onToggleField(field.source_field, event.target.checked)} />
                    ) : null}
                  </td>
                  {/* 字段名 */}
                  <td className="max-w-28 px-2 py-2">
                    <span className="font-semibold text-slate-700">{fieldName}</span>
                    <span className="mt-0.5 block font-mono text-[10px] text-slate-400">{field.source_field}</span>
                  </td>
                  {/* 状态 */}
                  <td className="px-2 py-2"><Status status={field.status} /></td>
                  {/* 来源值 */}
                  <td className="max-w-24 px-2 py-2 font-mono text-[11px] text-slate-700">{readableValue(field.source_value)}</td>
                  {/* 标准值 */}
                  <td className="max-w-24 px-2 py-2 font-mono text-[11px] text-emerald-700">
                    {field.status === 'mapped' ? readableValue(field.standard_value) : '—'}
                  </td>
                  {/* 关联指标 */}
                  <td className="max-w-32 px-2 py-2 text-[11px] text-slate-600">
                    {field.metric_code ? (
                      <span className="flex items-center gap-1 text-emerald-700"><Link2 className="size-3 shrink-0" />{field.metric_name || field.metric_code}</span>
                    ) : '—'}
                  </td>
                  {/* 操作列 */}
                  <td className="min-w-44 px-2 py-2">
                    {field.status === 'unmapped' && (
                      <div className="flex flex-col gap-1.5 rounded-lg bg-blue-50/60 p-2">
                        <p className="text-[10px] font-semibold text-blue-800">绑定已有指标</p>
                        <div className="flex gap-1.5">
                          <select aria-label={`${fieldName}已有指标`} value={selectedMetrics[field.source_field] || ''}
                            onChange={(event) => onSelectMetric(field.source_field, event.target.value)}
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
          </tbody>
        </table>
      </div>

      {!fields.length && <Empty text="该知识没有适用的标化字段" />}

      {!!selectedSources.length && (
        <button type="button" onClick={() => onCreateMetricDrafts(selectedSources)}
          className="sticky bottom-2 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-lg hover:bg-blue-700">
          <Check className="size-4" />批量生成指标草稿 ({selectedSources.length})
        </button>
      )}
    </div>
  )
}
