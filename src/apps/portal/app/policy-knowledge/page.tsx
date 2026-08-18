'use client'

import Link from 'next/link'
import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import {
  AlertTriangle,
  BadgeCheck,
  BookOpenCheck,
  ChevronRight,
  Database,
  FileText,
  Network,
  ScanText,
  ShieldCheck,
} from 'lucide-react'

import {
  getActiveRelease,
  getGovernanceDashboard,
  getPipelineSummary,
  getPolicyKnowledgeStats,
  getSemanticSummary,
  listKnowledgeBuildTasks,
  type GovernanceDashboard,
  type KnowledgeBuildTask,
  type KnowledgeRelease,
  type PipelineSummary,
  type SemanticSummary,
} from '@/lib/policy-knowledge-api'

type BlockState<T> =
  | { kind: 'loading' }
  | { kind: 'ready'; data: T }
  | { kind: 'failed' }

type ReleaseState =
  | { kind: 'loading' }
  | { kind: 'active'; data: KnowledgeRelease }
  | { kind: 'none' }
  | { kind: 'failed' }

const loadingBlock = { kind: 'loading' } as const
const failedBlock = { kind: 'failed' } as const
const PIPELINE_STAGES = [
  ['输入快照', 'INPUT_SNAPSHOT'],
  ['LLM 提取', 'LLM_EXTRACTION'],
  ['规范化', 'CANONICALIZE'],
  ['规则组装', 'COMPOSE'],
  ['引用解析', 'RESOLVE'],
  ['规则派生', 'DERIVE'],
  ['确定性校验', 'VALIDATE'],
] as const

