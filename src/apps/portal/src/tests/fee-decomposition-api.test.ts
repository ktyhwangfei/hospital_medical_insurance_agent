// 费用分解工作台 API 客户端测试 — Issue #78 Phase 3。
// 覆盖：decompose 请求路径/方法/body、token 注入（sessionStorage → env 回退）、503 错误映射；
// resolvePerson 请求路径/body/token；looksLikeIdCard 格式判定。
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  decomposeFee,
  looksLikeIdCard,
  resolvePerson,
  type FeeDecompositionResponseDto,
  type ResolvePersonResponseDto,
} from '@/lib/fee-decomposition-api'
import { ApiClientError } from '@/lib/types'

const DECOMPOSE_URL = '/api/v1/medical-insurance-ai-agent/fee-decomposition/decompose'
const RESOLVE_PERSON_URL = '/api/v1/medical-insurance-ai-agent/fee-decomposition/resolve-person'

const RESPONSE: FeeDecompositionResponseDto = {
  schema_version: '1.0',
  algorithm_version: 'fee-decomp-v1',
  execution_status: 'complete',
  reconciliation_status: 'matched',
  summary_text: '本笔门诊费用分解核对完成。',
  summary_source: 'template',
  may_claim_full_explanation: true,
  fields: [],
  uncertainties: [],
  coverage: null,
  meta: {
    identifier: 'T123456789012345',
    chain: 'outpatient',
    profile: 'employee_outpatient',
    algorithm_version: 'fee-decomp-v1',
  },
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function okResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  window.sessionStorage.clear()
})

describe('decomposeFee', () => {
  it('POST 到 /fee-decomposition/decompose，body 携带 identifier 与 chain', async () => {
    const fetchMock = stubFetch(okResponse(RESPONSE))

    const result = await decomposeFee('T123456789012345', 'outpatient')

    expect(result.meta.chain).toBe('outpatient')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(DECOMPOSE_URL)
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      identifier: 'T123456789012345',
      chain: 'outpatient',
    })
  })

  it('chain 缺省传 auto', async () => {
    const fetchMock = stubFetch(okResponse(RESPONSE))
    await decomposeFee('604')
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual({ identifier: '604', chain: 'auto' })
  })

  it('sessionStorage token 注入 Authorization 头', async () => {
    window.sessionStorage.setItem('fee-decomposition-token', 'session-jwt')
    const fetchMock = stubFetch(okResponse(RESPONSE))

    await decomposeFee('604')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer session-jwt')
  })

  it('sessionStorage 为空时回退 NEXT_PUBLIC_FEE_DECOMPOSITION_TOKEN', async () => {
    vi.stubEnv('NEXT_PUBLIC_FEE_DECOMPOSITION_TOKEN', 'env-jwt')
    const fetchMock = stubFetch(okResponse(RESPONSE))

    await decomposeFee('604')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer env-jwt')
  })

  it('未配置 503：抛出 ApiClientError，携带 FEE_DECOMPOSITION_NOT_CONFIGURED 与缺失项说明', async () => {
    stubFetch(
      new Response(
        JSON.stringify({
          detail: {
            error_code: 'FEE_DECOMPOSITION_NOT_CONFIGURED',
            message: '费用分解未配置：缺少 FEE_DECOMPOSITION_ROUNDING_MODE',
            audit_event: {},
          },
        }),
        { status: 503, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const error = await decomposeFee('604').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiClientError)
    if (!(error instanceof ApiClientError)) throw error
    expect(error.status).toBe(503)
    expect(error.detail.error_code).toBe('FEE_DECOMPOSITION_NOT_CONFIGURED')
    expect(error.detail.message).toContain('FEE_DECOMPOSITION_ROUNDING_MODE')
  })
})

const RESOLVE_RESPONSE: ResolvePersonResponseDto = {
  match_status: 'multiple_candidates',
  truncated: false,
  candidates: [
    {
      chain: 'outpatient',
      identifier: 'T123456789012345',
      chain_label: '普通门诊',
      profile_label: '职工门诊',
      service_date: '2025-11-02',
      total_amount: '6.50',
    },
    {
      chain: 'special',
      identifier: '604',
      chain_label: '门诊特殊病',
      profile_label: '居民门特',
      service_date: null,
      total_amount: null,
    },
  ],
}

describe('resolvePerson', () => {
  it('POST 到 /fee-decomposition/resolve-person，body 携带 id_card', async () => {
    const fetchMock = stubFetch(okResponse(RESOLVE_RESPONSE))

    const result = await resolvePerson('110101199001011234')

    expect(result.match_status).toBe('multiple_candidates')
    expect(result.candidates).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(RESOLVE_PERSON_URL)
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ id_card: '110101199001011234' })
  })

  it('sessionStorage token 注入 Authorization 头', async () => {
    window.sessionStorage.setItem('fee-decomposition-token', 'session-jwt')
    const fetchMock = stubFetch(okResponse(RESOLVE_RESPONSE))

    await resolvePerson('110101199001011234')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer session-jwt')
  })

  it('sessionStorage 为空时回退 NEXT_PUBLIC_FEE_DECOMPOSITION_TOKEN', async () => {
    vi.stubEnv('NEXT_PUBLIC_FEE_DECOMPOSITION_TOKEN', 'env-jwt')
    const fetchMock = stubFetch(okResponse(RESOLVE_RESPONSE))

    await resolvePerson('110101199001011234')

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(init.headers)
    expect(headers.get('Authorization')).toBe('Bearer env-jwt')
  })

  it('422 身份证格式非法：抛出 ApiClientError 并透传 error_code', async () => {
    stubFetch(
      new Response(
        JSON.stringify({
          detail: { error_code: 'ID_CARD_INVALID', message: '身份证号格式非法', audit_event: {} },
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const error = await resolvePerson('123').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiClientError)
    if (!(error instanceof ApiClientError)) throw error
    expect(error.status).toBe(422)
    expect(error.detail.error_code).toBe('ID_CARD_INVALID')
  })
})

describe('looksLikeIdCard', () => {
  it('15 位纯数字命中', () => {
    expect(looksLikeIdCard('110101900101123')).toBe(true)
  })

  it('17 位数字 + 数字末位命中', () => {
    expect(looksLikeIdCard('110101199001011234')).toBe(true)
  })

  it('17 位数字 + X/x 末位命中', () => {
    expect(looksLikeIdCard('11010119900101123X')).toBe(true)
    expect(looksLikeIdCard('11010119900101123x')).toBe(true)
  })

  it('前后空白 trim 后判定', () => {
    expect(looksLikeIdCard('  110101199001011234  ')).toBe(true)
  })

  it('交易号不误判', () => {
    expect(looksLikeIdCard('T123456789012345')).toBe(false)
    expect(looksLikeIdCard('T1234567890123456')).toBe(false)
  })

  it('门特登记号 djh 短号不误判', () => {
    expect(looksLikeIdCard('604')).toBe(false)
    expect(looksLikeIdCard('12345678')).toBe(false)
    expect(looksLikeIdCard('12345678901234')).toBe(false)
  })

  it('16 位纯数字不命中（既非 15 位也非 18 位）', () => {
    expect(looksLikeIdCard('1234567890123456')).toBe(false)
  })
})
