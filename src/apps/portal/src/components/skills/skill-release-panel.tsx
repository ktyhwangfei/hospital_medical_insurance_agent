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
import { ApiClientError } from '@/lib/types'
import type {
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
} from '@/lib/types'

interface SkillReleasePanelProps {
  skillId: string
  versions: SkillVersionResponse[]
  environment?: 'dev' | 'test'
  readOnly?: boolean
  onChanged?: () => Promise<void> | void
}

type ReleaseAction = 'create_candidate' | 'request_approval' | 'approve' | 'activate' | 'none'

const ACTION_LABELS: Record<Exclude<ReleaseAction, 'none'>, string> = {
  create_candidate: '从通过评测创建候选',
  request_approval: '申请审批',
  approve: '人工审批通过',
  activate: '激活 Test Shadow',
}

const STATUS_LABELS: Record<SkillReleaseResponse['status'], string> = {
  candidate: '候选版',
  approval_pending: '待人工审批',
  approved: '审批通过',
  active: 'Test Active',
  retired: '已退役',
}

const GATE_LABELS: Record<string, string> = {
  artifact_changed: '制品内容已变化，需要重新登记和评测',
  config_changed: '评测配置已变化，需要重新评测',
  suite_changed: '固定测试集已变化，需要重新评测',
  routing_manifest_changed: '路由 Manifest 已变化，需要重新评测',
  baseline_changed: '活动基线已变化，需要重新评测和审批',
  manual_approval_required: '需要不同身份的人工审批',
}

export function nextReleaseAction(release: SkillReleaseResponse | undefined): ReleaseAction {
  if (!release) return 'create_candidate'
  if (release.status === 'candidate') return 'request_approval'
  if (release.status === 'approval_pending') return 'approve'
  if (release.status === 'approved') return 'activate'
  return 'none'
}

function mutationKey(skillId: string, action: string): string {
  return `${skillId}-${action}-${Date.now()}`
}

function gateFailureLabels(error: unknown): string[] {
  if (!(error instanceof ApiClientError)) return []
  const raw = error.detail.audit_event?.gate_failures
  if (!Array.isArray(raw)) return []
  return raw
    .filter((value): value is string => typeof value === 'string')
    .map((value) => GATE_LABELS[value] ?? value)
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiClientError && error.status === 409 && gateFailureLabels(error).length === 0) {
    return '状态已变化，刷新后重新确认'
  }
  return error instanceof Error ? error.message : '测试发布请求失败'
}

