'use client'

import { Suspense, useCallback, useEffect, useState } from 'react'
import { AlertCircle, GitBranch } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { getSkillGovernanceWorkbench } from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'

// /skills/releases 发布记录页：Test 发布、确认、停用、恢复、归档（设计 §3.1 §6）
function ReleasesContent() {
  const skillFilter = useSearchParams().get('skill')
  const [items, setItems] = useState<{ skill_id: string; skill_name: string; test_release_status: string | null; governance_status: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getSkillGovernanceWorkbench({ page: 1, page_size: 50 })
      setItems(data.items ?? [])
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载发布记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const filteredItems = skillFilter
    ? items.filter((i) => i.skill_id === skillFilter)
    : items

  return (
    <div className="mt-4 space-y-4">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            Skill 管理工作台
          </span>
          <span className="text-xs text-slate-500">发布记录</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">发布记录</h2>
        <p className="text-sm text-slate-600">
          Skill 版本的 Test 发布、确认、激活、停用、恢复与归档记录。
        </p>
        {skillFilter && (
          <p className="text-xs text-slate-500">
            筛选中：<span className="font-medium text-slate-700">{items.find((i) => i.skill_id === skillFilter)?.skill_name ?? skillFilter}</span>
            （<code className="font-mono">{skillFilter}</code>）
            <a href="/skills/releases" className="ml-2 text-blue-700 hover:underline">清除筛选</a>
          </p>
        )}
      </header>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">Skill</th>
              <th className="px-4 py-3 font-medium">治理状态</th>
              <th className="px-4 py-3 font-medium">Test 发布状态</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && (
              <tr>
                <td colSpan={3} className="px-4 py-12 text-center text-slate-400">加载中…</td>
              </tr>
            )}
            {!loading && filteredItems.length === 0 && (
              <tr>
                <td colSpan={3} className="px-4 py-12 text-center text-slate-400">
                  {skillFilter ? '该 Skill 暂无发布记录' : '暂无发布记录'}
                </td>
              </tr>
            )}
            {filteredItems.map((item) => (
              <tr key={item.skill_id} className="hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 font-medium text-slate-900">
                    <GitBranch className="h-4 w-4 text-slate-400" />
                    {item.skill_name}
                  </div>
                  <div className="font-mono text-xs text-slate-500">{item.skill_id}</div>
                </td>
                <td className="px-4 py-3 text-slate-600">{item.governance_status ?? '—'}</td>
                <td className="px-4 py-3">
                  {item.test_release_status ? (
                    <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                      {item.test_release_status}
                    </span>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function SkillReleasesPage() {
  return (
    <Suspense fallback={<div className="mt-4 text-sm text-slate-400">加载中…</div>}>
      <ReleasesContent />
    </Suspense>
  )
}
