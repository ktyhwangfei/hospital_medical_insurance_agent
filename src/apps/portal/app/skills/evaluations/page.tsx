'use client'

import { Suspense, useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { AlertCircle, FlaskConical, Plus } from 'lucide-react'
import { createSkillEvalCase, listSkillEvalCases } from '@/lib/api-client'
import { useSkillNameMap } from '@/lib/use-skill-name-map'
import { ApiClientError } from '@/lib/types'
import type { SkillEvalCaseListResponse, SkillEvalRunListResponse } from '@/lib/types'

// /skills/evaluations 评测记录页：浏览评测用例与运行记录（设计 §3.1）
// 意见4 方案A：单 Skill 的评测管理（新增用例）从详情工作区 tab 迁移至此，?skill=xxx 时启用
function EvaluationsContent() {
  const skillFilter = useSearchParams().get('skill')
  const skillNameMap = useSkillNameMap()
  // 评测用例/运行只有 skill_id，统一映射为中文名；未就绪/未命中时回退 ID
  const displayName = (id: string | null | undefined) =>
    id ? (skillNameMap.get(id) ?? id) : '通用'

  const [cases, setCases] = useState<SkillEvalCaseListResponse | null>(null)
  // 跨 Skill 的评测运行汇总需要后端 /infra-skills/eval-runs 端点；当前仅有按 skill 的端点，
  // 旧代码用 listSkillEvalRuns('') 取全部会稳定 404（每次加载浪费一次请求）。暂置空，待后端补端点。
  const [runs] = useState<SkillEvalRunListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // 新增评测用例（意见4 方案A：从详情页评测 tab 迁移至此）
  const [newQuestion, setNewQuestion] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const c = await listSkillEvalCases()
      setCases(c)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载评测记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function addCase(): Promise<void> {
    const q = newQuestion.trim()
    if (!q || !skillFilter) return
    setAdding(true)
    setAddError(null)
    try {
      await createSkillEvalCase({ question_template: q, expected_skill_id: skillFilter })
      setNewQuestion('')
      await load()
    } catch (err) {
      setAddError(err instanceof ApiClientError ? err.detail.message : '新增用例失败')
    } finally {
      setAdding(false)
    }
  }

  const visibleCases =
    cases?.items?.filter((c) => !skillFilter || c.expected_skill_id === skillFilter) ?? []

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
        {skillFilter && (
          <p className="text-xs text-slate-500">
            筛选中：<span className="font-medium text-slate-700">{displayName(skillFilter)}</span>
            （<code className="font-mono">{skillFilter}</code>）
            <a href="/skills/evaluations" className="ml-2 text-blue-700 hover:underline">清除筛选</a>
          </p>
        )}
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
          {/* 意见4 方案A：?skill 时提供新增用例入口（从详情页评测 tab 迁移）*/}
          {skillFilter && (
            <div className="mb-3 rounded-lg border border-slate-100 bg-slate-50 p-2">
              <textarea
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="输入评测问题模板，新增到当前 Skill 的必测用例…"
                className="w-full resize-none rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                rows={2}
              />
              <div className="mt-2 flex items-center justify-between">
                <span className="text-xs text-red-600">{addError}</span>
                <button
                  type="button"
                  onClick={() => void addCase()}
                  disabled={adding || !newQuestion.trim()}
                  className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  <Plus className="h-3.5 w-3.5" />
                  新增必测用例
                </button>
              </div>
            </div>
          )}
          {loading ? (
            <p className="py-6 text-center text-sm text-slate-400">加载中…</p>
          ) : visibleCases.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {visibleCases.map((c) => (
                <li key={c.case_id} className="rounded-lg border border-slate-100 p-2">
                  <div className="font-medium text-slate-800">{displayName(c.expected_skill_id)}</div>
                  <div className="text-xs text-slate-500">{c.question_template}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-slate-400">
              {skillFilter ? '该 Skill 暂无评测用例' : '暂无评测用例'}
            </p>
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
                    <span className="font-medium text-slate-800">{displayName(r.skill_id)}</span>
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

export default function SkillEvaluationsPage() {
  return (
    <Suspense fallback={<div className="mt-4 text-sm text-slate-400">加载中…</div>}>
      <EvaluationsContent />
    </Suspense>
  )
}
