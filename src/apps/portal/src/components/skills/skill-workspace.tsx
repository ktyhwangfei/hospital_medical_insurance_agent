'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  approveSkillRelease,
  activateSkillRelease,
  createSkillEvalRun,
  createSkillRelease,
  getInfraSkillDetail,
  listInfraSkillVersions,
  listSkillEvalRuns,
  listSkillReleases,
  requestSkillReleaseApproval,
} from '@/lib/api-client'
import type {
  InfraSkillDetailResponse,
  SkillEvalRunResponse,
  SkillReleaseResponse,
  SkillVersionResponse,
  SkillWorkbenchItem,
  SkillWorkbenchTab,
} from '@/lib/types'

import SkillDevelopmentTab from './skill-development-tab'
import SkillEvalMetricStrip from './skill-eval-metric-strip'
import SkillEvidenceRail from './skill-evidence-rail'
import SkillLifecycleStepper from './skill-lifecycle-stepper'
import SkillNextActionBar from './skill-next-action-bar'
import SkillRegressionTable from './skill-regression-table'
import SkillVersionsTab from './skill-versions-tab'
import {
  computePrimaryAction,
  latestActiveRelease,
} from './skill-primary-action'

interface SkillWorkspaceProps {
  item: SkillWorkbenchItem
  activeTab: SkillWorkbenchTab
  environment: 'dev' | 'test'
  onTabChange: (tab: SkillWorkbenchTab) => void
  onOpenTopPage: (page: 'evaluations' | 'releases') => void
  onChanged: () => void
  onOpenExecution: () => void
}

interface EvidenceErrors {
  detail: string | null
  versions: string | null
  evaluations: string | null
  releases: string | null
}

const emptyErrors: EvidenceErrors = {
  detail: null,
  versions: null,
  evaluations: null,
  releases: null,
}

const errorLabels: Record<keyof EvidenceErrors, string> = {
  detail: 'Skill 详情',
  versions: '版本证据',
  evaluations: '评测证据',
  releases: '发布记录',
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : '证据加载失败'
}

