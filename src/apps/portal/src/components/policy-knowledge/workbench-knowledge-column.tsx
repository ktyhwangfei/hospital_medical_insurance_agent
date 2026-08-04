'use client'

// 政策知识对齐工作台 · 中栏：结构化知识
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 治理台设计（迭代12.5）：
//   · 字段三层模型：事实型（数值徽章面板）/ 维度型（chips 标签行）/ 描述型（折叠区）
//   · 原文对照（Evidence-first）：知识卡片内嵌原文引用，抽取数字高亮，可审计
//   · 表格 / JSON 视图切换保留（JSON 展示完整知识结构）

import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, ChevronRight as ChevronRightIcon, CircleAlert, Code2, Link2, MinusCircle, SkipForward, Sparkles, Table2, X } from 'lucide-react'

import type { KnowledgeItem, WorkbenchDocument } from '@/lib/policy-knowledge-api'

import { Empty, FieldValue, fieldTier, hasNumericPattern, knowledgeHasStructuredValue, pct, readableValue } from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  unitId: string
  selectedKnowledgeId: string
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

export function KnowledgeColumn({ document, unitId, selectedKnowledgeId, onSelectKnowledge }: Props) {
  const [view, setView] = useState<KnowledgeView>('table')
  const [focusId, setFocusId] = useState<string | null>(null)
  const unit = document.units.find((item) => item.unit_id === unitId) || document.units[0]
  const knowledge = unit?.knowledge.find((item) => item.knowledge_id === selectedKnowledgeId) || unit?.knowledge[0]
  const focusKnowledge = unit?.knowledge.find((item) => item.knowledge_id === focusId) || null

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
            onSelect={() => onSelectKnowledge(item.knowledge_id)}
            onFocus={() => setFocusId(item.knowledge_id)} />
        ))}
        {unit && !unit.knowledge.length && <Empty text="该单元尚无结构化知识" />}
      </div>

      {/* 聚焦弹层：原文对照 + 决策动作（迭代12.8） */}
      {focusKnowledge && (
        <FocusDialog knowledge={focusKnowledge} onClose={() => setFocusId(null)} />
      )}
    </div>
  )
}

