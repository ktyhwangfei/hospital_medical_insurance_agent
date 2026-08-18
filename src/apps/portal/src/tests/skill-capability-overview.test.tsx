import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillCapabilityOverview from '@/components/skills/skill-capability-overview'
import type { SkillWorkbenchItem, SkillWorkbenchResponse } from '@/lib/types'

const mockGetSkillGovernanceWorkbench = vi.fn()

vi.mock('@/lib/api-client', () => ({
  getSkillGovernanceWorkbench: (...args: unknown[]) => mockGetSkillGovernanceWorkbench(...args),
}))

const baseItem: SkillWorkbenchItem = {
  skill_id: 'settlement_explain_skill',
  skill_name: '结算费用解释',
  business_action: 'explain',
  business_object: 'settlement',
  description: '解释医保结算费用构成与个人负担原因',
  execution_contract: {
    version: 2,
    common: {
      context_inputs: [],
      metric_inputs: [{ metric_code: 'settlement.total_amount', alias: '结算总金额', required: true }],
    },
    profiles: [
      {
        profile_id: 'deductible-explanation',
        name: '起付线解释',
        purpose: '说明起付线金额及适用原因',
        metric_inputs: [{ metric_code: 'settlement.deductible', alias: '起付金额', required: true }],
      },
      {
        profile_id: 'self-pay-explanation',
        name: '大额自付解释',
        purpose: '定位个人负担较高原因',
        metric_inputs: [{ metric_code: 'settlement.self_pay', alias: '个人自付金额', required: true }],
      },
    ],
  },
  semantic_version: '1.2.0',
  artifact_status: 'registered',
  validation_status: 'passed',
  latest_eval_status: 'passed',
  test_release_status: 'active',
  test_active_version: '1.2.0',
  governance_status: 'healthy',
  attention_reason: null,
  current_stage: 'healthy',
  priority: 'normal',
  latest_eval_run_id: 'run-1',
  candidate_version: '1.2.0',
  baseline_version: '1.1.0',
  regression_count: 0,
  required_failure_count: 0,
  linked_draft_id: null,
  linked_draft_status: null,
  waiting_since: '2026-08-14T00:00:00Z',
  next_action: 'view_evidence',
  next_action_reason: null,
}

const emptyItem: SkillWorkbenchItem = {
  ...baseItem,
  skill_id: 'benefit_query_skill',
  skill_name: '待遇查询',
  business_action: 'query',
  description: '查询患者医保待遇信息',
  execution_contract: undefined,
  governance_status: 'needs_evaluation',
  current_stage: 'evaluate',
  next_action: 'run_evaluation',
}

const draftItem: SkillWorkbenchItem = {
  ...baseItem,
  skill_id: 'mzsettlement_verify_skill',
  skill_name: '门诊结算结果核验',
  business_action: 'verify',
  description: '核验门诊结算结果是否准确',
  execution_contract: {
    version: 2,
    common: { context_inputs: [], metric_inputs: [] },
    profiles: [],
  },
  semantic_version: '',
  artifact_status: 'unregistered',
  governance_status: 'artifact_changed',
  attention_reason: 'draft_only',
  current_stage: 'modify',
  linked_draft_id: 'draft-cf24aa3b34fe',
  linked_draft_status: 'editing',
  next_action: 'continue_draft',
}

const response: SkillWorkbenchResponse = {
  summary: {
    total: 2,
    healthy: 1,
    needs_evaluation: 1,
    pending_approval: 0,
    test_active: 1,
    draft_only: 0,
    updated_at: '2026-08-14T00:00:00Z',
  },
  items: [baseItem, emptyItem],
  total: 2,
  page: 1,
  page_size: 50,
}

