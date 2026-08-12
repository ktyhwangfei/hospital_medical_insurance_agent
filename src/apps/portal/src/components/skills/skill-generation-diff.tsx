'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import type { SkillAIOptimizationProposal } from '../../lib/types'

interface SkillGenerationDiffProps {
  proposal: SkillAIOptimizationProposal
  onAccept: (proposal: SkillAIOptimizationProposal) => void | Promise<void>
  onDismiss: () => void
  accepting?: boolean
}

const CHANGE_LABELS = {
  added: '已新增',
  changed: '已更改',
  removed: '已移除',
} as const

const CHANGE_STYLES = {
  added: 'bg-green-50 text-green-700',
  changed: 'bg-blue-50 text-blue-700',
  removed: 'bg-red-50 text-red-700',
} as const

export function SkillGenerationDiff({
  proposal,
  onAccept,
  onDismiss,
  accepting = false,
}: SkillGenerationDiffProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggle(key: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <section className="space-y-3 rounded-xl border border-blue-200 bg-white p-4 shadow-sm" aria-label="AI 优化差异">
      <div>
        <h3 className="text-sm font-semibold text-slate-900">AI 优化提案</h3>
        <p className="text-xs text-slate-500">基于 revision {proposal.base_revision}，接受前不会改动当前草稿。</p>
      </div>

      {proposal.diff.length === 0 ? (
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">没有检测到内容变化。</p>
      ) : (
        <ul className="space-y-2">
          {proposal.diff.map((item) => {
            const key = `${item.scope}:${item.path}`
            const isExpanded = expanded.has(key)
            return (
              <li key={key} className="rounded-lg border border-slate-200">
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  aria-controls={`diff-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
                  onClick={() => toggle(key)}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left"
                >
                  {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${CHANGE_STYLES[item.change_type]}`}>
                    {CHANGE_LABELS[item.change_type]}
                  </span>
                  <code className="min-w-0 flex-1 truncate text-xs text-slate-700">{item.path}</code>
                  <span className="text-xs text-slate-400">{item.scope === 'file' ? '文件' : '字段'}</span>
                </button>
                {isExpanded && (
                  <div id={`diff-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`} className="grid gap-2 border-t border-slate-100 p-3 md:grid-cols-2">
                    <div>
                      <p className="mb-1 text-xs font-medium text-slate-500">修改前</p>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-red-50 p-2 text-xs text-red-800">{item.before ?? '—'}</pre>
                    </div>
                    <div>
                      <p className="mb-1 text-xs font-medium text-slate-500">修改后</p>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-green-50 p-2 text-xs text-green-800">{item.after ?? '—'}</pre>
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onDismiss} disabled={accepting} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 disabled:opacity-50">
          放弃提案
        </button>
        <button type="button" onClick={() => void onAccept(proposal)} disabled={accepting} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
          {accepting ? '正在接受…' : '接受优化'}
        </button>
      </div>
    </section>
  )
}
