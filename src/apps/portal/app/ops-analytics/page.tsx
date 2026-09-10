'use client'

// 门诊运营分析 /ops-analytics 页 — #40 P3 受控问数与运营指导。
// 六指标卡（人次/次均诚实 unavailable）+ 月度趋势 + 维度拆分（科室 unavailable）
// + 就诊行级下钻（data_batch_id 溯源）+ 周报（环比/结论引用/AI 摘要可降级）。
import { useCallback, useEffect, useState } from 'react'
import { BarChart3, ChevronLeft, ChevronRight, Loader2, RefreshCw } from 'lucide-react'
import {
  getOpsBreakdown,
  getOpsDrill,
  getOpsOverview,
  getOpsTrend,
  getOpsWeeklyReport,
  type OpsAnalyticsDimension,
  type OpsDimensionBreakdownDto,
  type OpsDrillResultDto,
  type OpsOverviewDto,
  type OpsTrendPointDto,
  type OpsWeeklyReportDto,
} from '@/lib/ops-analytics-api'

const DIMENSION_TABS: Array<{ key: OpsAnalyticsDimension; label: string }> = [
  { key: 'fund_type', label: '险种' },
  { key: 'cure_type', label: '门诊业务类别' },
  { key: 'settle_state', label: '结算状态' },
  { key: 'department', label: '科室' },
]

const CARD_ACCENT: Record<string, string> = {
  'mzjyxx.op_valid_settle_count': 'bg-sky-50 text-sky-900 border-sky-200',
  'mzjyxx.op_total_fee': 'bg-violet-50 text-violet-900 border-violet-200',
  'mzjyxx.op_fund_pay': 'bg-emerald-50 text-emerald-900 border-emerald-200',
  'mzjyxx.op_self_pay': 'bg-amber-50 text-amber-900 border-amber-200',
  'mzjyxx.insured_encounter_count': 'bg-slate-50 text-slate-500 border-slate-200',
  'mzjyxx.average_fee': 'bg-slate-50 text-slate-500 border-slate-200',
}

function formatValue(value: number | null, precision: number): string {
  if (value === null) return '—'
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  })
}

function MetricCard({ card }: { card: OpsOverviewDto['cards'][number] }) {
  const accent = CARD_ACCENT[card.metric_code] ?? 'bg-slate-50 text-slate-900 border-slate-200'
  return (
    <div className={`rounded-lg border p-3 ${accent}`} data-testid={`metric-card-${card.metric_code}`}>
      <div className="text-xs opacity-70">{card.name}</div>
      {card.result_status === 'complete' ? (
        <div className="mt-1 font-mono text-xl font-semibold">
          {formatValue(card.value, card.precision)}
          <span className="ml-1 text-xs font-normal opacity-70">{card.unit}</span>
        </div>
      ) : (
        <div className="mt-1 space-y-1">
          <div className="text-sm font-semibold">
            暂不可用
            <span className="ml-2 rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px]">
              {card.halt_reason}
            </span>
          </div>
          <div className="text-[11px] leading-snug opacity-80">{card.halt_detail}</div>
        </div>
      )}
    </div>
  )
}

function TrendBars({ points }: { points: OpsTrendPointDto[] }) {
  const max = Math.max(...points.map((p) => p.total_fee), 1)
  return (
    <div className="space-y-1.5" data-testid="ops-trend">
      {points.map((p) => (
        <div key={p.month} className="flex items-center gap-2 text-xs">
          <span className="w-14 shrink-0 font-mono text-slate-500">{p.month}</span>
          <div className="h-3.5 flex-1 overflow-hidden rounded bg-slate-100">
            <div
              className="h-full rounded bg-violet-400"
              style={{ width: `${Math.max((p.total_fee / max) * 100, 1)}%` }}
            />
          </div>
          <span className="w-20 shrink-0 text-right font-mono">
            {formatValue(p.total_fee, 0)} 元
          </span>
          <span className="w-16 shrink-0 text-right font-mono text-slate-500">
            {p.valid_count} 笔
          </span>
        </div>
      ))}
    </div>
  )
}

