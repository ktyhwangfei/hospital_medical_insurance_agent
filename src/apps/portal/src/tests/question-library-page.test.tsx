// 可信问题库 /question-library 页测试 — #37（概览/列表过滤/审核发布/新建草稿/
// 试问命中执行与澄清/越问越准采纳/冷启动）。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/question-library',
}))

vi.mock('@/lib/question-library-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/question-library-api')>()
  return {
    ...actual,
    getQuestionLibraryStats: vi.fn(),
    listTrustedQuestions: vi.fn(),
    reviewTrustedQuestion: vi.fn(),
    archiveTrustedQuestion: vi.fn(),
    createTrustedQuestionDraft: vi.fn(),
    addTrustedQuestionSynonym: vi.fn(),
    matchQuestion: vi.fn(),
    executeQuestion: vi.fn(),
    listQuestionMatchEvents: vi.fn(),
    listColdStartCandidates: vi.fn(),
  }
})

import QuestionLibraryPage from '../../app/question-library/page'
import {
  addTrustedQuestionSynonym,
  createTrustedQuestionDraft,
  executeQuestion,
  getQuestionLibraryStats,
  listColdStartCandidates,
  listQuestionMatchEvents,
  listTrustedQuestions,
  matchQuestion,
  reviewTrustedQuestion,
  type QuestionMatchOutcomeDto,
  type TrustedQuestionDto,
} from '@/lib/question-library-api'

function question(overrides: Partial<TrustedQuestionDto> = {}): TrustedQuestionDto {
  return {
    question_id: 'tq_1',
    standard_question: '本年度医保基金支付总额是多少',
    synonyms: ['今年基金支付总额是多少'],
    roles: ['information_department'],
    object_code: 'mzjyxx',
    metrics: ['fund_pay_total'],
    dimensions: [],
    time_scope: '本年度',
    filters: [],
    query_plan: { object_code: 'mzjyxx', metrics: ['fund_pay_total'], group_by: [] },
    allow_drilldown: false,
    expected_result: {},
    reviewer: null,
    version: 1,
    status: 'draft',
    revision: 1,
    created_at: '2026-09-10T04:00:00+00:00',
    updated_at: '2026-09-10T04:00:00+00:00',
    ...overrides,
  }
}

