// 治理 Flow 列表页测试 — Phase 2（新建骨架走最小结构模板）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

const push = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/flow',
}))

vi.mock('@/lib/flow-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/flow-api')>()
  return {
    ...actual,
    listFlows: vi.fn(),
    createFlow: vi.fn(),
    deleteFlow: vi.fn(),
  }
})

import FlowListPage from '../../app/flow/page'
import { createFlow, listFlows } from '@/lib/flow-api'
import type { FlowDefinitionDto } from '@/lib/flow-api'

function flow(overrides: Partial<FlowDefinitionDto> = {}): FlowDefinitionDto {
  return {
    flow_id: 'flow_op_outpatient_processed',
    name: '门诊有效结算加工视图',
    owner: 'data_governance',
    status: 'draft',
    nodes: [
      { node_type: 'source', node_id: 'src_1', name: '源', dataset_code: 'mz_trade', object_code: 'mzjyxx', fields: ['T_TradeNo'] },
      { node_type: 'aggregate', node_id: 'agg_1', name: '聚合', group_by: [], measures: [{ output_code: 'op_row_count', source_field: 'T_TradeNo', operator: 'count' }] },
      { node_type: 'consumer', node_id: 'c_1', name: '问数', consumer_kind: 'query_planner', consumes: ['op_row_count'] },
    ],
    edges: [{ edge_id: 'e1', from_node: 'src_1', to_node: 'agg_1' }],
    source_contracts: [{ dataset_code: 'mz_trade', object_code: 'mzjyxx', fields: ['T_TradeNo'] }],
    metric_outputs: [{ metric_code: 'op_row_count', name: '行数', node_id: 'agg_1', policy_definition: '口径句' }],
    revision: 1,
    ...overrides,
  }
}

describe('FlowListPage 列表页', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('渲染 Flow 清单与状态徽标', async () => {
    vi.mocked(listFlows).mockResolvedValue([
      flow(),
      flow({ flow_id: 'flow_published', name: '已发布流', status: 'published', revision: 4 }),
    ])
    render(<FlowListPage />)
    await waitFor(() => expect(screen.getByTestId('flow-list').children).toHaveLength(2))
    expect(screen.getByText('草稿')).toBeTruthy()
    expect(screen.getByText('已发布')).toBeTruthy()
  })

  it('空清单展示新建引导', async () => {
    vi.mocked(listFlows).mockResolvedValue([])
    render(<FlowListPage />)
    await waitFor(() => expect(screen.getByText(/尚无治理 Flow/)).toBeTruthy())
  })

  it('新建对话框生成最小结构骨架并跳转画布', async () => {
    vi.mocked(listFlows).mockResolvedValue([])
    vi.mocked(createFlow).mockResolvedValue(flow())
    render(<FlowListPage />)
    await waitFor(() => screen.getByTestId('flow-list-page'))

    fireEvent.click(screen.getByRole('button', { name: /新建 Flow/ }))
    const dialog = await screen.findByTestId('flow-create-dialog')

    const inputs = dialog.querySelectorAll('input')
    fireEvent.change(inputs[0], { target: { value: 'flow_op_outpatient_processed' } })
    fireEvent.change(inputs[3], { target: { value: 'mz_trade' } })
    fireEvent.change(inputs[4], { target: { value: 'mzjyxx' } })
    fireEvent.change(inputs[5], { target: { value: 'T_TradeNo' } })
    fireEvent.click(screen.getByRole('button', { name: '创建并进入画布' }))

    await waitFor(() => expect(createFlow).toHaveBeenCalledTimes(1))
    const definition = vi.mocked(createFlow).mock.calls[0][0]
    expect(definition.nodes.map((n) => n.node_type)).toEqual(['source', 'aggregate', 'consumer'])
    expect(definition.source_contracts[0]).toEqual({
      dataset_code: 'mz_trade', object_code: 'mzjyxx', fields: ['T_TradeNo'],
    })
    expect(push).toHaveBeenCalledWith('/flow/flow_op_outpatient_processed')
  })

  it('必填缺失时不发请求并提示', async () => {
    vi.mocked(listFlows).mockResolvedValue([])
    render(<FlowListPage />)
    await waitFor(() => screen.getByTestId('flow-list-page'))

    fireEvent.click(screen.getByRole('button', { name: /新建 Flow/ }))
    fireEvent.click(await screen.findByRole('button', { name: '创建并进入画布' }))
    expect(await screen.findByText(/必填/)).toBeTruthy()
    expect(createFlow).not.toHaveBeenCalled()
  })
})