function formatRate(value: number): string {
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`
}

/** 骨架屏占位块 */
function Sk({ className }: { className: string }) {
  return <span aria-hidden className={`block animate-pulse rounded bg-slate-200/80 ${className}`} />
}

/** 区块三态渲染：加载中显示骨架屏，失败显示占位文案 */
function cell<T>(state: BlockState<T>, render: (data: T) => ReactNode, skClass = 'h-4 w-12'): ReactNode {
  if (state.kind === 'loading') return <Sk className={skClass} />
  if (state.kind === 'failed') return <span className="text-xs text-slate-400">暂不可用</span>
  return render(state.data)
}

export default function GovernanceOverviewPage() {
  const [summary, setSummary] = useState<BlockState<PipelineSummary>>(loadingBlock)
  const [publishedKnowledge, setPublishedKnowledge] = useState<BlockState<number>>(loadingBlock)
  const [dashboard, setDashboard] = useState<BlockState<GovernanceDashboard>>(loadingBlock)
  const [buildTasks, setBuildTasks] = useState<BlockState<KnowledgeBuildTask[]>>(loadingBlock)
  const [semantic, setSemantic] = useState<BlockState<SemanticSummary>>(loadingBlock)
  const [release, setRelease] = useState<ReleaseState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false

    // 各区块独立加载：任一请求完成后立即渲染对应区块，不再等待全部请求
    const settle = <T,>(promise: Promise<T>, apply: (state: BlockState<T>) => void) => {
      promise
        .then((data) => { if (!cancelled) apply({ kind: 'ready', data }) })
        .catch(() => { if (!cancelled) apply(failedBlock) })
    }

    settle(getPipelineSummary(), setSummary)
    settle(getGovernanceDashboard(), setDashboard)
    settle(listKnowledgeBuildTasks(), setBuildTasks)
    settle(getSemanticSummary(), setSemantic)
    getPolicyKnowledgeStats()
      .then((stats) => { if (!cancelled) setPublishedKnowledge({ kind: 'ready', data: stats.total ?? 0 }) })
      .catch(() => { if (!cancelled) setPublishedKnowledge(failedBlock) })
    getActiveRelease()
      .then((data) => { if (!cancelled) setRelease({ kind: 'active', data }) })
      .catch((error: unknown) => {
        if (cancelled) return
        const status = (error as { status?: number } | null)?.status
        setRelease(status === 404 ? { kind: 'none' } : { kind: 'failed' })
      })

    return () => { cancelled = true }
  }, [])

  const tasks = buildTasks.kind === 'ready' ? buildTasks.data : []
  const buildingCount = buildTasks.kind === 'ready'
    ? tasks.filter((task) => task.status === 'QUEUED' || task.status === 'RUNNING').length
    : null
  const pendingReleaseCount = buildTasks.kind === 'ready'
    ? tasks.filter((task) => task.status === 'APPROVED_PENDING_RELEASE').length
    : null
  const dash = dashboard.kind === 'ready' ? dashboard.data : null
  const reviewChangeSets = dash?.change_sets_by_status.PENDING_REVIEW ?? 0
  const pendingChangeSets = reviewChangeSets + (dash?.change_sets_by_status.NEEDS_DECISION ?? 0)
  const contractVersion = release.kind === 'active' ? release.data.contract_version : 'v2.1'

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-[-0.025em] text-slate-900">知识资产概览</h2>
          <p className="mt-1 text-sm text-slate-500">先盘点可用资产，再查看治理状态与生产阻塞</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1.5 font-medium text-blue-700">
            <ShieldCheck className="size-3.5" />语义契约 {contractVersion}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 font-medium text-emerald-700">
            <BadgeCheck className="size-3.5" />
            生效版本 {release.kind === 'active' ? release.data.release_id : release.kind === 'none' ? '未发布' : release.kind === 'failed' ? '暂不可用' : '…'}
          </span>
        </div>
      </header>

      <KpiStrip dashboard={dashboard} publishedKnowledge={publishedKnowledge} />

      <AssetLedger
        summary={summary}
        dashboard={dashboard}
        semantic={semantic}
        release={release}
        buildingCount={buildingCount}
        pendingReleaseCount={pendingReleaseCount}
      />

      <KnowledgeAssetDetail
        dashboard={dashboard}
        semantic={semantic}
        buildingCount={buildingCount}
        pendingReleaseCount={pendingReleaseCount}
        reviewChangeSets={reviewChangeSets}
      />

      <GovernanceStatus
        summary={summary}
        dashboard={dashboard}
        semantic={semantic}
        release={release}
        buildingCount={buildingCount}
        reviewChangeSets={reviewChangeSets}
        pendingChangeSets={pendingChangeSets}
      />
    </div>
  )
}

/* ---------------------------------- KPI 指标条 ---------------------------------- */

const KPI_TONES = {
  blue: { box: 'bg-blue-50 text-blue-600', value: 'text-slate-900' },
  emerald: { box: 'bg-emerald-50 text-emerald-600', value: 'text-emerald-700' },
  amber: { box: 'bg-amber-50 text-amber-600', value: 'text-amber-700' },
} as const

function KpiStrip({
  dashboard,
  publishedKnowledge,
}: {
  dashboard: BlockState<GovernanceDashboard>
  publishedKnowledge: BlockState<number>
}) {
  const approved = dashboard.kind === 'ready' ? dashboard.data.rules_approved : null
  const pendingReview = dashboard.kind === 'ready' ? dashboard.data.rules_pending_review : null
  const approvedIdle = approved === 0 && (pendingReview ?? 0) > 0

  return (
    <section aria-label="关键指标" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <KpiCard
        icon={BookOpenCheck}
        label="知识总量"
        tone="blue"
        state={dashboard}
        pick={(data) => data.knowledge_total}
        sub="政策规则单元"
      />
      <KpiCard
        icon={BadgeCheck}
        label="已批准变更规则"
        tone={approvedIdle ? 'amber' : 'emerald'}
        state={dashboard}
        pick={(data) => data.rules_approved}
        sub={approvedIdle ? (
          <Link href="/policy-knowledge/knowledge/review" className="font-semibold text-amber-700 hover:underline">
            {pendingReview} 条待审核，去处理 →
          </Link>
        ) : '变更规则'}
      />
      <KpiCard
        icon={ScanText}
        label="待审核规则"
        tone={(pendingReview ?? 0) > 0 ? 'amber' : 'blue'}
        state={dashboard}
        pick={(data) => data.rules_pending_review}
        sub="变更规则"
      />
      <KpiCard
        icon={Database}
        label="已进入检索池"
        tone="blue"
        state={publishedKnowledge}
        pick={(total) => total}
        sub="可供问答检索"
      />
    </section>
  )
}

function KpiCard<T>({
  icon: Icon,
  label,
  tone,
  state,
  pick,
  sub,
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  tone: keyof typeof KPI_TONES
  state: BlockState<T>
  pick: (data: T) => number
  sub: ReactNode
}) {
  const colors = KPI_TONES[tone]
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2.5">
        <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${colors.box}`}>
          <Icon className="size-4" />
        </span>
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <div className={`mt-3 font-mono text-2xl font-bold tabular-nums ${colors.value}`}>
        {state.kind === 'loading' ? <Sk className="h-7 w-14" /> : state.kind === 'failed' ? <span className="text-sm font-normal text-slate-400">暂不可用</span> : pick(state.data)}
      </div>
      <div className="mt-1 text-[11px] text-slate-500">{sub}</div>
    </div>
  )
}