describe('Skill capability overview', () => {
  beforeEach(() => {
    mockGetSkillGovernanceWorkbench.mockReset()
    mockGetSkillGovernanceWorkbench.mockResolvedValue(response)
  })

  afterEach(cleanup)

  it('renders every Skill as a compact dossier with scenarios and business metrics', async () => {
    render(<SkillCapabilityOverview />)

    expect(await screen.findByRole('heading', { name: 'Skill 能力与场景概览' })).toBeVisible()
    const settlement = screen.getByTestId('skill-overview-settlement_explain_skill')
    expect(within(settlement).getByText('解释医保结算费用构成与个人负担原因')).toBeVisible()
    expect(within(settlement).getByText('结算总金额')).toBeVisible()
    expect(within(settlement).getByText('起付线解释')).toBeVisible()
    expect(within(settlement).getByText('起付金额')).toBeVisible()
    expect(within(settlement).getByText('大额自付解释')).toBeVisible()
    expect(within(settlement).getByTestId('scenario-grid')).toHaveClass('xl:grid-cols-3')
    expect(within(screen.getByTestId('skill-overview-benefit_query_skill')).getByText('尚未配置执行场景')).toBeVisible()
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(1)
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledWith({ page: 1, page_size: 50 })
  })

  it('searches Skill, scenario and metric text and combines action/object filters', async () => {
    const user = userEvent.setup()
    render(<SkillCapabilityOverview />)
    await screen.findByText('起付线解释')

    await user.type(screen.getByLabelText('搜索 Skill、场景或业务指标'), '起付金额')
    expect(screen.getByTestId('skill-overview-settlement_explain_skill')).toBeVisible()
    expect(screen.queryByTestId('skill-overview-benefit_query_skill')).not.toBeInTheDocument()

    await user.clear(screen.getByLabelText('搜索 Skill、场景或业务指标'))
    await user.selectOptions(screen.getByLabelText('业务动作'), 'query')
    await user.selectOptions(screen.getByLabelText('业务对象'), 'settlement')
    expect(screen.queryByTestId('skill-overview-settlement_explain_skill')).not.toBeInTheDocument()
    expect(screen.getByTestId('skill-overview-benefit_query_skill')).toBeVisible()

    await user.type(screen.getByLabelText('搜索 Skill、场景或业务指标'), '不存在')
    expect(screen.getByText('没有符合条件的 Skill')).toBeVisible()
    await user.click(screen.getByRole('button', { name: '清除筛选' }))
    expect(screen.getAllByTestId(/^skill-overview-/)).toHaveLength(2)
  })

  it('shows a retryable error without losing the overview shell', async () => {
    mockGetSkillGovernanceWorkbench
      .mockRejectedValueOnce(new Error('WORKBENCH_UNAVAILABLE'))
      .mockResolvedValueOnce(response)
    render(<SkillCapabilityOverview />)

    expect(await screen.findByRole('alert')).toHaveTextContent('WORKBENCH_UNAVAILABLE')
    await userEvent.click(screen.getByRole('button', { name: '重试' }))

    await waitFor(() => expect(screen.getByTestId('skill-overview-settlement_explain_skill')).toBeVisible())
    expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(2)
  })

  it('marks draft-only skills with a 草稿 badge and shows draft count in the header', async () => {
    mockGetSkillGovernanceWorkbench.mockResolvedValueOnce({
      ...response,
      summary: { ...response.summary, total: 3, draft_only: 1 },
      items: [baseItem, draftItem],
      total: 2,
    })
    render(<SkillCapabilityOverview />)

    expect(await screen.findByTestId('skill-overview-mzsettlement_verify_skill')).toBeVisible()
    const draftCard = screen.getByTestId('skill-overview-mzsettlement_verify_skill')
    // 草稿 skill 显示「草稿」徽章，而非「制品有变更」
    expect(within(draftCard).getByText('草稿')).toBeVisible()
    expect(within(draftCard).queryByText('制品有变更')).not.toBeInTheDocument()
    // header 摘要显示草稿计数
    expect(screen.getByText(/个草稿/)).toBeVisible()
    // 正常 skill 不显示草稿徽章
    const normalCard = screen.getByTestId('skill-overview-settlement_explain_skill')
    expect(within(normalCard).queryByText('草稿')).not.toBeInTheDocument()
  })
})