/** 聚焦弹层：完整结构化 + 原文对照 + 决策动作（绑定/驳回/跳过） */
function FocusDialog({ knowledge, onClose }: { knowledge: KnowledgeItem; onClose: () => void }) {
  const factFields = knowledge.fields.filter((f) => fieldTier(f) === 'fact')
  const dimFields = knowledge.fields.filter((f) => fieldTier(f) === 'dimension')
  const descFields = knowledge.fields.filter((f) => fieldTier(f) === 'descriptive')
  const evidence = knowledge.citations[0]?.evidence || knowledge.source_text || ''

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="知识聚焦审核" onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
          <Sparkles className="size-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-800">知识聚焦审核</h3>
          {!knowledgeHasStructuredValue(knowledge) && (
            <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
              <MinusCircle className="size-3" />无结构化价值
            </span>
          )}
          <button type="button" onClick={onClose} aria-label="关闭" className="ml-auto rounded-md p-1 text-slate-400 hover:bg-slate-100"><X className="size-4" /></button>
        </div>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto p-5">
          {/* 原文对照（Evidence-first，替代业务句，避免重复） */}
          <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-3">
            <p className="text-[10px] font-semibold text-amber-700">原文对照 · 数字高亮</p>
            <p className="mt-1.5 text-sm font-medium leading-6 text-slate-800"><EvidenceQuote text={evidence} /></p>
            {knowledge.citations[0] && (
              <p className="mt-1.5 text-[10px] text-slate-400">来源：{knowledge.citations[0].title}</p>
            )}
          </div>

          {/* 结构化值（事实型） */}
          {factFields.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase text-slate-400">结构化值</p>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {factFields.map((field) => (
                  <div key={field.field_code} className="rounded-lg bg-amber-50 px-3 py-2 ring-1 ring-amber-200">
                    <p className="text-[9px] text-slate-400">{field.field_name || field.field_code}</p>
                    <p className="text-base font-bold text-amber-800">{readableValue(field.raw_value)}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 维度 */}
          {dimFields.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {dimFields.map((field) => (
                <span key={field.field_code} className="rounded bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                  {field.field_name || field.field_code}：<span className="font-medium">{readableValue(field.raw_value)}</span>
                </span>
              ))}
            </div>
          )}

          {/* 置信度（总分条+明细 title） */}
          <div className="rounded-lg bg-slate-50 px-3 py-2" title={`完整性 ${pct(knowledge.confidence.completeness)} · 原文一致 ${pct(knowledge.confidence.source_fidelity)} · 模型 ${pct(knowledge.confidence.model_confidence)} · 值域 ${pct(knowledge.confidence.value_domain_compliance)}`}>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-400">置信度</span>
              <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.round((knowledge.confidence.overall || 0) * 100)}%` }} />
              </div>
              <span className="text-xs font-semibold text-slate-700">{pct(knowledge.confidence.overall)}</span>
            </div>
            {!!knowledge.confidence.uncertainties.length && (
              <p className="mt-1 flex items-start gap-1 text-[11px] leading-4 text-amber-700">
                <CircleAlert className="mt-0.5 size-3 shrink-0" />{knowledge.confidence.uncertainties.join('；')}
              </p>
            )}
          </div>

          {/* 描述字段 */}
          {descFields.length > 0 && (
            <details className="rounded-xl border border-slate-100">
              <summary className="cursor-pointer px-3 py-2 text-[11px] font-medium text-slate-500">
                描述字段（{descFields.length}）：entities / relations 等
              </summary>
              <div className="border-t border-slate-100 px-3 py-2">
                {descFields.map((field) => (
                  <div key={field.field_code} className="flex items-start gap-2 py-1 text-[11px]">
                    <span className="w-20 shrink-0 text-slate-500">{field.field_name || field.field_code}</span>
                    <span className="min-w-0 break-all text-slate-600"><FieldValue value={field.raw_value} /></span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>

        {/* 决策动作（键盘 1/2/3） */}
        <div className="flex items-center gap-2 border-t border-slate-100 bg-slate-50/60 px-5 py-3">
          <span className="mr-auto text-[10px] text-slate-400">快捷键 1/2/3 · Esc 关闭</span>
          <button type="button" onClick={onClose} className="flex items-center gap-1 rounded-md bg-slate-100 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200" title="跳过 (3)">
            <SkipForward className="size-3.5" />跳过
          </button>
          <button type="button" onClick={onClose} className="flex items-center gap-1 rounded-md border border-red-200 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50" title="驳回 (2)">
            <X className="size-3.5" />驳回
          </button>
          <button type="button" onClick={onClose} className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700" title="绑定指标 (1)">
            <Check className="size-3.5" />绑定指标
          </button>
        </div>
      </div>
    </div>
  )
}

function KnowledgeCard({ knowledge, index, selected, view, onSelect, onFocus }: {
  knowledge: KnowledgeItem
  index: number
  selected: boolean
  view: KnowledgeView
  onSelect: () => void
  onFocus: () => void
}) {
  const [showDescriptive, setShowDescriptive] = useState(false)
  const factFields = knowledge.fields.filter((f) => fieldTier(f) === 'fact')
  const dimFields = knowledge.fields.filter((f) => fieldTier(f) === 'dimension')
  const descFields = knowledge.fields.filter((f) => fieldTier(f) === 'descriptive')

  // 主展示文本：优先含量化数字的文本（rule_value > evidence > business_sentence），审计可高亮；
//   全都不含数字时退回用 business_sentence 兜底，避免无内容可展示
  const ruleValue = knowledge.fields.find((f) => f.field_code === 'rule_value')?.raw_value
  const evidence = knowledge.citations[0]?.evidence || ''
  const rvStr = ruleValue == null ? '' : (typeof ruleValue === 'string' ? ruleValue : readableValue(ruleValue))
  const numericSource = [rvStr, evidence, knowledge.business_sentence].find((t) => hasNumericPattern(t))
  const mainText = numericSource || knowledge.business_sentence
  const mainLabel = mainText === rvStr ? '规则值 · 数字高亮' : mainText === evidence ? '原文对照 · 数字高亮' : '知识摘要 · 数字高亮'

  return (
    <button type="button" id={`policy-knowledge-${knowledge.knowledge_id}`} role="option" aria-selected={selected}
      aria-controls="policy-standardization-column"
      onClick={onSelect}
      onDoubleClick={onFocus}
      title="双击进入聚焦审核"
      className={`w-full rounded-xl border p-3 text-left transition ${selected ? 'border-indigo-400 bg-indigo-50/60 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
      <div className="flex items-center gap-2 text-[11px] font-semibold text-indigo-700">
        <Sparkles className="size-3.5" />知识 {index + 1}
        {knowledge.relationship_source === 'legacy_match' && <span className="font-normal text-amber-600">历史文本关联</span>}
        {!knowledgeHasStructuredValue(knowledge) && (
          <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-normal text-slate-500" title="无金额或数值类结构化字段，仅人群/类别/实体描述">
            <MinusCircle className="size-3" />无结构化价值
          </span>
        )}
        <ChevronRightIcon className="ml-auto size-3.5" />
      </div>

      {/* 主文本：优先含量化数字的文本（rule_value/evidence/business_sentence），只展示一个 + 高亮 */}
      <div className="mt-2 rounded-lg border border-amber-100 bg-amber-50/40 px-2.5 py-2">
        <p className="text-[10px] font-semibold text-amber-700">{mainLabel}</p>
        <p className="mt-0.5 text-sm font-medium leading-6 text-slate-800"><EvidenceQuote text={mainText} /></p>
        {knowledge.citations[0] && (
          <p className="mt-1 flex items-center gap-1 text-[10px] text-slate-400"><Link2 className="size-3 shrink-0" />{knowledge.citations[0].title}</p>
        )}
      </div>

      {view === 'table' ? (
        <TableContent knowledge={knowledge}
          factFields={factFields} dimFields={dimFields} descFields={descFields}
          showDescriptive={showDescriptive} onToggleDescriptive={() => setShowDescriptive((v) => !v)} />
      ) : (
        <JsonContent knowledge={knowledge} />
      )}
    </button>
  )
}

