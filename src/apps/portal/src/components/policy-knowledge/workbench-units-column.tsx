'use client'

// 政策知识对齐工作台 · 左栏：审核通过的单元
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.5]
//
// 展示修复：原实现将 unit.path 全路径（含叶子自身标题/首句）与 source_text（叶子全文）
// 同时渲染，当叶子标题与正文开头重叠时出现同一文本重复展示。此处改为：
//   · 面包屑 = 父级路径（path 去掉末段），叶子自身标题由正文承载，避免重叠
//   · 正文 = source_text（与标题重叠部分折叠）

import { FileCheck2 } from 'lucide-react'

import type { WorkbenchDocument } from '@/lib/policy-knowledge-api'

import { Empty } from './workbench-shared'

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

export function UnitsColumn({ document, selectedUnitId, onSelectUnit }: Props) {
  return (
    <div role="listbox" aria-label="审核通过的单元" className="space-y-2">
      {document.units.map((item) => {
        const title = item.path[item.path.length - 1] || ''
        const parentPath = item.path.slice(0, -1)
        const redundant = isTitleRedundant(title, item.source_text)
        return (
          <button key={item.unit_id} id={`policy-unit-${item.unit_id}`} role="option" type="button"
            aria-selected={item.unit_id === selectedUnitId}
            aria-controls="policy-knowledge-column"
            onClick={() => onSelectUnit(item.unit_id)}
            className={`w-full rounded-xl border p-3 text-left transition ${item.unit_id === selectedUnitId ? 'border-blue-400 bg-blue-50 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300'}`}>
            <div className="flex items-center gap-2">
              <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                <FileCheck2 className="mr-1 inline size-3" />{item.status === 'published' ? '已发布' : '已审核'}
              </span>
              <span className="ml-auto text-[11px] text-slate-400">{item.knowledge_count} 条知识</span>
            </div>

            {/* 面包屑：仅父级路径，避免与正文重复 */}
            {parentPath.length > 0 && (
              <p className="mt-2 truncate text-[10px] text-slate-400" title={parentPath.join(' / ')}>
                {parentPath.join(' / ')}
              </p>
            )}

            {/* 标题（叶子自身标题/首句） */}
            <p className="mt-1 text-xs font-semibold text-slate-700">{title || '政策正文'}</p>

            {/* 正文：与标题重叠（叶子标题即全文）时不再渲染，避免同文本二次展示 */}
            {!redundant && (
              <p className="mt-1 text-xs leading-5 text-slate-500 line-clamp-4">
                {item.source_text}
              </p>
            )}
          </button>
        )
      })}
      {!document.units.length && <Empty text="单元页暂无审核通过的内容" />}
    </div>
  )
}