/* ---------------------------------- 资产台账 ---------------------------------- */

function Pill({ tone, children }: { tone: 'good' | 'warn' | 'muted'; children: ReactNode }) {
  const cls = tone === 'good'
    ? 'bg-emerald-50 text-emerald-700'
    : tone === 'warn'
      ? 'bg-amber-50 text-amber-700'
      : 'bg-slate-100 text-slate-500'
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{children}</span>
}

function AssetLedger({
  summary,
  dashboard,
  semantic,
  release,
  buildingCount,
  pendingReleaseCount,
}: {
  summary: BlockState<PipelineSummary>
  dashboard: BlockState<GovernanceDashboard>
  semantic: BlockState<SemanticSummary>
  release: ReleaseState
  buildingCount: number | null
  pendingReleaseCount: number | null
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white px-5 py-5 sm:px-6">
      <div className="mb-3 flex items-baseline gap-3">
        <h3 className="text-base font-semibold text-slate-900">资产台账</h3>
        <p className="text-xs text-slate-500">数量、可用状态和治理缺口统一查看</p>
      </div>

      {/* 列宽自适应内容，不做 min-width，保证窄视口下"需关注"列始终可见 */}
      <table aria-label="知识资产台账" className="w-full text-left text-sm text-slate-700">
        <thead>
          <tr className="border-b border-slate-200 text-[11px] font-medium text-slate-500">
            <th className="px-3 py-2.5">资产类型</th>
            <th className="px-3 py-2.5">当前规模</th>
            <th className="px-3 py-2.5">可用资产</th>
            <th className="px-3 py-2.5">治理中</th>
            <th className="px-3 py-2.5">需关注</th>
            <th className="px-3 py-2.5"><span className="sr-only">操作</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          <AssetRow
            icon={FileText}
            label="政策文档"
            href="/policy-knowledge/documents"
            scale={cell(summary, (data) => <AssetNumber value={data.documents_count} />, 'h-5 w-8')}
            available={cell(summary, (data) => <Pill tone="good">{Math.max(0, data.documents_count - data.documents_raw)} 已完成解析</Pill>, 'h-5 w-20')}
            governing={cell(summary, (data) => `${data.documents_raw} 待解析`, 'h-4 w-14')}
            attention={<span className="text-slate-300">—</span>}
          />
          <AssetRow
            icon={ScanText}
            label="政策单元"
            href="/policy-knowledge/units"
            scale={cell(summary, (data) => <AssetNumber value={data.units_count} />, 'h-5 w-8')}
            available={cell(summary, (data) => <Pill tone="good">{data.units_audited} 已审核</Pill>, 'h-5 w-16')}
            governing={<span className="text-slate-300">—</span>}
            attention={cell(summary, (data) => data.units_pending > 0 ? <Pill tone="warn">{data.units_pending} 待审核</Pill> : <Pill tone="good">无积压</Pill>, 'h-5 w-14')}
          />
          <AssetRow
            icon={BookOpenCheck}
            label="结构化知识"
            href="/policy-knowledge/knowledge/build"
            selected
            scale={cell(dashboard, (data) => <AssetNumber value={data.knowledge_total} sub="政策规则单元" />, 'h-5 w-10')}
            available={cell(dashboard, (data) => data.rules_approved > 0 ? <Pill tone="good">{data.rules_approved} 已批准</Pill> : <Pill tone="warn">0 已批准</Pill>, 'h-5 w-16')}
            governing={buildingCount === null ? <span className="text-xs text-slate-400">暂不可用</span> : `${buildingCount} 个构建任务`}
            attention={cell(dashboard, (data) => data.rules_pending_review > 0 ? <Pill tone="warn">{data.rules_pending_review} 条待审核</Pill> : <Pill tone="good">无积压</Pill>, 'h-5 w-16')}
            action="已展开"
          />
          <AssetRow
            icon={Network}
            label="语义资产"
            href="/policy-knowledge/knowledge/semantic-discovery"
            scale={cell(semantic, (data) => <AssetNumber value={data.metrics_count} sub="指标" />, 'h-5 w-10')}
            available={cell(semantic, (data) => <Pill tone="good">{data.mapped_count} 已映射</Pill>, 'h-5 w-16')}
            governing={cell(semantic, (data) => `映射率 ${formatRate(data.mapping_rate)}`, 'h-4 w-16')}
            attention={cell(semantic, (data) => data.unmapped_count > 0 ? <Pill tone="warn">{data.unmapped_count} 未映射</Pill> : <Pill tone="good">全部映射</Pill>, 'h-5 w-14')}
          />
          <ReleaseRow release={release} pendingReleaseCount={pendingReleaseCount} />
        </tbody>
      </table>
    </section>
  )
}

