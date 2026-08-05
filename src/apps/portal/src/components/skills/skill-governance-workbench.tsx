'use client'

import { useCallback, useEffect, useState } from 'react'

import { getSkillGovernanceWorkbench, listInfraSkillCatalog } from '@/lib/api-client'
import type {
  InfraSkillCatalogItem,
  SkillGovernanceStatus,
  SkillWorkbenchItem,
  SkillWorkbenchSummary,
  SkillWorkbenchTab,
} from '@/lib/types'

import SkillCatalogPanel from './skill-catalog-panel'
import SkillGovernanceSummary from './skill-governance-summary'
import SkillExecutionTestDrawer from './skill-execution-test-drawer'
import SkillRouteTestDrawer from './skill-route-test-drawer'
import SkillWorkbenchHeader from './skill-workbench-header'
import SkillWorkspace from './skill-workspace'

const VALID_TABS = new Set<SkillWorkbenchTab>([
  'overview',
  'versions',
  'evaluation',
  'release',
  'development',
])
const VALID_STATUSES = new Set<SkillGovernanceStatus>([
  'gate_failed',
  'pending_approval',
  'needs_evaluation',
  'artifact_changed',
  'healthy',
])

interface WorkbenchUrlState {
  skillId: string | null
  tab: SkillWorkbenchTab
  env: 'dev' | 'test'
  query: string
  governanceStatus: SkillGovernanceStatus | null
  businessAction: string
  businessObject: string
}

function readWorkbenchUrl(): WorkbenchUrlState {
  const params = new URLSearchParams(window.location.search)
  const tab = params.get('tab') as SkillWorkbenchTab | null
  const status = params.get('status') as SkillGovernanceStatus | null
  return {
    skillId: params.get('skill'),
    tab: tab && VALID_TABS.has(tab) ? tab : 'overview',
    env: params.get('env') === 'dev' ? 'dev' : 'test',
    query: params.get('q') ?? '',
    governanceStatus: status && VALID_STATUSES.has(status) ? status : null,
    businessAction: params.get('action') ?? '',
    businessObject: params.get('object') ?? '',
  }
}

function setOrDelete(params: URLSearchParams, key: string, value: string | null): void {
  if (value) params.set(key, value)
  else params.delete(key)
}

function replaceWorkbenchUrl(state: WorkbenchUrlState): void {
  const params = new URLSearchParams()
  setOrDelete(params, 'skill', state.skillId)
  params.set('tab', state.tab)
  params.set('env', state.env)
  setOrDelete(params, 'q', state.query)
  setOrDelete(params, 'status', state.governanceStatus)
  setOrDelete(params, 'action', state.businessAction)
  setOrDelete(params, 'object', state.businessObject)
  window.history.replaceState({}, '', `/skills?${params.toString()}`)
}

function catalogFallback(item: InfraSkillCatalogItem): SkillWorkbenchItem {
  return {
    skill_id: item.skill_id,
    skill_name: item.skill_name,
    business_action: item.business_action,
    business_object: item.business_object,
    semantic_version: item.semantic_version,
    artifact_status: item.artifact_status,
    validation_status: item.registered_version?.validation_status ?? 'pending',
    latest_eval_status: null,
    test_release_status: null,
    test_active_version: null,
    governance_status: item.artifact_status === 'registered' ? 'needs_evaluation' : 'artifact_changed',
    attention_reason: 'governance_summary_unavailable',
  }
}

