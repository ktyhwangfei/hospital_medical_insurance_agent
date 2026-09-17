'use client'

// 质量与发布页（数据治理中心一级模块）：质量门禁与发布证据的统一视图。
// ① 同步质量：各数据源最近批次质量门状态（overview 聚合）；
// ② Flow 发布：已发布 Flow 的活跃版本证据（artifact_hash / 发布人 / 发布时间）+ 修订历史；
// 均为既有只读接口聚合，不新增后端写路径。
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeftRight, Loader2, ShieldCheck } from 'lucide-react'

import { compareSource, getDataGovernanceOverview, type DataGovernanceOverview, type SourceCompareResult } from '@/lib/data-governance-api'
import { listFlowRevisions, listFlows, type FlowDefinitionDto, type FlowRevisionViewDto } from '@/lib/flow-api'
import { NextStepCard } from '@/components/next-step-card'

interface FlowRelease {
  flow: FlowDefinitionDto
  active: FlowRevisionViewDto | null
  revisionCount: number
}

function formatTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

// ── 源库对照：系统落地值 vs 源库值并排，数字可信度自证 ───────────────

const COMPARE_PRESETS = [
  { label: '门诊交易笔数', table: 'o_Trade', column: null, op: 'count' },
  { label: '门诊费用明细行数', table: 'o_FeeItem', column: null, op: 'count' },
  { label: '门诊总费用合计', table: 'o_Trade', column: 'T_FeeAll', op: 'sum' },
  { label: '统筹支付合计', table: 'o_Trade', column: 'T_FundPay', op: 'sum' },
  { label: '医保门诊交易笔数', table: 'yb_mzjyxx', column: null, op: 'count' },
  { label: '医保结算总金额', table: 'yb_mzjyxx', column: 'zje', op: 'sum' },
] as const

