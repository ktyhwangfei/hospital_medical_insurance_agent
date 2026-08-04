'use client'

// 政策知识对齐工作台 · 三栏编排（Unit × Knowledge × Metric）
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 结构：
//   左栏 审核通过的单元        → workbench-units-column.tsx
//   中栏 结构化知识（表格/JSON）→ workbench-knowledge-column.tsx
//   右栏 指标与值域标化（表格） → workbench-standardization-column.tsx
// 公共组件/工具/类型           → workbench-shared.tsx

import { useState } from 'react'

import type {
  KnowledgeItem,
  MetricDraftSource,
  SemanticMetricSummary,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

import { Column } from './workbench-shared'
import { UnitsColumn } from './workbench-units-column'
import { KnowledgeColumn } from './workbench-knowledge-column'
import { StandardizationColumn } from './workbench-standardization-column'

interface Props {
  document: WorkbenchDocument
  metrics: SemanticMetricSummary[]
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
}

type MobileStep = 'units' | 'knowledge' | 'standardization'

export function KnowledgeWorkbench(props: Props) {
  return <KnowledgeWorkbenchState key={props.document.doc_id} {...props} />
}

function KnowledgeWorkbenchState({ document, metrics, onBindExisting, onCreateMetricDrafts, onProposeValue }: Props) {
  const [unitId, setUnitId] = useState(document.units[0]?.unit_id || '')
  const [knowledgeId, setKnowledgeId] = useState('')
  const [selectedFields, setSelectedFields] = useState<string[]>([])
  const [selectedMetrics, setSelectedMetrics] = useState<Record<string, string>>({})
  const [mobileStep, setMobileStep] = useState<MobileStep>('units')

  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const knowledge: KnowledgeItem | undefined =
    unit?.knowledge.find((item) => item.knowledge_id === knowledgeId) || unit?.knowledge[0]

  /** 选中单元联动：重置其下知识选中 */
  function selectUnit(nextUnitId: string) {
    const next = document.units.find((item) => item.unit_id === nextUnitId)
    setUnitId(nextUnitId)
    setKnowledgeId(next?.knowledge[0]?.knowledge_id || '')
    setSelectedFields([])
    setMobileStep('knowledge')
  }

  function selectKnowledge(nextKnowledgeId: string) {
    setKnowledgeId(nextKnowledgeId)
    setSelectedFields([])
    setMobileStep('standardization')
  }

  function toggleField(sourceField: string, checked: boolean) {
    setSelectedFields((current) => checked ? [...current, sourceField] : current.filter((item) => item !== sourceField))
  }

  const handleBindExisting = (source: MetricDraftSource, metricCode: string) => {
    onBindExisting(source, metricCode)
    setSelectedMetrics({})
  }

  return (
    <div>
      {/* 移动端阶段切换（三栏折叠为单列） */}
      <div role="tablist" aria-label="移动端工作台阶段" className="mb-3 grid grid-cols-3 rounded-xl bg-slate-100 p-1 lg:hidden">
        {([['units', '单元'], ['knowledge', '知识'], ['standardization', '标准化']] as const).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-label={`${label}阶段`} aria-selected={mobileStep === key}
            onClick={() => setMobileStep(key)}
            className={`rounded-lg px-2 py-2 text-xs ${mobileStep === key ? 'bg-white font-semibold text-blue-700 shadow-sm' : 'text-slate-500'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="grid min-h-[620px] gap-3 lg:grid-cols-[0.85fr_1.15fr_1.2fr]">
        <Column className={mobileStep === 'units' ? '' : 'hidden lg:block'} title="审核通过的单元" subtitle={`${document.units.length} 个可用单元`}>
          <UnitsColumn document={document} selectedUnitId={unit?.unit_id || ''} onSelectUnit={selectUnit} />
        </Column>

        <Column id="policy-knowledge-column" className={mobileStep === 'knowledge' ? '' : 'hidden lg:block'} title="结构化知识" subtitle={unit ? `当前单元 · ${unit.knowledge_count} 条` : '请选择单元'}>
          <KnowledgeColumn document={document} unitId={unit?.unit_id || ''} selectedKnowledgeId={knowledge?.knowledge_id || ''} onSelectKnowledge={selectKnowledge} />
        </Column>

        <Column id="policy-standardization-column" className={mobileStep === 'standardization' ? '' : 'hidden lg:block'} title="指标与值域标化" subtitle={`语义契约 v${document.contract_version || '不可用'}`}>
          <StandardizationColumn
            document={document}
            unitId={unit?.unit_id || ''}
            knowledgeId={knowledge?.knowledge_id || ''}
            metrics={metrics}
            selectedFields={selectedFields}
            selectedMetrics={selectedMetrics}
            onToggleField={toggleField}
            onSelectMetric={(sourceField, metricCode) => setSelectedMetrics((current) => ({ ...current, [sourceField]: metricCode }))}
            onBindExisting={handleBindExisting}
            onCreateMetricDrafts={onCreateMetricDrafts}
            onProposeValue={onProposeValue} />
        </Column>
      </div>
    </div>
  )
}