/** 发布快照行：无活动版本时显示引导式空态，而不是一串 0 */
function ReleaseRow({
  release,
  pendingReleaseCount,
}: {
  release: ReleaseState
  pendingReleaseCount: number | null
}) {
  const href = '/policy-knowledge/knowledge/releases'

  if (release.kind === 'none') {
    return (
      <tr className="transition-colors hover:bg-slate-50/70">
        <td className="border-l-2 border-transparent px-3 py-3.5">
          <Link href={href} className="inline-flex items-center gap-2.5 rounded-sm font-semibold text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
            <span className="grid size-7 place-items-center rounded-lg bg-slate-100 text-slate-600">
              <BadgeCheck className="size-3.5" />
            </span>
            发布快照
          </Link>
        </td>
        <td colSpan={4} className="px-3 py-3.5">
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            尚未发布版本，知识资产固化后才会生成快照
            <Link href={href} className="font-semibold text-blue-700 hover:underline">前往发布管理 →</Link>
          </span>
        </td>
        <td className="px-3 py-3.5 text-right">
          <Link href={href} className="inline-flex items-center gap-1 rounded-sm text-xs font-semibold text-blue-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
            去发布<ChevronRight className="size-3" />
          </Link>
        </td>
      </tr>
    )
  }

  return (
    <AssetRow
      icon={BadgeCheck}
      label="发布快照"
      href={href}
      scale={release.kind === 'loading'
        ? <Sk className="h-5 w-8" />
        : release.kind === 'failed'
          ? <span className="text-xs text-slate-400">暂不可用</span>
          : <AssetNumber value={1} sub="活动版本" />}
      available={release.kind === 'loading'
        ? <Sk className="h-5 w-24" />
        : release.kind === 'failed'
          ? <span className="text-xs text-slate-400">暂不可用</span>
          : <Pill tone="good"><span className="font-mono">{release.data.release_id}</span></Pill>}
      governing={pendingReleaseCount === null ? <span className="text-xs text-slate-400">暂不可用</span> : `${pendingReleaseCount} 待发布`}
      attention={<Pill tone="good">质量门禁正常</Pill>}
    />
  )
}

function AssetRow({
  icon: Icon,
  label,
  href,
  scale,
  available,
  governing,
  attention,
  selected = false,
  action = '查看',
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  href: string
  scale: ReactNode
  available: ReactNode
  governing: ReactNode
  attention: ReactNode
  selected?: boolean
  action?: string
}) {
  const iconClass = selected
    ? 'grid size-7 place-items-center rounded-lg bg-blue-600 text-white'
    : 'grid size-7 place-items-center rounded-lg bg-slate-100 text-slate-600'

  return (
    <tr className={`transition-colors ${selected ? 'bg-blue-50/90' : 'hover:bg-slate-50/70'}`}>
      <td className={`px-3 py-3.5 ${selected ? 'border-l-2 border-blue-600' : 'border-l-2 border-transparent'}`}>
        <Link href={href} className="inline-flex items-center gap-2.5 rounded-sm font-semibold text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
          <span className={iconClass}>
            <Icon className="size-3.5" />
          </span>
          {label}
        </Link>
      </td>
      <td className="px-3 py-3.5">{scale}</td>
      <td className="px-3 py-3.5">{available}</td>
      <td className="px-3 py-3.5">{governing}</td>
      <td className="px-3 py-3.5">{attention}</td>
      <td className="px-3 py-3.5 text-right">
        <Link href={href} className="inline-flex items-center gap-1 rounded-sm text-xs font-semibold text-blue-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
          {action}<ChevronRight className={`size-3 ${selected ? 'rotate-90' : ''}`} />
        </Link>
      </td>
    </tr>
  )
}

