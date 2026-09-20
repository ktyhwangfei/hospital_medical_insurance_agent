// Issue #75 A4 浏览器验收回归：requestJson 对认证类 401 的统一跳登录兜底。
// 后端 auth_deps.py 无凭证时返回 error_code=AUTH_REQUIRED（六域统一契约），
// 前端集合漏收该码会导致未登录访问治理页只显示错误横幅、不引导登录。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { requestJson } from '@/lib/api-client'
import { setToken } from '@/lib/auth'

function authRequiredResponse(): Response {
  return new Response(
    JSON.stringify({ detail: { error_code: 'AUTH_REQUIRED', message: '缺少 Authorization 凭据' } }),
    { status: 401, headers: { 'Content-Type': 'application/json' } },
  )
}

describe('requestJson 认证类 401 统一兜底（#75 A4 回归）', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(authRequiredResponse()))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    window.sessionStorage.clear()
    window.location.href = '/'
  })

  it('401 AUTH_REQUIRED（无凭证）清 token 并跳登录页带回跳', async () => {
    setToken('stale-token')
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign, pathname: '/question-library' })

    await expect(requestJson('/question-library/questions')).rejects.toThrow()
    expect(window.sessionStorage.getItem('portal-token')).toBeNull()
    expect(assign).toHaveBeenCalledWith('/login?redirect=%2Fquestion-library')
  })

  it('401 AUTH_INVALID（凭据无效）同样清 token 跳登录', async () => {
    setToken('bad-token')
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({ detail: { error_code: 'AUTH_INVALID', message: '登录凭据无效' } }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign, pathname: '/ops' })

    await expect(requestJson('/ops/findings')).rejects.toThrow()
    expect(window.sessionStorage.getItem('portal-token')).toBeNull()
    expect(assign).toHaveBeenCalledWith('/login?redirect=%2Fops')
  })
})
