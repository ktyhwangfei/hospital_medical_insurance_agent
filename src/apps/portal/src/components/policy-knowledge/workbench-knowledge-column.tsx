'use client'

// 政策知识对齐工作台 · 中栏：结构化知识
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 结构化展示：每条知识以「业务句 + 结构化字段表 + 置信度表 + 溯源」呈现，
// 并提供 表格 / JSON 两种视图切换（JSON 展示字段级完整结构）。

import { useState } from 'react'
import { ChevronRight, CircleAlert, Code2, Link2, MinusCircle, Sparkles, Table2 } from 'lucide-react'

import type { KnowledgeItem, WorkbenchDocument } from '@/lib/policy-knowledge-api'

import { Empty, FieldValue, knowledgeHasStructuredValue, pct, Score } from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  unitId: string
  selectedKnowledgeId: string
  onSelectKnowledge: (knowledgeId: string) => void
}

type KnowledgeView = 'table' | 'json'

export function KnowledgeColumn({ document, unitId, selectedKnowledgeId, onSelectKnowledge }: Props) {
  const [view, setView] = useState<KnowledgeView>('table')
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const knowledge = unit?.knowledge.find((item) => item.knowledge_id === selectedKnowledgeId) || unit?.knowledge[0]

  return (
    <div>
      {/* 视图切换：表格 / JSON */}
      <div className="mb-3 flex items-center gap-0.5 rounded-md bg-slate-200/60 p-0.5 w-fit">
        <button type="button" aria-label="表格视图" onClick={() => setView('table')}
          className={`flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium transition ${view === 'table' ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
          <Table2 className="size-3" />表格
        </button>
        <button type="button" aria-label="JSON视图" onClick={() => setView('json')}
          className={`flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium transition ${view === 'json' ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
          <Code2 className="size-3" />JSON
        </button>
      </div>

      <div role="listbox" aria-label="结构化知识" className="space-y-3">
        {unit?.knowledge.map((item, index) => (
          <KnowledgeCard key={item.knowledge_id} knowledge={item} index={index}
            selected={item.knowledge_id === knowledge?.knowledge_id}
            view={view}
            onSelect={() => onSelectKnowledge(item.knowledge_id)} />
        ))}
        {unit && !unit.knowledge.length && <Empty text="该单元尚无结构化知识" />}
      </div>
    </div>
  )
}

function KnowledgeCard({ knowledge, index, selected, view, onSelect }: {
  knowledge: KnowledgeItem
  index: number
  selected: boolean
  view: KnowledgeView
  onSelect: () => void
}) {
  return (
    <button type="button" id={`policy-knowledge-${knowledge.knowledge_id}`} role="option" aria-selected={selected}
      aria-controls="policy-standardization-column" onClick={onSelect}
      className={`w-full rounded-xl border p-3 text-left transition ${selected ? 'border-indigo-400 bg-indigo-50/60 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
      <div className="flex items-center gap-2 text-[11px] font-semibold text-indigo-700">
        <Sparkles className="size-3.5" />知识 {index + 1}
        {knowledge.relationship_source === 'legacy_match' && <span className="font-normal text-amber-600">历史文本关联</span>}
        {!knowledgeHasStructuredValue(knowledge) && (
          <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-normal text-slate-500" title="无金额或数值类结构化字段，仅人群/类别/实体描述">
            <MinusCircle className="size-3" />无结构化价值
          </span>
        )}
        <ChevronRight className="ml-auto size-3.5" />
      </div>

      {/* 业务句 */}
      <p className="mt-2 text-sm font-medium leading-6 text-slate-800">{knowledge.business_sentence}</p>

      {view === 'table' ? (
        <TableContent knowledge={knowledge} />
      ) : (
        <JsonContent knowledge={knowledge} />
      )}

      {!!knowledge.citations.length && (
        <ul aria-label="来源引用" className="mt-2 space-y-1 text-[11px] text-slate-500">
          {knowledge.citations.map((citation, citationIndex) => (
            <li key={`${citation.title}-${citationIndex}`}><Link2 className="mr-1 inline size-3" />{citation.title}：{citation.evidence}</li>
          ))}
        </ul>
      )}
    </button>
  )
}

/** 表格视图：结构化字段表 + 置信度表 + 不确定项 */
function TableContent({ knowledge }: { knowledge: KnowledgeItem }) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      {/* 结构化字段表 */}
      {knowledge.fields.length > 0 && (
        <table className="w-full border-collapse overflow-hidden rounded-lg text-[11px]">
          <thead>
            <tr className="bg-slate-100 text-left text-[10px] text-slate-500">
              <th className="w-20 px-2 py-1 font-medium">字段</th>
              <th className="px-2 py-1 font-medium">值</th>
            </tr>
          </thead>
          <tbody>
            {knowledge.fields.map((field) => (
              <tr key={field.field_code} className="border-t border-slate-100 bg-white align-top">
                <td className="px-2 py-1 text-slate-500">{field.field_name || field.field_code}</td>
                <td className="px-2 py-1"><FieldValue value={field.raw_value} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* 置信度表 */}
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-5">
        <Score label="完整性" value={pct(knowledge.confidence.completeness)} />
        <Score label="准确性" value={pct(knowledge.confidence.accuracy)} pending={knowledge.confidence.accuracy === null} />
        <Score label="原文一致" value={pct(knowledge.confidence.source_fidelity)} />
        <Score label="模型置信" value={pct(knowledge.confidence.model_confidence)} />
        <Score label="值域合规" value={pct(knowledge.confidence.value_domain_compliance)} pending={knowledge.confidence.value_domain_compliance === null} />
      </div>

      {!!knowledge.confidence.uncertainties.length && (
        <p className="flex items-start gap-1 text-[11px] leading-4 text-amber-700">
          <CircleAlert className="mt-0.5 size-3 shrink-0" />{knowledge.confidence.uncertainties.join('；')}
        </p>
      )}
    </div>
  )
}

/** JSON 视图：完整知识结构（字段级溯源、标化映射、置信度） */
function JsonContent({ knowledge }: { knowledge: KnowledgeItem }) {
  const payload = {
    knowledge_id: knowledge.knowledge_id,
    unit_id: knowledge.unit_id,
    relationship_source: knowledge.relationship_source,
    business_sentence: knowledge.business_sentence,
    fields: knowledge.fields,
    standardized_fields: knowledge.standardized_fields,
    confidence: knowledge.confidence,
  }
  return (
    <pre className="mt-3 max-h-64 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[10px] leading-4 text-slate-200">
      {JSON.stringify(payload, null, 2)}
    </pre>
  )
}
