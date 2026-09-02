'use client'

import { useEffect, useState } from 'react'
import { AlertCircle, Loader2, Play } from 'lucide-react'
import {
  createSkillEvalBenchmarkRun,
  listInfraSkillVersions,
} from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import type { SkillEvalRunResponse, SkillVersionResponse } from '@/lib/types'

/** 发起评测面板：选 Skill → 选版本 → 发起路由回归评测。 */
export default function SkillEvalLaunchPanel({
  skillId,
  benchmarkId,
  onLaunched,
  taskCount,
}: {
  skillId: string | null
  benchmarkId: string | null
  onLaunched: (run: SkillEvalRunResponse) => void
  taskCount: number
}) {
  const [versions, setVersions] = useState<SkillVersionResponse[]>([])
  const [selectedVersion, setSelectedVersion] = useState('')
  const [loadingVersions, setLoadingVersions] = useState(Boolean(skillId))
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!skillId) return
    let active = true
    listInfraSkillVersions(skillId)
      .then((items) => {
        if (active) {
          setVersions(items.filter((item) => item.validation_status === 'passed'))
        }
      })
      .catch(() => {
        if (active) setVersions([])
      })
      .finally(() => {
        if (active) setLoadingVersions(false)
      })
    return () => { active = false }
  }, [skillId])

  async function launch() {
    if (!benchmarkId || !selectedVersion) return
    setLaunching(true)
    setError(null)
    try {
      const run = await createSkillEvalBenchmarkRun(benchmarkId, {
        version_id: selectedVersion,
      })
      onLaunched(run)
      setSelectedVersion('')
    } catch (err) {
      setError(err instanceof ApiClientError ? err.detail.message : '发起评测失败')
    } finally {
      setLaunching(false)
    }
  }

  return (
    <section data-testid="eval-launch-panel" className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
        <Play className="h-4 w-4 text-blue-600" />
        发起评测
      </h3>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
        <div className="min-w-[200px] flex-1">
          <label className="block text-xs text-slate-600">候选版本</label>
          <select
            data-testid="eval-launch-version"
            value={selectedVersion}
            onChange={(e) => setSelectedVersion(e.target.value)}
            disabled={!versions.length || loadingVersions}
            className="mt-1 w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm disabled:bg-slate-50"
          >
            <option value="">{loadingVersions ? '加载中...' : '请选择已校验版本'}</option>
            {versions.map((v) => (
              <option key={v.version_id} value={v.version_id}>
                {v.semantic_version} ({v.version_id})
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[200px] rounded-md border border-dashed border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span className="font-medium text-slate-700">基线版本</span>
          <p className="mt-1">待接入版本隔离执行后开放，当前不会生成伪对比。</p>
        </div>
        <button
          type="button"
          data-testid="eval-launch-button"
          onClick={() => void launch()}
          disabled={launching || !benchmarkId || !selectedVersion}
          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {launching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          发起评测
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        本次运行锁定 Benchmark <span className="font-mono text-slate-700">{benchmarkId ?? '未选择'}</span>，
        共 <span className="font-medium text-slate-700">{taskCount}</span> 个端到端任务。
      </p>
      {error ? (
        <div className="mt-2 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {error}
        </div>
      ) : null}
    </section>
  )
}
