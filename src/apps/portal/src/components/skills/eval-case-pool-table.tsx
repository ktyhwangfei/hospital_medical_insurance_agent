'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Database } from 'lucide-react'

import { listEvalCasePool, type EvalCasePoolItem } from '@/lib/policy-qa-feedback'
import { useSkillNameMap } from '@/lib/use-skill-name-map'
import { ApiClientError } from '@/lib/types'

const STATUS_LABELS: Record<string, string> = {
  pending_triage: '待分类',
  triaged: '已分类',
  transformed: '已物化',
  discarded: '已丢弃',
}

const DIMENSION_LABELS: Record<string, string> = {
  calculation: '计算',
  citation: '引用',
  routing: '路由',
  coverage: '覆盖',
  knowledge: '知识',
  hallucination: '幻觉',
  other: '其他',
}

/** Skill 错误案例池表格：评测者浏览用户反馈挖掘出的回归案例。 */
export default function EvalCasePoolTable() {
  const [items, setItems] = useState<EvalCasePoolItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const skillNameMap = useSkillNameMap()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listEvalCasePool({ limit: 100 })
      setItems(result.items)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载案例池失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 服务端数据加载的标准模式
    void load()
  }, [load])

  const displayName = (id: string | null | undefined) =>
    id ? (skillNameMap.get(id) ?? id) : '—'

  return (
    <section data-testid="eval-case-pool-table" className="space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-slate-800">
          <Database className="size-5" aria-hidden />
          <h2 className="text-lg font-semibold">错误案例池</h2>
        </div>
        <span className="text-sm text-slate-500">共 {items.length} 条</span>
      </header>

      {error ? (
        <div className="flex items-center gap-2 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">
          <AlertCircle className="size-4" aria-hidden />
          {error}
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-slate-500">加载中…</p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">
          暂无案例。用户在政策问答中提交「回答有误」反馈后，案例将在此汇总。
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">来源轮次</th>
                <th className="px-3 py-2">错误维度</th>
                <th className="px-3 py-2">原因码</th>
                <th className="px-3 py-2">目标技能</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">创建时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((item) => (
                <tr key={item.poolId} data-testid={`eval-case-pool-row-${item.poolId}`}>
                  <td className="px-3 py-2 font-mono text-xs text-slate-600">
                    {item.sourceQaTurnId}
                  </td>
                  <td className="px-3 py-2">
                    <span className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                      {DIMENSION_LABELS[item.errorDimension] ?? item.errorDimension}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{item.reasonCode}</td>
                  <td className="px-3 py-2 text-slate-700">
                    {displayName(item.targetSkillId)}
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {STATUS_LABELS[item.status] ?? item.status}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">
                    {new Date(item.createdAt).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
