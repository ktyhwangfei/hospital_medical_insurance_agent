'use client'

import { Table2 } from 'lucide-react'

import type { PolicyQADataQueryResult } from '@/lib/policy-qa-session'

/**
 * V4.0 运营问数智能体：答案富块（表格 + 图表同时呈现）。
 *
 * 设计 §4.3："结果肯定得有表格类和图表类的"——数据表格与图表两个富块
 * 并列展示；口径/时间范围并入富块头部。图表纯 CSS/SVG 渲染（克制动效，
 * 不引入图表库），金额与指标值一律等宽字体 tabular-nums（§6.1）。
 */

/** 单色深浅阶（accent 阶梯，禁彩虹渐变，§6.2）；结算构成分段条共用。 */
export const SERIES_COLORS = [
  'oklch(0.55 0.09 195)',
  'oklch(0.68 0.07 195)',
  'oklch(0.80 0.05 195)',
  'oklch(0.45 0.08 165)',
  'oklch(0.62 0.09 85)',
]

interface OpsAnswerBlockProps {
  result: PolicyQADataQueryResult
}

function toNumber(value: number | string): number {
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function formatValue(value: number | string): string {
  return typeof value === 'number'
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : value
}

/** 柱状图：垂直分列，高度按最大值归一。 */
function BarChart({
  xAxis,
  series,
}: {
  xAxis?: string[]
  series: Array<{ name: string; data: (number | string)[] }>
}) {
  const first = series[0]
  const max = Math.max(...first.data.map(toNumber), 1)
  return (
    <div className="flex items-end justify-between gap-2 pt-4" role="img" aria-label={`柱状图：${first.name}`}>
      {first.data.map((value, index) => {
        const height = Math.max((toNumber(value) / max) * 100, 2)
        return (
          <div key={index} className="flex min-w-0 flex-1 flex-col items-center gap-1">
            <span className="tabular-amounts text-[10px] text-slate-500">{formatValue(value)}</span>
            <div
              className="w-full max-w-10 rounded-t-sm"
              style={{ height: `${height}px`, backgroundColor: SERIES_COLORS[0] }}
            />
            <span className="w-full truncate text-center text-[10px] text-slate-500">
              {xAxis?.[index] ?? ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** 折线图：内联 SVG polyline，0-100 归一化坐标。 */
function LineChart({
  xAxis,
  series,
}: {
  xAxis?: string[]
  series: Array<{ name: string; data: (number | string)[] }>
}) {
  const first = series[0]
  const values = first.data.map(toNumber)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const points = values
    .map((value, index) => {
      const x = values.length > 1 ? (index / (values.length - 1)) * 100 : 50
      const y = 40 - ((value - min) / span) * 36
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
  return (
    <div role="img" aria-label={`折线图：${first.name}`}>
      <svg
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        className="h-32 w-full"
        aria-hidden="true"
      >
        <polyline
          points={points}
          fill="none"
          stroke={SERIES_COLORS[0]}
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {xAxis && xAxis.length > 0 ? (
        <div className="flex justify-between text-[10px] text-slate-500">
          {xAxis.map((label, index) => (
            <span key={index} className="min-w-0 truncate">
              {label}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** 饼图：conic-gradient 圆环 + 图例。 */
function PieChart({ series }: { series: Array<{ name: string; data: (number | string)[] }> }) {
  const first = series[0]
  const values = first.data.map(toNumber)
  const total = values.reduce((sum, value) => sum + value, 0) || 1
  let cursor = 0
  const stops = values
    .map((value, index) => {
      const start = (cursor / total) * 360
      cursor += value
      const end = (cursor / total) * 360
      return `${SERIES_COLORS[index % SERIES_COLORS.length]} ${start}deg ${end}deg`
    })
    .join(', ')
  return (
    <div className="flex items-center gap-5" role="img" aria-label={`饼图：${first.name}`}>
      <div
        className="size-28 shrink-0 rounded-full"
        style={{ background: `conic-gradient(${stops})` }}
      />
      <ul className="min-w-0 space-y-1.5 text-xs text-slate-600">
        {first.data.map((value, index) => (
          <li key={index} className="flex items-center gap-2">
            <span
              className="size-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length] }}
            />
            <span className="truncate">{first.data.length === 1 ? first.name : `分项 ${index + 1}`}</span>
            <span className="tabular-amounts ml-auto text-slate-500">
              {((toNumber(value) / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChartBlock({ chart }: { chart: NonNullable<PolicyQADataQueryResult['chart']> }) {
  if (chart.type === 'table' || chart.series.length === 0) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4" data-testid="ops-chart-block">
      <p className="mb-1 text-xs font-medium text-slate-500">
        图表（{chart.type === 'bar' ? '柱状' : chart.type === 'line' ? '趋势' : '占比'}）
      </p>
      {chart.type === 'bar' ? <BarChart xAxis={chart.xAxis} series={chart.series} /> : null}
      {chart.type === 'line' ? <LineChart xAxis={chart.xAxis} series={chart.series} /> : null}
      {chart.type === 'pie' ? <PieChart series={chart.series} /> : null}
    </div>
  )
}

export default function OpsAnswerBlock({ result }: OpsAnswerBlockProps) {
  return (
    <div
      data-testid="ops-answer-block"
      className="space-y-3 rounded-xl border border-blue-100 bg-blue-50/50 p-4"
    >
      {/* 头部：指标名 + 口径（§4.3 口径/时间范围并入富块头部） */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-blue-900">
          <Table2 className="size-4" aria-hidden />
          {result.metricName}
        </div>
        {result.caliber ? (
          <p className="text-xs text-slate-500">口径：{result.caliber}</p>
        ) : null}
      </div>
      {result.summary ? <p className="text-sm text-slate-700">{result.summary}</p> : null}

      <div className="grid gap-3" data-testid="ops-table-and-chart">
        {result.table ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  {result.table.columns.map((col) => (
                    <th key={col.key} className="px-3 py-2 font-medium">
                      {col.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.table.rows.map((row, i) => (
                  <tr key={i}>
                    {result.table!.columns.map((col) => (
                      <td key={col.key} className="tabular-amounts px-3 py-2 text-slate-700">
                        {row[col.key] ?? '-'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {result.chart ? <ChartBlock chart={result.chart} /> : null}
      </div>
    </div>
  )
}
