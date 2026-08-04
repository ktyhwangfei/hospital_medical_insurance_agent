'use client'

// 政策知识对齐工作台 · 右栏：指标与值域标化
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 治理台设计（迭代12.6）：标化字段按映射状态分组展示（待处理/已映射/不适用），
// 提供「仅待办」开关；描述型字段（entities/relations 等）折叠于底部，不占主区。

import { useMemo, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Link2, Plus } from 'lucide-react'

import type {
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
  selectedFields: string[]
  selectedMetrics: Record<string, string>
  onToggleField: (sourceField: string, checked: boolean) => void
  onSelectMetric: (sourceField: string, metricCode: string) => void
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
}

type StatusTab = 'pending' | 'mapped' | 'other'

const STATUS_TABS: { key: StatusTab; label: string }[] = [
  { key: 'pending', label: '待处理' },
  { key: 'mapped', label: '已映射' },
  { key: 'other', label: '不适用' },
]

export function StandardizationColumn(props: Props) {
  const {
    document, unitId, knowledgeId, metrics,
    selectedFields, selectedMetrics,
    onToggleField, onSelectMetric, onBindExisting, onCreateMetricDrafts, onProposeValue,
  } = props
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const knowledge = unit?.knowledge.find((item) => item.knowledge_id === knowledgeId) || unit?.knowledge[0]
  const [tab, setTab] = useState<StatusTab>('pending')
  const [showDescriptive, setShowDescriptive] = useState(false)

  // 分组统计
  const grouped = useMemo(() => {
    if (!knowledge) return { pending: [], mapped: [], other: [], descriptive: [] as StandardizedField[] }
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
  }, [knowledge])

  if (!knowledge) return <Empty text="请选择一条结构化知识" />

  const { pending, mapped, other, descriptive } = grouped
  const counts: Record<StatusTab, number> = { pending: pending.length, mapped: mapped.length, other: other.length }
  const tabFields: Record<StatusTab, StandardizedField[]> = { pending, mapped, other }
  const visibleFields = tabFields[tab]

  const selectedSources = pending
    .filter((field) => selectedFields.includes(field.source_field))
    .map((field) => toDraftSource(document, unit.unit_id, knowledge, field))

  return (
    <div className="flex flex-col gap-3">
      {/* 状态分组 Tab + 仅待办 */}
      <div className="flex items-center gap-1">
        <div className="flex gap-0.5 rounded-md bg-slate-200/60 p-0.5">
          {STATUS_TABS.map(({ key, label }) => (
            <button key={key} type="button" aria-label={`${label}字段`}
              onClick={() => setTab(key)}
              className={`rounded px-2 py-1 text-[10px] font-medium transition ${tab === key ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
              {label} {counts[key] > 0 && <span className="ml-0.5 text-slate-400">({counts[key]})</span>}
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-1 text-[10px] text-slate-500 cursor-pointer">
          <input type="checkbox" checked={selectedFields.length > 0} onChange={() => {}} className="hidden" aria-hidden />
          已选 {selectedFields.length}
        </label>
      </div>

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
            {visibleFields.map((field) => {
              const source = toDraftSource(document, unit.unit_id, knowledge, field)
              const fieldName = knowledge.fields.find((item) => item.field_code === field.source_field)?.field_name || field.source_field
              return (
                <tr key={field.source_field} className="border-b border-slate-100 align-top last:border-b-0 hover:bg-slate-50/60">
                  {/* 选择列：仅待处理字段可勾选 */}
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
                  {/* 来源值：长对象截断 */}
                  <td className="max-w-24 px-2 py-2 font-mono text-[11px] text-slate-700">
                    <span className="line-clamp-2 break-all">{readableValue(field.source_value)}</span>
                  </td>
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
            {visibleFields.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-xs text-slate-400">该分组暂无字段</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 描述型字段折叠区 */}
      {descriptive.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white">
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
          className="sticky bottom-2 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-lg hover:bg-blue-700">
          <Check className="size-4" />批量生成指标草稿 ({selectedSources.length})
        </button>
      )}
    </div>
  )
}
