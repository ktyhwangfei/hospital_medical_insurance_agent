'use client'

import { useCallback, useEffect, useState } from 'react'
import { Beaker, BookOpen, Code2, Database, GitCommit, Play, Search, FolderTree } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  getInfraSkillDetail,
  getInfraSkillsOverview,
  listInfraSkillCatalog,
  listInfraSkillVersions,
  syncInfraSkillVersion,
  testInfraSkillExecution,
  testInfraSkillRouting,
  getSkillSemanticMetrics,
} from '@/lib/api-client'
import type {
  InfraSkillDetailResponse,
  InfraSkillCatalogItem,
  FieldMappingItem,
  InfraSkillOverviewItem,
  SkillVersionResponse,
} from '@/lib/types'
import SkillQuestionExplainer from './skill-question-explainer'
import SkillQueryPlan from './skill-query-plan'

// ── Business Action / Object 中文标签映射 ──

const ACTION_LABELS: Record<string, string> = {
  explain: '解释',
  query: '查询',
  guide: '导办',
  verify: '核验',
  compare: '对比',
  evaluate: '评估',
  analyze: '分析',
}

const OBJECT_LABELS: Record<string, string> = {
  settlement: '结算',
  benefit: '待遇',
  policy: '政策',
  directory: '目录',
  chronic_disease: '慢特病',
  referral: '转诊',
  appeal: '申诉',
  medical_record: '病案',
  drg_dip: 'DRG/DIP',
  complaint: '投诉',
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] || action || '—'
}

function objectLabel(obj: string): string {
  return OBJECT_LABELS[obj] || obj || '—'
}

const ARTIFACT_STATUS_LABELS: Record<InfraSkillCatalogItem['artifact_status'], string> = {
  registered: '已登记',
  changed: '文件已变化',
  unregistered: '未登记',
}

function ArtifactStatusBadge({ status }: { status: InfraSkillCatalogItem['artifact_status'] }) {
  const className = status === 'registered'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : status === 'changed'
      ? 'border-amber-200 bg-amber-50 text-amber-700'
      : 'border-slate-200 bg-slate-50 text-slate-600'
  return <Badge variant="outline" className={className}>{ARTIFACT_STATUS_LABELS[status]}</Badge>
}

// ── 动作 × 对象 组合徽章 ──

function ActionObjectBadge({ action, object }: { action: string; object: string }) {
  if (!action && !object) return <span className="text-gray-400 text-xs">—</span>
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-flex items-center rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-medium text-blue-700">
        {actionLabel(action)}
      </span>
      <span className="text-gray-400 text-[10px]">·</span>
      <span className="inline-flex items-center rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">
        {objectLabel(object)}
      </span>
    </span>
  )
}

// ── 字段映射详情子组件 ──

