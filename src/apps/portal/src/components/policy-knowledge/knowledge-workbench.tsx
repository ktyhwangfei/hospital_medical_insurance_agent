'use client'

// 政策知识对齐工作台 · 三栏编排（Unit × Knowledge × Metric）
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 结构：
//   左栏 审核通过的单元（全文/按价值倒序/高亮跳转）→ workbench-units-column.tsx
//   中栏 结构化知识（覆盖比例/字段定位/评审落库）   → workbench-knowledge-column.tsx
//   右栏 指标与值域标化（仅评审通过/弹框操作）      → workbench-standardization-column.tsx
// 公共组件/工具/类型                                → workbench-shared.tsx

import { useState } from 'react'

import type {
  KnowledgeItem,
  MetricDraftSource,
  SemanticMetricSummary,
  StandardizedField,
  WorkbenchDocument,
} from '@/lib/policy-knowledge-api'

import { Column } from './workbench-shared'
import { knowledgeHasStructuredValue } from './workbench-shared'
import { UnitsColumn } from './workbench-units-column'
import { KnowledgeColumn } from './workbench-knowledge-column'
import { StandardizationColumn } from './workbench-standardization-column'

interface Props {
  document: WorkbenchDocument
  metrics: SemanticMetricSummary[]
  onBindExisting: (source: MetricDraftSource, metricCode: string) => void
  onCreateMetricDrafts: (sources: MetricDraftSource[]) => void
  onProposeValue: (source: MetricDraftSource, field: StandardizedField) => void
  /** 评审结论（通过/驳回）落库回调。 */
  onReviewKnowledge: (knowledge: KnowledgeItem, status: 'approved' | 'rejected') => void
}

type MobileStep = 'units' | 'knowledge' | 'standardization'

export function KnowledgeWorkbench(props: Props) {
  return <KnowledgeWorkbenchState key={props.document.doc_id} {...props} />
}

function KnowledgeWorkbenchState({ document, metrics, onBindExisting, onCreateMetricDrafts, onProposeValue, onReviewKnowledge }: Props) {
  const [unitId, setUnitId] = useState(document.units[0]?.unit_id || '')
  const [knowledgeId, setKnowledgeId] = useState('')
  const [mobileStep, setMobileStep] = useState<MobileStep>('units')
  // 跨栏联动：高亮 token + 滚动定位 nonce
  const [highlightToken, setHighlightToken] = useState<string | null>(null)
  const [scrollNonce, setScrollNonce] = useState(0)

  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const knowledge: KnowledgeItem | undefined =
    unit?.knowledge.find((item) => item.knowledge_id === knowledgeId)
    || unit?.knowledge.find(knowledgeHasStructuredValue)
    || unit?.knowledge[0]

  function firstValuableKnowledge(list: KnowledgeItem[]): string {
    return list.find(knowledgeHasStructuredValue)?.knowledge_id || list[0]?.knowledge_id || ''
  }

  function selectUnit(nextUnitId: string) {
    const next = document.units.find((item) => item.unit_id === nextUnitId)
    setUnitId(nextUnitId)
    setKnowledgeId(firstValuableKnowledge(next?.knowledge || []))
    setHighlightToken(null)
    setMobileStep('knowledge')
  }

  function selectKnowledge(nextKnowledgeId: string) {
    setKnowledgeId(nextKnowledgeId)
    setMobileStep('standardization')
  }

  /** 中栏点击字段值/证据句：高亮左栏原文并滚动到当前单元。 */
  function locateInUnit(token: string) {
    if (!token) return
    setHighlightToken(token)
    setScrollNonce((value) => value + 1)
  }

  return (
    <div>
      {/* 移动端阶段切换 */}
      <div role="tablist" aria-label="移动端工作台阶段" className="mb-3 grid grid-cols-3 rounded-xl bg-slate-100 p-1 lg:hidden">
        {([['units', '单元'], ['knowledge', '知识'], ['standardization', '标准化']] as const).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-label={`${label}阶段`} aria-selected={mobileStep === key}
            onClick={() => setMobileStep(key)}
            className={`rounded-lg px-2 py-2 text-xs ${mobileStep === key ? 'bg-white font-semibold text-blue-700 shadow-sm' : 'text-slate-500'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="grid min-h-[620px] gap-3 lg:grid-cols-[minmax(0,0.7fr)_minmax(0,1.05fr)_minmax(0,1.25fr)]">
        <Column className={mobileStep === 'units' ? '' : 'hidden lg:block'} title="审核通过的单元" subtitle={`${document.units.length} 个 · 按价值倒序`}>
          <UnitsColumn document={document} selectedUnitId={unit?.unit_id || ''}
            highlightToken={highlightToken}
            scrollUnitId={unit?.unit_id}
            scrollNonce={scrollNonce}
            onSelectUnit={selectUnit} />
        </Column>

        <Column id="policy-knowledge-column" className={mobileStep === 'knowledge' ? '' : 'hidden lg:block'} title="结构化知识" subtitle={unit ? `当前单元 · ${unit.knowledge_count} 条` : '请选择单元'}>
          {unit ? (
            <KnowledgeColumn document={document} unitId={unit.unit_id}
              selectedKnowledgeId={knowledge?.knowledge_id || ''}
              onLocate={locateInUnit}
              onReview={onReviewKnowledge}
              onSelectKnowledge={selectKnowledge} />
          ) : null}
        </Column>

        <Column id="policy-standardization-column" className={mobileStep === 'standardization' ? '' : 'hidden lg:block'} title="指标与值域标化" subtitle={`语义契约 v${document.contract_version || '不可用'}`}>
          {unit ? (
            <StandardizationColumn
              document={document}
              unitId={unit.unit_id}
              knowledgeId={knowledge?.knowledge_id || ''}
              metrics={metrics}
              onBindExisting={onBindExisting}
              onCreateMetricDrafts={onCreateMetricDrafts}
              onProposeValue={onProposeValue} />
          ) : null}
        </Column>
      </div>
    </div>
  )
}
