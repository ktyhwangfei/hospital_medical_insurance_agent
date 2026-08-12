'use client'

import { Suspense, useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { AlertCircle, ChevronDown, ChevronRight, FlaskConical, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react'
import {
  createSkillEvalCase,
  dedupeSkillEvalCases,
  deleteSkillEvalCase,
  listAllSkillEvalRuns,
  listSkillEvalCases,
  seedGoldenSkillEvalCases,
} from '@/lib/api-client'
import { useSkillNameMap } from '@/lib/use-skill-name-map'
import { ApiClientError } from '@/lib/types'
import type {
  SkillEvalCaseListResponse,
  SkillEvalRunListResponse,
  SkillEvalRunResponse,
} from '@/lib/types'
import RunDetail from '@/components/skills/skill-eval-run-detail'
import SkillEvalLaunchPanel from '@/components/skills/skill-eval-launch-panel'

const RUN_STATUS_TONE: Record<string, string> = {
  passed: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-rose-50 text-rose-700',
  running: 'bg-blue-50 text-blue-700',
  cancelled: 'bg-slate-100 text-slate-500',
  error: 'bg-rose-50 text-rose-700',
}

const RUN_STATUS_LABEL: Record<string, string> = {
  passed: '通过',
  failed: '未通过',
  running: '运行中',
  cancelled: '已取消',
  error: '异常',
}

function EvaluationsContent() {
  const skillFilter = useSearchParams().get('skill')
  const skillNameMap = useSkillNameMap()
  const displayName = (id: string | null | undefined) =>
    id ? (skillNameMap.get(id) ?? id) : '通用'

  const [cases, setCases] = useState<SkillEvalCaseListResponse | null>(null)
  const [runs, setRuns] = useState<SkillEvalRunListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [newQuestion, setNewQuestion] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [busyCases, setBusyCases] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, r] = await Promise.all([
        listSkillEvalCases(),
        listAllSkillEvalRuns(skillFilter ? { skillId: skillFilter, limit: 50 } : { limit: 50 }),
      ])
      setCases(c)
      setRuns(r)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '加载评测记录失败')
    } finally {
      setLoading(false)
    }
  }, [skillFilter])

  useEffect(() => {
    void Promise.resolve().then(load)
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

  async function handleSeedGolden(): Promise<void> {
    setBusyCases(true)
    try {
      const result = await seedGoldenSkillEvalCases()
      setCases(result)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '载入黄金案例失败')
    } finally {
      setBusyCases(false)
    }
  }

  async function handleDedupe(): Promise<void> {
    setBusyCases(true)
    try {
      const result = await dedupeSkillEvalCases()
      setCases(result)
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '去重失败')
    } finally {
      setBusyCases(false)
    }
  }

  async function handleDeleteCase(caseId: string): Promise<void> {
    try {
      await deleteSkillEvalCase(caseId)
      await load()
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '删除用例失败')
    }
  }

  const visibleCases =
    cases?.items?.filter((c) => !skillFilter || c.expected_skill_id === skillFilter) ?? []
  const enabledCaseCount = cases?.items?.filter((c) => c.enabled).length ?? 0

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
          评测用例与运行记录。发起评测做路由回归，点击运行记录展开门禁指标与逐用例差异。
        </p>
        {skillFilter && (
          <p className="text-xs text-slate-500">
            筛选中：<span className="font-medium text-slate-700">{displayName(skillFilter)}</span>
            （<code className="font-mono">{skillFilter}</code>）
            <Link href="/skills/evaluations" className="ml-2 text-blue-700 hover:underline">清除筛选</Link>
          </p>
        )}
      </header>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <SkillEvalLaunchPanel
        enabledCaseCount={enabledCaseCount}
        onLaunched={(run: SkillEvalRunResponse) => {
          void load().then(() => setExpandedRun(run.run_id))
        }}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <FlaskConical className="h-4 w-4 text-blue-600" />
              评测用例
              <span className="text-xs font-normal text-slate-400">（{visibleCases.length}）</span>
            </h3>
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => void handleDedupe()}
                disabled={busyCases}
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              >
                <Wand2 className="h-3.5 w-3.5" />
                去重
              </button>
              <button
                type="button"
                onClick={() => void handleSeedGolden()}
                disabled={busyCases}
                className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-2 py-1 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" />
                载入黄金案例
              </button>
            </div>
          </div>
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
                <li key={c.case_id} className="flex items-start justify-between gap-2 rounded-lg border border-slate-100 p-2">
                  <div className="min-w-0">
                    <div className="font-medium text-slate-800">{displayName(c.expected_skill_id)}</div>
                    <div className="truncate text-xs text-slate-500">{c.question_template}</div>
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      {c.source_type}{c.enabled ? '' : ' · 已禁用'}
                    </div>
                  </div>
                  <button
                    type="button"
                    aria-label="删除用例"
                    onClick={() => void handleDeleteCase(c.case_id)}
                    className="shrink-0 rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-600"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-slate-400">
              {skillFilter ? '该 Skill 暂无评测用例' : '暂无评测用例，点击「载入黄金案例」快速开始'}
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
          ) : runs && runs.items.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {runs.items.map((r) => {
                const expanded = expandedRun === r.run_id
                return (
                  <li key={r.run_id} className="rounded-lg border border-slate-100">
                    <button
                      type="button"
                      data-testid={`eval-run-row-${r.run_id}`}
                      onClick={() => setExpandedRun(expanded ? null : r.run_id)}
                      className="flex w-full items-center justify-between gap-2 rounded-lg p-2 text-left hover:bg-slate-50"
                    >
                      <span className="flex items-center gap-2">
                        {expanded ? (
                          <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
                        )}
                        <span className="font-medium text-slate-800">{displayName(r.skill_id)}</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-xs ${
                            RUN_STATUS_TONE[r.status] ?? 'bg-slate-100 text-slate-500'
                          }`}
                        >
                          {RUN_STATUS_LABEL[r.status] ?? r.status}
                        </span>
                        <span className="text-xs text-slate-500">
                          {r.metrics.passed}/{r.metrics.total} 通过
                          {r.metrics.gate_passed ? ' · 门禁通过' : ' · 门禁未过'}
                        </span>
                      </span>
                      <span className="text-xs text-slate-400">
                        {new Date(r.created_at).toLocaleString('zh-CN')}
                      </span>
                    </button>
                    {expanded ? <RunDetail run={r} displayName={displayName} /> : null}
                  </li>
                )
              })}
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
