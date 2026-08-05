'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, RefreshCw, ShieldCheck } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  activateSkillRelease,
  approveSkillRelease,
  createSkillRelease,
  listSkillEvalRuns,
  listSkillReleases,
  requestSkillReleaseApproval,
} from '@/lib/api-client'
import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
} from '@/lib/types'


interface SkillReleasePanelProps {
  skillId: string
  versions: SkillVersionResponse[]
}


function mutationKey(skillId: string, action: string): string {
  return `${skillId}-${action}-${Date.now()}`
}


function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '测试发布请求失败'
}


const STATUS_LABELS: Record<SkillReleaseResponse['status'], string> = {
  candidate: '候选版',
  approval_pending: '待人工审批',
  approved: '审批通过',
  active: 'test active',
  retired: '已退役',
}


export default function SkillReleasePanel({ skillId, versions }: SkillReleasePanelProps) {
  const [runs, setRuns] = useState<SkillEvalRunResponse[]>([])
  const [releases, setReleases] = useState<SkillReleaseResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [mutating, setMutating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [runPage, releasePage] = await Promise.all([
        listSkillEvalRuns(skillId),
        listSkillReleases(skillId, 'test'),
      ])
      setRuns(runPage.items)
      setReleases(releasePage.items)
    } catch (loadError) {
      setError(errorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [skillId])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const eligible = useMemo(() => runs.find((run) => (
    run.status === 'passed'
    && run.metrics.gate_passed
    && versions.some((version) => version.version_id === run.version_id)
  )), [runs, versions])

  const mutate = async (action: () => Promise<unknown>) => {
    setMutating(true)
    setError(null)
    try {
      await action()
      await load()
    } catch (mutationError) {
      setError(errorMessage(mutationError))
    } finally {
      setMutating(false)
    }
  }

  const createCandidate = () => {
    if (!eligible) return
    void mutate(() => createSkillRelease(
      skillId,
      {
        version_id: eligible.version_id,
        eval_run_id: eligible.run_id,
        environment: 'test',
      },
      mutationKey(skillId, 'candidate'),
    ))
  }

  const advance = (release: SkillReleaseResponse) => {
    if (release.status === 'candidate') {
      void mutate(() => requestSkillReleaseApproval(
        skillId,
        release.release_id,
        { expected_revision: release.revision },
        mutationKey(skillId, 'request-approval'),
      ))
    } else if (release.status === 'approval_pending') {
      void mutate(() => approveSkillRelease(
        skillId,
        release.release_id,
        {
          expected_revision: release.revision,
          reason: '固定评测门禁通过，同意 test shadow 激活',
        },
        mutationKey(skillId, 'approve'),
      ))
    } else if (release.status === 'approved') {
      void mutate(() => activateSkillRelease(
        skillId,
        release.release_id,
        { expected_revision: release.revision },
        mutationKey(skillId, 'activate'),
      ))
    }
  }

  if (loading) {
    return <div className="py-10 text-center text-sm text-gray-500">正在加载 test 发布状态...</div>
  }

  return (
    <div className="space-y-4" data-testid="skill-release-panel">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-slate-50 px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldCheck className="h-4 w-4 text-blue-600" />test 发布门禁
            <Badge variant="outline">shadow only</Badge>
          </div>
          <p className="mt-1 text-xs text-gray-500">不会切换真实业务流量；阶段 3 才接管运行时解析。</p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={createCandidate} disabled={mutating || !eligible}>
            从通过评测创建候选
          </Button>
          <Button variant="ghost" size="icon" onClick={() => void load()} aria-label="刷新发布">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {!eligible && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          当前没有可发布的 passed 评测，请先在“批量评测”页签运行固定测试集。
        </div>
      )}

      {releases.length === 0 ? (
        <div className="rounded-lg border border-dashed py-8 text-center text-sm text-gray-500">尚无 test 发布记录</div>
      ) : releases.map((release) => (
        <div key={release.release_id} className="rounded-lg border px-4 py-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {release.status === 'active' && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
              <strong>{STATUS_LABELS[release.status]}</strong>
              <Badge variant="outline">rev {release.revision}</Badge>
              <Badge variant="secondary">{release.runtime_mode}</Badge>
            </div>
            {['candidate', 'approval_pending', 'approved'].includes(release.status) && (
              <Button size="sm" onClick={() => advance(release)} disabled={mutating}>
                {release.status === 'candidate'
                  ? '申请审批'
                  : release.status === 'approval_pending'
                    ? '人工审批通过'
                    : '激活到 test'}
              </Button>
            )}
          </div>
          <dl className="mt-2 grid gap-1 text-xs text-gray-600 md:grid-cols-2">
            <div><dt className="inline text-gray-400">release：</dt><dd className="inline font-mono">{release.release_id}</dd></div>
            <div><dt className="inline text-gray-400">version：</dt><dd className="inline font-mono">{release.version_id}</dd></div>
            <div><dt className="inline text-gray-400">eval run：</dt><dd className="inline font-mono">{release.eval_run_id}</dd></div>
            <div><dt className="inline text-gray-400">baseline：</dt><dd className="inline font-mono">{release.baseline_release_id ?? 'none'}</dd></div>
          </dl>
        </div>
      ))}
    </div>
  )
}
