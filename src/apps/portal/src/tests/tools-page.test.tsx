// Tool 与 Workflow 可视化 /tools 页测试 — 第一批增量：Tool 清单 + Workflow 步骤链绑定状态。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/tools',
}))

vi.mock('@/lib/tool-workflow-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/tool-workflow-api')>()
  return {
    ...actual,
    listTools: vi.fn(),
    listWorkflows: vi.fn(),
  }
})

import ToolsPage from '../../app/tools/page'
import { listTools, listWorkflows } from '@/lib/tool-workflow-api'
import type { ToolCatalogDto, WorkflowCatalogDto } from '@/lib/tool-workflow-api'

const toolCatalog: ToolCatalogDto = {
  items: [
    {
      tool_id: 'tool_get_settlement_fact',
      name: '查询结算事实',
      description: '包装既有结算数据 provider',
      contract_kind: 'function',
      target_ref: 'src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider',
      risk_level: 'low',
      status: 'materialized',
      semantic_version: '1.1.0',
      bound: true,
      tags: ['数据类', '结算事实'],
    },
    {
      tool_id: 'tool_get_refund_record',
      name: '查询退费记录',
      description: '当前无既有数据源接入',
      contract_kind: 'adapter_port',
      target_ref: 'src.adapters.ports.refund_record_port',
      risk_level: 'medium',
      status: 'materialized',
      semantic_version: '1.0.0',
      bound: false,
      tags: ['数据类', '退费记录'],
    },
    {
      tool_id: 'tool_comprehensive_knowledge_lookup',
      name: '综合知识检索',
      description: '先可信问题库结构化命中、未命中降级向量政策证据',
      contract_kind: 'function',
      target_ref: 'src.runtime.policy_qa.knowledge_lookup.comprehensive_knowledge_lookup',
      risk_level: 'low',
      status: 'materialized',
      semantic_version: '1.0.0',
      bound: true,
      tags: ['知识类', '综合检索'],
    },
  ],
}

const workflowCatalog: WorkflowCatalogDto = {
  items: [
    {
      workflow_id: 'wf_refund_verification',
      name: '退费核对',
      description: '核对结算单是否存在对应退费/冲正记录',
      intent_keywords: ['退费', '退款'],
      missing_evidence_rules: [
        { field_name: 'settlement_id', clarify_message: '请提供结算单号' },
      ],
      steps: [
        {
          step_id: 'fetch_settlement',
          tool_id: 'tool_get_settlement_fact',
          description: '',
          tool_bound: true,
          input_mapping: {},
        },
        {
          step_id: 'fetch_refund_record',
          tool_id: 'tool_get_refund_record',
          description: '',
          tool_bound: false,
          input_mapping: {},
        },
      ],
    },
    {
      workflow_id: 'wf_outpatient_settlement_explain',
      name: '门诊结算解释',
      description: '结算事实 → 政策证据 → 确定性对比的标准核验链',
      intent_keywords: ['核对结算', '结算单对不对'],
      missing_evidence_rules: [
        { field_name: 'settlement_id', clarify_message: '请提供需要核对解释的结算单号后再继续。' },
      ],
      steps: [
        {
          step_id: 'fetch_settlement',
          tool_id: 'tool_get_settlement_fact',
          description: '',
          tool_bound: true,
          input_mapping: {},
        },
        {
          step_id: 'retrieve_policy_evidence',
          tool_id: 'tool_retrieve_policy_evidence',
          description: '',
          tool_bound: true,
          input_mapping: { settlement_fact: 'fetch_settlement' },
        },
        {
          step_id: 'compare_settlement_vs_policy',
          tool_id: 'tool_compare_settlement_vs_policy',
          description: '',
          tool_bound: true,
          input_mapping: {
            settlement_fact: 'fetch_settlement',
            policy_evidence: 'retrieve_policy_evidence',
          },
        },
      ],
    },
  ],
}

describe('ToolsPage Tool 与 Workflow 可视化页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listTools).mockResolvedValue(toolCatalog)
    vi.mocked(listWorkflows).mockResolvedValue(workflowCatalog)
  })
  afterEach(() => cleanup())

  it('默认展示 Tool 清单，标注分类与绑定状态', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    expect(screen.getByTestId('tool-item-tool_get_settlement_fact').textContent).toContain('已绑定实现')
    expect(screen.getByTestId('tool-item-tool_get_settlement_fact').textContent).toContain('数据类')
    expect(screen.getByTestId('tool-item-tool_get_refund_record').textContent).toContain('未绑定 · 无数据源')
    expect(screen.getByTestId('tool-item-tool_comprehensive_knowledge_lookup').textContent).toContain('知识类')
  })

  it('切换到 Workflow 页签展示步骤链，未绑定步骤高亮无数据源', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Workflow 编排' }))

    await waitFor(() => expect(screen.getByTestId('workflow-item-wf_refund_verification')).toBeTruthy())
    const steps = screen.getByTestId('workflow-steps-wf_refund_verification')
    expect(steps.textContent).toContain('fetch_settlement')
    expect(steps.textContent).toContain('fetch_refund_record')
    expect(steps.textContent).toContain('无数据源 → unavailable')
    expect(screen.getByTestId('workflow-item-wf_refund_verification').textContent).toContain('请提供结算单号')
  })

  it('门诊结算解释 Workflow 展示步骤间数据流（input_mapping）', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Workflow 编排' }))

    await waitFor(() => expect(screen.getByTestId('workflow-item-wf_outpatient_settlement_explain')).toBeTruthy())
    const steps = screen.getByTestId('workflow-steps-wf_outpatient_settlement_explain')
    expect(steps.textContent).toContain('settlement_fact ← fetch_settlement')
    expect(steps.textContent).toContain('policy_evidence ← retrieve_policy_evidence')
    expect(steps.textContent).toContain('输入 ← 会话上下文')
  })

  it('接口失败时展示错误提示', async () => {
    vi.mocked(listTools).mockRejectedValue(new Error('网络错误'))
    render(<ToolsPage />)

    await waitFor(() => expect(screen.getByTestId('tool-workflow-error')).toBeTruthy())
    expect(screen.getByTestId('tool-workflow-error').textContent).toContain('网络错误')
  })
})
