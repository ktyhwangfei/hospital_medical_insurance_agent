// 画布编辑页组件测试 — Phase 2（jsdom 桩见 Phase 0 §5 陷阱 2：
// ResizeObserver 同步回调非零尺寸、DOMMatrixReadOnly.m22=1；SVG 边不在此断言）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

const push = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/flow',
}))

// 把 Promise 分支替换为同步返回已知路由参数，其余走原实现（同 skill-detail-page 模式）。
const ROUTE_PARAMS = vi.hoisted(() => ({ flowId: 'flow_op_outpatient_processed' }))
vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>()
  return {
    ...actual,
    use: (payload: unknown) => {
      if (payload && typeof (payload as { then?: unknown }).then === 'function') {
        return ROUTE_PARAMS
      }
      return actual.use(payload as never)
    },
  }
})

vi.mock('@/lib/flow-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/flow-api')>()
  return {
    ...actual,
    getFlow: vi.fn(),
    listFlowRevisions: vi.fn().mockResolvedValue([]),
    updateFlow: vi.fn(),
    validateFlow: vi.fn(),
    submitFlowReview: vi.fn(),
    publishFlow: vi.fn(),
    deprecateFlow: vi.fn(),
    rollbackFlow: vi.fn(),
    previewFlow: vi.fn(),
  }
})

import FlowEditorPage from '../../app/flow/[flowId]/page'
import {
  getFlow, updateFlow, validateFlow, submitFlowReview,
} from '@/lib/flow-api'
import type { FlowDefinitionDto } from '@/lib/flow-api'

const CALIBER = '口径句v4：T_State IN (2,3) AND NP_Settle_State=1'

function goldenFlow(overrides: Partial<FlowDefinitionDto> = {}): FlowDefinitionDto {
  return {
    flow_id: 'flow_op_outpatient_processed',
    name: '门诊有效结算加工视图（Golden Flow）',
    owner: 'data_governance',
    status: 'draft',
    nodes: [
      {
        node_type: 'source', node_id: 'src_trade', name: '门诊结算落地表 mz_trade',
        dataset_code: 'mz_trade', object_code: 'mzjyxx',
        fields: ['T_TradeNo', 'T_State', 'T_FeeAll'],
        position: { x: 40, y: 200 },
      },
      {
        node_type: 'filter', node_id: 'filter_valid', name: '有效结算口径句 v4',
        conditions: [{ field_code: 'T_State', operator: 'in', value: [2, 3] }],
        position: { x: 280, y: 200 },
      },
      {
        node_type: 'aggregate', node_id: 'agg_snapshot', name: '门诊加工视图',
        group_by: [],
        measures: [
          { output_code: 'op_valid_settle_count', source_field: 'T_TradeNo', operator: 'count_distinct', distinct_key: 'T_TradeNo' },
          { output_code: 'op_total_fee', source_field: 'T_FeeAll', operator: 'sum' },
        ],
        position: { x: 520, y: 200 },
      },
      {
        node_type: 'consumer', node_id: 'consumer_qp', name: '受控问数',
        consumer_kind: 'query_planner', consumes: ['op_total_fee'],
        position: { x: 1000, y: 200 },
      },
    ],
    edges: [
      { edge_id: 'e1', from_node: 'src_trade', to_node: 'filter_valid' },
      { edge_id: 'e2', from_node: 'filter_valid', to_node: 'agg_snapshot' },
      { edge_id: 'e3', from_node: 'agg_snapshot', to_node: 'consumer_qp' },
    ],
    source_contracts: [
      { dataset_code: 'mz_trade', object_code: 'mzjyxx', fields: ['T_TradeNo', 'T_State', 'T_FeeAll'] },
    ],
    metric_outputs: [
      { metric_code: 'op_total_fee', name: '门诊总费用', node_id: 'agg_snapshot', policy_definition: CALIBER },
    ],
    materialization: 'view',
    revision: 1,
    ...overrides,
  }
}

