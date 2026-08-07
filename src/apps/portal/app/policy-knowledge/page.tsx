'use client'

// 政策知识治理 · 概览（治理看板）。
// 治理流水线 + 待办队列 + 统计卡带 + 生命周期分布 + 标化概览 + 质量风险 + 影响分析占位。
// [来源: docs/steering/政策知识治理-概览页丰富设计-V1.0.md]
// [来源: docs/steering/政策知识治理平台设计-V2.1.md §5.2]
//
// 数据聚合（全部现有接口，Promise.allSettled 并发，单接口失败按区块降级）：
//   policy-pipeline/summary + extractions（低置信扫描，≤100 条上限）
//   policy-knowledge/stats（Milvus 已发布）
//   policy-workbench/governance/dashboard + knowledge-build/tasks + eligible-units
//   policy-workbench/releases/active + quality/latest（404 = 未发布/暂无，正常态）
//   semantic/summary（标化四格）

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  FileText, Anchor, Lightbulb, ShieldCheck, AlertTriangle,
  Activity, GitBranch, Gauge, Compass, Check, Hammer,
  ClipboardCheck, Rocket, BadgeCheck, ListTodo, SlidersHorizontal,
} from 'lucide-react'
import {
  getActiveRelease,
  getGovernanceDashboard,
  getLatestReleaseQuality,
  getPipelineSummary,
  getPolicyKnowledgeStats,
  getSemanticSummary,
  listEligibleKnowledgeUnits,
  listKnowledgeBuildTasks,
  listPipelineExtractions,
  PolicyKnowledgeApiError,
  type GovernanceDashboard,
  type KnowledgeBuildTask,
  type KnowledgeRelease,
  type PipelineSummary,
  type QualityRun,
  type SemanticSummary,
} from '@/lib/policy-knowledge-api'

// —— 设计令牌（设计.pen variables，见设计文档 §5）——
const PRIMARY = '#1E5AA8'
const SUCCESS = '#1C8A55'
const WARNING = '#A16207'
const DANGER = '#C0392B'
const INDIGO = '#4F46E5'
const MUTED = '#64748B'

/** 区块加载三态：loading 骨架 / failed 暂不可用 / ready 渲染 */
type BlockState<T> =
  | { kind: 'loading' }
  | { kind: 'failed' }
  | { kind: 'ready'; data: T }

const loadingBlock: BlockState<never> = { kind: 'loading' }
const failedBlock: BlockState<never> = { kind: 'failed' }

function toBlock<T>(result: PromiseSettledResult<T>): BlockState<T> {
  return result.status === 'fulfilled' ? { kind: 'ready', data: result.value } : failedBlock
}

/** releases/active 404 是正常业务态（未发布），需与其他失败区分 */
type ReleaseState =
  | { kind: 'loading' }
  | { kind: 'none' }
  | { kind: 'failed' }
  | { kind: 'active'; data: KnowledgeRelease }

interface LowConfStats {
  count: number
  capped: boolean
}