function SourceComparePanel({ sourceId }: { sourceId: string }) {
  const [selected, setSelected] = useState(0)
  const [result, setResult] = useState<SourceCompareResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const preset = COMPARE_PRESETS[selected]
      setResult(await compareSource(sourceId, {
        table_name: preset.table, column: preset.column, op: preset.op,
      }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '对照查询失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" data-testid="source-compare">
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
        <ArrowLeftRight className="size-4 text-slate-500" />
        <h3 className="font-semibold text-slate-900">源库对照</h3>
        <span className="text-xs text-slate-500">系统落地值与源库值并排——数字可信度自证</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <select aria-label="对照项" value={selected} onChange={(e) => { setSelected(Number(e.target.value)); setResult(null) }}
          className="h-8 rounded-md border border-slate-300 bg-white px-2 text-xs outline-none focus:border-blue-500">
          {COMPARE_PRESETS.map((p, i) => <option key={p.label} value={i}>{p.label}（{p.table}）</option>)}
        </select>
        <button type="button" onClick={() => void run()} disabled={busy}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-slate-900 px-3 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-40"
          data-testid="compare-run">
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}对照
        </button>
        {error && <span role="alert" className="text-xs text-red-700">{error}</span>}
      </div>
      {result && (
        <div className="grid gap-3 border-t border-slate-100 px-4 py-3 sm:grid-cols-3" data-testid="compare-result">
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-[11px] text-slate-500">源库（{result.table_name}）</p>
            <p className="mt-1 font-mono text-lg font-semibold text-slate-900">{result.source_value ?? '—'}</p>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-[11px] text-slate-500">落地库（{result.target_table}）</p>
            <p className="mt-1 font-mono text-lg font-semibold text-slate-900">{result.landing_value ?? '—'}</p>
          </div>
          <div className={`rounded-lg p-3 ${result.match ? 'bg-emerald-50' : 'bg-red-50'}`}>
            <p className="text-[11px] text-slate-500">差异</p>
            <p className={`mt-1 font-mono text-lg font-semibold ${result.match ? 'text-emerald-700' : 'text-red-700'}`}>
              {result.diff ?? '—'}{result.match ? ' ✓ 一致' : ' ✗ 不一致'}
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

export default function DataQualityPage() {
  const [overview, setOverview] = useState<DataGovernanceOverview | null>(null)
  const [releases, setReleases] = useState<FlowRelease[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [ov, flows] = await Promise.all([getDataGovernanceOverview(), listFlows()])
        const published = flows.filter((f) => f.status === 'published')
        const detail = await Promise.all(
          published.map(async (flow) => {
            const revisions = await listFlowRevisions(flow.flow_id).catch(() => [] as FlowRevisionViewDto[])
            return {
              flow,
              active: revisions.find((r) => r.is_active) ?? null,
              revisionCount: revisions.length,
            } satisfies FlowRelease
          }),
        )
        if (cancelled) return
        setOverview(ov)
        setReleases(detail)
        setError(null)
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '质量与发布数据加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  return <div className="space-y-5" data-testid="data-quality-page">
    <div>
      <h2 className="font-semibold text-slate-900">质量与发布</h2>
      <p className="mt-1 text-sm text-slate-600">
        质量门禁状态与发布证据：同步批次质量门、Flow 活跃发布版本（产物哈希可溯源、可回滚）。
      </p>
    </div>

    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}
    {loading && <div className="flex items-center gap-2 py-10 text-sm text-slate-500"><Loader2 className="size-4 animate-spin" />正在加载…</div>}

    {!loading && overview && (
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" data-testid="sync-quality">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
          <ShieldCheck className="size-4 text-slate-500" />
          <h3 className="font-semibold text-slate-900">同步质量门</h3>
        </div>
        {overview.sources.length === 0
          ? <p className="px-4 py-8 text-center text-sm text-slate-500">暂无数据源</p>
          : <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr><th className="px-4 py-3 font-medium">数据源</th><th className="px-4 py-3 font-medium">最近批次质量</th><th className="px-4 py-3 font-medium">端到端延迟</th><th className="px-4 py-3 font-medium">最近成功</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {overview.sources.map((source) => <tr key={source.sourceId}>
                <td className="px-4 py-3">{source.hospitalName}<span className="ml-2 text-xs text-slate-500">{source.sourceId}</span></td>
                <td className="px-4 py-3">
                  {source.qualityStatus === 'accepted'
                    ? <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">通过</span>
                    : source.qualityStatus === 'blocked'
                      ? <span className="rounded bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">已阻断</span>
                      : <span className="text-xs text-slate-400">暂无</span>}
                </td>
                <td className="px-4 py-3 font-mono text-xs">{source.latestLatencySeconds === null ? '—' : `${Math.round(source.latestLatencySeconds)} 秒`}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{formatTime(source.lastSucceededAt)}</td>
              </tr>)}
            </tbody>
          </table>}
      </section>
    )}

    {!loading && overview && (
      <SourceComparePanel sourceId={overview.sources[0]?.sourceId ?? ''} />
    )}

    {!loading && (
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" data-testid="flow-releases">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
          <ShieldCheck className="size-4 text-slate-500" />
          <h3 className="font-semibold text-slate-900">Flow 发布证据</h3>
        </div>
        {releases.length === 0
          ? <p className="px-4 py-8 text-center text-sm text-slate-500">
            暂无已发布 Flow；到<Link href="/data-governance/flows" className="mx-1 text-blue-600 hover:underline">数据加工</Link>创建并发布。
          </p>
          : <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr><th className="px-4 py-3 font-medium">Flow</th><th className="px-4 py-3 font-medium">活跃版本</th><th className="px-4 py-3 font-medium">产物哈希</th><th className="px-4 py-3 font-medium">发布人</th><th className="px-4 py-3 font-medium">发布时间</th><th className="px-4 py-3 font-medium">修订数</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {releases.map(({ flow, active, revisionCount }) => <tr key={flow.flow_id} data-testid={`release-${flow.flow_id}`}>
                <td className="px-4 py-3">
                  <Link href={`/data-governance/flows/${encodeURIComponent(flow.flow_id)}`} className="font-medium text-blue-700 hover:underline">
                    {flow.name}
                  </Link>
                  <p className="mt-0.5 font-mono text-xs text-slate-500">{flow.flow_id}</p>
                </td>
                <td className="px-4 py-3 font-mono text-xs">{active?.revision.revision_id ?? '—'}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{active ? `${active.revision.artifact_hash.slice(0, 12)}…` : '—'}</td>
                <td className="px-4 py-3 text-xs">{active?.revision.published_by ?? '—'}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{formatTime(active?.revision.published_at)}</td>
                <td className="px-4 py-3 text-xs">{revisionCount}</td>
              </tr>)}
            </tbody>
          </table>}
      </section>
    )}
  
      <NextStepCard href="C:/Program Files/Git/data-governance/assets" title="在数据目录查看资产与血缘"
        description="资产是治理的最终产物" />
</div>
}