export default function OpsAnalyticsPage() {
  const [overview, setOverview] = useState<OpsOverviewDto | null>(null)
  const [trend, setTrend] = useState<OpsTrendPointDto[]>([])
  const [breakdown, setBreakdown] = useState<OpsDimensionBreakdownDto | null>(null)
  const [dimension, setDimension] = useState<OpsAnalyticsDimension>('fund_type')
  const [drill, setDrill] = useState<OpsDrillResultDto | null>(null)
  const [drillOffset, setDrillOffset] = useState(0)
  const [weekly, setWeekly] = useState<OpsWeeklyReportDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [ov, tr] = await Promise.all([getOpsOverview(), getOpsTrend(12)])
      setOverview(ov)
      setTrend(tr.points)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  useEffect(() => {
    getOpsBreakdown(dimension)
      .then(setBreakdown)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [dimension])

  useEffect(() => {
    getOpsDrill({ limit: 20, offset: drillOffset })
      .then(setDrill)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [drillOffset])

  useEffect(() => {
    getOpsWeeklyReport()
      .then(setWeekly)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const drillPage = drill ? Math.floor(drill.offset / drill.limit) + 1 : 1
  const drillPages = drill ? Math.max(1, Math.ceil(drill.total / drill.limit)) : 1

  return (
    <div className="mx-auto max-w-5xl space-y-5" data-testid="ops-analytics-page">
      <header className="flex flex-wrap items-center gap-3">
        <span className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-slate-900 px-2.5 py-2 text-white">
          <BarChart3 className="size-4" />
          门诊运营分析
        </span>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold">受控问数与运营指导（P3）</h1>
          <p className="text-xs text-slate-500">
            六指标 × 五维度 · 口径句 v4 · 结论可溯源到指标批次
            {overview?.data_batch_ids?.length
              ? ` · 批次 ${overview.data_batch_ids.join(', ')}`
              : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={reload}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs hover:bg-slate-50"
          data-testid="ops-analytics-refresh"
        >
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          刷新
        </button>
      </header>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700" data-testid="ops-analytics-error">
          {error}
        </div>
      )}

      {overview && (
        <section className="space-y-2" data-testid="ops-analytics-overview">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">指标总览</h2>
            <span className="text-[11px] text-slate-500">
              数据范围 {overview.date_min?.slice(0, 10) ?? '—'} ~ {overview.date_max?.slice(0, 10) ?? '—'}
              {' '}· {overview.row_count} 行
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
            {overview.cards.map((card) => (
              <MetricCard key={card.metric_code} card={card} />
            ))}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">月度趋势（总费用）</h2>
        {trend.length > 0 ? (
          <TrendBars points={trend} />
        ) : (
          <p className="text-xs text-slate-500">暂无趋势数据</p>
        )}
      </section>

      <section className="space-y-2" data-testid="ops-analytics-breakdown">
        <div className="flex flex-wrap items-center gap-1.5">
          <h2 className="mr-1 text-sm font-semibold">维度拆分</h2>
          {DIMENSION_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setDimension(tab.key)}
              className={`rounded-md border px-2 py-1 text-xs ${
                dimension === tab.key
                  ? 'border-slate-900 bg-slate-900 text-white'
                  : 'border-slate-200 hover:bg-slate-50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {breakdown && breakdown.result_status === 'unavailable' ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800" data-testid="ops-breakdown-unavailable">
            <div className="font-semibold">
              {breakdown.dimension_name}维度暂不可用
              <span className="ml-2 rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px]">
                {breakdown.halt_reason}
              </span>
            </div>
            <div className="mt-1 leading-snug">{breakdown.halt_detail}</div>
          </div>
        ) : breakdown && breakdown.items.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-1.5 pr-2 font-medium">{breakdown.dimension_name}</th>
                <th className="py-1.5 pr-2 text-right font-medium">有效结算（笔）</th>
                <th className="py-1.5 pr-2 text-right font-medium">总费用（元）</th>
                <th className="py-1.5 pr-2 text-right font-medium">统筹支付（元）</th>
                <th className="py-1.5 pr-2 text-right font-medium">个人支付（元）</th>
                <th className="py-1.5 text-right font-medium">占比</th>
              </tr>
            </thead>
            <tbody>
              {breakdown.items.map((item) => (
                <tr key={item.code} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2">{item.label}</td>
                  <td className="py-1.5 pr-2 text-right font-mono">{item.valid_count}</td>
                  <td className="py-1.5 pr-2 text-right font-mono">{formatValue(item.total_fee, 2)}</td>
                  <td className="py-1.5 pr-2 text-right font-mono">{formatValue(item.fund_pay, 2)}</td>
                  <td className="py-1.5 pr-2 text-right font-mono">{formatValue(item.self_pay, 2)}</td>
                  <td className="py-1.5 text-right font-mono">{(item.share * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-slate-500">该维度暂无数据</p>
        )}
      </section>

      <section className="space-y-2" data-testid="ops-analytics-drill">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">就诊明细下钻</h2>
          {drill && (
            <span className="text-[11px] text-slate-500">
              共 {drill.total} 笔 · 批次 {drill.data_batch_ids.join(', ') || '—'}
            </span>
          )}
        </div>
        {drill && drill.rows.length > 0 ? (
          <>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="py-1.5 pr-2 font-medium">结算单号</th>
                  <th className="py-1.5 pr-2 font-medium">交易日期</th>
                  <th className="py-1.5 pr-2 font-medium">险种</th>
                  <th className="py-1.5 pr-2 font-medium">业务类别</th>
                  <th className="py-1.5 pr-2 font-medium">状态</th>
                  <th className="py-1.5 pr-2 text-right font-medium">总费用</th>
                  <th className="py-1.5 pr-2 text-right font-medium">统筹支付</th>
                  <th className="py-1.5 text-right font-medium">批次</th>
                </tr>
              </thead>
              <tbody>
                {drill.rows.map((row) => (
                  <tr key={row.trade_no} className="border-b border-slate-100">
                    <td className="py-1.5 pr-2 font-mono">{row.trade_no}</td>
                    <td className="py-1.5 pr-2 font-mono">{row.trade_date?.slice(0, 16).replace('T', ' ') ?? '—'}</td>
                    <td className="py-1.5 pr-2">{row.fund_type ?? '—'}</td>
                    <td className="py-1.5 pr-2">{row.cure_type ?? '—'}</td>
                    <td className="py-1.5 pr-2">{row.settle_state ?? '—'}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatValue(row.total_fee, 2)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{formatValue(row.fund_pay, 2)}</td>
                    <td className="py-1.5 text-right font-mono text-[10px] text-slate-500">
                      {row.data_batch_id ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                disabled={drillPage <= 1}
                onClick={() => setDrillOffset(Math.max(0, drillOffset - drill!.limit))}
                className="rounded-md border border-slate-200 px-2 py-1 disabled:opacity-40"
              >
                <ChevronLeft className="size-3.5" />
              </button>
              <span className="font-mono">
                {drillPage} / {drillPages}
              </span>
              <button
                type="button"
                disabled={drillPage >= drillPages}
                onClick={() => setDrillOffset(drillOffset + drill!.limit)}
                className="rounded-md border border-slate-200 px-2 py-1 disabled:opacity-40"
              >
                <ChevronRight className="size-3.5" />
              </button>
            </div>
          </>
        ) : (
          <p className="text-xs text-slate-500">
            {drill?.halt_reason === 'data_unavailable' ? '当前过滤条件下无就诊记录' : '暂无数据'}
          </p>
        )}
      </section>

      {weekly && (
        <section className="space-y-2" data-testid="ops-analytics-weekly">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">运营周报（{weekly.week_start} 起）</h2>
            <span className="text-[11px] text-slate-500">
              本周 {weekly.current_week_rows} 行 · 上周 {weekly.previous_week_rows} 行
            </span>
          </div>
          {weekly.result_status === 'partial' && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
              本周无有效数据（{weekly.halt_reason}）
            </div>
          )}
          {weekly.summary && (
            <div
              className="rounded-md border border-sky-200 bg-sky-50 p-3 text-xs leading-relaxed text-sky-900"
              data-testid="ops-weekly-summary"
            >
              <div className="mb-1 font-semibold">AI 运营摘要</div>
              {weekly.summary}
            </div>
          )}
          {weekly.uncertainties.length > 0 && (
            <ul className="list-inside list-disc text-[11px] text-slate-500">
              {weekly.uncertainties.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          )}
          {weekly.deltas.length > 0 && (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="py-1.5 pr-2 font-medium">指标</th>
                  <th className="py-1.5 pr-2 text-right font-medium">本周</th>
                  <th className="py-1.5 pr-2 text-right font-medium">上周</th>
                  <th className="py-1.5 pr-2 text-right font-medium">环比</th>
                </tr>
              </thead>
              <tbody>
                {weekly.deltas.map((d) => (
                  <tr key={d.metric_code} className="border-b border-slate-100">
                    <td className="py-1.5 pr-2">{d.name}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {formatValue(d.current, d.precision)} {d.unit}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {formatValue(d.previous, d.precision)} {d.unit}
                    </td>
                    <td
                      className={`py-1.5 text-right font-mono ${
                        d.direction === 'up' ? 'text-red-600' : d.direction === 'down' ? 'text-emerald-600' : ''
                      }`}
                    >
                      {d.pct !== null ? `${d.pct > 0 ? '+' : ''}${d.pct}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {weekly.conclusions.length > 0 && (
            <div className="space-y-1.5">
              {weekly.conclusions.map((c) => (
                <div key={c.text} className="rounded-md border border-slate-200 bg-white p-2 text-xs">
                  <div>{c.text}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {c.citations.map((ref, i) => (
                      <span
                        key={`${ref.type}-${i}`}
                        className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600"
                      >
                        {ref.type === 'metric_batch'
                          ? `批次 ${ref.data_batch_id}`
                          : `口径 ${ref.metric_code}`}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