describe('FlowEditorPage 画布编辑页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    push.mockClear()
    // Phase 0 §5 陷阱 2：observe 同步回调非零尺寸，视口才能初始化
    vi.stubGlobal('ResizeObserver', class {
      private cb: ResizeObserverCallback
      constructor(cb: ResizeObserverCallback) { this.cb = cb }
      observe(target: Element) {
        this.cb(
          [{ target, contentRect: { x: 0, y: 0, width: 800, height: 600, top: 0, left: 0 } } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        )
      }
      unobserve() {}
      disconnect() {}
    })
    vi.stubGlobal('DOMMatrixReadOnly', class { m22 = 1 })
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('加载 Flow 并渲染 4 个自定义节点卡片', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)
    await waitFor(() => {
      expect(screen.getByTestId('flow-node-src_trade')).toBeTruthy()
    })
    expect(screen.getByTestId('flow-node-filter_valid')).toBeTruthy()
    expect(screen.getByTestId('flow-node-agg_snapshot')).toBeTruthy()
    expect(screen.getByTestId('flow-node-consumer_qp')).toBeTruthy()
    // 标题在 header input 中回显（可编辑），非文本节点
    expect(screen.getByDisplayValue('门诊有效结算加工视图（Golden Flow）')).toBeTruthy()
  })

  it('选中节点编辑名称后保存，PUT 载荷携带改名与乐观锁修订号', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    vi.mocked(updateFlow).mockResolvedValue(goldenFlow({ revision: 2 }))
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)

    await waitFor(() => screen.getByTestId('flow-node-filter_valid'))
    fireEvent.click(screen.getByTestId('flow-node-filter_valid'))

    const nameInput = await screen.findByDisplayValue('有效结算口径句 v4')
    fireEvent.change(nameInput, { target: { value: '有效结算口径句 v4（修订）' } })
    fireEvent.click(screen.getByRole('button', { name: '保存修订' }))

    await waitFor(() => expect(updateFlow).toHaveBeenCalledTimes(1))
    const [flowId, payload, expectedRevision] = vi.mocked(updateFlow).mock.calls[0]
    expect(flowId).toBe('flow_op_outpatient_processed')
    expect(expectedRevision).toBe(1)
    const renamed = payload.nodes.find((n) => n.node_id === 'filter_valid')
    expect(renamed?.name).toBe('有效结算口径句 v4（修订）')
    // snake_case 序列化契约（§3.3）
    expect(payload.edges[0]).toMatchObject({ edge_id: 'e1', from_node: 'src_trade', to_node: 'filter_valid' })
  })

  it('节点面板添加质量门禁节点并进入选中编辑态', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)
    await waitFor(() => screen.getByTestId('flow-canvas-pane'))

    fireEvent.click(screen.getByRole('button', { name: '质量门禁' }))
    await waitFor(() => expect(screen.getByTestId('flow-node-quality_gate_5')).toBeTruthy())
    expect(screen.getByTestId('flow-node-editor').textContent).toContain('quality_gate_5')
  })

  it('校验报告渲染并点击问题定位节点', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    vi.mocked(getFlow).mockResolvedValueOnce(goldenFlow())
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    vi.mocked(validateFlow).mockResolvedValue({
      issues: [
        { code: 'FLOW_FIELD_NOT_IN_CONTRACT', message: '字段 T_X 不在契约内', node_id: 'filter_valid', severity: 'blocking' },
      ],
      has_blocking: true,
    })
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)

    await waitFor(() => screen.getByTestId('flow-canvas-pane'))
    fireEvent.click(screen.getByRole('button', { name: '校验' }))

    const issue = await screen.findByTestId('flow-validation-issue')
    expect(issue.textContent).toContain('FLOW_FIELD_NOT_IN_CONTRACT')
    expect(screen.getByText('存在阻断问题，发布将 fail closed。')).toBeTruthy()
    fireEvent.click(issue)
    expect(screen.getByTestId('flow-node-editor').textContent).toContain('filter_valid')
  })

  it('窄屏（390px）布局契约：中段纵向堆叠、属性面板全宽、节点面板横条、画布保有最小高度', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)
    await waitFor(() => screen.getByTestId('flow-canvas-pane'))

    // 中段行在窄屏堆叠为列，桌面仍为行
    const mid = screen.getByTestId('flow-editor-mid')
    expect(mid.className).toContain('flex-col')
    expect(mid.className).toContain('md:flex-row')
    // 属性面板窄屏全宽，桌面固定 320px
    const aside = screen.getByTestId('flow-editor-aside')
    expect(aside.className).toContain('w-full')
    expect(aside.className).toContain('md:w-80')
    // 节点面板窄屏横向滚动条，桌面纵向栏
    const palette = screen.getByTestId('flow-palette')
    expect(palette.className).toContain('flex-row')
    expect(palette.className).toContain('md:flex-col')
    // 画布窄屏显式 320px 高 + flex-none（纵向 flex 的 basis:0 会压掉 height，真浏览器实测 0 高），桌面交还 flex
    expect(mid.firstElementChild?.className).toContain('h-[320px]')
    expect(mid.firstElementChild?.className).toContain('flex-none')
    expect(mid.firstElementChild?.className).toContain('md:h-auto')
    expect(mid.firstElementChild?.className).toContain('md:flex-1')
  })

  it('键盘 Enter 选中画布节点同样打开属性面板（键盘全路径）', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)
    await waitFor(() => screen.getByTestId('flow-node-src_trade'))

    // XYFlow 节点 wrapper tabindex=0；聚焦后 Enter 仅产生 selection change（不触发 onNodeClick）
    const wrapper = screen.getByTestId('flow-node-src_trade').closest('.react-flow__node') as HTMLElement
    expect(wrapper.getAttribute('tabindex')).toBe('0')
    wrapper.focus()
    fireEvent.keyDown(wrapper, { key: 'Enter' })

    await waitFor(() =>
      expect(screen.getByTestId('flow-node-editor').textContent).toContain('src_trade'))
  })

  it('状态机门控：draft 只能保存/校验/提交，发布按钮禁用', async () => {
    vi.mocked(getFlow).mockResolvedValue(goldenFlow())
    vi.mocked(submitFlowReview).mockResolvedValue(goldenFlow({ status: 'pending_review' }))
    render(<FlowEditorPage params={Promise.resolve({ flowId: 'flow_op_outpatient_processed' })} />)

    await waitFor(() => screen.getByRole('button', { name: '发布' }))
    expect(screen.getByRole('button', { name: '发布' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '退役' }).hasAttribute('disabled')).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: '提交评审' }))
    await waitFor(() => expect(submitFlowReview).toHaveBeenCalledWith('flow_op_outpatient_processed'))
  })
})
