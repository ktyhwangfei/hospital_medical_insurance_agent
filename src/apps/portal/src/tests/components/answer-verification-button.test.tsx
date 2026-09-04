import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AnswerVerificationButton from '@/components/policy-qa/answer-verification-button'
import { verifyPolicyQAAnswer } from '@/lib/policy-qa-feedback'

vi.mock('@/lib/policy-qa-feedback', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/policy-qa-feedback')>()
  return {
    ...actual,
    verifyPolicyQAAnswer: vi.fn(),
  }
})

const mockedVerify = vi.mocked(verifyPolicyQAAnswer)

describe('AnswerVerificationButton', () => {
  afterEach(cleanup)

  it('verifies the current turn and renders inline five-dimension result', async () => {
    mockedVerify.mockResolvedValue({
      verification: {
        status: 'passed',
        dimensions: {
          citation_authenticity: { status: 'passed' },
          conclusion_consistency: { status: 'passed' },
          calculation_consistency: { status: 'passed' },
          coverage_completeness: { status: 'passed' },
        },
      },
      trace_available: true,
      degraded: false,
    } as never)

    render(<AnswerVerificationButton qaTurnId="qat_current" />)

    fireEvent.click(screen.getByRole('button', { name: '答案验证' }))

    await waitFor(() => expect(mockedVerify).toHaveBeenCalledWith('qat_current'))
    expect(screen.getByText('整体状态：通过')).toBeInTheDocument()
    expect(screen.getByText('引用真实性')).toBeInTheDocument()
    expect(screen.getByText('覆盖完整性')).toBeInTheDocument()
  })

  it('shows a degraded hint when trace is unavailable', async () => {
    mockedVerify.mockResolvedValue({
      verification: {
        status: 'not_evaluable',
        dimensions: {},
      },
      trace_available: false,
      degraded: true,
    } as never)

    render(<AnswerVerificationButton qaTurnId="qat_degraded" />)
    fireEvent.click(screen.getByRole('button', { name: '答案验证' }))

    await waitFor(() => expect(screen.getByText('仅公开信息降级验证')).toBeInTheDocument())
    // 无内部证据 → 明确提示「无法验证」，而非展示无意义的维度
    expect(screen.getByText('无法验证')).toBeInTheDocument()
    expect(screen.getByText(/未生成完整验证所需的内部证据/)).toBeInTheDocument()
  })
})
