'use client'

// 政策知识对齐工作台 · 左栏：审核通过的单元
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 治理台设计（迭代13）：单元按「价值」倒序排列（数字越多价值越高），
// 无数字单元默认隐藏，点击「展示全部」才显示；展示全文，支持高亮跳转定位。

import { useEffect, useState } from 'react'
import { FileCheck2, Gauge, Hash, MinusCircle } from 'lucide-react'

import type { KnowledgeItem, WorkbenchDocument } from '@/lib/policy-knowledge-api'

import { Empty, HighlightText, unitValueScore } from './workbench-shared'

interface Props {
  document: WorkbenchDocument
  selectedUnitId: string
  highlightToken?: string | null
  /** 触发滚动定位到该单元（配合 scrollNonce 变化重复触发）。 */
  scrollUnitId?: string
  scrollNonce?: number
  onSelectUnit: (unitId: string) => void
}

/** 叶子标题是否与正文重复：正文以标题开头（归一化后），则视为重叠 */
function isTitleRedundant(title: string, sourceText: string): boolean {
  const norm = (value: string) => (value || '').replace(/[\s，。、；：“”‘’（）()【】\[\]「」.,;:％%·—\-—]/g, '')
  const normTitle = norm(title)
  const normSource = norm(sourceText)
  if (!normTitle || !normSource) return false
  return normSource.startsWith(normTitle)
}

/** 单元最低置信度（取其知识置信最小值；无知识视为 1 即正常） */
function unitMinConfidence(knowledgeList: KnowledgeItem[]): number {
  if (knowledgeList.length === 0) return 1
  return Math.min(...knowledgeList.map((k) => k.confidence.overall ?? 1))
}

export function UnitsColumn({ document, selectedUnitId, highlightToken, scrollUnitId, scrollNonce, onSelectUnit }: Props) {
  const [showAll, setShowAll] = useState(false)

  // 预计算价值评分（幂等，无副作用）
  const scored = document.units.map((item) => {
    const score = unitValueScore(item.knowledge)
    const minConf = unitMinConfidence(item.knowledge)
    return { item, score, lowConf: minConf < 0.8, hasValue: score > 0 }
  })

  // 按价值倒序排列（价值相同时保持原文档 order_no 稳定）
  scored.sort((left, right) => right.score - left.score || left.item.order_no - right.item.order_no)

  const noValueCount = scored.filter((entry) => !entry.hasValue).length
  const visible = showAll
    ? scored
    : scored.filter((entry) => entry.hasValue || entry.item.unit_id === selectedUnitId)

  // 高亮跳转：nonce 变化时滚动目标单元到可视区（仅在真实触发时执行）
  useEffect(() => {
    if (!scrollUnitId || !scrollNonce) return
    const target = window.document.getElementById(`policy-unit-${scrollUnitId}`)
    if (target && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [scrollUnitId, scrollNonce, document])

  return (
    <div>
      {/* 排序与展示全部开关 */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-[10px] font-medium text-slate-500">
          <Hash className="size-3" />按价值倒序
        </span>
        <button type="button" aria-pressed={showAll} onClick={() => setShowAll((value) => !value)}
          className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition ${showAll ? 'bg-slate-800 text-white' : 'bg-white ring-1 ring-slate-200 text-slate-500 hover:bg-slate-100'}`}>
          展示全部{noValueCount > 0 && <span className="opacity-70">（含无价值 {noValueCount}）</span>}
        </button>
      </div>

      <div role="listbox" aria-label="审核通过的单元" className="space-y-2">
        {visible.map(({ item, score, lowConf }) => {
          const title = item.path[item.path.length - 1] || ''
          const parentPath = item.path.slice(0, -1)
          const redundant = isTitleRedundant(title, item.source_text)
          const selected = item.unit_id === selectedUnitId
          const showHighlight = selected && !!highlightToken
          return (
            <div key={item.unit_id} id={`policy-unit-${item.unit_id}`} role="option" aria-selected={selected}
              onClick={() => onSelectUnit(item.unit_id)}
              className={`cursor-pointer rounded-xl border p-3 transition ${selected ? 'border-blue-400 bg-blue-50 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'} ${score > 0 ? '' : 'opacity-70'}`}>
              <div className="flex items-center gap-2">
                <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                  <FileCheck2 className="mr-1 inline size-3" />{item.status === 'published' ? '已发布' : '已审核'}
                </span>
                <span className="flex items-center gap-0.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700" title="数字越多结构化价值越高">
                  <Hash className="size-3" />价值 {score}
                </span>
                {lowConf && (
                  <span className="flex items-center gap-0.5 rounded bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600" title="存在低置信知识">
                    <Gauge className="size-3" />低置信
                  </span>
                )}
                {score === 0 && (
                  <span className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500" title="无金额或数值类结构化字段">
                    <MinusCircle className="size-3" />无价值
                  </span>
                )}
                <span className="ml-auto text-[11px] text-slate-400">{item.knowledge_count} 条</span>
              </div>

              {parentPath.length > 0 && (
                <p className="mt-2 truncate text-[10px] text-slate-400" title={parentPath.join(' / ')}>
                  {parentPath.join(' / ')}
                </p>
              )}

              {title && !redundant && (
                <p className="mt-1 text-xs font-semibold leading-5 text-slate-700">{title}</p>
              )}

              {/* 正文：全文展示（需求1），选中时对中栏选中的字段值/证据高亮定位 */}
              <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-slate-600">
                <HighlightText text={item.source_text} token={showHighlight ? highlightToken : null} />
              </p>
            </div>
          )
        })}
        {visible.length === 0 && <Empty text={showAll ? '该文档暂无审核通过的单元' : '暂无有价值单元，点击「展示全部」查看'} />}
        {document.units.length === 0 && <Empty text="单元页暂无审核通过的内容" />}
      </div>
    </div>
  )
}
