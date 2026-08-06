'use client'

// 政策知识对齐工作台 · 中栏：结构化知识
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 治理台设计（迭代13）：
//   · 单元结构化覆盖比例（含结构化价值的知识 / 总知识）
//   · 字段值 / 证据句可点击 → 高亮左栏原文并滚动定位（跨栏联动）
//   · 每组知识评审（通过 → 进入右栏标化；驳回）结论落库
//   · 表格 / JSON 视图切换保留

import { useState } from 'react'
import {
  Check, ChevronDown, ChevronRight, ChevronRight as ChevronRightIcon, CircleAlert,
  Code2, Crosshair, Link2, MinusCircle, SkipForward, Sparkles, Table2, X,
} from 'lucide-react'

import type { KnowledgeItem, WorkbenchDocument } from '@/lib/policy-knowledge-api'

import {
  Empty, FieldValue, fieldTier, hasNumericPattern, knowledgeHasStructuredValue,
  pct, readableValue, unitCoverage,
} from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  unitId: string
  selectedKnowledgeId: string
  /** 点击字段值/证据句时触发：高亮左栏原文并滚动定位。 */
  onLocate: (token: string) => void
  /** 评审：通过 / 驳回（落库）。 */
  onReview: (knowledge: KnowledgeItem, status: 'approved' | 'rejected') => void
  onSelectKnowledge: (knowledgeId: string) => void
}

type KnowledgeView = 'table' | 'json'

/** 原文中的数字/金额高亮（匹配 数字+元/万/% 或纯数字） */
const HIGHLIGHT_PATTERN = /\d+(?:\.\d+)?\s*(?:元|万元|万|块|%|％|分之)?/g

