'use client'

import Link from 'next/link'
import { useEffect, useState, type ComponentType, type ReactNode } from 'react'
import {
  BadgeCheck,
  BookOpenCheck,
  Boxes,
  ChevronRight,
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
  PolicyKnowledgeApiError,
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

function toBlock<T>(result: PromiseSettledResult<T>): BlockState<T> {
  return result.status === 'fulfilled'
    ? { kind: 'ready', data: result.value }
    : failedBlock
}

function blockValue<T>(state: BlockState<T>, render: (data: T) => ReactNode): ReactNode {
  if (state.kind === 'loading') return <span className="text-slate-400">…</span>
  if (state.kind === 'failed') return <span className="text-slate-400">暂不可用</span>
  return render(state.data)
}

function formatRate(value: number): string {
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`
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

    async function load() {
      const [summaryResult, statsResult, dashboardResult, tasksResult, releaseResult, semanticResult] =
        await Promise.allSettled([
          getPipelineSummary(),
          getPolicyKnowledgeStats(),
          getGovernanceDashboard(),
          listKnowledgeBuildTasks(),
          getActiveRelease(),
          getSemanticSummary(),
        ])
      if (cancelled) return

      setSummary(toBlock(summaryResult))
      setPublishedKnowledge(
        statsResult.status === 'fulfilled'
          ? { kind: 'ready', data: statsResult.value.total ?? 0 }
          : failedBlock,
      )
      setDashboard(toBlock(dashboardResult))
      setBuildTasks(toBlock(tasksResult))
      setSemantic(toBlock(semanticResult))

      if (releaseResult.status === 'fulfilled') {
        setRelease({ kind: 'active', data: releaseResult.value })
      } else {
        const status = (releaseResult.reason as { status?: number } | null)?.status
        setRelease(status === 404 ? { kind: 'none' } : { kind: 'failed' })
      }
    }

    void load()
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

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <AssetLedger
          summary={summary}
          dashboard={dashboard}
          publishedKnowledge={publishedKnowledge}
          semantic={semantic}
          release={release}
          buildingCount={buildingCount}
          pendingReleaseCount={pendingReleaseCount}
        />
        <KnowledgeAssetDetail
          dashboard={dashboard}
          publishedKnowledge={publishedKnowledge}
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
    </div>
  )
}

function AssetLedger({
  summary,
  dashboard,
  publishedKnowledge,
  semantic,
  release,
  buildingCount,
  pendingReleaseCount,
}: {
  summary: BlockState<PipelineSummary>
  dashboard: BlockState<GovernanceDashboard>
  publishedKnowledge: BlockState<number>
  semantic: BlockState<SemanticSummary>
  release: ReleaseState
  buildingCount: number | null
  pendingReleaseCount: number | null
}) {
  return (
    <section className="px-5 py-5 sm:px-6">
      <div className="mb-3 flex items-baseline gap-3">
        <h3 className="text-base font-semibold text-slate-900">资产台账</h3>
        <p className="text-xs text-slate-500">数量、可用状态和治理缺口统一查看</p>
      </div>

      <div className="overflow-x-auto">
        <table aria-label="知识资产台账" className="w-full min-w-[940px] table-fixed text-left">
          <colgroup>
            <col className="w-[24%]" />
            <col className="w-[13%]" />
            <col className="w-[19%]" />
            <col className="w-[19%]" />
            <col className="w-[17%]" />
            <col className="w-[8%]" />
          </colgroup>
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
          <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
            <AssetRow
              icon={FileText}
              label="政策文档"
              href="/policy-knowledge/documents"
              scale={blockValue(summary, (data) => <AssetNumber value={data.documents_count} />)}
              available={blockValue(summary, (data) => <Good>{Math.max(0, data.documents_count - data.documents_raw)} 已完成解析</Good>)}
              governing={blockValue(summary, (data) => `${data.documents_raw} 待解析`)}
              attention="—"
            />
            <AssetRow
              icon={ScanText}
              label="政策单元"
              href="/policy-knowledge/units"
              scale={blockValue(summary, (data) => <AssetNumber value={data.units_count} />)}
              available={blockValue(summary, (data) => <Good>{data.units_audited} 已审核</Good>)}
              governing="—"
              attention={blockValue(summary, (data) => <Warning>{data.units_pending} 待审核</Warning>)}
            />
            <AssetRow
              icon={BookOpenCheck}
              label="结构化知识"
              href="/policy-knowledge/knowledge/build"
              selected
              scale={blockValue(dashboard, (data) => <AssetNumber value={data.knowledge_total} sub="政策规则单元" />)}
              available={blockValue(dashboard, (data) => <Good>{data.rules_approved} 已批准</Good>)}
              governing={buildingCount === null ? <span className="text-slate-400">暂不可用</span> : `${buildingCount} 个构建任务`}
              attention={blockValue(dashboard, (data) => <Warning>{data.rules_pending_review} 条待审核</Warning>)}
              action="已展开"
            />
            <AssetRow
              icon={Network}
              label="语义资产"
              href="/policy-knowledge/knowledge/semantic-discovery"
              scale={blockValue(semantic, (data) => <AssetNumber value={data.metrics_count} sub="指标" />)}
              available={blockValue(semantic, (data) => <Good>{data.mapped_count} 已映射</Good>)}
              governing={blockValue(semantic, (data) => `映射率 ${formatRate(data.mapping_rate)}`)}
              attention={blockValue(semantic, (data) => <Warning>{data.unmapped_count} 未映射</Warning>)}
            />
            <AssetRow
              icon={BadgeCheck}
              label="发布快照"
              href="/policy-knowledge/knowledge/releases"
              scale={release.kind === 'loading' ? '…' : release.kind === 'failed' ? '暂不可用' : <AssetNumber value={release.kind === 'active' ? 1 : 0} sub={release.kind === 'active' ? '活动版本' : undefined} />}
              available={release.kind === 'active' ? <Good mono>{release.data.release_id}</Good> : release.kind === 'none' ? '未发布' : release.kind === 'failed' ? '暂不可用' : '…'}
              governing={pendingReleaseCount === null ? '暂不可用' : `${pendingReleaseCount} 待发布`}
              attention={release.kind === 'active' ? '质量门禁正常' : '—'}
            />
          </tbody>
        </table>
      </div>
    </section>
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
    <tr className={selected ? 'bg-blue-50/90' : undefined}>
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

function Good({ children, mono = false }: { children: ReactNode; mono?: boolean }) {
  return <span className={`font-semibold text-emerald-700 ${mono ? 'font-mono' : ''}`}>{children}</span>
}

function Warning({ children }: { children: ReactNode }) {
  return <span className="font-semibold text-amber-700">{children}</span>
}

function KnowledgeAssetDetail({
  dashboard,
  publishedKnowledge,
  semantic,
  buildingCount,
  pendingReleaseCount,
  reviewChangeSets,
}: {
  dashboard: BlockState<GovernanceDashboard>
  publishedKnowledge: BlockState<number>
  semantic: BlockState<SemanticSummary>
  buildingCount: number | null
  pendingReleaseCount: number | null
  reviewChangeSets: number
}) {
  const data = dashboard.kind === 'ready' ? dashboard.data : null
  const compile = data?.compilation_by_status ?? {}
  const hasCompilerBlocker = (compile.REVIEW ?? 0) > 0 || (compile.FAIL ?? 0) > 0

  return (
    <section aria-label="结构化知识详情" className="border-t border-slate-200 bg-slate-50/45 px-5 py-5 sm:px-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-3">
        <h3 className="text-base font-semibold text-slate-900">结构化知识</h3>
        <p className="text-xs text-slate-500">选中资产的构成、生产状态与工作入口</p>
        <Link href="/policy-knowledge/knowledge/build" className="ml-auto inline-flex items-center gap-1 rounded-sm text-xs font-semibold text-blue-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
          进入知识工作台<ChevronRight className="size-3" />
        </Link>
      </div>

      <div className="grid gap-7 lg:grid-cols-[minmax(0,1.7fr)_minmax(270px,.75fr)]">
        <div className="min-w-0">
          <div className="grid grid-cols-2 border-y border-slate-200 sm:grid-cols-4">
            <KnowledgeMeasure label="当前知识总量" value={data?.knowledge_total} failed={dashboard.kind === 'failed'} />
            <KnowledgeMeasure label="已批准变更规则" value={data?.rules_approved} failed={dashboard.kind === 'failed'} tone="good" />
            <KnowledgeMeasure label="待审核规则" value={data?.rules_pending_review} failed={dashboard.kind === 'failed'} tone="warning" />
            <KnowledgeMeasure label="已进入检索池" value={publishedKnowledge.kind === 'ready' ? publishedKnowledge.data : undefined} failed={publishedKnowledge.kind === 'failed'} />
          </div>

          <div className="mt-5 flex flex-wrap items-baseline gap-2">
            <h4 className="text-sm font-semibold text-slate-800">知识编译管线</h4>
            <p className="text-[11px] text-slate-500">七个实际阶段 · 状态按当前变更规则汇总</p>
            <div className="ml-auto flex flex-wrap gap-2 font-mono text-[10px] font-semibold tabular-nums">
              {dashboard.kind === 'failed' ? (
                <span className="text-slate-400">暂不可用</span>
              ) : dashboard.kind === 'loading' ? (
                <span className="text-slate-400">加载中</span>
              ) : Object.keys(compile).length === 0 ? (
                <span className="text-slate-400">暂无编译记录</span>
              ) : (
                ['PASS', 'WARN', 'REVIEW', 'FAIL'].map((status) => (
                  <span key={status} className={status === 'REVIEW' || status === 'FAIL' ? 'text-amber-700' : 'text-slate-600'}>
                    {status} {compile[status] ?? 0}
                  </span>
                ))
              )}
            </div>
          </div>

          <div className="mt-4 overflow-x-auto pb-1">
            <ol className="flex min-w-[700px] items-start">
              {PIPELINE_STAGES.map(([label, code], index) => (
                <li key={code} className="relative flex-1 text-center">
                  {index > 0 && <span aria-hidden className="absolute left-0 right-1/2 top-[7px] h-px bg-slate-300" />}
                  {index < PIPELINE_STAGES.length - 1 && <span aria-hidden className="absolute left-1/2 right-0 top-[7px] h-px bg-slate-300" />}
                  <span className="relative z-10 mx-auto block size-3.5 rounded-full border-[3px] border-blue-100 bg-blue-600" />
                  <span className="mt-2 block text-[11px] font-semibold text-slate-700">{label}</span>
                  <span className="mt-0.5 block font-mono text-[9px] text-slate-400">{code}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-dashed border-slate-200 pt-3 text-[11px] text-slate-500">
            {hasCompilerBlocker ? (
              <span><strong className="text-amber-700">REVIEW / FAIL 会阻断正式发布</strong>，请先在知识审核中处理。</span>
            ) : (
              <span>当前没有编译阻断。</span>
            )}
            <Link href="/policy-knowledge/knowledge/review" className="ml-auto font-semibold text-blue-700">查看需复核项 →</Link>
          </div>
        </div>

        <section aria-label="知识工作域" className="border-t border-slate-200 pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
          <h4 className="mb-1 text-sm font-semibold text-slate-800">知识工作域</h4>
          <WorkspaceLink href="/policy-knowledge/knowledge/build" label="知识构建" description="从审核单元生成知识变更" state={buildingCount === null ? '暂不可用' : `${buildingCount} 运行中`} />
          <WorkspaceLink href="/policy-knowledge/knowledge/review" label="知识审核" description="审查新增、修改、替代与失效" state={dashboard.kind === 'failed' ? '暂不可用' : `${reviewChangeSets} 变更集`} hot={reviewChangeSets > 0} />
          <WorkspaceLink href="/policy-knowledge/knowledge/releases" label="发布管理" description="候选版本、质量门禁与快照" state={pendingReleaseCount === null ? '暂不可用' : `${pendingReleaseCount} 待发布`} hot={(pendingReleaseCount ?? 0) > 0} />
          <WorkspaceLink href="/policy-knowledge/knowledge/semantic-discovery" label="语义发现" description="指标与值域候选治理" state={semantic.kind === 'ready' ? `${semantic.data.unmapped_count} 未映射` : semantic.kind === 'failed' ? '暂不可用' : '加载中'} hot={semantic.kind === 'ready' && semantic.data.unmapped_count > 0} />
        </section>
      </div>
    </section>
  )
}

function KnowledgeMeasure({
  label,
  value,
  failed,
  tone = 'default',
}: {
  label: string
  value?: number
  failed: boolean
  tone?: 'default' | 'good' | 'warning'
}) {
  const color = tone === 'good' ? 'text-emerald-700' : tone === 'warning' ? 'text-amber-700' : 'text-slate-900'
  return (
    <div className="px-3 py-3 first:pl-0 sm:border-l sm:border-slate-200 sm:first:border-l-0">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-xl font-bold tabular-nums ${value === undefined ? 'text-slate-400' : color}`}>
        {value === undefined ? (failed ? '—' : '…') : value}
      </div>
    </div>
  )
}