export default function SkillWorkspace({
  item,
  activeTab,
  environment,
  onTabChange,
  onOpenTopPage,
  onChanged,
  onOpenExecution,
}: SkillWorkspaceProps) {
  const [detail, setDetail] = useState<InfraSkillDetailResponse | null>(null)
  const [versions, setVersions] = useState<SkillVersionResponse[]>([])
  const [evalRuns, setEvalRuns] = useState<SkillEvalRunResponse[]>([])
  const [releases, setReleases] = useState<SkillReleaseResponse[]>([])
  const [errors, setErrors] = useState<EvidenceErrors>(emptyErrors)
  const [reloadToken, setReloadToken] = useState(0)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [evidenceLoading, setEvidenceLoading] = useState(true)

  const primaryAction = useMemo(
    () => computePrimaryAction(item, versions, evalRuns, releases),
    [item, versions, evalRuns, releases],
  )
  const canonicalRun = item.latest_eval_run_id
    ? evalRuns.find((run) => run.run_id === item.latest_eval_run_id) ?? null
    : null
  const canonicalVersion = canonicalRun
    ? versions.find((version) => version.version_id === canonicalRun.version_id) ?? null
    : null
  const canonicalFactsMatch = Boolean(
    canonicalRun
    && canonicalVersion
    && item.latest_eval_status === canonicalRun.status
    && item.artifact_status === 'registered'
    && item.validation_status === canonicalVersion.validation_status
    && canonicalVersion.validation_status === 'passed'
    && (!item.candidate_version || item.candidate_version === canonicalVersion.semantic_version),
  )
  const evidenceState = evidenceLoading
    ? 'loading'
    : errors.evaluations || errors.versions || (item.latest_eval_run_id ? !canonicalFactsMatch : false)
      ? 'unavailable'
      : 'ready'
  const latestRun = evidenceState === 'ready' && canonicalFactsMatch ? canonicalRun : null
  const latestVersion = evidenceState === 'ready' && canonicalFactsMatch ? canonicalVersion : null
  const evidenceRelease = latestRun && latestVersion
    ? latestActiveRelease(releases.filter((release) => (
        release.eval_run_id === latestRun.run_id && release.version_id === latestVersion.version_id
      ))) ?? null
    : null
  const localTab = activeTab === 'versions' || activeTab === 'development' ? activeTab : 'overview'

  const handleNavigate = useCallback(
    (tab: SkillWorkbenchTab) => {
      if (tab === 'evaluation') onOpenTopPage('evaluations')
      else if (tab === 'release') onOpenTopPage('releases')
      else onTabChange(tab)
    },
    [onTabChange, onOpenTopPage],
  )

  const loadEvidence = useCallback(async () => {
    setEvidenceLoading(true)
    const results = await Promise.allSettled([
      getInfraSkillDetail(item.skill_id),
      listInfraSkillVersions(item.skill_id),
      listSkillEvalRuns(item.skill_id),
      listSkillReleases(item.skill_id, 'test'),
    ])
    const nextErrors = { ...emptyErrors }
    if (results[0].status === 'fulfilled') setDetail(results[0].value)
    else nextErrors.detail = errorMessage(results[0].reason)
    if (results[1].status === 'fulfilled') setVersions(results[1].value)
    else nextErrors.versions = errorMessage(results[1].reason)
    if (results[2].status === 'fulfilled') setEvalRuns(results[2].value.items)
    else nextErrors.evaluations = errorMessage(results[2].reason)
    if (results[3].status === 'fulfilled') setReleases(results[3].value.items)
    else nextErrors.releases = errorMessage(results[3].reason)
    setErrors(nextErrors)
    setEvidenceLoading(false)
  }, [item.skill_id])

  useEffect(() => {
    const timer = window.setTimeout(() => void loadEvidence(), 0)
    return () => window.clearTimeout(timer)
  }, [loadEvidence, reloadToken])

  function handleChanged(): void {
    setReloadToken((value) => value + 1)
    onChanged()
  }

  function openEvidence(): void {
    setEvidenceOpen(true)
  }

  function currentWriteVersion(): SkillVersionResponse | null {
    const versionName = item.candidate_version ?? item.semantic_version
    if (item.artifact_status !== 'registered' || item.validation_status !== 'passed') return null
    return versions
      .filter((version) => (
        version.skill_id === item.skill_id
        && version.semantic_version === versionName
        && version.validation_status === 'passed'
      ))
      .sort((left, right) => (
        right.created_at.localeCompare(left.created_at) || right.version_id.localeCompare(left.version_id)
      ))[0] ?? null
  }

  function currentWriteRun(version: SkillVersionResponse): SkillEvalRunResponse | null {
    if (!item.latest_eval_run_id) return null
    const run = evalRuns.find((candidate) => candidate.run_id === item.latest_eval_run_id) ?? null
    if (!run || run.version_id !== version.version_id || run.status !== item.latest_eval_status) return null
    return run
  }

  function currentWriteRelease(
    version: SkillVersionResponse,
    run: SkillEvalRunResponse,
    status: SkillReleaseResponse['status'],
  ): SkillReleaseResponse | null {
    return releases
      .filter((release) => (
        release.environment === 'test'
        && release.version_id === version.version_id
        && release.eval_run_id === run.run_id
        && release.status === status
      ))
      .sort((left, right) => (
        right.created_at.localeCompare(left.created_at) || right.release_id.localeCompare(left.release_id)
      ))[0] ?? null
  }

  async function runPrimary(): Promise<void> {
    const action = primaryAction
    setActionError(null)
    if (action.kind === 'none') return
    if (action.kind === 'navigate') {
      if (action.targetTab) handleNavigate(action.targetTab)
      return
    }
    setActionBusy(true)
    try {
      const key = `${item.skill_id}:${action.kind}:${Date.now()}`
      switch (action.kind) {
        case 'run_evaluation': {
          const version = currentWriteVersion()
          if (!version) throw new Error('当前候选版本证据不一致，请刷新后重试')
          await createSkillEvalRun(item.skill_id, { version_id: version.version_id })
          break
        }
        case 'create_candidate': {
          const version = currentWriteVersion()
          const run = version ? currentWriteRun(version) : null
          if (!version || !run || run.status !== 'passed' || !run.metrics.gate_passed) {
            throw new Error('当前评测证据不一致，请刷新或重新评测')
          }
          await createSkillRelease(
            item.skill_id,
            { version_id: version.version_id, eval_run_id: run.run_id, environment: 'test' },
            key,
          )
          break
        }
        case 'request_approval': {
          const version = currentWriteVersion()
          const run = version ? currentWriteRun(version) : null
          const release = version && run ? currentWriteRelease(version, run, 'candidate') : null
          if (!release) throw new Error('当前候选发布证据不一致，请刷新后重试')
          await requestSkillReleaseApproval(
            item.skill_id,
            release.release_id,
            { expected_revision: release.revision },
            key,
          )
          break
        }
        case 'approve': {
          const version = currentWriteVersion()
          const run = version ? currentWriteRun(version) : null
          const release = version && run ? currentWriteRelease(version, run, 'approval_pending') : null
          if (!release) throw new Error('当前待审批发布证据不一致，请刷新后重试')
          await approveSkillRelease(
            item.skill_id,
            release.release_id,
            { expected_revision: release.revision, reason: '固定评测门禁通过，同意 Test Shadow 激活' },
            key,
          )
          break
        }
        case 'activate': {
          const version = currentWriteVersion()
          const run = version ? currentWriteRun(version) : null
          const release = version && run ? currentWriteRelease(version, run, 'approved') : null
          if (!release) throw new Error('当前已审批发布证据不一致，请刷新后重试')
          await activateSkillRelease(
            item.skill_id,
            release.release_id,
            { expected_revision: release.revision },
            key,
          )
          break
        }
      }
      handleChanged()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '操作失败，请重试')
    } finally {
      setActionBusy(false)
    }
  }

  const errorEntries = Object.entries(errors).filter((entry): entry is [keyof EvidenceErrors, string] => Boolean(entry[1]))
  const releaseTone = item.test_release_status === 'active'
    ? 'bg-emerald-50 text-emerald-700'
    : item.governance_status === 'gate_failed'
      ? 'bg-red-50 text-red-700'
      : 'bg-slate-100 text-slate-700'

  return (
    <section data-testid={`skill-workspace-${item.skill_id}`} className="min-h-0 bg-white">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-4 py-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{detail?.skill_name ?? item.skill_name}</h2>
          <p className="mt-1 font-mono text-xs text-slate-500">{item.skill_id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">候选 v{item.candidate_version ?? item.semantic_version}</span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">基线 {item.baseline_version ?? '无'}</span>
          <span className="rounded-full bg-blue-50 px-2.5 py-1 text-blue-700">{item.business_action} · {item.business_object}</span>
          <span className={`rounded-full px-2.5 py-1 ${releaseTone}`}>{item.test_release_status === 'active' ? 'Test Active' : 'Test 未激活'}</span>
        </div>
      </header>

      <div className="grid min-h-0 2xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-h-0 min-w-0 flex-col">
          {errorEntries.map(([source, message]) => (
            <p key={source} role="alert" className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
              {errorLabels[source]}加载失败：<span>{message}</span>。请刷新重试。
            </p>
          ))}
          <SkillLifecycleStepper item={item} onNavigate={handleNavigate} />
          <SkillEvalMetricStrip latest={latestRun} state={evidenceState} />
          <SkillRegressionTable latest={latestRun} state={evidenceState} />

          <Tabs data-testid="skill-workspace-tabs" value={localTab} onValueChange={(value) => onTabChange(value as SkillWorkbenchTab)} className="flex-col gap-0">
            <div className="overflow-x-auto border-b border-slate-200 px-4">
              <TabsList aria-label="Skill 治理视图" variant="line" className="h-11 gap-2">
                <TabsTrigger value="overview">总览</TabsTrigger>
                <TabsTrigger value="versions">版本</TabsTrigger>
                <TabsTrigger value="development">开发详情</TabsTrigger>
              </TabsList>
            </div>
            <div className="p-4">
              <TabsContent value="overview" className="flex flex-wrap gap-4 text-sm">
                <button type="button" onClick={onOpenExecution} className="min-h-11 font-medium text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:min-h-9">执行调试</button>
                <button type="button" onClick={() => onTabChange('development')} className="min-h-11 font-medium text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:min-h-9">查看开发详情</button>
              </TabsContent>
              <TabsContent value="versions">
                <SkillVersionsTab item={item} versions={versions} error={null} readOnly={environment === 'dev'} onChanged={handleChanged} />
              </TabsContent>
              <TabsContent value="development">
                <SkillDevelopmentTab detail={detail} error={null} onOpenExecution={onOpenExecution} />
              </TabsContent>
            </div>
          </Tabs>

          <SkillNextActionBar
            action={primaryAction}
            reason={item.next_action_reason}
            busy={actionBusy}
            readOnly={environment === 'dev'}
            error={actionError}
            onRun={() => void runPrimary()}
            onViewEvidence={openEvidence}
          />
        </div>
        <SkillEvidenceRail
          item={item}
          latestRun={latestRun}
          latestRelease={evidenceRelease}
          latestVersion={latestVersion}
          historicalRuns={evalRuns}
          state={evidenceState}
        />
      </div>

      <Dialog open={evidenceOpen} onOpenChange={setEvidenceOpen}>
        <DialogContent showCloseButton={false} className="inset-y-0 left-auto right-0 top-0 h-dvh w-full max-w-none translate-x-0 translate-y-0 content-start overflow-y-auto rounded-none p-0 sm:max-w-none md:max-w-xl">
          <DialogHeader className="border-b border-slate-200 p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <DialogTitle>治理证据</DialogTitle>
                <DialogDescription className="mt-2">当前 Skill 的门禁与冻结记录</DialogDescription>
              </div>
              <DialogClose render={<Button variant="outline" className="min-h-11 shrink-0" aria-label="关闭治理证据" />}>关闭</DialogClose>
            </div>
          </DialogHeader>
          <SkillEvidenceRail
            variant="drawer"
            item={item}
            latestRun={latestRun}
            latestRelease={evidenceRelease}
            latestVersion={latestVersion}
            historicalRuns={evalRuns}
            state={evidenceState}
          />
        </DialogContent>
      </Dialog>
    </section>
  )
}
