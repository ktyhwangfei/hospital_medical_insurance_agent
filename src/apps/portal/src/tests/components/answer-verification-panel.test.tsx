import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AnswerVerificationPanel from '@/components/policy-qa/answer-verification-panel'
import { fetchQAHistory } from '@/lib/api-client'
import { verifyPolicyQAAnswer } from '@/lib/policy-qa-feedback'
import { ApiClientError } from '@/lib/types'

vi.mock('@/lib/policy-qa-feedback', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-qa-feedback')>()
  return {
    ...actual,
    verifyPolicyQAAnswer: vi.fn(),
  }
})

vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>()
  return {
    ...actual,
    fetchQAHistory: vi.fn(),
  }
})

const mockedVerify = vi.mocked(verifyPolicyQAAnswer)
const mockedHistory = vi.mocked(fetchQAHistory)

function historyWith(turnIds: string[]): { items: unknown[] } {
  return {
    items: turnIds.map((id, index) => ({
      session_id: `sess_${index}`,
      workflows: [
        {
          tasks: [
            {
              task_id: id,
              input_data: { question_excerpt: `问题 ${index}` },
              output_data: { answer_excerpt: `回答 ${index}`, answer_status: 'complete' },
            },
          ],
        },
      ],
    })),
  }
}

const fiveDimResult = {
  verification: {
    status: 'failed',
    dimensions: {
      citation_authenticity: { status: 'passed' },
      citation_support: { status: 'not_evaluable' },
      conclusion_consistency: {
        status: 'failed',
        failures: [{ code: 'CONCLUSION_MISMATCH', message: '结论与政策不一致' }],
      },
      calculation_consistency: { status: 'blocked_by_evaluator' },
      coverage_completeness: { status: 'passed' },
    },
  },
  trace_available: true,
  degraded: true,
}

describe('AnswerVerificationPanel', () => {
  afterEach(cleanup)

  it('shows history entries for one-click verification', async () => {
    mockedHistory.mockResolvedValue(historyWith(['qat_t1', 'qat_t2']) as never)
    render(<AnswerVerificationPanel />)

    await waitFor(() => expect(screen.getByText('问题 0')).toBeInTheDocument())
    expect(screen.getByText('问题 1')).toBeInTheDocument()
  })

  it('verifies a selected history turn and renders five-dimension result', async () => {
    mockedHistory.mockResolvedValue(historyWith(['qat_t1']) as never)
    mockedVerify.mockResolvedValue(fiveDimResult as never)
    render(<AnswerVerificationPanel />)

    await waitFor(() => expect(screen.getByText('问题 0')).toBeInTheDocument())
    fireEvent.click(screen.getByText('问题 0'))

    await waitFor(() => expect(mockedVerify).toHaveBeenCalledWith('qat_t1'))
    expect(screen.getByText('整体状态：未通过')).toBeInTheDocument()
    expect(screen.getByText('仅公开信息降级验证')).toBeInTheDocument()
    for (const label of ['引用真实性', '引用支撑性', '结论一致性', '计算一致性', '覆盖完整性']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('CONCLUSION_MISMATCH')).toBeInTheDocument()
  })

  it('shows a hint when there is no history yet', async () => {
    mockedHistory.mockResolvedValue({ items: [] } as never)
    render(<AnswerVerificationPanel />)
    await waitFor(() =>
      expect(screen.getByText(/暂无历史问答/)).toBeInTheDocument(),
    )
  })

  it('shows friendly message when a turn is not found (404)', async () => {
    mockedHistory.mockResolvedValue(historyWith(['qat_t1']) as never)
    mockedVerify.mockRejectedValue(
      new ApiClientError(404, { error_code: 'QA_TURN_NOT_FOUND', message: '未找到该问答轮次' }),
    )
    render(<AnswerVerificationPanel />)

    await waitFor(() => expect(screen.getByText('问题 0')).toBeInTheDocument())
    fireEvent.click(screen.getByText('问题 0'))

    await waitFor(() =>
      expect(screen.getByText(/验证轨迹已失效/)).toBeInTheDocument(),
    )
  })
})
