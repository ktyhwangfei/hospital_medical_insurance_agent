// Tool 与 Workflow 可视化 /tools 页测试：Tool 契约展示 + 混合节点链（tool/domain/output）绑定状态。
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
      input_schema: {
        settlement_id: { type: 'string', required: true, description: '结算单号，来自会话上下文或用户澄清补充' },
      },
      output_schema: {
        basic_pooling_payment: { type: 'number', description: '统筹支付（比例分子）' },
        medical_insurance_inner_amount: { type: 'number', description: '医保内金额（比例分母）' },
      },
      execution_detail:
        '执行链：SemanticQueryPlanner.compile → SQLAlchemy Core 组装 → 出口白名单断言（仅只读聚合 SELECT）→ SQL Server 执行',
    },
    {
      tool_id: 'tool_get_refund_record',
      name: '查询退费记录',
      description: '双链路只读查询：住院 tflydjh + 门诊 HIS o_Trade 退费交易',
      contract_kind: 'adapter_port',
      target_ref: 'src.adapters.ports.refund_record_port',
      risk_level: 'medium',
      status: 'materialized',
      semantic_version: '1.3.0',
      bound: true,
      tags: ['数据类', '退费记录'],
      input_schema: {
        settlement_id: { type: 'string', required: false, description: '结算单号（djh）：走医保端退费链路' },
      },
      output_schema: {
        records: { type: 'array<object>', description: '退费/冲正记录列表' },
      },
      execution_detail:
        '住院：SELECT djh, jylsh, jyrq, zje, tflydjh FROM dbo.yb_zyjyxx WHERE tflydjh = :settlement_id；门诊：o_Trade 退费交易链路。',
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
      input_schema: {
        question: { type: 'string', required: true, description: '用户自然语言问题' },
        settlement_fact: { type: 'object', required: false, description: '结算事实，向量降级时提供适用性维度' },
      },
      output_schema: {
        lookup_kind: { type: 'string', description: '命中路径（structured_hit / vector_evidence）' },
      },
      execution_detail:
        '两级融合编排（优先级硬约束：确定性优先于向量）：1) 可信问题库精确匹配；2) 未命中 → Milvus 标量检索。',
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
          node_type: 'tool',
          tool_id: 'tool_get_settlement_fact',
          description: '',
          bound: true,
          input_mapping: { settlement_id: 'context.settlement_id' },
        },
        {
          step_id: 'fetch_fee_detail',
          node_type: 'tool',
          tool_id: 'tool_get_fee_detail',
          description: '',
          bound: true,
          input_mapping: { settlement_id: 'context.settlement_id' },
        },
        {
          // 覆盖未绑定节点的 fail-closed 高亮渲染（数据源缺失时的降级形态）。
          step_id: 'fetch_refund_record',
          node_type: 'tool',
          tool_id: 'tool_get_refund_record',
          description: '',
          bound: false,
          input_mapping: { settlement_id: 'context.settlement_id' },
        },
        {
          step_id: 'public_result',
          node_type: 'output',
          source_ref: 'fetch_refund_record',
          description: '',
          bound: true,
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
          node_type: 'tool',
          tool_id: 'tool_get_settlement_fact',
          description: '',
          bound: true,
          input_mapping: { settlement_id: 'context.settlement_id' },
        },
        {
          step_id: 'retrieve_policy_evidence',
          node_type: 'tool',
          tool_id: 'tool_retrieve_policy_evidence',
          description: '',
          bound: true,
          input_mapping: { settlement_fact: 'fetch_settlement' },
        },
        {
          step_id: 'check_evidence',
          node_type: 'domain',
          handler_id: 'evidence_completeness',
          handler_version: '1.0.0',
          description: '',
          bound: true,
          input_mapping: {
            settlement_fact: 'fetch_settlement',
            policy_evidence: 'retrieve_policy_evidence',
          },
        },
        {
          step_id: 'compare_settlement_vs_policy',
          node_type: 'domain',
          handler_id: 'settlement_policy_compare',
          handler_version: '1.0.0',
          description: '',
          bound: true,
          input_mapping: {
            settlement_fact: 'fetch_settlement',
            policy_evidence: 'retrieve_policy_evidence',
          },
        },
        {
          step_id: 'merge_evidence',
          node_type: 'domain',
          handler_id: 'evidence_merge',
          handler_version: '1.0.0',
          description: '',
          bound: true,
          input_mapping: {
            policy_evidence: 'retrieve_policy_evidence',
            comparison: 'compare_settlement_vs_policy',
            evidence_check: 'check_evidence',
          },
        },
        {
          step_id: 'public_result',
          node_type: 'output',
          source_ref: 'merge_evidence',
          description: '',
          bound: true,
          input_mapping: {},
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
    expect(screen.getByTestId('tool-item-tool_get_refund_record').textContent).toContain('已绑定实现')
    expect(screen.getByTestId('tool-item-tool_comprehensive_knowledge_lookup').textContent).toContain('知识类')
  })

  it('Tool 卡片优先展示输入参数与输出字段的契约信息', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    const inputs = screen.getByTestId('tool-input-fields-tool_get_settlement_fact')
    expect(inputs.textContent).toContain('settlement_id')
    expect(inputs.textContent).toContain('必填')

    const outputs = screen.getByTestId('tool-output-fields-tool_get_settlement_fact')
    expect(outputs.textContent).toContain('basic_pooling_payment')

    const lookupInputs = screen.getByTestId('tool-input-fields-tool_comprehensive_knowledge_lookup')
    expect(lookupInputs.textContent).toContain('settlement_fact')
    expect(lookupInputs.textContent).toContain('可选')
  })

  it('Tool 卡片展示执行细节（SQL 编译链 / 双链路退费查询）', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    const sqlChain = screen.getByTestId('tool-execution-detail-tool_get_settlement_fact')
    expect(sqlChain.textContent).toContain('SemanticQueryPlanner.compile')

    const refund = screen.getByTestId('tool-execution-detail-tool_get_refund_record')
    expect(refund.textContent).toContain('tflydjh')
    expect(refund.textContent).toContain('o_Trade')
  })

  it('切换到 Workflow 页签展示节点链，未绑定节点高亮无数据源', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Workflow 编排' }))

    await waitFor(() => expect(screen.getByTestId('workflow-item-wf_refund_verification')).toBeTruthy())
    const steps = screen.getByTestId('workflow-steps-wf_refund_verification')
    expect(steps.textContent).toContain('fetch_settlement')
    expect(steps.textContent).toContain('fetch_refund_record')
    expect(steps.textContent).toContain('无数据源 → unavailable')
    expect(steps.textContent).toContain('输出节点')
    expect(steps.textContent).toContain('输出 ← fetch_refund_record')
    expect(screen.getByTestId('workflow-item-wf_refund_verification').textContent).toContain('请提供结算单号')
  })

  it('门诊结算解释 Workflow 展示步骤间数据流与领域节点（input_mapping）', async () => {
    render(<ToolsPage />)
    await waitFor(() => expect(screen.getByTestId('tool-catalog')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Workflow 编排' }))

    await waitFor(() => expect(screen.getByTestId('workflow-item-wf_outpatient_settlement_explain')).toBeTruthy())
    const steps = screen.getByTestId('workflow-steps-wf_outpatient_settlement_explain')
    expect(steps.textContent).toContain('settlement_fact ← fetch_settlement')
    expect(steps.textContent).toContain('policy_evidence ← retrieve_policy_evidence')
    expect(steps.textContent).toContain('settlement_id ← context.settlement_id')
    expect(steps.textContent).toContain('领域节点')
    expect(steps.textContent).toContain('settlement_policy_compare:1.0.0')
    expect(steps.textContent).toContain('输出节点')
    expect(steps.textContent).toContain('输出 ← merge_evidence')
  })

  it('接口失败时展示错误提示', async () => {
    vi.mocked(listTools).mockRejectedValue(new Error('网络错误'))
    render(<ToolsPage />)

    await waitFor(() => expect(screen.getByTestId('tool-workflow-error')).toBeTruthy())
    expect(screen.getByTestId('tool-workflow-error').textContent).toContain('网络错误')
  })
})