export default function GovernanceOverviewPage() {
  const [summary, setSummary] = useState<BlockState<PipelineSummary>>(loadingBlock)
  const [milvusTotal, setMilvusTotal] = useState<BlockState<number>>(loadingBlock)
  const [lowConf, setLowConf] = useState<BlockState<LowConfStats>>(loadingBlock)
  const [dashboard, setDashboard] = useState<BlockState<GovernanceDashboard>>(loadingBlock)
  const [buildTasks, setBuildTasks] = useState<BlockState<KnowledgeBuildTask[]>>(loadingBlock)
  const [release, setRelease] = useState<ReleaseState>({ kind: 'loading' })
  const [qualityRun, setQualityRun] = useState<BlockState<QualityRun> | { kind: 'none' }>(loadingBlock)
  const [semantic, setSemantic] = useState<BlockState<SemanticSummary>>(loadingBlock)
  const [eligibleCount, setEligibleCount] = useState<BlockState<number>>(loadingBlock)

  useEffect(() => {
    let cancelled = false

    async function loadMain() {
      const [summaryR, statsR, extractionsR, dashboardR, tasksR, releaseR, semanticR] =
        await Promise.allSettled([
          getPipelineSummary(),
          getPolicyKnowledgeStats(),
          listPipelineExtractions(1, 100),
          getGovernanceDashboard(),
          listKnowledgeBuildTasks(),
          getActiveRelease(),
          getSemanticSummary(),
        ])
      if (cancelled) return

      setSummary(toBlock(summaryR))
      setMilvusTotal(
        statsR.status === 'fulfilled' ? { kind: 'ready', data: statsR.value.total ?? 0 } : failedBlock,
      )
      if (extractionsR.status === 'fulfilled') {
        const items = extractionsR.value.items ?? []
        setLowConf({
          kind: 'ready',
          data: {
            count: items.filter((e) => (e.confidence ?? 1) < 0.8).length,
            capped: (extractionsR.value.total ?? items.length) > items.length,
          },
        })
      } else {
        setLowConf(failedBlock)
      }
      setDashboard(toBlock(dashboardR))
      setBuildTasks(toBlock(tasksR))
      setSemantic(toBlock(semanticR))

      // releases/active：404 = 未发布（正常态），其余失败按降级处理
      if (releaseR.status === 'fulfilled') {
        setRelease({ kind: 'active', data: releaseR.value })
        // 有 active 才查质量门禁；404 = 暂无质量运行（正常态）
        try {
          const report = await getLatestReleaseQuality(releaseR.value.release_id)
          if (!cancelled) setQualityRun({ kind: 'ready', data: report.run })
        } catch (err) {
          if (cancelled) return
          if (err instanceof PolicyKnowledgeApiError && err.status === 404) {
            setQualityRun({ kind: 'none' })
          } else {
            setQualityRun(failedBlock)
          }
        }
      } else {
        // 404 = 尚无活动版本（正常业务态）；用 status 属性判定，兼容任意错误类型
        const status = (releaseR.reason as { status?: number } | null)?.status
        if (status === 404) {
          setRelease({ kind: 'none' })
          setQualityRun({ kind: 'none' })
        } else {
          setRelease({ kind: 'failed' })
          setQualityRun(failedBlock)
        }
      }
    }

    async function loadEligible() {
      // eligible-units ~2s 慢接口（迭代 16 已诊断）：独立加载，不阻塞首屏
      try {
        const units = await listEligibleKnowledgeUnits()
        if (!cancelled) setEligibleCount({ kind: 'ready', data: units.length })
      } catch {
        if (!cancelled) setEligibleCount(failedBlock)
      }
    }

    void loadMain()
    void loadEligible()
    return () => { cancelled = true }
  }, [])

  // —— 派生数据 ——
  const tasks = buildTasks.kind === 'ready' ? buildTasks.data : []
  const buildingCount = tasks.filter((t) => t.status === 'QUEUED' || t.status === 'RUNNING').length
  const waitingReviewCount = tasks.filter((t) => t.status === 'WAITING_REVIEW').length
  const pendingReleaseCount = tasks.filter((t) => t.status === 'APPROVED_PENDING_RELEASE').length

  const dash = dashboard.kind === 'ready' ? dashboard.data : null
  const pendingChangeSets = dash
    ? (dash.change_sets_by_status?.PENDING_REVIEW ?? 0) + (dash.change_sets_by_status?.NEEDS_DECISION ?? 0)
    : 0
  const decisionTasksPending = dash?.tasks_pending ?? 0
  const lowConfCount = lowConf.kind === 'ready' ? lowConf.data.count : 0

  const allClear =
    dashboard.kind === 'ready' && buildTasks.kind === 'ready' && lowConf.kind === 'ready' &&
    pendingChangeSets === 0 && pendingReleaseCount === 0 && decisionTasksPending === 0 && lowConfCount === 0

  const activeRelease = release.kind === 'active' ? release.data : null
  const contractVersion = activeRelease?.contract_version ?? 'v2.1'

  return (
    <div className="flex flex-col gap-6">
      {/* Header + 契约/版本 chips */}
      <header className="flex flex-wrap items-center gap-2">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight text-slate-800">治理概览</h2>
          <p className="text-xs text-slate-500">流水线 · 待办 · 质量 · 版本 · 影响分析</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-lg bg-[#E9F1FB] px-2.5 py-1 text-[11px] font-medium text-[#1E5AA8]">
            <ShieldCheck className="size-3" />
            语义契约 <span className="font-mono">{contractVersion}</span>
          </span>
          <span className="inline-flex items-center gap-1 rounded-lg bg-[#E5F6EC] px-2.5 py-1 text-[11px] font-medium text-[#1C8A55]">
            <BadgeCheck className="size-3" />
            生效版本 <span className="font-mono">{activeRelease?.release_id ?? '未发布'}</span>
          </span>
        </div>
      </header>

      {/* A. 治理流水线 */}
      <PipelineFlow
        documents={summary}
        eligible={eligibleCount}
        building={buildTasks.kind === 'ready' ? buildingCount : null}
        buildingFailed={buildTasks.kind === 'failed'}
        waitingReview={buildTasks.kind === 'ready' ? waitingReviewCount : null}
        pendingRelease={buildTasks.kind === 'ready' ? pendingReleaseCount : null}
        release={release}
      />

      {/* B. 待办队列 */}
      <WorkQueue
        dashboard={dashboard}
        pendingChangeSets={pendingChangeSets}
        pendingRelease={buildTasks.kind === 'ready' ? pendingReleaseCount : null}
        tasksFailed={buildTasks.kind === 'failed'}
        lowConf={lowConf}
        allClear={allClear}
      />

      {/* C. 统计卡带 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {summary.kind === 'ready' ? (
          <StatCard href="/policy-knowledge/documents" icon={FileText} color={PRIMARY} label="文档" value={summary.data.documents_count} sub={summary.data.documents_raw > 0 ? `${summary.data.documents_raw} 待提取` : undefined} />
        ) : (
          <StatCardPlaceholder state={summary} label="文档" />
        )}
        {summary.kind === 'ready' ? (
          <StatCard href="/policy-knowledge/units" icon={Anchor} color={INDIGO} label="单元 (Unit)" value={summary.data.extractions_count} />
        ) : (
          <StatCardPlaceholder state={summary} label="单元 (Unit)" />
        )}
        {milvusTotal.kind === 'ready' ? (
          <StatCard href="/policy-knowledge/knowledge?sub=library" icon={Lightbulb} color={SUCCESS} label="已发布知识" value={milvusTotal.data} sub="进入检索池" />
        ) : (
          <StatCardPlaceholder state={milvusTotal} label="已发布知识" />
        )}
        {summary.kind === 'ready' ? (
          <StatCard href="/policy-knowledge/knowledge/review" icon={ShieldCheck} color={WARNING} label="待审知识" value={summary.data.extractions_draft} sub={summary.data.extractions_draft > 0 ? '需人工审核' : undefined} />
        ) : (
          <StatCardPlaceholder state={summary} label="待审知识" />
        )}
      </div>

      {/* D. 生命周期分布 + E. 标化概览 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LifecycleBar summary={summary} />
        <SemanticStrip semantic={semantic} />
      </div>

      {/* F. 质量与风险 + G. 影响分析占位 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <QualityRiskPanel dashboard={dashboard} qualityRun={qualityRun} release={release} />
        <ImpactPlaceholder />
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Link href="/policy-knowledge/documents" className="flex items-center gap-3 rounded-lg border border-[#DCE3EC] bg-[#E9F1FB]/50 px-4 py-3 text-sm font-medium text-[#1E5AA8] hover:bg-[#E9F1FB] transition-colors">
          <FileText className="size-4" /> 管理文档 <span className="ml-auto text-slate-300">→</span>
        </Link>
        <Link href="/policy-knowledge/units" className="flex items-center gap-3 rounded-lg border border-[#DCE3EC] bg-[#EEF0FD]/50 px-4 py-3 text-sm font-medium text-[#4F46E5] hover:bg-[#EEF0FD] transition-colors">
          <Anchor className="size-4" /> 浏览单元 <span className="ml-auto text-slate-300">→</span>
        </Link>
        <Link href="/policy-knowledge/knowledge?sub=audit" className="flex items-center gap-3 rounded-lg border border-[#DCE3EC] bg-[#FBF0DC]/50 px-4 py-3 text-sm font-medium text-[#A16207] hover:bg-[#FBF0DC] transition-colors">
          <ShieldCheck className="size-4" /> 知识审核 <span className="ml-auto text-slate-300">→</span>
        </Link>
      </div>

      {/* Discovery 入口（候选指标回写语义层）*/}
      <Link href="/policy-knowledge/discovery" className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-600">
        <Compass className="size-3.5" /> 发现（扫描高频实体/关系 → 候选指标回写语义层）→
      </Link>
    </div>
  )
}

// ═══════════════ A. 治理流水线（设计.pen 评审流引导）═══════════════════

interface PipelineStep {
  key: string
  label: string
  href: string
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>
  /** null = 加载中/失败 */
  count: number | null
  countLabel: string
  /** info = 中性信息态（恒蓝）；counter = 计数状态机（>0 待处理 / =0 已清空）；static = 静态文本 */
  mode: 'info' | 'counter' | 'static'
  staticText?: string
}

function PipelineFlow({
  documents, eligible, building, buildingFailed, waitingReview, pendingRelease, release,
}: {
  documents: BlockState<PipelineSummary>
  eligible: BlockState<number>
  building: number | null
  buildingFailed: boolean
  waitingReview: number | null
  pendingRelease: number | null
  release: ReleaseState
}) {
  const docReady = documents.kind === 'ready' ? documents.data : null
  const steps: PipelineStep[] = [
    {
      key: 'documents', label: '文档', href: '/policy-knowledge/documents', icon: FileText,
      count: docReady ? docReady.documents_count : null,
      countLabel: docReady && docReady.documents_raw > 0 ? `导入 · ${docReady.documents_raw} 待解析` : '已导入',
      mode: 'info',
    },
    {
      key: 'units', label: '单元', href: '/policy-knowledge/units', icon: Anchor,
      count: eligible.kind === 'ready' ? eligible.data : null,
      countLabel: '可构建',
      mode: 'info',
    },
    {
      key: 'extract', label: '知识提取', href: '/policy-knowledge/knowledge/build', icon: Hammer,
      count: building, countLabel: '待处理', mode: 'counter',
    },
    {
      key: 'review', label: '知识审核', href: '/policy-knowledge/knowledge/review', icon: ClipboardCheck,
      count: waitingReview, countLabel: '待处理', mode: 'counter',
    },
    {
      key: 'release', label: '待发布', href: '/policy-knowledge/knowledge/releases', icon: Rocket,
      count: pendingRelease, countLabel: '待处理', mode: 'counter',
    },
    {
      key: 'active', label: '已生效', href: '/policy-knowledge/knowledge/published', icon: BadgeCheck,
      count: null, countLabel: '', mode: 'static',
      staticText: release.kind === 'active' ? release.data.release_id
        : release.kind === 'none' ? '未发布'
        : release.kind === 'failed' ? '暂不可用' : undefined,
    },
  ]

  return (
    <section aria-label="治理流水线" className="rounded-xl border border-[#DCE3EC] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <GitBranch className="size-4 text-[#1E5AA8]" />
        <h3 className="text-sm font-semibold text-slate-700">治理流水线</h3>
        <span className="ml-auto text-[11px] text-slate-400">文档 → 单元 → 知识 → 发布</span>
      </div>
      <ol className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-0">
        {steps.map((step, i) => {
          const isActive = step.mode === 'counter' && (step.count ?? 0) > 0
          const isDone = step.mode === 'counter' && step.count === 0
          const failed = step.count === null && step.mode !== 'static' &&
            (step.key === 'documents' ? documents.kind === 'failed'
              : step.key === 'units' ? eligible.kind === 'failed'
              : buildingFailed)
          return (
            <li key={step.key} className="flex items-center lg:flex-1">
              <Link href={step.href} className="group flex min-w-0 items-center gap-2.5">
                <span
                  className="flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                  style={
                    isActive ? { backgroundColor: PRIMARY, color: '#fff' }
                    : isDone || (step.mode === 'static' && release.kind === 'active') ? { backgroundColor: SUCCESS, color: '#fff' }
                    : step.mode === 'info' ? { backgroundColor: '#E9F1FB', color: PRIMARY }
                    : { backgroundColor: '#EEF1F5', color: MUTED }
                  }
                >
                  {isDone || (step.mode === 'static' && release.kind === 'active') ? <Check className="size-3.5" /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600 group-hover:text-slate-800">
                    <step.icon className="size-3.5" style={{ color: isActive ? PRIMARY : MUTED }} />
                    {step.label}
                  </span>
                  <span className="mt-0.5 block text-[11px]">
                    {step.mode === 'static' ? (
                      <span className="font-mono font-semibold" style={{ color: release.kind === 'active' ? SUCCESS : MUTED }}>
                        {step.staticText ?? '加载中'}
                      </span>
                    ) : step.count === null ? (
                      <span className="text-slate-400">{failed ? '暂不可用' : '加载中'}</span>
                    ) : step.mode === 'info' ? (
                      <span className="font-mono font-semibold" style={{ color: MUTED }}>
                        {step.count} {step.countLabel}
                      </span>
                    ) : (
                      <span className="font-mono font-semibold" style={{ color: isActive ? PRIMARY : MUTED }}>
                        {step.count} {isActive ? step.countLabel : '已清空'}
                      </span>
                    )}
                  </span>
                </span>
              </Link>
              {i < steps.length - 1 && (
                <span aria-hidden className="mx-3 hidden h-px flex-1 bg-[#DCE3EC] lg:block" />
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// ═══════════════ B. 待办队列 ═══════════════

function WorkQueue({
  dashboard, pendingChangeSets, pendingRelease, tasksFailed, lowConf, allClear,
}: {
  dashboard: BlockState<GovernanceDashboard>
  pendingChangeSets: number
  pendingRelease: number | null
  tasksFailed: boolean
  lowConf: BlockState<LowConfStats>
  allClear: boolean
}) {
  const dashReady = dashboard.kind === 'ready'
  const tasksByType = dashReady ? dashboard.data.tasks_by_type ?? {} : {}
  const decisionPending = dashReady ? dashboard.data.tasks_pending : null

  if (allClear) {
    return (
      <section aria-label="待办队列" className="rounded-xl border border-[#DCE3EC] bg-[#E5F6EC] px-5 py-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-medium text-[#1C8A55]">
          <Check className="size-4" /> 暂无待办 · 流水线畅通
        </div>
      </section>
    )
  }

  return (
    <section aria-label="待办队列" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <TodoCard
        href="/policy-knowledge/knowledge/review"
        label="待审变更集"
        value={dashReady ? pendingChangeSets : null}
        failed={dashboard.kind === 'failed'}
        sub="PENDING_REVIEW + NEEDS_DECISION"
      />
      <TodoCard
        href="/policy-knowledge/knowledge/releases"
        label="待发布"
        value={pendingRelease}
        failed={tasksFailed}
        sub="审核通过待发布"
      />
      <TodoCard
        href="/policy-knowledge/knowledge/decisions"
        label="决策任务待处理"
        value={decisionPending}
        failed={dashboard.kind === 'failed'}
        sub={
          Object.keys(tasksByType).length > 0
            ? Object.entries(tasksByType).map(([t, n]) => `${t} ${n}`).join(' · ')
            : undefined
        }
      />
      <TodoCard
        href="/policy-knowledge/knowledge/review"
        label="低置信预警"
        value={lowConf.kind === 'ready' ? lowConf.data.count : null}
        failed={lowConf.kind === 'failed'}
        sub={lowConf.kind === 'ready' && lowConf.data.capped ? '<0.8 · 前 100 条中' : '置信度 <0.8'}
      />
    </section>
  )
}

function TodoCard({
  href, label, value, sub, failed,
}: {
  href: string
  label: string
  value: number | null
  sub?: string
  failed: boolean
}) {
  const hot = (value ?? 0) > 0
  return (
    <Link href={href} className="block group" aria-label={`待办-${label}`}>
      <div
        className="rounded-xl border border-[#DCE3EC] bg-white px-4 py-3 shadow-sm transition-shadow hover:shadow-md"
        style={{ borderLeft: `4px solid ${hot ? WARNING : '#DCE3EC'}` }}
      >
        <div className="flex items-center gap-2">
          <ListTodo className="size-3.5" style={{ color: hot ? WARNING : MUTED }} />
          <span className="text-xs text-slate-500">{label}</span>
          <span className="ml-auto font-mono text-lg font-bold" style={{ color: hot ? WARNING : MUTED }}>
            {value === null ? (failed ? '—' : '…') : value}
          </span>
        </div>
        {failed && <div className="mt-1 text-[10px] text-slate-400">暂不可用</div>}
        {!failed && sub && <div className="mt-1 truncate text-[10px] text-slate-400" title={sub}>{sub}</div>}
      </div>
    </Link>
  )
}

// ═══════════════ C. 统计卡 ═══════════════

function StatCard({
  href, icon: Icon, color, label, value, sub,
}: {
  href: string
  icon: React.ComponentType<{ className?: string }>
  color: string
  label: string
  value: number
  sub?: string
}) {
  return (
    <Link href={href} className="block group">
      <div className="rounded-xl border border-[#DCE3EC] bg-white px-5 py-4 shadow-sm transition-shadow hover:shadow-md">
        <div className="mb-2 flex items-center gap-2" style={{ color }}>
          <Icon className="size-4" />
          <span className="text-xs text-slate-500">{label}</span>
        </div>
        <div className="font-mono text-2xl font-bold" style={{ color }}>{value}</div>
        {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
      </div>
    </Link>
  )
}

function StatCardPlaceholder({ state, label }: { state: BlockState<unknown>; label: string }) {
  return (
    <div className="rounded-xl border border-[#DCE3EC] bg-white px-5 py-4 shadow-sm">
      <div className="mb-2 text-xs text-slate-500">{label}</div>
      <div className="text-sm text-slate-400">{state.kind === 'failed' ? '暂不可用' : '加载中'}</div>
    </div>
  )
}

// ═══════════════ D. 生命周期分布 ═══════════════

const LC_BAR: { key: string; label: string; color: string }[] = [
  { key: 'draft', label: '待审 Draft', color: '#94A3B8' },
  { key: 'reviewed', label: '待发布 Review', color: WARNING },
  { key: 'published', label: '已发布 Published', color: SUCCESS },
  { key: 'rejected', label: '已驳回', color: DANGER },
]

function LifecycleBar({ summary }: { summary: BlockState<PipelineSummary> }) {
  if (summary.kind === 'loading') {
    return <BlockPending label="知识生命周期分布" icon={GitBranch} />
  }
  if (summary.kind === 'failed') {
    return <BlockFailed label="知识生命周期分布" icon={GitBranch} />
  }
  const d = summary.data
  const rejected = Math.max(0, d.extractions_count - d.extractions_draft - d.extractions_reviewed - d.extractions_published)
  const lcCounts: Record<string, number> = {
    draft: d.extractions_draft,
    reviewed: d.extractions_reviewed,
    published: d.extractions_published,
    rejected,
  }
  const lcTotal = d.extractions_count || 1

  return (
    <section aria-label="知识生命周期分布" className="rounded-xl border border-[#DCE3EC] bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <GitBranch className="size-4 text-[#4F46E5]" />
        <h3 className="text-sm font-semibold text-slate-700">知识生命周期分布</h3>
        <span className="ml-auto text-xs text-slate-400">共 {d.extractions_count} 条</span>
      </div>
      <div className="mb-3 flex h-3 w-full overflow-hidden rounded-full bg-[#EEF1F5]">
        {LC_BAR.map((b) => {
          const cnt = lcCounts[b.key] || 0
          const pct = (cnt / lcTotal) * 100
          return pct > 0 ? (
            <div key={b.key} style={{ width: `${pct}%`, backgroundColor: b.color }} title={`${b.label}: ${cnt}`} />
          ) : null
        })}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {LC_BAR.map((b) => (
          <div key={b.key} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={{ backgroundColor: b.color }} />
            <span className="text-[11px] text-slate-500">{b.label}</span>
            <span className="ml-auto font-mono text-sm font-semibold text-slate-700">{lcCounts[b.key] || 0}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-1.5 rounded-lg bg-[#F6F8FB] px-3 py-2 text-[11px] text-slate-500">
        <span className="rounded bg-violet-100 px-1.5 py-0.5 text-violet-700">已替代</span>
        <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-zinc-600">已废止</span>
        两态随版本治理接入（V2.1 §3.1），当前数据暂未承载。
      </div>
    </section>
  )
}

// ═══════════════ E. 标化概览（设计.pen 右栏四格）═══════════════════

function SemanticStrip({ semantic }: { semantic: BlockState<SemanticSummary> }) {
  if (semantic.kind === 'loading') {
    return <BlockPending label="标化概览" icon={SlidersHorizontal} />
  }
  if (semantic.kind === 'failed') {
    return <BlockFailed label="标化概览" icon={SlidersHorizontal} />
  }
  const s = semantic.data
  const cells: { label: string; value: string; color: string }[] = [
    { label: '已映射', value: String(s.mapped_count), color: SUCCESS },
    { label: '未映射', value: String(s.unmapped_count), color: PRIMARY },
    { label: '映射率', value: `${(s.mapping_rate ?? 0).toFixed(1)}%`, color: '#1F2A37' },
    { label: '指标总数', value: String(s.metrics_count), color: MUTED },
  ]
  return (
    <Link href="/semantic-layer" className="block group" aria-label="标化概览">
      <section className="h-full rounded-xl border border-[#DCE3EC] bg-white p-6 shadow-sm transition-shadow group-hover:shadow-md">
        <div className="mb-4 flex items-center gap-2">
          <SlidersHorizontal className="size-4 text-[#1E5AA8]" />
          <h3 className="text-sm font-semibold text-slate-700">标化概览</h3>
          <span className="ml-auto text-[11px] text-slate-400">语义层 · 只读跨链 →</span>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-[#DCE3EC]">
          {cells.map((c, i) => (
            <div
              key={c.label}
              className="flex-1 px-3 py-2.5"
              style={i < cells.length - 1 ? { borderRight: '1px solid #DCE3EC' } : undefined}
            >
              <div className="text-[10px] text-slate-400">{c.label}</div>
              <div className="mt-0.5 font-mono text-base font-bold" style={{ color: c.color }}>{c.value}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-slate-400">映射管理在语义层进行，本页仅只读跨链（V2.1 §5.6）。</p>
      </section>
    </Link>
  )
}

// ═══════════════ F. 质量与风险 ═══════════════

const RISK_LEVELS: { key: string; label: string; color: string }[] = [
  { key: 'LOW', label: '低', color: SUCCESS },
  { key: 'MEDIUM', label: '中', color: WARNING },
  { key: 'HIGH', label: '高', color: '#C2410C' },
  { key: 'CRITICAL', label: '严重', color: DANGER },
]

function QualityRiskPanel({
  dashboard, qualityRun, release,
}: {
  dashboard: BlockState<GovernanceDashboard>
  qualityRun: BlockState<QualityRun> | { kind: 'none' }
  release: ReleaseState
}) {
  if (dashboard.kind === 'loading') {
    return <BlockPending label="质量与风险" icon={Gauge} />
  }
  if (dashboard.kind === 'failed') {
    return <BlockFailed label="质量与风险" icon={Gauge} />
  }
  const dash = dashboard.data
  return (
    <section aria-label="质量与风险" className="rounded-xl border border-[#DCE3EC] bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <Gauge className="size-4 text-[#1E5AA8]" />
        <h3 className="text-sm font-semibold text-slate-700">质量与风险</h3>
      </div>
      <div className="flex flex-col gap-4">
        <MetricTrack label="平均来源保真度" value={dash.avg_source_fidelity} />
        <MetricTrack label="平均完整度" value={dash.avg_completeness} />
        <div className="flex items-center gap-2">
          <AlertTriangle className="size-3.5 text-slate-400" />
          <span className="text-xs text-slate-500">风险摘要</span>
          <span className="ml-auto flex gap-1.5">
            {RISK_LEVELS.map((r) => (
              <span
                key={r.key}
                className="rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold"
                style={{ backgroundColor: '#F6F8FB', color: r.color }}
                title={r.key}
              >
                {r.label} {dash.risk_summary?.[r.key] ?? 0}
              </span>
            ))}
          </span>
        </div>
        <div className="flex items-center gap-2 border-t border-[#F6F8FB] pt-3">
          <ShieldCheck className="size-3.5 text-slate-400" />
          <span className="text-xs text-slate-500">最近质量门禁</span>
          <span className="ml-auto text-xs">
            {qualityRun.kind === 'ready' ? (
              <span className="font-mono font-semibold" style={{ color: qualityRun.data.status === 'passed' ? SUCCESS : qualityRun.data.status === 'failed' ? DANGER : WARNING }}>
                {qualityRun.data.status}
                {qualityRun.data.candidate_score !== null && ` · ${(qualityRun.data.candidate_score * 100).toFixed(0)}%`}
              </span>
            ) : qualityRun.kind === 'none' ? (
              <span className="text-slate-400">{release.kind === 'none' ? '未发布' : '暂无'}</span>
            ) : qualityRun.kind === 'failed' ? (
              <span className="text-slate-400">暂不可用</span>
            ) : (
              <span className="text-slate-400">加载中</span>
            )}
          </span>
        </div>
      </div>
    </section>
  )
}

function MetricTrack({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 text-xs text-slate-500">{label}</span>
      {value === null || value === undefined ? (
        <span className="text-xs text-slate-400">暂无数据</span>
      ) : (
        <>
          <span className="h-[5px] flex-1 overflow-hidden rounded-full bg-[#EEF1F5]">
            <span
              className="block h-full rounded-full"
              style={{ width: `${Math.round(value * 100)}%`, backgroundColor: value >= 0.8 ? SUCCESS : value >= 0.6 ? WARNING : DANGER }}
            />
          </span>
          <span className="w-10 text-right font-mono text-xs font-semibold text-slate-700">
            {(value * 100).toFixed(0)}%
          </span>
        </>
      )}
    </div>
  )
}

// ═══════════════ G. 影响分析（占位）═══════════════

function ImpactPlaceholder() {
  return (
    <section aria-label="影响分析" className="rounded-xl border border-dashed border-[#C3D0E2] bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <Activity className="size-4 text-[#4F46E5]" />
        <h3 className="text-sm font-semibold text-slate-700">影响分析</h3>
        <span className="ml-auto rounded bg-[#EEF1F5] px-1.5 py-0.5 text-[10px] text-slate-500">待接入</span>
      </div>
      <p className="text-xs leading-relaxed text-slate-500">
        政策变更 → 定位受影响 Unit → 关联 Knowledge → 经提取契约反查 Metric（止于此，Skill/Agent 独立消费）。
        影响链 <code className="rounded bg-[#F6F8FB] px-1 font-mono text-[10px]">Document → Unit → Knowledge → Metric</code>{' '}
        随 <code className="rounded bg-[#F6F8FB] px-1 font-mono text-[10px]">policy-pipeline/impact/recent</code> 接口接入（Phase 2）。
      </p>
    </section>
  )
}

// ═══════════════ 通用：区块降级 ═══════════════

function BlockPending({ label, icon: Icon }: { label: string; icon: React.ComponentType<{ className?: string }> }) {
  return (
    <section aria-label={label} className="rounded-xl border border-[#DCE3EC] bg-white p-6 shadow-sm">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Icon className="size-4 animate-pulse" />
        {label} · 加载中
      </div>
    </section>
  )
}

function BlockFailed({ label, icon: Icon }: { label: string; icon: React.ComponentType<{ className?: string }> }) {
  return (
    <section aria-label={label} className="rounded-xl border border-dashed border-[#C3D0E2] bg-white p-6 shadow-sm">
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <Icon className="size-4" />
        {label} · 暂不可用
      </div>
    </section>
  )
}
