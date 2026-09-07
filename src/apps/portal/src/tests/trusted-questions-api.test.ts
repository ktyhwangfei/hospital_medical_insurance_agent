import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addTrustedQuestionSynonym,
  approveTrustedQuestion,
  createTrustedQuestion,
  listTrustedQuestions,
  matchTrustedQuestion,
  rejectTrustedQuestion,
  removeTrustedQuestionSynonym,
  retireTrustedQuestion,
  submitTrustedQuestionReview,
  updateTrustedQuestion,
} from '@/lib/trusted-questions-api'

const API = '/api/v1/medical-insurance-ai-agent/trusted-questions'

function mockFetchOnce(payload: unknown, status = 200) {
  const spy = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('trusted-questions-api', () => {
  it('listTrustedQuestions 透传 status/keyword/limit 查询参数', async () => {
    const spy = mockFetchOnce({ items: [], limit: 200, offset: 0 })
    await listTrustedQuestions({ status: 'active', keyword: '起付线', limit: 200 })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(`${API}?status=active&keyword=%E8%B5%B7%E4%BB%98%E7%BA%BF&limit=200`)
    expect(init?.method ?? 'GET').toBe('GET')
  })

  it('createTrustedQuestion POST created_by 与 synonyms', async () => {
    const spy = mockFetchOnce({ question_id: 'tq_1' }, 201)
    await createTrustedQuestion({
      standard_question: '门诊报销比例是多少？',
      created_by: 'op-1',
      synonyms: ['门诊报销比例'],
    })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(API)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({
      standard_question: '门诊报销比例是多少？',
      created_by: 'op-1',
      synonyms: ['门诊报销比例'],
    })
  })

  it('updateTrustedQuestion 携带 expected_version 乐观锁', async () => {
    const spy = mockFetchOnce({ question_id: 'tq_1', version: 2 })
    await updateTrustedQuestion('tq_1', { standard_question: '新问题', expected_version: 1 })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(`${API}/tq_1`)
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(String(init?.body)).expected_version).toBe(1)
  })

  it('审核流四个端点共用 transition 请求形态', async () => {
    for (const [fn, action] of [
      [submitTrustedQuestionReview, 'submit-review'],
      [approveTrustedQuestion, 'approve'],
      [retireTrustedQuestion, 'retire'],
    ] as const) {
      const spy = mockFetchOnce({ question_id: 'tq_1' })
      await fn('tq_1', { expected_version: 3, operator: 'reviewer-1' })
      const [url, init] = spy.mock.calls[0]
      expect(url).toBe(`${API}/tq_1/${action}`)
      expect(JSON.parse(String(init?.body))).toEqual({
        expected_version: 3, operator: 'reviewer-1',
      })
      vi.unstubAllGlobals()
    }
  })

  it('reject 必须携带 review_note', async () => {
    const spy = mockFetchOnce({ question_id: 'tq_1' })
    await rejectTrustedQuestion('tq_1', {
      expected_version: 2, operator: 'reviewer-1', review_note: '表述不清晰',
    })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(`${API}/tq_1/reject`)
    expect(JSON.parse(String(init?.body)).review_note).toBe('表述不清晰')
  })

  it('addTrustedQuestionSynonym POST added_by；remove 走 path + query 参数', async () => {
    let spy = mockFetchOnce({ question_id: 'tq_1' })
    await addTrustedQuestionSynonym('tq_1', {
      expression: '门诊报销比例', added_by: 'op-1', expected_version: 4,
    })
    expect(spy.mock.calls[0][0]).toBe(`${API}/tq_1/synonyms`)
    expect(JSON.parse(String(spy.mock.calls[0][1]?.body))).toEqual({
      expression: '门诊报销比例', added_by: 'op-1', expected_version: 4,
    })
    vi.unstubAllGlobals()

    spy = mockFetchOnce({ question_id: 'tq_1' })
    await removeTrustedQuestionSynonym('tq_1', '门诊报销比例', 5)
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(
      `${API}/tq_1/synonyms/${encodeURIComponent('门诊报销比例')}?expected_version=5`,
    )
    expect(init?.method).toBe('DELETE')
  })

  it('matchTrustedQuestion POST /match 并解析三态结果', async () => {
    const payload = {
      outcome: 'candidates',
      question: null,
      candidates: [
        { question_id: 'tq_1', standard_question: '甲', score: 0.8, matched_expression: '甲' },
      ],
    }
    const spy = mockFetchOnce(payload)
    const result = await matchTrustedQuestion({ question: '甲问题', role: 'cashier' })
    const [url, init] = spy.mock.calls[0]
    expect(url).toBe(`${API}/match`)
    expect(JSON.parse(String(init?.body))).toEqual({ question: '甲问题', role: 'cashier' })
    expect(result.outcome).toBe('candidates')
    expect(result.candidates[0].score).toBe(0.8)
  })
})
