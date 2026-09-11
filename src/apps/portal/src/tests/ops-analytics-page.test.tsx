// 门诊运营分析 /ops-analytics 页测试 — #40（六指标卡状态 / 科室维度 unavailable /
// 下钻行批次溯源 / 周报结论引用与 AI 摘要降级）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/ops-analytics',
}))

vi.mock('@/lib/ops-analytics-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/ops-analytics-api')>()
  return {
    ...actual,
    getOpsOverview: vi.fn(),
    getOpsTrend: vi.fn(),
    getOpsBreakdown: vi.fn(),
    getOpsDrill: vi.fn(),
    getOpsWeeklyReport: vi.fn(),
  }
})

import OpsAnalyticsPage from '../../app/ops-analytics/page'
import {
  getOpsBreakdown,
  getOpsDrill,
  getOpsOverview,
  getOpsTrend,
  getOpsWeeklyReport,
  type OpsOverviewDto,
} from '@/lib/ops-analytics-api'

const overview: OpsOverviewDto = {
  result_status: 'complete',
  halt_reason: null,
  generated_at: '2026-09-10T08:00:00',
  date_min: '2024-03-11T09:28:38',
  date_max: '2026-04-17T10:41:45',
  row_count: 12,
  semantic_version: null,
  data_batch_ids: ['batch_2026_04_17'],
  cards: [
    { metric_code: 'mzjyxx.op_valid_settle_count', name: '有效结算笔数', unit: '笔', precision: 0, result_status: 'complete', value: 12, halt_reason: null, halt_detail: null },
    { metric_code: 'mzjyxx.op_total_fee', name: '总费用', unit: '元', precision: 2, result_status: 'complete', value: 6643.69, halt_reason: null, halt_detail: null },
    { metric_code: 'mzjyxx.op_fund_pay', name: '统筹基金支付', unit: '元', precision: 2, result_status: 'complete', value: 113.66, halt_reason: null, halt_detail: null },
    { metric_code: 'mzjyxx.op_self_pay', name: '个人支付', unit: '元', precision: 2, result_status: 'complete', value: 6530.03, halt_reason: null, halt_detail: null },
    { metric_code: 'mzjyxx.insured_encounter_count', name: '门诊医保就诊人次', unit: '人次', precision: 0, result_status: 'unavailable', value: null, halt_reason: 'data_unavailable', halt_detail: '门诊医保就诊人次需 HIS 就诊关联（P1 必需输入），当前数据供给未接入' },
    { metric_code: 'mzjyxx.average_fee', name: '次均费用', unit: '元', precision: 2, result_status: 'unavailable', value: null, halt_reason: 'data_unavailable', halt_detail: '次均费用=总费用/就诊人次，人次口径未接入前不可计算' },
  ],
}

