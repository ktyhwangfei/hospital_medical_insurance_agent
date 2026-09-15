import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import OpsAnswerBlock from '@/components/policy-qa/ops-answer-block'
import type { PolicyQADataQueryResult } from '@/lib/policy-qa-session'

afterEach(() => cleanup())

const baseResult: PolicyQADataQueryResult = {
  metricId: 'outpatient.avg_fee',
  metricName: '门诊次均费用',
  summary: '本月门诊次均费用 512.40 元，环比 +3.2%。',
  caliber: '结算清单/人次',
  table: {
    columns: [
      { key: 'month', title: '月份' },
      { key: 'avgFee', title: '次均费用' },
      { key: 'visits', title: '门诊人次' },
    ],
    rows: [
      { month: '7月', avgFee: '496.40', visits: 2310 },
      { month: '8月', avgFee: '512.40', visits: 2548 },
    ],
  },
  chart: {
    type: 'bar',
    xAxis: ['7月', '8月'],
    series: [{ name: '次均费用', data: [496.4, 512.4] }],
  },
}

describe('OpsAnswerBlock（表格 + 图表富块）', () => {
  it('表格与图表同时呈现（设计 §4.3：结果必出表格和图表）', () => {
    render(<OpsAnswerBlock result={baseResult} />)

    expect(screen.getByTestId('ops-answer-block')).toBeInTheDocument()
    expect(screen.getByTestId('ops-table-and-chart')).toBeInTheDocument()
    // 数据表格
    expect(screen.getByText('月份')).toBeInTheDocument()
    expect(screen.getByText('512.40')).toBeInTheDocument()
    // 图表富块
    expect(screen.getByTestId('ops-chart-block')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '柱状图：次均费用' })).toBeInTheDocument()
  })

  it('口径并入富块头部', () => {
    render(<OpsAnswerBlock result={baseResult} />)
    expect(screen.getByText('口径：结算清单/人次')).toBeInTheDocument()
  })

  it('line 图表渲染 SVG 折线', () => {
    render(
      <OpsAnswerBlock
        result={{
          ...baseResult,
          chart: {
            type: 'line',
            xAxis: ['7月', '8月', '9月'],
            series: [{ name: '住院人次', data: [120, 135, 128] }],
          },
        }}
      />,
    )
    expect(screen.getByRole('img', { name: '折线图：住院人次' })).toBeInTheDocument()
    expect(document.querySelector('svg polyline')).not.toBeNull()
  })

  it('pie 图表渲染占比图例', () => {
    render(
      <OpsAnswerBlock
        result={{
          ...baseResult,
          chart: {
            type: 'pie',
            series: [{ name: '费用构成', data: [60, 40] }],
          },
        }}
      />,
    )
    expect(screen.getByRole('img', { name: '饼图：费用构成' })).toBeInTheDocument()
    expect(screen.getByText('60.0%')).toBeInTheDocument()
    expect(screen.getByText('40.0%')).toBeInTheDocument()
  })

  it('chart.type=table 时只渲染表格，不出图表块', () => {
    render(
      <OpsAnswerBlock
        result={{ ...baseResult, chart: { type: 'table', series: [{ name: 'x', data: [1] }] } }}
      />,
    )
    expect(screen.getByText('月份')).toBeInTheDocument()
    expect(screen.queryByTestId('ops-chart-block')).not.toBeInTheDocument()
  })

  it('无 chart 字段时不渲染图表块', () => {
    const { chart, ...withoutChart } = baseResult
    void chart
    render(<OpsAnswerBlock result={withoutChart} />)
    expect(screen.getByTestId('ops-answer-block')).toBeInTheDocument()
    expect(screen.queryByTestId('ops-chart-block')).not.toBeInTheDocument()
  })
})
