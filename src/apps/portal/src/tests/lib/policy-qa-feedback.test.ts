import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  listEvalCasePool,
  submitPolicyQAFeedback,
  type PolicyQAFeedbackPayload,
} from '@/lib/policy-qa-feedback'
import { API_PREFIX } from '@/lib/api-client'

const FEEDBACK_URL = `${API_PREFIX}/policy-qa/feedback`

function mockResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
    headers: new Headers(),
  } as unknown as Response
}

describe('submitPolicyQAFeedback', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('posts only qa_turn_id + reason_code + comment (no forged source)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({
        pool_id: 'pool_1',
        status: 'pending_triage',
        error_dimension: 'calculation',
        source_selected_skill_id: 'deductible',
      }),
    )

    await submitPolicyQAFeedback({
      qaTurnId: 'qat_1',
      reasonCode: 'wrong_calculation',
      comment: '口径不对',
    })

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(Object.keys(body).sort()).toEqual(['comment', 'qa_turn_id', 'reason_code'])
    expect(body).toEqual({
      qa_turn_id: 'qat_1',
      reason_code: 'wrong_calculation',
      comment: '口径不对',
    })
  })

  it('uses the same demo principal as policy QA turns in development', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({
        pool_id: 'pool_auth',
        status: 'pending_triage',
        error_dimension: 'policy_content',
        source_selected_skill_id: 'mzsettlement_verify_skill',
      }),
    )

    await submitPolicyQAFeedback({
      qaTurnId: 'qat_auth',
      reasonCode: 'wrong_policy_content',
      comment: null,
    })

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const authorization = new Headers((init as RequestInit).headers).get('Authorization')
    expect(authorization).toMatch(/^Bearer test\./)
    const encoded = authorization!.slice('Bearer '.length).split('.')[1]
    const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=')))
    expect(payload.sub).toBe('demo')
  })

  it('maps snake_case response to camelCase', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({
        pool_id: 'pool_2',
        status: 'pending_triage',
        error_dimension: 'citation',
        source_selected_skill_id: 'settlement',
      }),
    )

    const result = await submitPolicyQAFeedback({
      qaTurnId: 'qat_2',
      reasonCode: 'wrong_citation',
      comment: null,
    })

    expect(result).toEqual({
      poolId: 'pool_2',
      status: 'pending_triage',
      errorDimension: 'citation',
      sourceSelectedSkillId: 'settlement',
    })
  })

  it('returns identical poolId on duplicate (idempotent)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({
        pool_id: 'pool_dup',
        status: 'pending_triage',
        error_dimension: 'calculation',
        source_selected_skill_id: 'deductible',
      }),
    )

    const first = await submitPolicyQAFeedback({
      qaTurnId: 'qat_dup',
      reasonCode: 'wrong_calculation',
      comment: null,
    })
    const second = await submitPolicyQAFeedback({
      qaTurnId: 'qat_dup',
      reasonCode: 'wrong_calculation',
      comment: null,
    })

    expect(first.poolId).toBe(second.poolId)
  })

  it('throws on 404 (cross-tenant, no disclosure)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({ detail: '问答轮次不存在或无权访问' }, false, 404),
    )
    await expect(
      submitPolicyQAFeedback({
        qaTurnId: 'qat_other',
        reasonCode: 'wrong_routing',
        comment: null,
      }),
    ).rejects.toThrow()
    expect(fetch).toHaveBeenCalledWith(FEEDBACK_URL, expect.any(Object))
  })

  it('type check: payload only carries allowed fields', () => {
    const payload: PolicyQAFeedbackPayload = {
      qaTurnId: 'qat_1',
      reasonCode: 'wrong_calculation',
      comment: 'x',
    }
    expect(payload.qaTurnId).toBe('qat_1')
  })
})

describe('listEvalCasePool', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('maps list response items to camelCase', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({
        items: [
          {
            pool_id: 'pool_a',
            tenant_id: 'default',
            source_qa_turn_id: 'qat_a',
            source_user_id: 'user_a',
            reason_code: 'wrong_calculation',
            error_dimension: 'calculation',
            initial_dimension: 'calculation',
            transformed_dimension: null,
            target_skill_id: 'deductible',
            status: 'pending_triage',
            revision: 1,
            eval_case_ref: null,
            created_at: '2026-08-10T00:00:00Z',
            updated_at: '2026-08-10T00:00:00Z',
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    )

    const result = await listEvalCasePool({ status: 'pending_triage' })

    expect(result.items[0].poolId).toBe('pool_a')
    expect(result.items[0].errorDimension).toBe('calculation')
    expect(result.total).toBe(1)
  })
})