describe('QuestionLibraryPage 可信问题库页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getQuestionLibraryStats).mockResolvedValue({
      question_counts: { draft: 1, published: 2, archived: 0 },
      match_event_counts: { hit: 5, clarify: 3 },
    })
    vi.mocked(listTrustedQuestions).mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 50,
    })
  })
  afterEach(() => cleanup())

  it('渲染概览统计 chips', async () => {
    render(<QuestionLibraryPage />)
    await waitFor(() => expect(screen.getByTestId('qlib-overview-chips')).toBeTruthy())
    // 「已发布」同时在 chip / 状态下拉 option / 行徽标出现，断言必须限定范围
    const chips = within(screen.getByTestId('qlib-overview-chips'))
    expect(chips.getByText('已发布').textContent).toContain('2')
    expect(chips.getByText('命中').textContent).toContain('5')
  })

  it('渲染问题列表：标准问题/状态徽标/同义数', async () => {
    vi.mocked(listTrustedQuestions).mockResolvedValue({
      items: [question(), question({ question_id: 'tq_2', standard_question: '个人自付总额是多少', status: 'published', synonyms: [] })],
      total: 2, page: 1, page_size: 50,
    })
    render(<QuestionLibraryPage />)
    await waitFor(() => expect(screen.getAllByTestId('qlib-row').length).toBe(2))
    expect(screen.getByText('本年度医保基金支付总额是多少')).toBeTruthy()
    expect(within(screen.getAllByTestId('qlib-row')[1]).getByText('已发布')).toBeTruthy()
    expect(screen.getByText('同义 1')).toBeTruthy()
  })

  it('状态过滤变化后按新条件查询', async () => {
    vi.mocked(listTrustedQuestions).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    render(<QuestionLibraryPage />)
    await waitFor(() => expect(listTrustedQuestions).toHaveBeenCalled())
    fireEvent.change(screen.getByTestId('qlib-status-filter'), { target: { value: 'published' } })
    await waitFor(() =>
      expect(listTrustedQuestions).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'published' })),
    )
  })

  it('展开草稿行可审核发布并刷新', async () => {
    vi.mocked(listTrustedQuestions).mockResolvedValue({
      items: [question()], total: 1, page: 1, page_size: 50,
    })
    vi.mocked(reviewTrustedQuestion).mockResolvedValue({
      question_id: 'tq_1', status: 'published', version: 2,
    })
    render(<QuestionLibraryPage />)
    await waitFor(() => expect(screen.getByTestId('qlib-row')).toBeTruthy())
    fireEvent.click(screen.getByTestId('qlib-row'))
    await waitFor(() => expect(screen.getByTestId('qlib-detail')).toBeTruthy())
    fireEvent.click(screen.getByTestId('qlib-approve-button'))
    await waitFor(() => expect(reviewTrustedQuestion).toHaveBeenCalledWith('tq_1', {
      approve: true, reviewer: 'portal-reviewer', expected_revision: 1,
    }))
    await waitFor(() => expect(screen.getByTestId('qlib-note').textContent).toContain('已发布'))
  })

  it('新建草稿对话框提交创建', async () => {
    vi.mocked(createTrustedQuestionDraft).mockResolvedValue({ question_id: 'tq_new', status: 'draft' })
    render(<QuestionLibraryPage />)
    await waitFor(() => expect(screen.getByTestId('qlib-create-button')).toBeTruthy())
    fireEvent.click(screen.getByTestId('qlib-create-button'))
    await waitFor(() => expect(screen.getByTestId('qlib-create-dialog')).toBeTruthy())
    fireEvent.change(screen.getByTestId('qlib-create-standard'), { target: { value: '门诊总费用是多少' } })
    fireEvent.click(screen.getByTestId('qlib-create-submit'))
    await waitFor(() => expect(createTrustedQuestionDraft).toHaveBeenCalledTimes(1))
    const body = vi.mocked(createTrustedQuestionDraft).mock.calls[0][0]
    expect(body.standard_question).toBe('门诊总费用是多少')
    expect(body.query_plan.object_code).toBe('mzjyxx')
  })

  it('试问命中后可执行查询', async () => {
    const outcome: QuestionMatchOutcomeDto = {
      kind: 'hit',
      asked_text: '本年度医保基金支付总额是多少？',
      question: question({ status: 'published' }),
      matched_text: '本年度医保基金支付总额是多少',
      candidates: [],
    }
    vi.mocked(matchQuestion).mockResolvedValue(outcome)
    vi.mocked(executeQuestion).mockResolvedValue({
      rows: [{ fund_pay_total: 88 }],
      quality_status: 'complete',
    })
    render(<QuestionLibraryPage />)
    fireEvent.click(screen.getByText('试问'))
    await waitFor(() => expect(screen.getByTestId('qlib-try-input')).toBeTruthy())
    fireEvent.change(screen.getByTestId('qlib-try-input'), { target: { value: '本年度医保基金支付总额是多少？' } })
    fireEvent.click(screen.getByTestId('qlib-try-button'))
    await waitFor(() => expect(screen.getByTestId('qlib-try-hit')).toBeTruthy())
    fireEvent.click(screen.getByTestId('qlib-try-execute'))
    await waitFor(() => expect(executeQuestion).toHaveBeenCalledWith('tq_1'))
    await waitFor(() => expect(screen.getByTestId('qlib-try-result')).toBeTruthy())
    expect(screen.getByText(/complete/)).toBeTruthy()
  })

  it('试问不确定时展示澄清候选，绝不自动执行', async () => {
    const outcome: QuestionMatchOutcomeDto = {
      kind: 'clarify',
      asked_text: '医保基金支付总额',
      question: null,
      matched_text: null,
      candidates: [{
        question_id: 'tq_1',
        standard_question: '本年度医保基金支付总额是多少',
        score: 0.72,
        matched_text: '本年度医保基金支付总额是多少',
      }],
    }
    vi.mocked(matchQuestion).mockResolvedValue(outcome)
    render(<QuestionLibraryPage />)
    fireEvent.click(screen.getByText('试问'))
    await waitFor(() => expect(screen.getByTestId('qlib-try-input')).toBeTruthy())
    fireEvent.change(screen.getByTestId('qlib-try-input'), { target: { value: '医保基金支付总额' } })
    fireEvent.click(screen.getByTestId('qlib-try-button'))
    await waitFor(() => expect(screen.getByTestId('qlib-try-clarify')).toBeTruthy())
    expect(screen.getByText('本年度医保基金支付总额是多少')).toBeTruthy()
    expect(executeQuestion).not.toHaveBeenCalled()
  })

  it('越问越准：澄清事件选择目标后一键采纳为同义', async () => {
    vi.mocked(listQuestionMatchEvents).mockResolvedValue({
      items: [{
        event_id: 'qme_1',
        asked_text: '今年基金支付了多少',
        outcome: 'clarify',
        matched_question_id: null,
        created_at: '2026-09-10T05:00:00+00:00',
      }],
      total: 1, page: 1, page_size: 50,
    })
    vi.mocked(listTrustedQuestions).mockResolvedValue({
      items: [question({ status: 'published', revision: 3 })],
      total: 1, page: 1, page_size: 100,
    })
    vi.mocked(addTrustedQuestionSynonym).mockResolvedValue({
      question_id: 'tq_1',
      synonyms: ['今年基金支付了多少'],
    })
    render(<QuestionLibraryPage />)
    fireEvent.click(screen.getByText('越问越准'))
    await waitFor(() => expect(screen.getByTestId('qlib-loop-list')).toBeTruthy())
    fireEvent.change(screen.getByTestId('qlib-loop-target-qme_1'), { target: { value: 'tq_1' } })
    fireEvent.click(screen.getByTestId('qlib-loop-adopt-qme_1'))
    await waitFor(() =>
      expect(addTrustedQuestionSynonym).toHaveBeenCalledWith('tq_1', {
        synonym: '今年基金支付了多少', expected_revision: 3,
      }),
    )
    await waitFor(() => expect(screen.getByTestId('qlib-note').textContent).toContain('已采纳'))
  })

  it('冷启动展示历史高频候选并可沉淀为草稿', async () => {
    vi.mocked(listColdStartCandidates).mockResolvedValue([
      { question_text: '个人自付总额怎么查', frequency: 7 },
    ])
    vi.mocked(createTrustedQuestionDraft).mockResolvedValue({ question_id: 'tq_cold', status: 'draft' })
    render(<QuestionLibraryPage />)
    fireEvent.click(screen.getByText('冷启动'))
    await waitFor(() => expect(screen.getByTestId('qlib-cold-table')).toBeTruthy())
    expect(screen.getByText('个人自付总额怎么查')).toBeTruthy()
    expect(screen.getByText('7')).toBeTruthy()
    fireEvent.click(screen.getByText('创建草稿'))
    await waitFor(() => expect(screen.getByTestId('qlib-cold-create-dialog')).toBeTruthy())
    fireEvent.click(screen.getByTestId('qlib-cold-submit'))
    await waitFor(() => expect(createTrustedQuestionDraft).toHaveBeenCalledTimes(1))
    const body = vi.mocked(createTrustedQuestionDraft).mock.calls[0][0]
    expect(body.standard_question).toBe('个人自付总额怎么查')
  })

  it('列表加载失败展示错误条', async () => {
    vi.mocked(listTrustedQuestions).mockRejectedValue(new Error('无法连接可信问题库'))
    render(<QuestionLibraryPage />)
    await waitFor(() => expect(screen.getByTestId('qlib-error')).toBeTruthy())
    expect(screen.getByTestId('qlib-error').textContent).toContain('无法连接可信问题库')
  })
})