function WorkspaceLink({
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
    <Link href={href} className="group grid min-h-14 grid-cols-[1fr_auto] items-center gap-3 border-b border-slate-200 last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500">
      <span>
        <strong className="text-xs font-semibold text-slate-800 group-hover:text-blue-700">{label}</strong>
        <small className="mt-0.5 block text-[10px] text-slate-500">{description}</small>
      </span>
      <span className={`text-xs font-semibold ${hot ? 'text-amber-700' : 'text-blue-700'}`}>{state}</span>
    </Link>
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
  const stages = [
    { label: '文档', status: summary.kind === 'ready' ? `${summary.data.documents_raw} 待解析` : summary.kind === 'failed' ? '暂不可用' : '加载中', hot: summary.kind === 'ready' && summary.data.documents_raw > 0 },
    { label: '单元', status: summary.kind === 'ready' ? `${summary.data.units_pending} 待审核` : summary.kind === 'failed' ? '暂不可用' : '加载中', hot: summary.kind === 'ready' && summary.data.units_pending > 0 },
    { label: '知识', status: buildingCount === null ? '暂不可用' : `${buildingCount} 构建中`, hot: (buildingCount ?? 0) > 0 },
    { label: '审核', status: dashboard.kind === 'failed' ? '暂不可用' : dashboard.kind === 'loading' ? '加载中' : `${reviewChangeSets} 变更集`, hot: reviewChangeSets > 0 },
    { label: '发布', status: release.kind === 'active' ? '活动版本正常' : release.kind === 'none' ? '尚未发布' : release.kind === 'failed' ? '暂不可用' : '加载中', hot: false, done: release.kind === 'active' },
  ]

  return (
    <section aria-label="治理进度" className="border-t border-slate-200 px-5 py-5 sm:px-6">
      <div className="grid gap-7 lg:grid-cols-[minmax(0,1.8fr)_minmax(280px,.72fr)]">
        <div>
          <div className="flex items-baseline gap-3">
            <h3 className="text-base font-semibold text-slate-900">治理进度</h3>
            <p className="text-xs text-slate-500">只显示各阶段当前积压，不重复资产总量</p>
          </div>
          <ol className="mt-5 flex min-w-[560px] overflow-x-auto">
            {stages.map((stage, index) => (
              <li key={stage.label} className="relative min-w-28 flex-1 pr-5">
                {index < stages.length - 1 && <span aria-hidden className="absolute left-4 right-1 top-[7px] h-px bg-slate-300" />}
                <span className={`relative z-10 block size-4 rounded-full border-2 ${stage.done ? 'border-emerald-600 bg-emerald-600 shadow-[inset_0_0_0_3px_white]' : stage.hot ? 'border-amber-600 bg-amber-50' : 'border-slate-400 bg-white'}`} />
                <span className="mt-2 block text-xs font-semibold text-slate-800">{stage.label}</span>
                <span className={`mt-0.5 block text-[10px] ${stage.hot ? 'font-semibold text-amber-700' : 'text-slate-500'}`}>{stage.status}</span>
              </li>
            ))}
          </ol>
        </div>

        <section aria-label="当前需要处理" className="border-t border-slate-200 pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
          <h4 className="mb-1 text-sm font-semibold text-slate-800">当前需要处理</h4>
          <AttentionRow label="编译结果需人工复核" value={compilationReview} />
          <AttentionRow label="待审核知识变更集" value={dashboard.kind === 'ready' ? pendingChangeSets : null} />
          <AttentionRow label="语义指标尚未映射" value={semantic.kind === 'ready' ? semantic.data.unmapped_count : null} />
        </section>
      </div>
    </section>
  )
}

function AttentionRow({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex min-h-11 items-center gap-3 border-b border-slate-200 last:border-b-0">
      <span className="text-xs text-slate-600">{label}</span>
      <strong className={`ml-auto font-mono text-sm tabular-nums ${value === null || value === 0 ? 'text-slate-400' : 'text-amber-700'}`}>
        {value === null ? '—' : value}
      </strong>
    </div>
  )
}