function SkillFieldMapping({ detail }: { detail: InfraSkillDetailResponse }) {
  const manifest = detail.manifest as Record<string, unknown> | undefined
  const requiredSettlementFields: string[] = (manifest?.required_settlement_fields as string[] | undefined) ?? []
  const requiredMcp: string[] = (manifest?.required_mcp as string[] | undefined) ?? []
  const fieldMapping = detail.field_mapping

  if (!fieldMapping?.settlement_fields) {
    return <div className="py-12 text-center text-gray-500">此技能包未配置 field_mapping.yaml</div>
  }

  const entries = Object.entries(fieldMapping.settlement_fields) as [string, FieldMappingItem][]
  const requiredEntries = entries.filter(([k]) => requiredSettlementFields.includes(k))
  const optionalEntries = entries.filter(([k]) => !requiredSettlementFields.includes(k))

  return (
    <div className="space-y-4">
      {/* 顶部摘要条 */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 bg-gray-50 rounded-lg px-4 py-2.5">
        <span className="flex items-center gap-1">
          <Database className="w-3.5 h-3.5 text-blue-500" />
          共 <strong className="text-gray-700">{entries.length}</strong> 个字段
          （<span className="text-blue-600 font-medium">{requiredEntries.length} 必需</span>
          <span className="mx-1">·</span>
          <span>{optionalEntries.length} 可选</span>）
        </span>
        {requiredMcp.length > 0 && (
          <>
            <span className="text-gray-300">|</span>
            <span className="flex items-center gap-1">MCP: {requiredMcp.join('、')}</span>
          </>
        )}
        {/* 默认值 */}
        {fieldMapping.defaults && Object.keys(fieldMapping.defaults).length > 0 && (
          <>
            <span className="text-gray-300">|</span>
            <span className="flex items-center gap-1 flex-wrap">
              默认：
              {Object.entries(fieldMapping.defaults).map(([k, v]) => (
                <code key={k} className="text-[11px] bg-white border px-1 py-0.5 rounded">{k}={v}</code>
              ))}
            </span>
          </>
        )}
      </div>

      {/* 必需字段 */}
      {requiredEntries.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-2">必需字段</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {requiredEntries.map(([fieldName, item]) => (
              <FieldCard key={fieldName} fieldName={fieldName} item={item} required />
            ))}
          </div>
        </div>
      )}

      {/* 可选字段 */}
      {optionalEntries.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 mt-1">可选字段</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {optionalEntries.map(([fieldName, item]) => (
              <FieldCard key={fieldName} fieldName={fieldName} item={item} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function FieldCard({ fieldName, item, required }: { fieldName: string; item: FieldMappingItem; required?: boolean }) {
  return (
    <div className={`rounded-lg border px-3 py-2.5 text-sm transition-colors ${required ? 'border-blue-200 bg-blue-50/30' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <code className="text-[11px] bg-gray-100 px-1 py-0.5 rounded font-mono text-gray-700">{fieldName}</code>
        {required && <Badge className="text-[9px] bg-blue-100 text-blue-700 px-1 py-0 leading-normal">必需</Badge>}
      </div>
      <div className="font-medium text-gray-800">{item.label}</div>
      <div className="flex items-center gap-2 mt-1 text-xs">
        <code className="text-[11px] text-orange-600 bg-orange-50/60 px-1 py-0.5 rounded font-mono">{item.db_source}</code>
        {item.description && <span className="text-gray-400 truncate" title={item.description}>{item.description}</span>}
      </div>
    </div>
  )
}

export default function InfraSkillManagement() {
  const [skills, setSkills] = useState<InfraSkillCatalogItem[]>([])
  const [catalogTotal, setCatalogTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [overview, setOverview] = useState<InfraSkillOverviewItem[]>([])
  const [overviewError, setOverviewError] = useState<string | null>(null)

  // Filter state
  const [actionFilter, setActionFilter] = useState<string>('')
  const [objectFilter, setObjectFilter] = useState<string>('')
  const [search, setSearch] = useState('')

  // Modals state
  const [detailDialogOpen, setDetailDialogOpen] = useState(false)
  const [testDialogOpen, setTestDialogOpen] = useState(false)
  const [routeDialogOpen, setRouteDialogOpen] = useState(false)

  // Selected skill
  const [selectedSkill, setSelectedSkill] = useState<InfraSkillDetailResponse | null>(null)
  const [selectedCatalogSkill, setSelectedCatalogSkill] = useState<InfraSkillCatalogItem | null>(null)
  const [versions, setVersions] = useState<SkillVersionResponse[]>([])
  const [versionError, setVersionError] = useState<string | null>(null)
  const [syncingVersion, setSyncingVersion] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)

  // Route Test State
  const [routeQuestion, setRouteQuestion] = useState('')
  const [routeResult, setRouteResult] = useState<string | null>(null)
  const [routeDetails, setRouteDetails] = useState<Awaited<ReturnType<typeof testInfraSkillRouting>> | null>(null)
  const [routeTesting, setRouteTesting] = useState(false)

  // 各技能引用的语义指标数（语义层消费视图）
  const [metricCounts, setMetricCounts] = useState<Record<string, number>>({})

  // Execution Test State
  const [testQuestion, setTestQuestion] = useState('')
  const [testTargetFeeItem, setTestTargetFeeItem] = useState('')
  const [testContext, setTestContext] = useState('{\n  "patient_id": "P001",\n  "encounter_id": "E001"\n}')
  const [testResult, setTestResult] = useState<string | null>(null)
  const [executionDetails, setExecutionDetails] = useState<Awaited<ReturnType<typeof testInfraSkillExecution>> | null>(null)
  const [executingTest, setExecutingTest] = useState(false)

  const loadSkills = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listInfraSkillCatalog({
        page: 1,
        page_size: 100,
        business_action: actionFilter || undefined,
        business_object: objectFilter || undefined,
      })
      setSkills(data.items)
      setCatalogTotal(data.total)
      try {
        const summary = await getInfraSkillsOverview()
        setOverview(summary.skills)
        setOverviewError(null)
      } catch (overviewErr) {
        setOverviewError(overviewErr instanceof Error ? overviewErr.message : '无法加载 Skill 状态')
      }
      // 并发拉取每个技能引用的语义指标数（容错：失败记 0）
      const counts = await Promise.all(
        data.items.map(async (s) => {
          try {
            const ms = await getSkillSemanticMetrics(s.skill_id)
            return [s.skill_id, ms.length] as const
          } catch {
            return [s.skill_id, 0] as const
          }
        })
      )
      setMetricCounts(Object.fromEntries(counts))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载研发技能失败')
    } finally {
      setLoading(false)
    }
  }, [actionFilter, objectFilter])

  useEffect(() => {
    // 页面进入和筛选变化时需要主动同步远端 Skill 列表。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadSkills()
  }, [loadSkills])

  const openDetail = async (skillId: string) => {
    setDetailDialogOpen(true)
    setLoadingDetail(true)
    setSelectedCatalogSkill(skills.find((skill) => skill.skill_id === skillId) ?? null)
    setVersionError(null)
    setVersions([])
    try {
      const detail = await getInfraSkillDetail(skillId)
      setSelectedSkill(detail)
    } catch (err) {
      setVersionError(err instanceof Error ? err.message : 'Skill 详情加载失败')
    } finally {
      setLoadingDetail(false)
    }
    try {
      setVersions(await listInfraSkillVersions(skillId))
    } catch (err) {
      setVersionError(err instanceof Error ? err.message : '版本证据加载失败')
    }
  }

  const handleSyncVersion = async () => {
    if (!selectedCatalogSkill) return
    setSyncingVersion(true)
    setVersionError(null)
    try {
      await syncInfraSkillVersion(selectedCatalogSkill.skill_id, {
        created_by: 'portal-workbench',
      })
      const versionItems = await listInfraSkillVersions(selectedCatalogSkill.skill_id)
      setVersions(versionItems)
      await loadSkills()
      setSelectedCatalogSkill((current) => {
        if (!current || versionItems.length === 0) return current
        return {
          ...current,
          artifact_status: 'registered',
          registered_version: versionItems[0],
        }
      })
    } catch (err) {
      setVersionError(err instanceof Error ? err.message : '版本登记失败')
    } finally {
      setSyncingVersion(false)
    }
  }

  const openTest = (skillId: string) => {
    setTestDialogOpen(true)
    setTestResult(null)
    setExecutionDetails(null)
    // Pre-load details if needed, but we mainly need skillId
    // If we want to show skill name, we can find it
    const s = skills.find((x) => x.skill_id === skillId)
    setSelectedSkill(s ? { ...s, manifest: {}, readme: '', files_structure: { agents: [], schemas: [], templates: [], scripts: [], references: [], tests: [], strategies: [] }, field_mapping: null } : null)
  }

  const handleRouteTest = async () => {
    if (!routeQuestion.trim()) return
    setRouteTesting(true)
    setRouteResult(null)
    setRouteDetails(null)
    try {
      const res = await testInfraSkillRouting({ question: routeQuestion })
      setRouteDetails(res)
      setRouteResult(res.matched_skill_id ? `匹配到技能: ${res.matched_skill_id}` : '未匹配到任何技能')
    } catch (err) {
      setRouteResult(`错误: ${err instanceof Error ? err.message : '未知错误'}`)
    } finally {
      setRouteTesting(false)
    }
  }

  const handleExecuteTest = async () => {
    if (!selectedSkill || !testQuestion.trim()) return
    setExecutingTest(true)
    setTestResult(null)
    setExecutionDetails(null)
    try {
      let parsedContext = undefined
      if (testContext.trim()) {
        parsedContext = JSON.parse(testContext)
      }
      
      const payload = {
        question: testQuestion,
        target_fee_item: testTargetFeeItem.trim() || null,
        context: parsedContext
      }

      const res = await testInfraSkillExecution(selectedSkill.skill_id, payload)
      setExecutionDetails(res)
      setTestResult(JSON.stringify(res, null, 2))
    } catch (err) {
      setTestResult(`执行失败:\n${err instanceof Error ? err.message : '未知错误'}`)
    } finally {
      setExecutingTest(false)
    }
  }

  const visibleSkills = skills.filter((skill) => {
    const query = search.trim().toLowerCase()
    return !query || `${skill.skill_name} ${skill.skill_id}`.toLowerCase().includes(query)
  })

  return (
    <div className="space-y-4">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Code2 className="w-5 h-5" />
              Skill 版本化资产库
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setRouteDialogOpen(true)}>
                <Search className="w-4 h-4 mr-1" />
                路由测试
              </Button>
              <Button variant="outline" size="sm" onClick={loadSkills} disabled={loading}>
                {loading ? '加载中...' : '刷新'}
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        {/* 筛选栏 */}
        <div className="px-6 pb-3 flex items-center gap-3">
          <span className="text-xs text-gray-500 shrink-0">筛选:</span>
          <select
            className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
            value={actionFilter}
            onChange={e => setActionFilter(e.target.value)}
          >
            <option value="">全部动作</option>
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-emerald-400"
            value={objectFilter}
            onChange={e => setObjectFilter(e.target.value)}
          >
            <option value="">全部对象</option>
            {Object.entries(OBJECT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          {(actionFilter || objectFilter) && (
            <button
              className="text-xs text-gray-400 hover:text-gray-600"
              onClick={() => { setActionFilter(''); setObjectFilter(''); }}
            >
              清除筛选
            </button>
          )}
          <span className="text-xs text-gray-400 ml-auto">{catalogTotal} 个技能</span>
        </div>
        <div className="px-6 pb-3">
          <Input aria-label="搜索 Skill" placeholder="搜索名称或 Skill ID" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {overviewError && (
          <div className="mx-6 mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            状态摘要加载失败：{overviewError}。列表仍可使用。
            <button className="ml-2 underline" onClick={loadSkills}>重试</button>
          </div>
        )}
        {overview.length > 0 && (
          <div className="mx-6 mb-4 grid grid-cols-2 gap-2 md:grid-cols-4">
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><div className="text-slate-500">已加载</div><strong>{overview.filter((item) => item.loaded).length}</strong></div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><div className="text-slate-500">Manifest 正常</div><strong>{overview.filter((item) => item.manifest_valid).length}</strong></div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><div className="text-slate-500">字段映射</div><strong>{overview.filter((item) => item.field_mapping_configured).length}</strong></div>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><div className="text-slate-500">指标引用</div><strong>{overview.reduce((total, item) => total + item.metric_count, 0)}</strong></div>
          </div>
        )}
        <CardContent>
          {loading ? (
            <div className="text-center py-8 text-gray-500">加载中...</div>
          ) : skills.length === 0 ? (
            <div className="text-center py-8 text-gray-500">未发现技能包</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-3 pr-4 font-medium text-gray-600">技能名称 / ID</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">业务动作</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">版本</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">制品状态</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">校验</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">引用指标</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">包含关键词</th>
                    <th className="pb-3 pr-4 font-medium text-gray-600">排除关键词</th>
                    <th className="pb-3 font-medium text-gray-600">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleSkills.map((skill) => (
                    <tr
                      key={skill.skill_id}
                      className="border-b last:border-0 hover:bg-gray-50"
                      data-testid={`skill-row-${skill.skill_id}`}
                    >
                      <td className="py-3 pr-4">
                        <div className="font-medium">{skill.skill_name}</div>
                        <div className="text-xs text-gray-500 mt-0.5 font-mono">{skill.skill_id}</div>
                      </td>
                      <td className="py-3 pr-4">
                        <ActionObjectBadge action={skill.business_action} object={skill.business_object} />
                      </td>
                      <td className="py-3 pr-4">
                        <div className="font-mono text-xs">v{skill.semantic_version}</div>
                        <div
                          className="mt-0.5 font-mono text-[10px] text-gray-400"
                          title={skill.artifact_hash}
                        >
                          {skill.artifact_hash.slice(0, 12)}
                        </div>
                      </td>
                      <td className="py-3 pr-4">
                        <ArtifactStatusBadge status={skill.artifact_status} />
                      </td>
                      <td className="py-3 pr-4 text-xs">
                        {skill.registered_version?.validation_status === 'passed' ? (
                          <span className="text-emerald-700">通过</span>
                        ) : skill.registered_version?.validation_status === 'failed' ? (
                          <span className="text-red-600">失败</span>
                        ) : (
                          <span className="text-gray-400">未校验</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`font-mono text-sm tabular-nums ${(metricCounts[skill.skill_id] ?? 0) > 0 ? 'text-blue-600 font-semibold' : 'text-gray-400'}`} title="从语义层 /semantic/skills/{id}/metrics 统计">
                          {metricCounts[skill.skill_id] ?? '—'}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <div className="flex flex-wrap gap-1">
                          {skill.include_keywords.map((kw, i) => (
                            <Badge key={i} variant="secondary" className="text-xs font-normal">{kw}</Badge>
                          ))}
                        </div>
                      </td>
                      <td className="py-3 pr-4">
                        <div className="flex flex-wrap gap-1">
                          {skill.excluded_intents.map((kw, i) => (
                            <Badge key={i} variant="outline" className="text-xs text-red-500 border-red-200">{kw}</Badge>
                          ))}
                        </div>
                      </td>
                      <td className="py-3">
                        <div className="flex gap-2">
                          <Button variant="outline" size="sm" onClick={() => openDetail(skill.skill_id)}>
                            <BookOpen className="w-3 h-3 mr-1" />
                            详情
                          </Button>
                          <Button variant="default" size="sm" onClick={() => openTest(skill.skill_id)}>
                            <Play className="w-3 h-3 mr-1" />
                            测试
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 技能详情弹窗 */}
      <Dialog open={detailDialogOpen} onOpenChange={setDetailDialogOpen}>
        <DialogContent className="sm:max-w-4xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span>技能详情 - {selectedSkill?.skill_name || '加载中...'}</span>
              {selectedSkill && (
                <ActionObjectBadge action={selectedSkill.business_action} object={selectedSkill.business_object} />
              )}
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">{selectedSkill?.skill_id}</DialogDescription>
          </DialogHeader>
          
          {loadingDetail ? (
            <div className="py-12 text-center text-gray-500">加载详情中...</div>
          ) : selectedSkill ? (
            <Tabs defaultValue="explain" orientation="horizontal" className="flex-col">
              <TabsList className="mb-4">
                <TabsTrigger value="explain">费用项解析</TabsTrigger>
                <TabsTrigger value="query-plan">查询计划</TabsTrigger>
                <TabsTrigger value="versions">版本证据</TabsTrigger>
                <TabsTrigger value="manifest">Manifest (元数据)</TabsTrigger>
                <TabsTrigger value="fields">字段映射</TabsTrigger>
                <TabsTrigger value="files">目录结构</TabsTrigger>
                <TabsTrigger value="readme">SKILL.md</TabsTrigger>
              </TabsList>

              <TabsContent value="explain">
                <SkillQuestionExplainer
                  skillId={selectedSkill.skill_id}
                  strategies={selectedSkill.files_structure.strategies}
                />
              </TabsContent>

              <TabsContent value="query-plan">
                <SkillQueryPlan skillId={selectedSkill.skill_id} />
              </TabsContent>

              <TabsContent value="versions">
                <div className="space-y-4" data-testid="version-evidence">
                  {versionError && (
                    <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      {versionError}
                    </div>
                  )}
                  {selectedCatalogSkill && (
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-slate-50 px-4 py-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <ArtifactStatusBadge status={selectedCatalogSkill.artifact_status} />
                          <span className="font-mono text-sm">v{selectedCatalogSkill.semantic_version}</span>
                          <span className="text-xs text-gray-500">{selectedCatalogSkill.file_count} 个文件</span>
                        </div>
                        <div className="font-mono text-xs text-gray-500" title={selectedCatalogSkill.artifact_hash}>
                          artifact hash: {selectedCatalogSkill.artifact_hash}
                        </div>
                      </div>
                      {selectedCatalogSkill.artifact_status !== 'registered' && (
                        <Button
                          size="sm"
                          onClick={handleSyncVersion}
                          disabled={syncingVersion}
                          data-testid="register-skill-version"
                        >
                          <GitCommit className="mr-1 h-4 w-4" />
                          {syncingVersion ? '登记中...' : '登记当前版本'}
                        </Button>
                      )}
                    </div>
                  )}
                  {versions.length === 0 ? (
                    <div className="py-8 text-center text-sm text-gray-500">尚无已登记版本</div>
                  ) : (
                    <div className="space-y-2">
                      {versions.map((version) => (
                        <div key={version.version_id} className="rounded-lg border px-4 py-3 text-sm">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <strong>v{version.semantic_version}</strong>
                            <span className={version.validation_status === 'passed' ? 'text-emerald-700' : 'text-amber-700'}>
                              {version.validation_status === 'passed' ? '校验通过' : version.validation_status}
                            </span>
                          </div>
                          <dl className="mt-2 grid gap-1 text-xs text-gray-600 md:grid-cols-2">
                            <div><dt className="inline text-gray-400">Git commit：</dt><dd className="inline font-mono">{version.source_commit}</dd></div>
                            <div><dt className="inline text-gray-400">文件数：</dt><dd className="inline">{version.file_count}</dd></div>
                            <div className="md:col-span-2 break-all"><dt className="inline text-gray-400">artifact hash：</dt><dd className="inline font-mono">{version.artifact_hash}</dd></div>
                            <div><dt className="inline text-gray-400">登记人：</dt><dd className="inline">{version.created_by}</dd></div>
                            <div><dt className="inline text-gray-400">登记时间：</dt><dd className="inline">{new Date(version.created_at).toLocaleString()}</dd></div>
                          </dl>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </TabsContent>
              
              <TabsContent value="manifest" className="bg-gray-50 p-4 rounded-md overflow-x-auto">
                <pre className="text-xs font-mono text-gray-800">
                  {JSON.stringify(selectedSkill.manifest, null, 2)}
                </pre>
              </TabsContent>
              
              <TabsContent value="fields">
                <SkillFieldMapping detail={selectedSkill} />
              </TabsContent>
              
              <TabsContent value="files">
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  {Object.entries(selectedSkill.files_structure).map(([dirName, files]) => (
                    <Card key={dirName} className="shadow-sm">
                      <CardHeader className="py-3 bg-gray-50 border-b">
                        <CardTitle className="text-sm flex items-center gap-2">
                          <FolderTree className="w-4 h-4 text-blue-500" />
                          {dirName}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="py-3">
                        {files.length > 0 ? (
                          <ul className="text-xs space-y-1 font-mono text-gray-600">
                            {files.map((f: string) => <li key={f}>{f}</li>)}
                          </ul>
                        ) : (
                          <span className="text-xs text-gray-400 italic">空目录</span>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </TabsContent>
              
              <TabsContent value="readme" className="bg-white border p-4 rounded-md">
                {selectedSkill.readme ? (
                  <pre className="text-sm whitespace-pre-wrap font-sans">{selectedSkill.readme}</pre>
                ) : (
                  <span className="text-gray-500 italic">暂无说明文档</span>
                )}
              </TabsContent>
            </Tabs>
          ) : null}
        </DialogContent>
      </Dialog>

      {/* 技能路由测试弹窗 */}
      <Dialog open={routeDialogOpen} onOpenChange={setRouteDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>技能路由匹配测试</DialogTitle>
            <DialogDescription>
              输入用户的自然语言问题，测试底层的路由分发机制会将其分配给哪个技能包。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium mb-1 block">测试问题</label>
              <Input 
                placeholder="例如：统筹自付是什么？" 
                value={routeQuestion}
                onChange={e => setRouteQuestion(e.target.value)}
                aria-label="路由测试问题"
                data-testid="route-question"
              />
            </div>
            <Button onClick={handleRouteTest} disabled={routeTesting || !routeQuestion.trim()} className="w-full">
              {routeTesting ? '匹配中...' : '测试匹配'}
            </Button>
            
            {routeResult && (
              <div className="mt-4 p-3 bg-gray-50 border rounded-md">
                <span className="text-sm font-medium text-gray-700">匹配结果：</span>
                <div data-testid="route-result" className="mt-1 text-sm font-mono text-blue-600 font-bold">{routeResult}</div>
                {routeDetails && (
                  <div className="mt-3 space-y-2 text-xs text-gray-600">
                    <div>置信度：<strong>{Math.round(routeDetails.confidence * 100)}%</strong>　方式：{routeDetails.match_method}</div>
                    <div>命中关键词：{routeDetails.matched_keywords.length ? routeDetails.matched_keywords.join('、') : '无'}</div>
                    {routeDetails.candidates.length > 1 && <div>候选：{routeDetails.candidates.map((candidate) => `${candidate.skill_name} (${Math.round(candidate.confidence * 100)}%)`).join('、')}</div>}
                  </div>
                )}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* 技能执行测试弹窗 */}
      <Dialog open={testDialogOpen} onOpenChange={setTestDialogOpen}>
        <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>技能执行测试 - {selectedSkill?.skill_name}</DialogTitle>
            <DialogDescription>
              直接调用 assembler.execute() 测试技能的核心逻辑。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium mb-1 block">提问 (Question)</label>
              <Input 
                placeholder="用户的提问" 
                value={testQuestion}
                onChange={e => setTestQuestion(e.target.value)}
                aria-label="执行测试问题"
                data-testid="execution-question"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">目标费用项 (Target Fee Item) <span className="text-gray-400 font-normal ml-1">可选，测试特定策略</span></label>
              <Input 
                placeholder="例如：pooling_self_pay" 
                value={testTargetFeeItem}
                onChange={e => setTestTargetFeeItem(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">上下文 (Context JSON) <span className="text-gray-400 font-normal ml-1">可选</span></label>
              <Textarea 
                placeholder="{}" 
                value={testContext}
                onChange={e => setTestContext(e.target.value)}
                className="font-mono text-xs h-24"
              />
            </div>
            
            <Button onClick={handleExecuteTest} disabled={executingTest || !testQuestion.trim()} className="w-full flex items-center gap-2">
              <Beaker className="w-4 h-4" />
              {executingTest ? '执行中...' : '运行测试'}
            </Button>
            
            {testResult && (
              <div className="mt-4">
                <label className="text-sm font-medium mb-1 block">执行结果：</label>
                {executionDetails && (
                  <div className="mb-3 space-y-2 text-xs">
                    {executionDetails.warnings.length > 0 && <div className="rounded border border-amber-200 bg-amber-50 p-2 text-amber-700">警告：{executionDetails.warnings.join('；')}</div>}
                    {executionDetails.uncertainties.length > 0 && <div className="rounded border border-orange-200 bg-orange-50 p-2 text-orange-700">不确定性：{executionDetails.uncertainties.join('；')}</div>}
                    {executionDetails.citations.length > 0 && <div className="rounded border border-blue-200 bg-blue-50 p-2 text-blue-700">来源：{executionDetails.citations.length} 条</div>}
                    {executionDetails.latency_ms != null && <div className="text-gray-500">耗时：{executionDetails.latency_ms}ms</div>}
                  </div>
                )}
                <pre data-testid="execution-result" className="p-3 bg-gray-900 text-gray-100 rounded-md text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
                  {testResult}
                </pre>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
