'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, FlaskConical } from 'lucide-react'
import { listSkillEvalCases, listSkillEvalRuns } from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import type { SkillEvalCaseListResponse, SkillEvalRunListResponse } from '@/lib/types'

// /skills/evaluations 评测记录页：浏览评测用例与运行记录（设计 §3.1）
export default function SkillEvaluationsPage() {
  const [cases, setCases] = useState<SkillEvalCaseListResponse | null>(null)
  const [runs, setRuns] = useState<SkillEvalRunListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, r] = await Promise.all([
        listSkillEvalCases(),
        listSkillEvalRuns('').catch(() => ({ items: [], total: 0 }) as SkillEvalRunListResponse),
      ])
      setCases(c)
      setRuns(r)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载评测记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="mt-4 space-y-4">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 items-center rounded-full bg-white/70 px-2.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200/80 backdrop-blur">
            Skill 管理工作台
          </span>
          <span className="text-xs text-slate-500">评测记录</span>
        </div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">评测记录</h2>
        <p className="text-sm text-slate-600">
          Skill 评测用例与评测运行记录。物化后的版本可在此运行评测，作为发布证据。
        </p>
      </header>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <FlaskConical className="h-4 w-4 text-blue-600" />
            评测用例
          </h3>
          {loading ? (
            <p className="py-6 text-center text-sm text-slate-400">加载中…</p>
          ) : cases && cases.items && cases.items.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {cases.items.map((c) => (
                <li key={c.case_id} className="rounded-lg border border-slate-100 p-2">
                  <div className="font-medium text-slate-800">{c.expected_skill_id ?? '通用'}</div>
                  <div className="text-xs text-slate-500">{c.question_template}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-slate-400">暂无评测用例</p>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <FlaskConical className="h-4 w-4 text-green-600" />
            评测运行
          </h3>
          {loading ? (
            <p className="py-6 text-center text-sm text-slate-400">加载中…</p>
          ) : runs && runs.items && runs.items.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {runs.items.map((r) => (
                <li key={r.run_id} className="rounded-lg border border-slate-100 p-2">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-800">{r.skill_id}</span>
                    <span className="text-xs text-slate-500">
                      {new Date(r.created_at).toLocaleString('zh-CN')}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500">
                    状态: {r.status} · 版本: {r.version_id}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-slate-400">暂无评测运行记录</p>
          )}
        </section>
      </div>
    </div>
  )
}
