// 统一鉴权库 auth.ts 的单元测试（Issue #75 S3）
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  authHeaders,
  clearToken,
  getPrincipal,
  getToken,
  hasPermission,
  login,
  logout,
  refreshToken,
  setToken,
} from '../auth'

function encodeBase64Url(payload: Record<string, unknown>): string {
  return btoa(JSON.stringify(payload)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
}

function makeToken(payload: Record<string, unknown>): string {
  return `header.${encodeBase64Url(payload)}.signature`
}

describe('auth.ts（portal-token 统一鉴权）', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    window.sessionStorage.clear()
  })

  describe('getToken / setToken / clearToken', () => {
    it('setToken 写入 sessionStorage，getToken 原样读回', () => {
      setToken('abc.def.ghi')
      expect(getToken()).toBe('abc.def.ghi')
      expect(window.sessionStorage.getItem('portal-token')).toBe('abc.def.ghi')
    })

    it('clearToken 移除 token，getToken 返回 null', () => {
      setToken('abc')
      clearToken()
      expect(getToken()).toBeNull()
    })

    it('无 token 时 getToken 返回 null', () => {
      expect(getToken()).toBeNull()
    })
  })

  describe('getPrincipal', () => {
    // 回归（A4 浏览器验收发现）：后端 token_issuer.py 签发的 JWT 主体字段是标准 `sub`，
    // 不是 `user_id`。前端必须按后端真实格式解码，否则登录后 principal 恒为 null。
    it('解码后端真实签发格式（sub claim）返回 principal', () => {
      setToken(makeToken({
        sub: 'admin',
        roles: ['admin'],
        permissions: ['workflow:write'],
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + 7200,
      }))
      const principal = getPrincipal()
      expect(principal?.user_id).toBe('admin')
      expect(principal?.roles).toEqual(['admin'])
    })

    it('解码 payload 返回 principal', () => {
      setToken(makeToken({
        sub: 'u-001',
        roles: ['information_department'],
        permissions: ['workflow:write', 'ops:read'],
        exp: Math.floor(Date.now() / 1000) + 3600,
      }))
      expect(getPrincipal()).toEqual({
        user_id: 'u-001',
        roles: ['information_department'],
        permissions: ['workflow:write', 'ops:read'],
        exp: expect.any(Number),
      })
    })

    it('容忍存储值带 Bearer 前缀', () => {
      setToken(`Bearer ${makeToken({ sub: 'u-002', exp: Math.floor(Date.now() / 1000) + 60 })}`)
      expect(getPrincipal()?.user_id).toBe('u-002')
    })

    it('exp 已过（exp*1000 <= now）视为 null', () => {
      setToken(makeToken({ sub: 'u-003', exp: Math.floor(Date.now() / 1000) - 1 }))
      expect(getPrincipal()).toBeNull()
    })

    it('payload 非法或缺 sub 视为 null', () => {
      setToken('not-a-jwt')
      expect(getPrincipal()).toBeNull()
      setToken(makeToken({ exp: Math.floor(Date.now() / 1000) + 60 }))
      expect(getPrincipal()).toBeNull()
    })
  })

  describe('hasPermission', () => {
    it('有 principal 时按 permissions 判定', () => {
      setToken(makeToken({
        sub: 'u-004',
        permissions: ['workflow:write'],
        exp: Math.floor(Date.now() / 1000) + 3600,
      }))
      expect(hasPermission('workflow:write')).toBe(true)
      expect(hasPermission('ops:write')).toBe(false)
    })

    it('无 token 时 dev 环境宽松返回 true', () => {
      vi.stubEnv('NODE_ENV', 'development')
      expect(hasPermission('workflow:write')).toBe(true)
    })

    it('无 token 时 production 返回 false', () => {
      vi.stubEnv('NODE_ENV', 'production')
      expect(hasPermission('workflow:write')).toBe(false)
    })
  })

  describe('authHeaders', () => {
    it('有 token 返回 Bearer Authorization', () => {
      setToken('raw-token')
      expect(authHeaders()).toEqual({ Authorization: 'Bearer raw-token' })
    })

    it('无 token 返回空对象', () => {
      expect(authHeaders()).toEqual({})
    })
  })

  describe('login', () => {
    it('成功时写 token 并返回解码的 principal', async () => {
      const exp = Math.floor(Date.now() / 1000) + 3600
      const accessToken = makeToken({ sub: 'portal-user', roles: [], permissions: ['ops:read'], exp })
      const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
        access_token: accessToken,
        token_type: 'bearer',
        expires_in: 3600,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      vi.stubGlobal('fetch', fetchMock)

      const principal = await login('portal-user', 'secret')

      const [url, init] = fetchMock.mock.calls[0]
      expect(String(url)).toContain('/api/v1/medical-insurance-ai-agent/auth/login')
      expect(init.method).toBe('POST')
      expect(JSON.parse(init.body)).toEqual({ username: 'portal-user', password: 'secret' })
      expect(principal.user_id).toBe('portal-user')
      expect(getToken()).toBe(accessToken)
    })

    it('失败时 throw 后端 message 且不写 token', async () => {
      const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
        detail: { error_code: 'AUTH_INVALID', message: '账号或密码错误' },
      }), { status: 401, headers: { 'Content-Type': 'application/json' } }))
      vi.stubGlobal('fetch', fetchMock)

      await expect(login('bad', 'wrong')).rejects.toThrow('账号或密码错误')
      expect(getToken()).toBeNull()
    })
  })

  describe('refreshToken（滑动续签）', () => {
    it('成功时携带旧 Bearer 换新 token 并返回 principal', async () => {
      const oldToken = makeToken({ sub: 'u-refresh', roles: [], permissions: ['ops:read'], exp: Math.floor(Date.now() / 1000) + 60 })
      setToken(oldToken)
      const newToken = makeToken({ sub: 'u-refresh', roles: [], permissions: ['ops:read'], exp: Math.floor(Date.now() / 1000) + 7200 })
      const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
        access_token: newToken,
        token_type: 'bearer',
        expires_in: 7200,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      vi.stubGlobal('fetch', fetchMock)

      const principal = await refreshToken()

      const [url, init] = fetchMock.mock.calls[0]
      expect(String(url)).toContain('/api/v1/medical-insurance-ai-agent/auth/refresh')
      expect(init.method).toBe('POST')
      expect(init.headers.Authorization).toBe(`Bearer ${oldToken}`)
      expect(principal?.user_id).toBe('u-refresh')
      expect(getToken()).toBe(newToken)
    })

    it('后端拒绝（401 超绝对上限）时返回 null 且保留旧 token', async () => {
      const oldToken = makeToken({ sub: 'u-refresh', exp: Math.floor(Date.now() / 1000) + 60 })
      setToken(oldToken)
      const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
        detail: { error_code: 'EXPIRED_TOKEN', message: '会话已超时可续期上限' },
      }), { status: 401, headers: { 'Content-Type': 'application/json' } }))
      vi.stubGlobal('fetch', fetchMock)

      await expect(refreshToken()).resolves.toBeNull()
      expect(getToken()).toBe(oldToken)
    })

    it('无 token 时直接返回 null 不发请求', async () => {
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)

      await expect(refreshToken()).resolves.toBeNull()
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })

  describe('logout（服务端登出）', () => {
    it('先清本地 token，再携带 Bearer 调用 /auth/logout', async () => {
      const token = makeToken({ sub: 'u-logout', exp: Math.floor(Date.now() / 1000) + 3600 })
      setToken(token)
      const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
      vi.stubGlobal('fetch', fetchMock)

      await logout()

      expect(getToken()).toBeNull()
      const [url, init] = fetchMock.mock.calls[0]
      expect(String(url)).toContain('/api/v1/medical-insurance-ai-agent/auth/logout')
      expect(init.method).toBe('POST')
      expect(init.headers.Authorization).toBe(`Bearer ${token}`)
    })

    it('黑名单请求失败不阻断本地登出', async () => {
      setToken(makeToken({ sub: 'u-logout', exp: Math.floor(Date.now() / 1000) + 3600 }))
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))

      await expect(logout()).resolves.toBeUndefined()
      expect(getToken()).toBeNull()
    })

    it('无 token 时不发请求', async () => {
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)

      await expect(logout()).resolves.toBeUndefined()
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })
})
