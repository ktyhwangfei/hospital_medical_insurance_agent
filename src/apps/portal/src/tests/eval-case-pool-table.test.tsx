import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EvalCasePoolTable from '@/components/skills/eval-case-pool-table'
import { ApiClientError } from '@/lib/types'

const poolMocks = vi.hoisted(() => ({
  list: vi.fn(),
  confirm: vi.fn(),
  reject: vi.fn(),
  transform: vi.fn(),
}))

vi.mock('@/lib/policy-qa-feedback', () => ({
  listEvalCasePool: (...a: unknown[]) => poolMocks.list(...a),
}))

vi.mock('@/lib/api-client', () => ({
  confirmEvalCasePoolItem: (...a: unknown[]) => poolMocks.confirm(...a),
  rejectEvalCasePoolItem: (...a: unknown[]) => poolMocks.reject(...a),
  transformEvalCasePoolItem: (...a: unknown[]) => poolMocks.transform(...a),
}))

vi.mock('@/lib/use-skill-name-map', () => ({
  useSkillNameMap: () => new Map([['deductible', '起付线技能']]),
}))

afterEach(cleanup)

function makeItem(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    poolId: 'pool-1',
    tenantId: 'default',
    sourceQaTurnId: 'qat_1',
    sourceUserId: 'u',
    reasonCode: 'wrong_calculation',
    errorDimension: 'calculation',
    initialDimension: 'calculation',
    transformedDimension: null,
    targetSkillId: 'deductible',
    questionExcerpt: '起付线怎么算',
    answerExcerpt: '累计 1800 元',
    comment: '',
    status: 'pending_triage',
    revision: 1,
    evalCaseRef: null,
    createdAt: '2026-08-10T00:00:00Z',
    updatedAt: '2026-08-10T00:00:00Z',
    ...overrides,
  }
}

describe('EvalCasePoolTable — 摘要展示与行内编辑', () => {
  beforeEach(() => {
    poolMocks.list.mockReset()
    poolMocks.confirm.mockReset()
    poolMocks.reject.mockReset()
    poolMocks.transform.mockReset()
  })

  it('渲染脱敏摘要（区分条目，解决视觉重复）', async () => {
    poolMocks.list.mockResolvedValue({
      items: [
        makeItem({ poolId: 'pool-a', questionExcerpt: '起付线多少' }),
        makeItem({ poolId: 'pool-b', questionExcerpt: '大额自付标准' }),
      ],
      total: 2,
      limit: 100,
      offset: 0,
    })

    render(<EvalCasePoolTable />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-row-pool-a')).toBeInTheDocument(),
    )
    expect(screen.getByText('起付线多少')).toBeInTheDocument()
    expect(screen.getByText('大额自付标准')).toBeInTheDocument()
    expect(screen.getAllByText('起付线技能')).toHaveLength(2)
  })

  it('pending_triage 行点 AI 转换 → 调 transform 并重载', async () => {
    const user = userEvent.setup()
    poolMocks.list.mockResolvedValue({
      items: [makeItem({ status: 'pending_triage' })],
      total: 1,
      limit: 100,
      offset: 0,
    })
    poolMocks.transform.mockResolvedValue(undefined)
    poolMocks.list.mockResolvedValueOnce({
      items: [makeItem({ status: 'pending_triage' })],
      total: 1,
      limit: 100,
      offset: 0,
    })

    render(<EvalCasePoolTable />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-row-pool-1')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'AI 转换' }))
    await waitFor(() => expect(poolMocks.transform).toHaveBeenCalledWith('pool-1', 1))
  })

  it('transformed 行展开编辑 → 确认投影 → 调 confirm', async () => {
    const user = userEvent.setup()
    poolMocks.list.mockResolvedValue({
      items: [makeItem({ status: 'transformed', revision: 2 })],
      total: 1,
      limit: 100,
      offset: 0,
    })
    poolMocks.confirm.mockResolvedValue(undefined)

    render(<EvalCasePoolTable />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-row-pool-1')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: '编辑确认' }))
    await user.selectOptions(
      screen.getByTestId('eval-case-pool-dimension-pool-1'),
      'policy_content',
    )
    await user.click(screen.getByRole('button', { name: '确认投影' }))

    await waitFor(() => expect(poolMocks.confirm).toHaveBeenCalled())
    const [poolId, req] = poolMocks.confirm.mock.calls[0]
    expect(poolId).toBe('pool-1')
    expect(req.expected_revision).toBe(2)
    expect(req.error_dimension).toBe('policy_content')
  })

  it('拒绝 → 调 reject', async () => {
    const user = userEvent.setup()
    poolMocks.list.mockResolvedValue({
      items: [makeItem({ status: 'pending_triage', revision: 3 })],
      total: 1,
      limit: 100,
      offset: 0,
    })
    poolMocks.reject.mockResolvedValue(undefined)

    render(<EvalCasePoolTable />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-row-pool-1')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: '拒绝' }))
    await waitFor(() => expect(poolMocks.reject).toHaveBeenCalledWith('pool-1', 3, expect.any(String)))
  })

  it('409 冲突时提示重新加载', async () => {
    poolMocks.list.mockResolvedValue({
      items: [makeItem({ status: 'transformed', revision: 2 })],
      total: 1,
      limit: 100,
      offset: 0,
    })
    poolMocks.confirm.mockRejectedValue(
      new ApiClientError(409, {
        error_code: 'EVAL_CASE_POOL_REVISION_CONFLICT',
        message: '冲突',
      }),
    )

    render(<EvalCasePoolTable />)
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-row-pool-1')).toBeInTheDocument(),
    )
    await userEvent.setup().click(screen.getByRole('button', { name: '编辑确认' }))
    await userEvent.setup().click(screen.getByRole('button', { name: '确认投影' }))
    await waitFor(() =>
      expect(screen.getByTestId('eval-case-pool-action-error')).toBeInTheDocument(),
    )
  })
})