function AssetNumber({ value, sub }: { value: number; sub?: string }) {
  return (
    <span>
      <strong className="font-mono text-lg font-bold tabular-nums text-slate-900">{value}</strong>
      {sub && <small className="mt-0.5 block text-[10px] text-slate-500">{sub}</small>}
    </span>
  )
}

/* ---------------------------------- 结构化知识 ---------------------------------- */

const COMPILE_SEGMENTS = [
  ['PASS', 'bg-emerald-500', 'bg-emerald-500'],
  ['WARN', 'bg-amber-400', 'bg-amber-400'],
  ['REVIEW', 'bg-orange-500', 'bg-orange-500'],
  ['FAIL', 'bg-red-500', 'bg-red-500'],
] as const

function KnowledgeAssetDetail({
  dashboard,
  semantic,
  buildingCount,
  pendingReleaseCount,
  reviewChangeSets,
}: {
  dashboard: BlockState<GovernanceDashboard>
  semantic: BlockState<SemanticSummary>
  buildingCount: number | null
  pendingReleaseCount: number | null
  reviewChangeSets: number
}) {
  const data = dashboard.kind === 'ready' ? dashboard.data : null
  const compile = data?.compilation_by_status ?? {}
  const compileTotal = COMPILE_SEGMENTS.reduce((sum, [status]) => sum + (compile[status] ?? 0), 0)
  const hasCompilerBlocker = (compile.REVIEW ?? 0) > 0 || (compile.FAIL ?? 0) > 0

  return (
    <section aria-label="结构化知识详情" className="rounded-2xl border border-slate-200 bg-white px-5 py-5 sm:px-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-3">
        <h3 className="text-base font-semibold text-slate-900">结构化知识</h3>
        <p className="text-xs text-slate-500">选中资产的生产状态与工作入口</p>
        <Link href="/policy-knowledge/knowledge/build" className="ml-auto inline-flex items-center gap-1 rounded-sm text-xs font-semibold text-blue-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
          进入知识工作台<ChevronRight className="size-3" />
        </Link>
      </div>

      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="text-sm font-semibold text-slate-800">知识编译管线</h4>
        <p className="text-[11px] text-slate-500">七个实际阶段 · 状态按当前变更规则汇总</p>
        <div className="ml-auto flex flex-wrap gap-3 font-mono text-[10px] font-semibold tabular-nums">
          {dashboard.kind === 'loading' ? (
            <Sk className="h-3 w-40" />
          ) : dashboard.kind === 'failed' ? (
            <span className="text-slate-400">暂不可用</span>
          ) : compileTotal === 0 ? (
            <span className="text-slate-400">暂无编译记录</span>
          ) : (
            COMPILE_SEGMENTS.map(([status, , dot]) => (
              <span key={status} className="inline-flex items-center gap-1 text-slate-600">
                <span aria-hidden className={`size-1.5 rounded-full ${dot}`} />
                {status} {compile[status] ?? 0}
              </span>
            ))
          )}
        </div>
      </div>

      {/* 编译状态分布条：一眼看出 REVIEW / FAIL 阻断面 */}
      <div className="mt-3">
        {dashboard.kind === 'loading' ? (
          <Sk className="h-2 w-full rounded-full" />
        ) : dashboard.kind === 'failed' || compileTotal === 0 ? (
          <div className="h-2 rounded-full bg-slate-100" />
        ) : (
          <div className="flex h-2 overflow-hidden rounded-full bg-slate-100" role="img" aria-label="编译状态分布">
            {COMPILE_SEGMENTS.filter(([status]) => (compile[status] ?? 0) > 0).map(([status, bar]) => (
              <span
                key={status}
                className={bar}
                style={{ width: `${((compile[status] ?? 0) / compileTotal) * 100}%` }}
                title={`${status} ${compile[status] ?? 0}`}
              />
            ))}
          </div>
        )}
      </div>

      <StageRail
        className="mt-4"
        stages={PIPELINE_STAGES.map(([label, code]) => ({ label, sub: code, tone: 'ok' as const }))}
      />

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-dashed border-slate-200 pt-3 text-[11px] text-slate-500">
        {dashboard.kind !== 'ready' ? (
          <Sk className="h-3 w-48" />
        ) : hasCompilerBlocker ? (
          <span className="inline-flex items-center gap-1.5">
            <AlertTriangle className="size-3.5 text-amber-600" />
            <span><strong className="text-amber-700">REVIEW / FAIL 会阻断正式发布</strong>，请先在知识审核中处理。</span>
          </span>
        ) : (
          <span>当前没有编译阻断。</span>
        )}
        <Link href="/policy-knowledge/knowledge/review" className="ml-auto font-semibold text-blue-700">查看需复核项 →</Link>
      </div>

      <div className="mt-5 border-t border-slate-100 pt-4">
        <h4 className="mb-3 text-sm font-semibold text-slate-800">知识工作域</h4>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <WorkspaceCard href="/policy-knowledge/knowledge/build" label="知识构建" description="从审核单元生成知识变更" state={buildingCount === null ? '暂不可用' : `${buildingCount} 运行中`} />
          <WorkspaceCard href="/policy-knowledge/knowledge/review" label="知识审核" description="审查新增、修改、替代与失效" state={dashboard.kind === 'failed' ? '暂不可用' : `${reviewChangeSets} 变更集`} hot={reviewChangeSets > 0} />
          <WorkspaceCard href="/policy-knowledge/knowledge/releases" label="发布管理" description="候选版本、质量门禁与快照" state={pendingReleaseCount === null ? '暂不可用' : `${pendingReleaseCount} 待发布`} hot={(pendingReleaseCount ?? 0) > 0} />
          <WorkspaceCard href="/policy-knowledge/knowledge/semantic-discovery" label="语义发现" description="指标与值域候选治理" state={semantic.kind === 'ready' ? `${semantic.data.unmapped_count} 未映射` : semantic.kind === 'failed' ? '暂不可用' : '加载中'} hot={semantic.kind === 'ready' && semantic.data.unmapped_count > 0} />
        </div>
      </div>
    </section>
  )
}

