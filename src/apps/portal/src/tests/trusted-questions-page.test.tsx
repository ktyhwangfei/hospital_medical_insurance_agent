import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TrustedQuestionsPage from '../../app/trusted-questions/page'
import type { TrustedQuestion } from '@/lib/trusted-questions-api'

const listMock = vi.hoisted(() => vi.fn())
const matchAndExecuteMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/trusted-questions-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/trusted-questions-api')>()),
  listTrustedQuestions: listMock,
  matchAndExecuteTrustedQuestion: matchAndExecuteMock,
}))

function makeQuestion(overrides: Partial<TrustedQuestion> = {}): TrustedQuestion {
  return {
    question_id: 'tq_1',
    standard_question: '门诊报销比例是多少？',
    synonyms: [],
    applicable_roles: [],
    metric_codes: ['total_amount'],
    dimensions: [],
    time_scope: {},
    filters: [],
    query_plan: { object_code: 'outpatient' },
    allowed_drilldowns: [],
    expected_result_traits: {},
    status: 'active',
    created_by: 'op-1',
    reviewed_by: 'reviewer-1',
    reviewed_at: '2026-01-01T00:00:00Z',
    review_note: null,
    version: 2,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

async function runMatch(question: string) {
  const user = userEvent.setup()
  render(<TrustedQuestionsPage />)
  await screen.findByText('匹配测试')
  await user.type(screen.getByLabelText('用户问题'), question)
  await user.click(screen.getByRole('button', { name: '测试' }))
  return user
}

describe('TrustedQuestionsPage MatchTester', () => {
  beforeEach(() => {
    listMock.mockReset()
    matchAndExecuteMock.mockReset()
    listMock.mockResolvedValue({ items: [], limit: 200, offset: 0 })
  })

  afterEach(() => {
    cleanup()
  })

  it('matched + executed 时展示执行结果区（徽章 / 质量状态 / 行数 / 行预览）', async () => {
    matchAndExecuteMock.mockResolvedValue({
      outcome: 'matched',
      question: makeQuestion(),
      candidates: [],
      answer: {
        outcome: 'executed',
        question_id: 'tq_1',
        result: {
          rows: [{ ratio: 0.8 }, { ratio: 0.7 }],
          quality_status: 'complete',
        },
        violations: [],
      },
    })

    await runMatch('门诊报销比例')

    expect(matchAndExecuteMock).toHaveBeenCalledWith({ question: '门诊报销比例', role: undefined })
    expect(await screen.findByText('命中：')).toBeInTheDocument()
    expect(screen.getByText('执行成功')).toBeInTheDocument()
    expect(screen.getByText('质量 complete · 2 行')).toBeInTheDocument()
    expect(screen.getByText('结果预览（前 3 行）')).toBeInTheDocument()
    expect(screen.getByText(/"ratio": 0.8/)).toBeInTheDocument()
  })

  it('matched + trait_violation 时展示违例列表', async () => {
    matchAndExecuteMock.mockResolvedValue({
      outcome: 'matched',
      question: makeQuestion(),
      candidates: [],
      answer: {
        outcome: 'trait_violation',
        question_id: 'tq_1',
        result: { rows: [], quality_status: 'partial' },
        violations: ['quality_status=partial 不在允许集合 ["complete"]'],
      },
    })

    await runMatch('门诊报销比例')

    expect(await screen.findByText('特征违例')).toBeInTheDocument()
    expect(screen.getByText('质量 partial · 0 行')).toBeInTheDocument()
    expect(screen.getByText('quality_status=partial 不在允许集合 ["complete"]')).toBeInTheDocument()
    expect(screen.queryByText('结果预览（前 3 行）')).not.toBeInTheDocument()
  })

  it('candidates 态保持现状，不展示执行结果区', async () => {
    matchAndExecuteMock.mockResolvedValue({
      outcome: 'candidates',
      question: null,
      candidates: [
        { question_id: 'tq_1', standard_question: '门诊报销比例是多少？', score: 0.82, matched_expression: '门诊报销比例' },
      ],
      answer: null,
    })

    await runMatch('报销比例')

    expect(await screen.findByText('不确定，需澄清（候选 1）：')).toBeInTheDocument()
    expect(screen.getByText('门诊报销比例是多少？')).toBeInTheDocument()
    expect(screen.queryByText('执行成功')).not.toBeInTheDocument()
    expect(screen.queryByText(/质量 /)).not.toBeInTheDocument()
  })
})
