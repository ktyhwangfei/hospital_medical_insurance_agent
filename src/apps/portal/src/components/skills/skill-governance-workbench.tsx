'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { getSkillGovernanceWorkbench, listInfraSkillCatalog } from '@/lib/api-client'
import type {
  InfraSkillCatalogItem,
  SkillGovernancePriority,
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

export { waitingLabel } from './skill-catalog-panel'

const VALID_TABS = new Set<SkillWorkbenchTab>([
  'overview',
  'versions',
  'development',
])
const VALID_STATUSES = new Set<SkillGovernanceStatus>([
  'gate_failed',
  'pending_approval',
  'needs_evaluation',
  'artifact_changed',
  'healthy',
])
const VALID_PRIORITIES = new Set<SkillGovernancePriority>(['blocked', 'high', 'normal'])

interface WorkbenchUrlState {
  skillId: string | null
  tab: SkillWorkbenchTab
  env: 'dev' | 'test'
  query: string
  governanceStatus: SkillGovernanceStatus | null
  priority: SkillGovernancePriority | null
  businessAction: string
  businessObject: string
}

export function readWorkbenchUrl(
  search = typeof window === 'undefined' ? '' : window.location.search,
): WorkbenchUrlState {
  const params = new URLSearchParams(search)
  const tab = params.get('tab') as SkillWorkbenchTab | null
  const status = params.get('status') as SkillGovernanceStatus | null
  const priority = params.get('priority') as SkillGovernancePriority | null
  return {
    skillId: params.get('skill'),
    tab: tab && VALID_TABS.has(tab) ? tab : 'overview',
    env: params.get('env') === 'dev' ? 'dev' : 'test',
    query: params.get('q') ?? '',
    governanceStatus: status && VALID_STATUSES.has(status) ? status : null,
    priority: priority && VALID_PRIORITIES.has(priority) ? priority : null,
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
  setOrDelete(params, 'priority', state.priority)
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
    current_stage: item.artifact_status === 'registered' ? 'evaluate' : 'modify',
    priority: item.artifact_status === 'registered' ? 'normal' : 'high',
    latest_eval_run_id: null,
    candidate_version: null,
    baseline_version: null,
    regression_count: 0,
    required_failure_count: 0,
    linked_draft_id: null,
    linked_draft_status: null,
    waiting_since: item.registered_version?.created_at ?? new Date().toISOString(),
    next_action: 'view_evidence',
    next_action_reason: '治理聚合暂不可用，仅展示资产信息',
  }
}

export default function SkillGovernanceWorkbench() {
  const router = useRouter()
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
  const [priority, setPriority] = useState<SkillGovernancePriority | null>(initialState.priority)
  const [businessAction, setBusinessAction] = useState(initialState.businessAction)
  const [businessObject, setBusinessObject] = useState(initialState.businessObject)
  const [refreshToken, setRefreshToken] = useState(0)
  const [routeDrawerOpen, setRouteDrawerOpen] = useState(false)
  const [executionDrawerOpen, setExecutionDrawerOpen] = useState(false)
  const [mobileDetailOpen, setMobileDetailOpen] = useState(initialState.skillId !== null)
  const mobileBackButtonRef = useRef<HTMLButtonElement>(null)
  // 选中项单次查找并记忆，避免每次渲染对 items 做多次 O(n) 扫描，同时稳定下传给 SkillWorkspace 的 prop 引用
  const selectedItem = useMemo(
    () => items.find((item) => item.skill_id === selectedSkillId) ?? null,
    [items, selectedSkillId],
  )

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
  const handlePriorityChange = useCallback((nextPriority: SkillGovernancePriority | null) => {
    prepareCatalogReload()
    setPriority(nextPriority)
  }, [prepareCatalogReload])
  const handleSelect = useCallback((skillId: string) => {
    setSelectedSkillId(skillId)
    setMobileDetailOpen(true)
  }, [])

  useEffect(() => {
    if (!mobileDetailOpen) return
    if (typeof window.matchMedia === 'function' && !window.matchMedia('(max-width: 767px)').matches) return
    mobileBackButtonRef.current?.focus()
  }, [mobileDetailOpen])

  useEffect(() => {
    let current = true
    getSkillGovernanceWorkbench({
      page: 1,
      page_size: 50,
      query: query || undefined,
      governance_status: governanceStatus || undefined,
      priority: priority || undefined,
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
  }, [businessAction, businessObject, governanceStatus, priority, query, refreshToken])

  useEffect(() => {
    replaceWorkbenchUrl({
      skillId: selectedSkillId,
      tab: activeTab,
      env: environment,
      query,
      governanceStatus,
      priority,
      businessAction,
      businessObject,
    })
  }, [activeTab, businessAction, businessObject, environment, governanceStatus, priority, query, selectedSkillId])

  const returnToQueue = useCallback(() => {
    setMobileDetailOpen(false)
    Array.from(document.querySelectorAll<HTMLButtonElement>('[data-skill-catalog-button]'))
      .find((button) => button.dataset.skillId === selectedSkillId)
      ?.focus()
  }, [selectedSkillId])

  return (
    <section aria-label="Skill 日常治理" data-testid="skill-governance-workbench" className="flex w-full min-w-0 flex-col gap-6 py-6">
      <SkillWorkbenchHeader
        environment={environment}
        priority={priority}
        onEnvironmentChange={setEnvironment}
        onPriorityChange={handlePriorityChange}
        onOpenRouteTest={() => setRouteDrawerOpen(true)}
        onRefresh={() => {
          prepareCatalogReload()
          setRefreshToken((value) => value + 1)
        }}
      />
      {catalogError && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{catalogError}</p>}
      <div className="min-w-0 flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <SkillGovernanceSummary
          summary={summary}
          activeStatus={governanceStatus}
          onStatusChange={handleGovernanceStatusChange}
        />
        <div className="grid min-w-0 md:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[288px_minmax(0,1fr)]">
          <SkillCatalogPanel
            items={items}
            selectedSkillId={selectedSkillId}
            query={query}
            businessAction={businessAction}
            businessObject={businessObject}
            loading={loading}
            hiddenOnMobile={mobileDetailOpen}
            onQueryChange={handleQueryChange}
            onBusinessActionChange={handleBusinessActionChange}
            onBusinessObjectChange={handleBusinessObjectChange}
            onSelect={handleSelect}
          />
          <section aria-label="治理决策区" className={`${mobileDetailOpen ? 'block' : 'hidden'} min-w-0 overflow-y-auto bg-slate-50/50 p-3 md:block md:p-6`}>
            {mobileDetailOpen && (
              <button
                ref={mobileBackButtonRef}
                type="button"
                onClick={returnToQueue}
                className="mb-3 min-h-11 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 md:hidden"
              >
                返回治理待办
              </button>
            )}
            {selectedItem ? (
              <SkillWorkspace
                key={selectedSkillId}
                item={selectedItem}
                activeTab={activeTab}
                environment={environment}
                onTabChange={setActiveTab}
                onOpenTopPage={(page) => router.push(`/skills/${page}?skill=${selectedItem.skill_id}`)}
                onOpenExecution={() => setExecutionDrawerOpen(true)}
                onChanged={() => {
                  prepareCatalogReload()
                  setRefreshToken((value) => value + 1)
                }}
              />
            ) : (
              <div className="flex min-h-72 items-center justify-center text-sm text-slate-500">请选择一个 Skill</div>
            )}
          </section>
        </div>
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
    </section>
  )
}