function WorkspaceCard({
  href,
  label,
  description,
  state,
  hot = false,
}: {
  href: string
  label: string
  description: string
  state: string
  hot?: boolean
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-slate-200 p-3.5 transition-all hover:border-blue-300 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      <span className="flex items-center justify-between gap-2">
        <strong className="text-xs font-semibold text-slate-800 group-hover:text-blue-700">{label}</strong>
        <span className={`shrink-0 text-xs font-semibold ${hot ? 'text-amber-700' : 'text-blue-700'}`}>{state}</span>
      </span>
      <small className="mt-1 block text-[10px] text-slate-500">{description}</small>
    </Link>
  )
}

/* ---------------------------------- 治理进度 ---------------------------------- */

type StageTone = 'ok' | 'done' | 'hot' | 'idle'

const STAGE_DOT: Record<StageTone, string> = {
  ok: 'border-[3px] border-blue-100 bg-blue-600',
  done: 'border-2 border-emerald-600 bg-emerald-600 shadow-[inset_0_0_0_3px_white]',
  hot: 'border-2 border-amber-600 bg-amber-50',
  idle: 'border-2 border-slate-300 bg-white',
}

/** 阶段轨道：节点 flex-1 自适应收缩，不做 min-width，任何视口都不截断 */
function StageRail({
  stages,
  className = '',
}: {
  stages: Array<{ label: string; sub?: ReactNode; tone: StageTone }>
  className?: string
}) {
  return (
    <ol className={`flex items-start ${className}`}>
      {stages.map((stage, index) => (
        <li key={stage.label} className="relative min-w-0 flex-1 text-center">
          {index > 0 && <span aria-hidden className="absolute left-0 right-1/2 top-[7px] h-px bg-slate-200" />}
          {index < stages.length - 1 && <span aria-hidden className="absolute left-1/2 right-0 top-[7px] h-px bg-slate-200" />}
          <span className={`relative z-10 mx-auto block size-3.5 rounded-full ${STAGE_DOT[stage.tone]}`} />
          <span className="mt-2 block truncate px-1 text-[11px] font-semibold text-slate-700">{stage.label}</span>
          {stage.sub !== undefined && (
            <span className="mt-0.5 block truncate px-1 font-mono text-[9px] text-slate-400">{stage.sub}</span>
          )}
        </li>
      ))}
    </ol>
  )
}