beforeEach(() => {
  vi.mocked(getOpsOverview).mockResolvedValue(overview)
  vi.mocked(getOpsTrend).mockResolvedValue({
    points: [
      { month: '2026-03', valid_count: 5, total_fee: 2000, fund_pay: 50, self_pay: 1950 },
      { month: '2026-04', valid_count: 12, total_fee: 6643.69, fund_pay: 113.66, self_pay: 6530.03 },
    ],
  })
  vi.mocked(getOpsBreakdown).mockResolvedValue({
    dimension: 'fund_type',
    dimension_name: '险种',
    result_status: 'complete',
    halt_reason: null,
    halt_detail: null,
    data_batch_ids: ['batch_2026_04_17'],
    items: [
      { code: '3', label: '城镇职工', valid_count: 8, total_fee: 4000, fund_pay: 80, self_pay: 3920, share: 0.6667 },
      { code: '32', label: '公疗医照', valid_count: 4, total_fee: 2643.69, fund_pay: 33.66, self_pay: 2610.03, share: 0.3333 },
    ],
  })
  vi.mocked(getOpsDrill).mockResolvedValue({
    result_status: 'complete',
    halt_reason: null,
    total: 2,
    limit: 20,
    offset: 0,
    data_batch_ids: ['batch_2026_04_17'],
    rows: [
      { trade_no: 'JY001', trade_date: '2026-04-17T10:00:00', fund_type: '城镇职工', cure_type: '普通门诊', settle_state: '有效结算（中心端完成）', total_fee: 100.5, fund_pay: 10.25, self_pay: 90.25, data_batch_id: 'batch_2026_04_17' },
      { trade_no: 'JY002', trade_date: '2026-04-16T09:00:00', fund_type: '公疗医照', cure_type: '普通急诊', settle_state: '有效结算（同步）', total_fee: 200, fund_pay: 20, self_pay: 180, data_batch_id: 'batch_2026_04_17' },
    ],
  })
  vi.mocked(getOpsWeeklyReport).mockResolvedValue({
    week_start: '2026-04-13',
    result_status: 'complete',
    halt_reason: null,
    current_week_rows: 12,
    previous_week_rows: 10,
    deltas: [
      { metric_code: 'mzjyxx.op_valid_settle_count', name: '有效结算笔数', unit: '笔', precision: 0, current: 12, previous: 10, delta: 2, pct: 20, direction: 'up' },
    ],
    conclusions: [
      {
        text: '有效结算笔数：本周 12笔，上周 10笔，环比 +20.0%',
        citations: [
          { type: 'metric_definition', metric_code: 'mzjyxx.op_valid_settle_count' },
          { type: 'metric_batch', data_batch_id: 'batch_w1' },
          { type: 'metric_batch', data_batch_id: 'batch_w2' },
        ],
      },
    ],
    summary: null,
    uncertainties: ['模型网关未配置，本周未生成 AI 运营摘要'],
    data_batch_ids: ['batch_w1', 'batch_w2'],
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('OpsAnalyticsPage', () => {
  it('渲染六指标卡：四卡显值、人次/次均显 unavailable 与原因', async () => {
    render(<OpsAnalyticsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('ops-analytics-overview')).toBeTruthy()
    })
    expect(screen.getByTestId('metric-card-mzjyxx.op_total_fee').textContent).toContain('6,643.69')
    const encounter = screen.getByTestId('metric-card-mzjyxx.insured_encounter_count')
    expect(encounter.textContent).toContain('暂不可用')
    expect(encounter.textContent).toContain('data_unavailable')
    expect(encounter.textContent).toContain('HIS')
    expect(screen.getByTestId('metric-card-mzjyxx.average_fee').textContent).toContain('暂不可用')
    // 页头携带指标批次
    expect(screen.getByTestId('ops-analytics-page').textContent).toContain('batch_2026_04_17')
  })

  it('险种拆分展示中文标签与占比，科室维度切到 unavailable 提示', async () => {
    render(<OpsAnalyticsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('ops-analytics-breakdown')).toBeTruthy()
    })
    const breakdown = screen.getByTestId('ops-analytics-breakdown')
    expect(breakdown.textContent).toContain('城镇职工')
    expect(breakdown.textContent).toContain('公疗医照')
    expect(breakdown.textContent).toContain('66.7%')

    vi.mocked(getOpsBreakdown).mockResolvedValue({
      dimension: 'department',
      dimension_name: '科室',
      result_status: 'unavailable',
      halt_reason: 'data_unavailable',
      halt_detail: 'mz_trade 无科室列，科室维度需 HIS 关联（P1 必需输入）后开放',
      data_batch_ids: [],
      items: [],
    })
    fireEvent.click(screen.getByRole('button', { name: '科室' }))
    await waitFor(() => {
      expect(screen.getByTestId('ops-breakdown-unavailable')).toBeTruthy()
    })
    expect(screen.getByTestId('ops-breakdown-unavailable').textContent).toContain('无科室列')
  })

  it('就诊明细行携带批次溯源', async () => {
    render(<OpsAnalyticsPage />)
    await waitFor(() => {
      expect(screen.getByText('JY001')).toBeTruthy()
    })
    const drill = screen.getByTestId('ops-analytics-drill')
    expect(drill.textContent).toContain('JY002')
    expect(drill.textContent).toContain('batch_2026_04_17')
    expect(drill.textContent).toContain('普通急诊')
  })

  it('周报渲染环比、结论引用批次与 AI 摘要降级说明', async () => {
    render(<OpsAnalyticsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('ops-analytics-weekly')).toBeTruthy()
    })
    const weekly = screen.getByTestId('ops-analytics-weekly')
    expect(weekly.textContent).toContain('+20%')
    expect(weekly.textContent).toContain('批次 batch_w1')
    expect(weekly.textContent).toContain('批次 batch_w2')
    expect(weekly.textContent).toContain('口径 mzjyxx.op_valid_settle_count')
    // 模型未配置：无摘要区块，但声明不确定性（诚实降级）
    expect(screen.queryByTestId('ops-weekly-summary')).toBeNull()
    expect(weekly.textContent).toContain('模型网关未配置')
  })
})