/** 原文引用：抽取数字高亮显示，支持 1 秒审计 */
function EvidenceQuote({ text }: { text: string }) {
  if (!text) return <span className="text-slate-400">（无原文引用）</span>
  const parts: React.ReactNode[] = []
  let lastIndex = 0
  for (const match of text.matchAll(HIGHLIGHT_PATTERN)) {
    const index = match.index ?? 0
    if (index > lastIndex) parts.push(text.slice(lastIndex, index))
    parts.push(<mark key={index} className="rounded bg-amber-100 px-0.5 font-semibold text-amber-800">{match[0]}</mark>)
    lastIndex = index + match[0].length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return <span className="leading-relaxed">{parts}</span>
}

function ReviewBadge({ status }: { status: KnowledgeItem['review_status'] }) {
  if (status === 'approved') {
    return <span className="flex items-center gap-0.5 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700"><Check className="size-3" />已通过</span>
  }
  if (status === 'rejected') {
    return <span className="flex items-center gap-0.5 rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-600"><X className="size-3" />已驳回</span>
  }
  return <span className="flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600"><CircleAlert className="size-3" />待评审</span>
}

export function KnowledgeColumn({ document, unitId, selectedKnowledgeId, onLocate, onReview, onSelectKnowledge }: Props) {
  const [view, setView] = useState<KnowledgeView>('table')
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const coverage = unitCoverage(unit?.knowledge || [])
  const coveragePct = coverage.total === 0 ? '—' : `${Math.round((coverage.covered / coverage.total) * 100)}%`

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        {/* 视图切换 */}
        <div className="flex items-center gap-0.5 rounded-md bg-slate-200/60 p-0.5 w-fit">
          <button type="button" aria-label="表格视图" onClick={() => setView('table')}
            className={`flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium transition ${view === 'table' ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
            <Table2 className="size-3" />表格
          </button>
          <button type="button" aria-label="JSON视图" onClick={() => setView('json')}
            className={`flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium transition ${view === 'json' ? 'bg-white text-slate-700 shadow-sm ring-1 ring-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
            <Code2 className="size-3" />JSON
          </button>
        </div>
        {/* 结构化覆盖比例 */}
        <div className="ml-auto flex items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-1 text-[10px] text-indigo-700" title="含结构化价值的知识 / 知识总条数">
          <span className="font-semibold">结构化覆盖</span>
          <span className="font-bold">{coverage.covered}/{coverage.total}</span>
          <span>({coverage.covered}/{coverage.total} · {coveragePct})</span>
        </div>
      </div>

      <div role="listbox" aria-label="结构化知识" className="space-y-3">
        {unit?.knowledge.map((item, index) => (
          <KnowledgeCard key={item.knowledge_id} knowledge={item} index={index}
            selected={item.knowledge_id === selectedKnowledgeId}
            view={view}
            onLocate={onLocate}
            onReview={onReview}
            onSelect={() => onSelectKnowledge(item.knowledge_id)} />
        ))}
        {unit && !unit.knowledge.length && <Empty text="该单元尚无结构化知识" />}
      </div>
    </div>
  )
}

function KnowledgeCard({ knowledge, index, selected, view, onLocate, onReview, onSelect }: {
  knowledge: KnowledgeItem
  index: number
  selected: boolean
  view: KnowledgeView
  onLocate: (token: string) => void
  onReview: (knowledge: KnowledgeItem, status: 'approved' | 'rejected') => void
  onSelect: () => void
}) {
  const [showDescriptive, setShowDescriptive] = useState(false)
  const factFields = knowledge.fields.filter((f) => fieldTier(f) === 'fact')
  const dimFields = knowledge.fields.filter((f) => fieldTier(f) === 'dimension')
  const descFields = knowledge.fields.filter((f) => fieldTier(f) === 'descriptive')

  // 主展示文本：优先含量化数字的文本（rule_value > evidence > business_sentence）
  const ruleValue = knowledge.fields.find((f) => f.field_code === 'rule_value')?.raw_value
  const evidence = knowledge.citations[0]?.evidence || knowledge.source_text || ''
  const rvStr = ruleValue == null ? '' : (typeof ruleValue === 'string' ? ruleValue : readableValue(ruleValue))
  const numericSource = [rvStr, evidence, knowledge.business_sentence].find((t) => hasNumericPattern(t))
  const mainText = numericSource || knowledge.business_sentence
  const mainLabel = mainText === rvStr ? '规则值 · 数字高亮' : mainText === evidence ? '原文对照 · 数字高亮' : '知识摘要 · 数字高亮'
  // 跳转 token：取证据片段（更可能在左栏原文中命中定位）
  const locateToken = evidence || knowledge.business_sentence
  const reviewed = knowledge.review_status

  return (
    <div id={`policy-knowledge-${knowledge.knowledge_id}`} role="option" aria-selected={selected}
      onClick={onSelect}
      className={`w-full cursor-pointer rounded-xl border p-3 text-left transition ${selected ? 'border-indigo-400 bg-indigo-50/60 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'} ${reviewed === 'rejected' ? 'opacity-70' : ''}`}>
      <div className="flex items-center gap-2 text-[11px] font-semibold text-indigo-700">
        <span className="flex items-center gap-1.5" aria-label={`知识 ${index + 1}`}>
          <Sparkles className="size-3.5" />知识 {index + 1}
        </span>
        {knowledge.relationship_source === 'legacy_match' && <span className="font-normal text-amber-600">历史文本关联</span>}
        {!knowledgeHasStructuredValue(knowledge) && (
          <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-normal text-slate-500">
            <MinusCircle className="size-3" />无结构化价值
          </span>
        )}
        <ReviewBadge status={reviewed} />
        <ChevronRightIcon className="ml-auto size-3.5 text-slate-300" />
      </div>

      {/* 主文本：可点击 → 高亮左栏原文并定位 */}
      <button type="button" onClick={(event) => { event.stopPropagation(); if (locateToken) onLocate(locateToken) }}
        title="点击在左栏原文中定位"
        className="mt-2 w-full rounded-lg border border-amber-100 bg-amber-50/40 px-2.5 py-2 text-left transition hover:border-amber-300 hover:bg-amber-50">
        <p className="flex items-center gap-1 text-[10px] font-semibold text-amber-700">
          {mainLabel}<Crosshair className="ml-auto size-3 text-amber-500" />
        </p>
        <p className="mt-0.5 text-sm font-medium leading-6 text-slate-800"><EvidenceQuote text={mainText} /></p>
        {knowledge.citations[0] && (
          <p className="mt-1 flex items-center gap-1 text-[10px] text-slate-400"><Link2 className="size-3 shrink-0" />{knowledge.citations[0].title}</p>
        )}
      </button>

      {view === 'table' ? (
        <TableContent knowledge={knowledge}
          factFields={factFields} dimFields={dimFields} descFields={descFields}
          showDescriptive={showDescriptive} onToggleDescriptive={() => setShowDescriptive((v) => !v)}
          onLocate={onLocate} />
      ) : (
        <JsonContent knowledge={knowledge} />
      )}

      {/* 评审动作：通过 → 进入右栏标化；驳回 */}
      <div className="mt-3 flex items-center gap-1.5 border-t border-slate-100 pt-2">
        <span className="mr-auto text-[10px] text-slate-400">评审结论落库</span>
        <button type="button" disabled={reviewed === 'approved'}
          onClick={(event) => { event.stopPropagation(); onReview(knowledge, 'rejected') }}
          className="flex items-center gap-1 rounded-md border border-red-200 px-2.5 py-1 text-[11px] font-medium text-red-600 hover:bg-red-50 disabled:opacity-40">
          <X className="size-3.5" />驳回
        </button>
        <button type="button" disabled={reviewed === 'approved'}
          onClick={(event) => { event.stopPropagation(); onReview(knowledge, 'approved') }}
          className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-700 disabled:opacity-40">
          <Check className="size-3.5" />通过并标化
        </button>
      </div>
    </div>
  )
}

/** 表格视图：事实型数值面板 + 维度型 chips + 描述型折叠 + 置信度条 */
function TableContent({ knowledge, factFields, dimFields, descFields, showDescriptive, onToggleDescriptive, onLocate }: {
  knowledge: KnowledgeItem
  factFields: KnowledgeItem['fields']
  dimFields: KnowledgeItem['fields']
  descFields: KnowledgeItem['fields']
  showDescriptive: boolean
  onToggleDescriptive: () => void
  onLocate: (token: string) => void
}) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      {/* 事实型数值面板：每个值可点击 → 高亮左栏原文 */}
      {factFields.length > 0 && (
        <div className="rounded-lg border border-amber-100 bg-amber-50/40 p-2">
          <p className="mb-1.5 text-[10px] font-semibold text-amber-700">结构化值（点击定位原文）</p>
          <div className="flex flex-wrap gap-2">
            {factFields.map((field) => {
              const token = String(field.raw_value ?? '')
              return (
                <button key={field.field_code} type="button" onClick={(event) => { event.stopPropagation(); onLocate(token) }}
                  title="点击在左栏原文中定位该值"
                  className="rounded-md bg-white px-2.5 py-1.5 text-left ring-1 ring-amber-200 transition hover:bg-amber-50 hover:ring-amber-400">
                  <p className="text-[9px] text-slate-400">{field.field_name || field.field_code}</p>
                  <p className="text-sm font-bold text-amber-800">{readableValue(field.raw_value)}</p>
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* 维度型 chips：可点击定位 */}
      {dimFields.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {dimFields.map((field) => (
            <button key={field.field_code} type="button" onClick={(event) => { event.stopPropagation(); onLocate(String(field.raw_value ?? '')) }}
              title="点击在左栏原文中定位"
              className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-slate-200">
              {field.field_name || field.field_code}：<span className="font-medium">{readableValue(field.raw_value)}</span>
            </button>
          ))}
        </div>
      )}

      {/* 描述型折叠 */}
      {descFields.length > 0 && (
        <div className="rounded-lg border border-slate-100 bg-white">
          <button type="button" onClick={(e) => { e.stopPropagation(); onToggleDescriptive() }}
            className="flex w-full items-center gap-1 px-2 py-1.5 text-[10px] font-medium text-slate-400 hover:text-slate-600">
            {showDescriptive ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
            描述字段（{descFields.length}）
          </button>
          {showDescriptive && (
            <table className="w-full border-collapse border-t border-slate-100 text-[11px]">
              <tbody>
                {descFields.map((field) => (
                  <tr key={field.field_code} className="border-b border-slate-50 align-top last:border-b-0">
                    <td className="w-20 px-2 py-1 text-slate-500">{field.field_name || field.field_code}</td>
                    <td className="px-2 py-1"><FieldValue value={field.raw_value} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 置信度条 */}
      <div className="rounded-lg bg-slate-50 px-2 py-1.5" title={`完整性 ${pct(knowledge.confidence.completeness)} · 原文一致 ${pct(knowledge.confidence.source_fidelity)} · 模型 ${pct(knowledge.confidence.model_confidence)} · 值域 ${pct(knowledge.confidence.value_domain_compliance)}`}>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-400">置信度</span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.round((knowledge.confidence.overall || 0) * 100)}%` }} />
          </div>
          <span className="text-[11px] font-semibold text-slate-700">{pct(knowledge.confidence.overall)}</span>
        </div>
      </div>

      {!!knowledge.confidence.uncertainties.length && (
        <p className="flex items-start gap-1 text-[11px] leading-4 text-amber-700">
          <CircleAlert className="mt-0.5 size-3 shrink-0" />{knowledge.confidence.uncertainties.join('；')}
        </p>
      )}
    </div>
  )
}

/** JSON 视图：完整知识结构 */
function JsonContent({ knowledge }: { knowledge: KnowledgeItem }) {
  const payload = {
    knowledge_id: knowledge.knowledge_id,
    unit_id: knowledge.unit_id,
    relationship_source: knowledge.relationship_source,
    review_status: knowledge.review_status,
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

// 保留原「跳过」语义占位（评审动作已内联到卡片），便于未来扩展聚焦弹层
export const REVIEW_SKIP = SkipForward