export default function SkillGovernanceWorkbench() {
  const [initialState] = useState(readWorkbenchUrl)
  const [items, setItems] = useState<SkillWorkbenchItem[]>([])
  const [summary, setSummary] = useState<SkillWorkbenchSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(initialState.skillId)
  const [activeTab, setActiveTab] = useState<SkillWorkbenchTab>(initialState.tab)
  const [environment, setEnvironment] = useState<'dev' | 'test'>(initialState.env)
  const [query, setQuery] = useState(initialState.query)
  const [governanceStatus, setGovernanceStatus] = useState<SkillGovernanceStatus | null>(initialState.governanceStatus)
  const [businessAction, setBusinessAction] = useState(initialState.businessAction)
  const [businessObject, setBusinessObject] = useState(initialState.businessObject)
  const [refreshToken, setRefreshToken] = useState(0)
  const [routeDrawerOpen, setRouteDrawerOpen] = useState(false)
  const [executionDrawerOpen, setExecutionDrawerOpen] = useState(false)

  const prepareCatalogReload = useCallback(() => {
    setLoading(true)
    setCatalogError(null)
  }, [])
  const handleQueryChange = useCallback((nextQuery: string) => {
    prepareCatalogReload()
    setQuery(nextQuery)
  }, [prepareCatalogReload])
  const handleBusinessActionChange = useCallback((action: string) => {
    prepareCatalogReload()
    setBusinessAction(action)
  }, [prepareCatalogReload])
  const handleBusinessObjectChange = useCallback((object: string) => {
    prepareCatalogReload()
    setBusinessObject(object)
  }, [prepareCatalogReload])
  const handleGovernanceStatusChange = useCallback((status: SkillGovernanceStatus | null) => {
    prepareCatalogReload()
    setGovernanceStatus(status)
  }, [prepareCatalogReload])
  const handleSelect = useCallback((skillId: string) => {
    setSelectedSkillId(skillId)
  }, [])

  useEffect(() => {
    let current = true
    getSkillGovernanceWorkbench({
      page: 1,
      page_size: 50,
      query: query || undefined,
      governance_status: governanceStatus || undefined,
      business_action: businessAction || undefined,
      business_object: businessObject || undefined,
    }).then((response) => {
      if (!current) return
      setItems(response.items)
      setSummary(response.summary)
      setSelectedSkillId((selected) => response.items.some((item) => item.skill_id === selected)
        ? selected
        : response.items[0]?.skill_id ?? null)
    }).catch(async (error: unknown) => {
      if (!current) return
      setSummary(null)
      try {
        const fallback = await listInfraSkillCatalog({
          page: 1,
          page_size: 50,
          query: query || undefined,
          business_action: businessAction || undefined,
          business_object: businessObject || undefined,
        })
        if (!current) return
        const fallbackItems = fallback.items.map(catalogFallback)
        setItems(fallbackItems)
        setSelectedSkillId((selected) => fallbackItems.some((item) => item.skill_id === selected)
          ? selected
          : fallbackItems[0]?.skill_id ?? null)
      } catch {
        if (!current) return
        setItems([])
        setCatalogError(error instanceof Error ? error.message : '无法加载 Skill 目录')
      }
    }).finally(() => {
      if (current) setLoading(false)
    })
    return () => { current = false }
  }, [businessAction, businessObject, governanceStatus, query, refreshToken])

  useEffect(() => {
    replaceWorkbenchUrl({
      skillId: selectedSkillId,
      tab: activeTab,
      env: environment,
      query,
      governanceStatus,
      businessAction,
      businessObject,
    })
  }, [activeTab, businessAction, businessObject, environment, governanceStatus, query, selectedSkillId])

  return (
    <div data-testid="skill-governance-workbench" className="mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-[1600px] flex-col gap-5 p-4 md:p-6">
      <SkillWorkbenchHeader
        environment={environment}
        onEnvironmentChange={setEnvironment}
        onOpenRouteTest={() => setRouteDrawerOpen(true)}
        onRefresh={() => {
          prepareCatalogReload()
          setRefreshToken((value) => value + 1)
        }}
      />
      <SkillGovernanceSummary
        summary={summary}
        activeStatus={governanceStatus}
        onStatusChange={handleGovernanceStatusChange}
      />
      {catalogError && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{catalogError}</p>}
      <div className="grid min-h-[620px] flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm md:grid-cols-[320px_minmax(0,1fr)]">
        <SkillCatalogPanel
          items={items}
          selectedSkillId={selectedSkillId}
          query={query}
          businessAction={businessAction}
          businessObject={businessObject}
          loading={loading}
          onQueryChange={handleQueryChange}
          onBusinessActionChange={handleBusinessActionChange}
          onBusinessObjectChange={handleBusinessObjectChange}
          onSelect={handleSelect}
        />
        <main className="min-w-0 bg-slate-50/50 p-4 md:p-6">
          {selectedSkillId && items.find((item) => item.skill_id === selectedSkillId) ? (
            <SkillWorkspace
              key={selectedSkillId}
              item={items.find((item) => item.skill_id === selectedSkillId)!}
              activeTab={activeTab}
              environment={environment}
              onTabChange={setActiveTab}
              onOpenExecution={() => setExecutionDrawerOpen(true)}
              onChanged={() => {
                prepareCatalogReload()
                setRefreshToken((value) => value + 1)
              }}
            />
          ) : (
            <div className="flex min-h-72 items-center justify-center text-sm text-slate-500">请选择一个 Skill</div>
          )}
        </main>
      </div>
      <SkillRouteTestDrawer
        open={routeDrawerOpen}
        onOpenChange={setRouteDrawerOpen}
        onSelectSkill={handleSelect}
      />
      <SkillExecutionTestDrawer
        open={executionDrawerOpen}
        skillId={selectedSkillId}
        onOpenChange={setExecutionDrawerOpen}
      />
    </div>
  )
}