export default function SkillReleasePanel({
  skillId,
  versions,
  environment = 'test',
  readOnly = false,
  onChanged,
}: SkillReleasePanelProps) {
  const [runs, setRuns] = useState<SkillEvalRunResponse[]>([])
  const [releases, setReleases] = useState<SkillReleaseResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [mutating, setMutating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [gateFailures, setGateFailures] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setGateFailures([])
    try {
      const [runPage, releasePage] = await Promise.all([
        listSkillEvalRuns(skillId),
        listSkillReleases(skillId, environment),
      ])
      setRuns(runPage.items)
      setReleases(releasePage.items)
    } catch (loadError) {
      setError(errorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [environment, skillId])

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const eligible = useMemo(() => runs.find((run) => (
    run.status === 'passed'
    && run.metrics.gate_passed
    && versions.some((version) => version.version_id === run.version_id)
  )), [runs, versions])
  const latestRelease = releases.find((release) => release.status !== 'retired')
  const action = nextReleaseAction(latestRelease)

  async function mutate(operation: () => Promise<unknown>): Promise<void> {
    setMutating(true)
    setError(null)
    setGateFailures([])
    try {
      await operation()
      await load()
      await onChanged?.()
    } catch (mutationError) {
      setGateFailures(gateFailureLabels(mutationError))
      setError(errorMessage(mutationError))
    } finally {
      setMutating(false)
    }
  }

  function runPrimaryAction(): void {
    if (action === 'create_candidate' && eligible) {
      void mutate(() => createSkillRelease(
        skillId,
        { version_id: eligible.version_id, eval_run_id: eligible.run_id, environment: 'test' },
        mutationKey(skillId, action),
      ))
    } else if (action === 'request_approval' && latestRelease) {
      void mutate(() => requestSkillReleaseApproval(
        skillId,
        latestRelease.release_id,
        { expected_revision: latestRelease.revision },
        mutationKey(skillId, action),
      ))
    } else if (action === 'approve' && latestRelease) {
      void mutate(() => approveSkillRelease(
        skillId,
        latestRelease.release_id,
        { expected_revision: latestRelease.revision, reason: '固定评测门禁通过，同意 Test Shadow 激活' },
        mutationKey(skillId, action),
      ))
    } else if (action === 'activate' && latestRelease) {
      void mutate(() => activateSkillRelease(
        skillId,
        latestRelease.release_id,
        { expected_revision: latestRelease.revision },
        mutationKey(skillId, action),
      ))
    }
  }

  if (loading) return <div className="py-10 text-center text-sm text-slate-500">正在加载 {environment} 发布状态…</div>

  return (
    <div className="space-y-4" data-testid="skill-release-panel">
      {environment === 'dev' && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">dev 环境在本工作台只读</div>
      )}
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      {gateFailures.length > 0 && (
        <ul className="list-disc space-y-1 rounded-lg bg-amber-50 px-8 py-3 text-sm text-amber-800">
          {gateFailures.map((failure) => <li key={failure}>{failure}</li>)}
        </ul>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <ShieldCheck className="h-4 w-4 text-blue-600" />{environment} 发布门禁
            <Badge variant="outline">shadow only</Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500">不会切换真实业务流量，仅用于治理验证。</p>
        </div>
        <div className="flex items-center gap-2">
          {!readOnly && action !== 'none' && (
            <Button
              onClick={runPrimaryAction}
              disabled={mutating || (action === 'create_candidate' && !eligible)}
            >
              {ACTION_LABELS[action]}
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={() => void load()} aria-label="刷新发布">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {action === 'create_candidate' && !eligible && environment === 'test' && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">当前没有可发布的 passed 评测，请先完成固定测试集。</div>
      )}
      {latestRelease?.status === 'active' && (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-4 text-emerald-800">
          <CheckCircle2 className="h-5 w-5" />
          <strong>Test Shadow 已激活</strong>
        </div>
      )}
      {latestRelease?.approval && (
        <section className="rounded-lg border border-slate-200 p-4">
          <h3 className="text-sm font-medium text-slate-900">人工审批证据</h3>
          <dl className="mt-3 grid gap-2 text-sm md:grid-cols-3">
            <div><dt className="text-xs text-slate-500">审批人</dt><dd className="mt-1">{latestRelease.approval.approved_by}</dd></div>
            <div><dt className="text-xs text-slate-500">审批角色</dt><dd className="mt-1">{latestRelease.approval.approver_role}</dd></div>
            <div><dt className="text-xs text-slate-500">审批时间</dt><dd className="mt-1">{new Date(latestRelease.approval.approved_at).toLocaleString('zh-CN')}</dd></div>
          </dl>
        </section>
      )}
      <div className="space-y-2">
        {releases.length === 0 ? (
          <div className="rounded-lg border border-dashed py-8 text-center text-sm text-slate-500">尚无 {environment} 发布记录</div>
        ) : releases.map((release) => (
          <div key={release.release_id} className="rounded-lg border border-slate-200 px-4 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <strong>{STATUS_LABELS[release.status]}</strong>
              <Badge variant="outline">rev {release.revision}</Badge>
              <span className="font-mono text-xs text-slate-500">{release.release_id}</span>
            </div>
            <p className="mt-2 font-mono text-xs text-slate-500">version {release.version_id} · eval {release.eval_run_id}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
