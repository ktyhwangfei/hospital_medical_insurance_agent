'use client'

// 政策知识对齐工作台 · 左栏：审核通过的单元
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 治理台设计（迭代12.7）：单元按风险/状态筛选（低置信/待审核/无价值/全部），
// 默认呈现待办队列而非平铺长列表；无结构化价值单元灰化标注。

import { useState } from 'react'
import { FileCheck2, Gauge, MinusCircle } from 'lucide-react'

import type { KnowledgeItem, WorkbenchDocument } from '@/lib/policy-knowledge-api'

import { Empty, unitHasStructuredValue } from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  selectedUnitId: string
  onSelectUnit: (unitId: string) => void
}

/** 归一化文本用于去重比较（去空白与标点） */
function normalizeText(value: string): string {
  return (value || '').replace(/[\s，。、；：“”‘’（）()【】\[\]「」.,;:％%·—\-—]/g, '')
}

/** 叶子标题是否与正文重复：正文以标题开头（归一化后），则视为重叠 */
function isTitleRedundant(title: string, sourceText: string): boolean {
  const normTitle = normalizeText(title)
  const normSource = normalizeText(sourceText)
  if (!normTitle || !normSource) return false
  return normSource.startsWith(normTitle)
}

/** 单元最低置信度（取其知识置信最小值；无知识视为 1 即正常） */
function unitMinConfidence(knowledgeList: KnowledgeItem[]): number {
  if (knowledgeList.length === 0) return 1
  return Math.min(...knowledgeList.map((k) => k.confidence.overall ?? 1))
}

type RiskFilter = 'all' | 'lowconf' | 'pending' | 'novalue'

const RISK_FILTERS: { key: RiskFilter; label: string; color: string }[] = [
  { key: 'all', label: '全部', color: 'text-slate-500' },
  { key: 'pending', label: '待审核', color: 'text-amber-600' },
  { key: 'lowconf', label: '低置信', color: 'text-red-600' },
  { key: 'novalue', label: '无价值', color: 'text-slate-400' },
]

export function UnitsColumn({ document, selectedUnitId, onSelectUnit }: Props) {
  const [filter, setFilter] = useState<RiskFilter>('all')

  // 预计算风险标签（幂等，无副作用）
  const risks = document.units.map((item) => {
    const minConf = unitMinConfidence(item.knowledge)
    const lowConf = minConf < 0.8
    const hasValue = unitHasStructuredValue(item.knowledge)
    const pending = item.status === 'reviewed' // 待发布（reviewed）视为待处理
    return { item, minConf, lowConf, hasValue, pending }
  })

  const counts = {
    all: risks.length,
    pending: risks.filter((r) => r.pending).length,
    lowconf: risks.filter((r) => r.lowConf).length,
    novalue: risks.filter((r) => !r.hasValue).length,
  }

  const visible = risks.filter((r) => {
    if (filter === 'pending') return r.pending
    if (filter === 'lowconf') return r.lowConf
    if (filter === 'novalue') return !r.hasValue
    return true
  })

  return (
    <div>
      {/* 风险筛选 chips */}
      <div className="mb-2 flex flex-wrap gap-1">
        {RISK_FILTERS.map(({ key, label, color }) => (
          <button key={key} type="button" aria-label={`筛选${label}单元`}
            onClick={() => setFilter(key)}
            className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${filter === key ? 'bg-slate-800 text-white' : `bg-white ring-1 ring-slate-200 ${color} hover:bg-slate-100`}`}>
            {label} {counts[key] > 0 && <span className="opacity-70">({counts[key]})</span>}
          </button>
        ))}
      </div>

      <div role="listbox" aria-label="审核通过的单元" className="space-y-2">
        {visible.map(({ item, minConf, lowConf, hasValue }) => {
          const title = item.path[item.path.length - 1] || ''
          const parentPath = item.path.slice(0, -1)
          const redundant = isTitleRedundant(title, item.source_text)
          const selected = item.unit_id === selectedUnitId
          return (
            <button key={item.unit_id} id={`policy-unit-${item.unit_id}`} role="option" type="button"
              aria-selected={selected}
              aria-controls="policy-knowledge-column"
              onClick={() => onSelectUnit(item.unit_id)}
              className={`w-full rounded-xl border p-3 text-left transition ${selected ? 'border-blue-400 bg-blue-50 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'} ${hasValue ? '' : 'opacity-70'}`}>
              <div className="flex items-center gap-2">
                <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                  <FileCheck2 className="mr-1 inline size-3" />{item.status === 'published' ? '已发布' : '已审核'}
                </span>
                {lowConf && (
                  <span className="flex items-center gap-0.5 rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600" title={`最低置信度 ${minConf.toFixed(2)}`}>
                    <Gauge className="size-3" />低置信
                  </span>
                )}
                {!hasValue && (
                  <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500" title="该单元知识均为人群/类别/实体描述，无金额或数值类结构化字段">
                    <MinusCircle className="size-3" />无结构化价值
                  </span>
                )}
                <span className="ml-auto text-[11px] text-slate-400">{item.knowledge_count} 条知识</span>
              </div>

              {/* 面包屑：仅父级路径，避免与正文重复 */}
              {parentPath.length > 0 && (
                <p className="mt-2 truncate text-[10px] text-slate-400" title={parentPath.join(' / ')}>
                  {parentPath.join(' / ')}
                </p>
              )}

              {/* 标题（叶子自身标题/首句） */}
              <p className="mt-1 line-clamp-2 text-xs font-semibold leading-5 text-slate-700">{title || '政策正文'}</p>

              {/* 正文：与标题重叠（叶子标题即全文）时不再渲染，避免同文本二次展示 */}
              {!redundant && (
                <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-500">
                  {item.source_text}
                </p>
              )}
            </button>
          )
        })}
        {visible.length === 0 && <Empty text="该筛选条件下无单元" />}
        {document.units.length === 0 && <Empty text="单元页暂无审核通过的内容" />}
      </div>
    </div>
  )
}
