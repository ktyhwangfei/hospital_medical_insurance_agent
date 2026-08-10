import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CaseProposalEditor from '@/components/skills/case-proposal-editor'
import EvalCasePoolList from '@/components/skills/eval-case-pool-list'
import { ApiClientError } from '@/lib/types'

const poolMocks = vi.hoisted(() => ({
  list: vi.fn(),
  confirm: vi.fn(),
  reject: vi.fn(),
  transform: vi.fn(),
}))

vi.mock('@/lib/policy-qa-feedback', () => ({
  listEvalCasePool: (...a: unknown[]) => poolMocks.list(...a),
  confirmEvalCasePoolItem: (...a: unknown[]) => poolMocks.confirm(...a),
  rejectEvalCasePoolItem: (...a: unknown[]) => poolMocks.reject(...a),
  transformEvalCasePoolItem: (...a: unknown[]) => poolMocks.transform(...a),
}))

vi.mock('@/lib/use-skill-name-map', () => ({
  useSkillNameMap: () => new Map(),
}))

afterEach(cleanup)

function field(id: string) {
  return screen.queryByTestId(`proposal-field-${id}`)
}

describe('CaseProposalEditor — 判别联合：每个维度只显示对应字段', () => {
  it('calculation 展示 expected_value/tolerance/rounding/steps', () => {
    render(
      <CaseProposalEditor
        dimension="calculation"
        proposal={{
          case_type: 'calculation',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: { case_type: 'calculation', expected_value: 100, tolerance: 0.01 },
        }}
        onChange={() => {}}
      />,
    )
    expect(field('expected_value')).toBeInTheDocument()
    expect(field('tolerance')).toBeInTheDocument()
    expect(field('rounding')).toBeInTheDocument()
    expect(field('applicability')).not.toBeInTheDocument()
  })

  it('policy_content 展示 applicability/must_include/forbidden/policy_version', () => {
    render(
      <CaseProposalEditor
        dimension="policy_content"
        proposal={{
          case_type: 'policy_content',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: {
            case_type: 'policy_content',
            applicability: 'applies',
            must_include: ['起付线'],
          },
        }}
        onChange={() => {}}
      />,
    )
    expect(field('applicability')).toBeInTheDocument()
    expect(field('must_include')).toBeInTheDocument()
    expect(field('forbidden')).toBeInTheDocument()
    expect(field('policy_version')).toBeInTheDocument()
    expect(field('expected_value')).not.toBeInTheDocument()
  })

  it('citation 展示 required_source_ids/support_required', () => {
    render(
      <CaseProposalEditor
        dimension="citation"
        proposal={{
          case_type: 'citation',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: { case_type: 'citation', required_source_ids: ['doc-1'] },
        }}
        onChange={() => {}}
      />,
    )
    expect(field('required_source_ids')).toBeInTheDocument()
    expect(field('support_required')).toBeInTheDocument()
    expect(field('expected_value')).not.toBeInTheDocument()
  })

  it('answer_quality 展示 answerable/must_include/must_not_include/rubric', () => {
    render(
      <CaseProposalEditor
        dimension="answer_quality"
        proposal={{
          case_type: 'answer_quality',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: {
            case_type: 'answer_quality',
            answerable: true,
            must_include: ['起付线'],
          },
        }}
        onChange={() => {}}
      />,
    )
    expect(field('answerable')).toBeInTheDocument()
    expect(field('must_include')).toBeInTheDocument()
    expect(field('must_not_include')).toBeInTheDocument()
    expect(field('rubric_id')).toBeInTheDocument()
  })

  it('safety 展示 sensitive_fields/blocked_actions/expected_state', () => {
    render(
      <CaseProposalEditor
        dimension="safety"
        proposal={{
          case_type: 'safety',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: {
            case_type: 'safety',
            blocked_actions: ['refund'],
            expected_state: 'waiting_human_confirmation',
          },
        }}
        onChange={() => {}}
      />,
    )
    expect(field('sensitive_fields')).toBeInTheDocument()
    expect(field('blocked_actions')).toBeInTheDocument()
    expect(field('expected_state')).toBeInTheDocument()
  })

  it('routing 展示 question_template/expected_skill_id（投影到现有路由用例）', () => {
    render(
      <CaseProposalEditor
        dimension="routing"
        proposal={{
          case_type: 'routing',
          question_template: '起付线怎么算',
          expected_skill_id: 'deductible',
        }}
        onChange={() => {}}
      />,
    )
    expect(field('question_template')).toBeInTheDocument()
    expect(field('expected_skill_id')).toBeInTheDocument()
  })

  it('other 只允许重新分型或拒绝（不渲染可执行字段）', () => {
    render(
      <CaseProposalEditor dimension="other" proposal={null} onChange={() => {}} />,
    )
    expect(field('expected_value')).not.toBeInTheDocument()
    expect(field('must_include')).not.toBeInTheDocument()
    expect(screen.getByTestId('proposal-other-notice')).toBeInTheDocument()
  })

  it('编辑字段触发 onChange 并更新 proposal', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <CaseProposalEditor
        dimension="calculation"
        proposal={{
          case_type: 'calculation',
          target_skill_id: 'deductible',
          input_template: {},
          assertions: { case_type: 'calculation', expected_value: 100, tolerance: 0.01 },
        }}
        onChange={onChange}
      />,
    )
    const input = screen.getByTestId('proposal-field-expected_value').querySelector('input')
      ?? screen.getByTestId('proposal-field-expected_value').querySelector('textarea')
    expect(input).not.toBeNull()
    await user.clear(input!)
    await user.type(input!, '200')
    expect(onChange).toHaveBeenCalled()
    const last = onChange.mock.calls.at(-1)![1]
    expect(last.assertions.expected_value).toBe(200)
  })
})

describe('EvalCasePoolList — 转换/确认/拒绝工作流', () => {
  beforeEach(() => {
    poolMocks.list.mockReset()
    poolMocks.confirm.mockReset()
    poolMocks.reject.mockReset()
    poolMocks.transform.mockReset()
  })

  it('409 时保留未提交修改并提示重新加载', async () => {
    const user = userEvent.setup()
    poolMocks.list.mockResolvedValue({
      items: [
        {
          poolId: 'pool-9',
          tenantId: 'default',
          sourceQaTurnId: 'qat_9',
          sourceUserId: 'u',
          reasonCode: 'wrong_calculation',
          errorDimension: 'calculation',
          initialDimension: 'calculation',
          transformedDimension: 'calculation',
          targetSkillId: 'deductible',
          status: 'transformed',
          revision: 2,
          evalCaseRef: null,
          createdAt: '2026-08-10T00:00:00Z',
          updatedAt: '2026-08-10T00:00:00Z',
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    })
    poolMocks.confirm.mockRejectedValue(
      new ApiClientError(409, {
        error_code: 'EVAL_CASE_POOL_REVISION_CONFLICT',
        message: '案例已被修改，请刷新',
      }),
    )

    render(<EvalCasePoolList />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-row-pool-9')).toBeInTheDocument(),
    )

    // 展开编辑、修改维度
    await user.click(screen.getByRole('button', { name: '编辑确认' }))
    await user.selectOptions(
      screen.getByTestId('eval-case-pool-dimension-pool-9'),
      'policy_content',
    )

    // 提交确认触发 409
    await user.click(screen.getByRole('button', { name: '确认投影' }))

    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-action-error')).toBeInTheDocument(),
    )
    // 仍可看到维度选择（未提交修改保留）
    expect(
      (screen.getByTestId('eval-case-pool-dimension-pool-9') as HTMLSelectElement).value,
    ).toBe('policy_content')
  })
})
