'use client'

import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { SkillEvalResultResponse, SkillEvalRunResponse } from '@/lib/types'

type RegressionView = 'regressions' | 'improvements' | 'all'

interface SkillRegressionTableProps {
  latest: SkillEvalRunResponse | null
  onViewEvidence: (caseId: string) => void
}

const regressionDiffs = new Set<SkillEvalResultResponse['diff']>([
  'new_failure',
  'route_changed',
  'unchanged_fail',
])

const diffLabels: Record<SkillEvalResultResponse['diff'], string> = {
  unchanged_pass: '持续通过',
  unchanged_fail: '持续失败',
  new_pass: '新增通过',
  new_failure: '新增失败',
  route_changed: '路由变化',
}

function resultLabel(skillId: string | null | undefined, confidence: number): string {
  return `${skillId ?? '未命中'} · ${Math.round(confidence * 100)}%`
}

export default function SkillRegressionTable({ latest, onViewEvidence }: SkillRegressionTableProps) {
  const [view, setView] = useState<RegressionView>('regressions')
  const [mobile, setMobile] = useState(false)
  const snapshots = useMemo(
    () => new Map(latest?.case_snapshots.map((item) => [item.case_id, item]) ?? []),
    [latest],
  )
  const results = (latest?.results ?? []).filter((result) => (
    view === 'all' || (view === 'improvements' ? result.diff === 'new_pass' : regressionDiffs.has(result.diff))
  ))

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(max-width: 767px)')
    const update = () => setMobile(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  function Risk({ result }: { result: SkillEvalResultResponse }) {
    const snapshot = snapshots.get(result.case_id)
    const labels = [result.required || snapshot?.required ? '必测' : null, ...(snapshot?.risk_tags ?? [])].filter(Boolean)
    return <span className="break-words text-xs text-slate-600">{labels.join(' · ') || '普通'}</span>
  }

  return (
    <section aria-labelledby="regression-heading" className="min-h-0 border-b border-slate-200">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <h3 id="regression-heading" className="text-sm font-semibold text-slate-950">评测差异案例</h3>
        <div aria-label="案例视图" className="flex rounded-lg border border-slate-200 p-0.5">
          {([
            ['regressions', '回归'],
            ['improvements', '改善'],
            ['all', '全部'],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={view === value}
              onClick={() => setView(value)}
              className={cn(
                'min-h-11 rounded-md px-3 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:min-h-8',
                view === value ? 'bg-blue-50 text-blue-700' : 'text-slate-600 hover:bg-slate-50',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {!results.length ? (
        <p className="border-t border-slate-200 px-4 py-8 text-center text-sm text-slate-500">当前视图没有差异案例</p>
      ) : mobile ? (
        <ul aria-label="评测差异案例" className="divide-y divide-slate-200 border-t border-slate-200">
          {results.map((result) => (
            <li key={result.case_id} className="space-y-2 p-4 text-sm">
              <div className="flex items-start justify-between gap-3"><div><strong className="break-all">{result.case_id}</strong><p className="mt-1 text-xs font-normal text-slate-500">脱敏摘要不可用</p></div><Risk result={result} /></div>
              <p className="text-slate-600">候选：{resultLabel(result.candidate_skill_id, result.candidate_confidence)}</p>
              <p className="text-slate-600">基线：{resultLabel(result.baseline_skill_id, result.baseline_confidence)}</p>
              <p className="text-slate-600">{diffLabels[result.diff]} · 失败码不可用</p>
              <Button variant="outline" className="min-h-11 w-full" onClick={() => onViewEvidence(result.case_id)}>查看脱敏证据</Button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="overflow-x-auto border-t border-slate-200">
          <table aria-label="评测差异案例" className="w-full min-w-[780px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                {['案例', '风险', '候选结果', '基线结果', '差异', '失败码', '操作'].map((label) => <th key={label} scope="col" className="px-3 py-2.5 font-medium">{label}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {results.map((result) => (
                <tr key={result.case_id}>
                  <th scope="row" className="max-w-44 px-3 py-3 font-medium text-slate-900"><span className="block break-all">{result.case_id}</span><span className="mt-1 block font-normal text-slate-500">脱敏摘要不可用</span></th>
                  <td className="px-3 py-3"><Risk result={result} /></td>
                  <td className="px-3 py-3 text-slate-600">{resultLabel(result.candidate_skill_id, result.candidate_confidence)}</td>
                  <td className="px-3 py-3 text-slate-600">{resultLabel(result.baseline_skill_id, result.baseline_confidence)}</td>
                  <td className="px-3 py-3 text-slate-600">{diffLabels[result.diff]}</td>
                  <td className="px-3 py-3 text-slate-500">失败码不可用</td>
                  <td className="px-3 py-3"><button type="button" onClick={() => onViewEvidence(result.case_id)} className="min-h-9 whitespace-nowrap font-medium text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">查看证据</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
