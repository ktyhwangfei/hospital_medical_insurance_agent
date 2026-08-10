'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

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
import SkillLifecycleStepper from './skill-lifecycle-stepper'
import SkillOverviewTab from './skill-overview-tab'
import SkillPrimaryActionBar from './skill-primary-action-bar'
import SkillVersionsTab from './skill-versions-tab'
import {
  computePrimaryAction,
  eligibleEvalRun,
  latestActiveRelease,
} from './skill-primary-action'

interface SkillWorkspaceProps {
  item: SkillWorkbenchItem
  activeTab: SkillWorkbenchTab
  environment: 'dev' | 'test'
  onTabChange: (tab: SkillWorkbenchTab) => void
  // 评测/发布已上移到顶层列表页（意见4 方案A）：工作区内点击相关导航时跳转过去（带 skill 筛选）
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

  // 下一个主治理动作：依据已加载证据推导，提到顶层一键执行，避免钻 Tab
  const primaryAction = useMemo(
    () => computePrimaryAction(item, versions, evalRuns, releases),
    [item, versions, evalRuns, releases],
  )

  // 评测/发布 Tab 已上移顶层列表页（意见4 方案A）：原 navigate('evaluation'|'release')
  // 统一重定向到对应顶层页（带 skill 筛选），其余 Tab 仍走 onTabChange
  const handleNavigate = useCallback(
    (tab: SkillWorkbenchTab) => {
      if (tab === 'evaluation') onOpenTopPage('evaluations')
      else if (tab === 'release') onOpenTopPage('releases')
      else onTabChange(tab)
    },
    [onTabChange, onOpenTopPage],
  )

  // 切换 Skill 时清掉上一次动作的残留状态
  useEffect(() => {
    setActionError(null)
    setActionBusy(false)
  }, [item.skill_id])

  const loadEvidence = useCallback(async () => {
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
  }, [item.skill_id])

  useEffect(() => {
    const timer = window.setTimeout(() => void loadEvidence(), 0)
    return () => window.clearTimeout(timer)
  }, [loadEvidence, reloadToken])

  function handleChanged(): void {
    setReloadToken((value) => value + 1)
    onChanged()
  }

  // 顶层主动作执行：写操作直接调 API 后刷新证据；navigate 仅切 Tab；none 无操作
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
          const version =
            versions.find((candidate) => candidate.validation_status === 'passed') ?? versions[0]
          if (!version) throw new Error('没有可评测的已登记版本')
          await createSkillEvalRun(item.skill_id, { version_id: version.version_id })
          break
        }
        case 'create_candidate': {
          const eligible = eligibleEvalRun(evalRuns, versions)
          if (!eligible) throw new Error('没有通过门禁的评测')
          await createSkillRelease(
            item.skill_id,
            { version_id: eligible.version_id, eval_run_id: eligible.run_id, environment: 'test' },
            key,
          )
          break
        }
        case 'request_approval': {
          const target = latestActiveRelease(releases)
          if (!target) throw new Error('没有可推进的候选发布')
          await requestSkillReleaseApproval(
            item.skill_id,
            target.release_id,
            { expected_revision: target.revision },
            key,
          )
          break
        }
        case 'approve': {
          const target = latestActiveRelease(releases)
          if (!target) throw new Error('没有待审批的发布')
          await approveSkillRelease(
            item.skill_id,
            target.release_id,
            {
              expected_revision: target.revision,
              reason: '固定评测门禁通过，同意 Test Shadow 激活',
            },
            key,
          )
          break
        }
        case 'activate': {
          const target = latestActiveRelease(releases)
          if (!target) throw new Error('没有可激活的发布')
          await activateSkillRelease(
            item.skill_id,
            target.release_id,
            { expected_revision: target.revision },
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

  return (
    <section data-testid={`skill-workspace-${item.skill_id}`} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{detail?.skill_name ?? item.skill_name}</h2>
          <p className="mt-1 font-mono text-xs text-slate-500">{item.skill_id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">v{item.semantic_version}</span>
          <span className="rounded-full bg-blue-50 px-2.5 py-1 text-blue-700">{item.business_action} · {item.business_object}</span>
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">{item.test_release_status === 'active' ? 'Test Active' : 'Test 未激活'}</span>
        </div>
      </div>
      <SkillPrimaryActionBar
        action={primaryAction}
        busy={actionBusy}
        readOnly={environment === 'dev'}
        error={actionError}
        onRun={() => void runPrimary()}
      />
      <SkillLifecycleStepper item={item} onNavigate={handleNavigate} />
      <Tabs
        data-testid="skill-workspace-tabs"
        value={activeTab}
        onValueChange={(value) => onTabChange(value as SkillWorkbenchTab)}
        className="flex-col gap-0"
      >
        <div className="overflow-x-auto border-b border-slate-200 px-4">
          <TabsList aria-label="Skill 治理视图" variant="line" className="h-11 gap-2">
            <TabsTrigger value="overview">总览</TabsTrigger>
            <TabsTrigger value="versions">版本</TabsTrigger>
            <TabsTrigger value="development">开发详情</TabsTrigger>
          </TabsList>
        </div>
        <div className="min-h-[360px] p-5">
          <TabsContent value="overview">
            <SkillOverviewTab
              item={item}
              versions={versions}
              evalRuns={evalRuns}
              releases={releases}
              onNavigate={handleNavigate}
              onOpenExecution={onOpenExecution}
            />
          </TabsContent>
          <TabsContent value="versions">
            <SkillVersionsTab
              item={item}
              versions={versions}
              error={errors.versions}
              readOnly={environment === 'dev'}
              onChanged={handleChanged}
            />
          </TabsContent>
          <TabsContent value="development">
            <SkillDevelopmentTab detail={detail} error={errors.detail} onOpenExecution={onOpenExecution} />
          </TabsContent>
          {activeTab !== 'development' && errors.detail && (
            <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{errors.detail}</p>
          )}
        </div>
      </Tabs>
    </section>
  )
}