function GovernanceStatus({
  summary,
  dashboard,
  semantic,
  release,
  buildingCount,
  reviewChangeSets,
  pendingChangeSets,
}: {
  summary: BlockState<PipelineSummary>
  dashboard: BlockState<GovernanceDashboard>
  semantic: BlockState<SemanticSummary>
  release: ReleaseState
  buildingCount: number | null
  reviewChangeSets: number
  pendingChangeSets: number
}) {
  const compilationReview = dashboard.kind === 'ready'
    ? (dashboard.data.compilation_by_status.REVIEW ?? 0) + (dashboard.data.compilation_by_status.FAIL ?? 0)
    : null

  const stageOf = (backlog: number | null, text: string): { tone: StageTone; sub: ReactNode } => ({
    tone: backlog !== null && backlog > 0 ? 'hot' : 'idle',
    sub: <span className={backlog !== null && backlog > 0 ? 'font-semibold text-amber-700' : ''}>{text}</span>,
  })

  const stages = [
    { label: '文档', ...stageOf(summary.kind === 'ready' ? summary.data.documents_raw : null, summary.kind === 'ready' ? `${summary.data.documents_raw} 待解析` : summary.kind === 'failed' ? '暂不可用' : '加载中') },
    { label: '单元', ...stageOf(summary.kind === 'ready' ? summary.data.units_pending : null, summary.kind === 'ready' ? `${summary.data.units_pending} 待审核` : summary.kind === 'failed' ? '暂不可用' : '加载中') },
    { label: '知识', ...stageOf(buildingCount, buildingCount === null ? '暂不可用' : `${buildingCount} 构建中`) },
    { label: '审核', ...stageOf(dashboard.kind === 'ready' ? reviewChangeSets : null, dashboard.kind === 'failed' ? '暂不可用' : dashboard.kind === 'loading' ? '加载中' : `${reviewChangeSets} 变更集`) },
    {
      label: '发布',
      tone: (release.kind === 'active' ? 'done' : 'idle') as StageTone,
      sub: release.kind === 'active' ? '活动版本正常' : release.kind === 'none' ? '尚未发布' : release.kind === 'failed' ? '暂不可用' : '加载中',
    },
  ]

  return (
    <section aria-label="治理进度" className="rounded-2xl border border-slate-200 bg-white px-5 py-5 sm:px-6">
      {/* min-w-0 防止子元素把 grid 列撑爆后与右栏重叠 */}
      <div className="grid gap-7 lg:grid-cols-[minmax(0,1.8fr)_minmax(280px,.72fr)]">
        <div className="min-w-0">
          <div className="flex items-baseline gap-3">
            <h3 className="text-base font-semibold text-slate-900">治理进度</h3>
            <p className="text-xs text-slate-500">只显示各阶段当前积压，不重复资产总量</p>
          </div>
          <StageRail className="mt-5" stages={stages} />
        </div>

        <section aria-label="当前需要处理" className="min-w-0 border-t border-slate-200 pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
          <h4 className="mb-1 text-sm font-semibold text-slate-800">当前需要处理</h4>
          <AttentionRow label="编译结果需人工复核" value={compilationReview} href="/policy-knowledge/knowledge/review" />
          <AttentionRow label="待审核知识变更集" value={dashboard.kind === 'ready' ? pendingChangeSets : null} href="/policy-knowledge/knowledge/review" />
          <AttentionRow label="语义指标尚未映射" value={semantic.kind === 'ready' ? semantic.data.unmapped_count : null} href="/policy-knowledge/knowledge/semantic-discovery" />
        </section>
      </div>
    </section>
  )
}

function AttentionRow({ label, value, href }: { label: string; value: number | null; href: string }) {
  const hot = value !== null && value > 0
  return (
    <Link
      href={href}
      className="group flex min-h-11 items-center gap-3 rounded-lg border-b border-slate-100 px-2 transition-colors last:border-b-0 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
    >
      <span className="text-xs text-slate-600 group-hover:text-slate-800">{label}</span>
      <strong className={`ml-auto font-mono text-base tabular-nums ${hot ? 'text-amber-700' : 'text-slate-300'}`}>
        {value === null ? '—' : value}
      </strong>
      <ChevronRight className="size-3.5 text-slate-300 transition-colors group-hover:text-blue-600" />
    </Link>
  )
}