/** 表格视图：事实型数值面板 + 维度型 chips + 描述型折叠 + 置信度条 + 不确定项 */
function TableContent({ knowledge, factFields, dimFields, descFields, showDescriptive, onToggleDescriptive }: {
  knowledge: KnowledgeItem
  factFields: KnowledgeItem['fields']
  dimFields: KnowledgeItem['fields']
  descFields: KnowledgeItem['fields']
  showDescriptive: boolean
  onToggleDescriptive: () => void
}) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      {/* 事实型数值面板（结构化值核心） */}
      {factFields.length > 0 && (
        <div className="rounded-lg border border-amber-100 bg-amber-50/40 p-2">
          <p className="mb-1.5 text-[10px] font-semibold text-amber-700">结构化值</p>
          <div className="flex flex-wrap gap-2">
            {factFields.map((field) => (
              <div key={field.field_code} className="rounded-md bg-white px-2.5 py-1.5 ring-1 ring-amber-200">
                <p className="text-[9px] text-slate-400">{field.field_name || field.field_code}</p>
                <p className="text-sm font-bold text-amber-800">{readableValue(field.raw_value)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 维度型 chips */}
      {dimFields.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {dimFields.map((field) => (
            <span key={field.field_code} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
              {field.field_name || field.field_code}：<span className="font-medium">{readableValue(field.raw_value)}</span>
            </span>
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

      {/* 置信度条（总分+明细缩为 title） */}
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
