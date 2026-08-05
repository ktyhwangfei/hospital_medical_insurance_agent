'use client'

import { useCallback, useEffect, useState } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  getInfraSkillDetail,
  listInfraSkillVersions,
  listSkillEvalRuns,
  listSkillReleases,
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
import SkillEvaluationSuite from './skill-evaluation-suite'
import SkillLifecycleStepper from './skill-lifecycle-stepper'
import SkillOverviewTab from './skill-overview-tab'
import SkillReleasePanel from './skill-release-panel'
import SkillVersionsTab from './skill-versions-tab'

interface SkillWorkspaceProps {
  item: SkillWorkbenchItem
  activeTab: SkillWorkbenchTab
  environment: 'dev' | 'test'
  onTabChange: (tab: SkillWorkbenchTab) => void
  onChanged: () => void
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
  onChanged,
}: SkillWorkspaceProps) {
  const [detail, setDetail] = useState<InfraSkillDetailResponse | null>(null)
  const [versions, setVersions] = useState<SkillVersionResponse[]>([])
  const [evalRuns, setEvalRuns] = useState<SkillEvalRunResponse[]>([])
  const [releases, setReleases] = useState<SkillReleaseResponse[]>([])
  const [errors, setErrors] = useState<EvidenceErrors>(emptyErrors)
  const [reloadToken, setReloadToken] = useState(0)

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
      <SkillLifecycleStepper item={item} onNavigate={onTabChange} />
      <Tabs value={activeTab} onValueChange={(value) => onTabChange(value as SkillWorkbenchTab)} className="gap-0">
        <div className="overflow-x-auto border-b border-slate-200 px-4">
          <TabsList aria-label="Skill 治理视图" variant="line" className="h-11 gap-2">
            <TabsTrigger value="overview">总览</TabsTrigger>
            <TabsTrigger value="versions">版本</TabsTrigger>
            <TabsTrigger value="evaluation">评测</TabsTrigger>
            <TabsTrigger value="release">发布</TabsTrigger>
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
              onNavigate={onTabChange}
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
          <TabsContent value="evaluation">
            {errors.evaluations ? <p role="alert" className="text-sm text-red-700">{errors.evaluations}</p> : (
              <SkillEvaluationSuite
                skillId={item.skill_id}
                versions={versions}
                readOnly={environment === 'dev'}
                onChanged={handleChanged}
              />
            )}
          </TabsContent>
          <TabsContent value="release">
            {errors.releases ? <p role="alert" className="text-sm text-red-700">{errors.releases}</p> : (
              <SkillReleasePanel
                skillId={item.skill_id}
                versions={versions}
                environment={environment}
                readOnly={environment === 'dev'}
                onChanged={handleChanged}
              />
            )}
          </TabsContent>
          <TabsContent value="development">
            <SkillDevelopmentTab detail={detail} error={errors.detail} />
          </TabsContent>
          {activeTab !== 'development' && errors.detail && (
            <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{errors.detail}</p>
          )}
        </div>
      </Tabs>
    </section>
  )
}
