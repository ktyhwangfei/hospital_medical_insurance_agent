// 统一鉴权库（Issue #75 S3）：单一 portal-token 存储 + principal 解码 + 权限查询。
// 替代各域独立的 sessionStorage token 孤岛；后端仍是权限裁决的唯一权威。

const TOKEN_KEY = 'portal-token'
const API_PREFIX = '/api/v1/medical-insurance-ai-agent'

export interface Principal {
  user_id: string
  roles: string[]
  permissions: string[]
  exp: number
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(TOKEN_KEY)
}

// base64url 解码（与各域旧实现同一手法：还原 - _ 并补齐 padding）
function decodePayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.replace(/^Bearer\s+/i, '').split('.')[1]
    if (!payload) return null
    const base64 = payload
      .replace(/-/g, '+')
      .replace(/_/g, '/')
      .padEnd(Math.ceil(payload.length / 4) * 4, '=')
    const parsed: unknown = JSON.parse(atob(base64))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

export function getPrincipal(): Principal | null {
  const token = getToken()
  if (!token) return null
  const payload = decodePayload(token)
  // 主体字段为标准 JWT `sub` claim（与后端 token_issuer.py 签发格式对齐）
  if (!payload || typeof payload.sub !== 'string') return null
  // 本地 exp 预检：过期即视为未登录，最终以后端 401 为硬裁决
  if (typeof payload.exp === 'number' && payload.exp * 1000 <= Date.now()) return null
  return {
    user_id: payload.sub,
    roles: Array.isArray(payload.roles)
      ? payload.roles.filter((role): role is string => typeof role === 'string')
      : [],
    permissions: Array.isArray(payload.permissions)
      ? payload.permissions.filter((scope): scope is string => typeof scope === 'string')
      : [],
    exp: typeof payload.exp === 'number' ? payload.exp : 0,
  }
}

export function hasPermission(scope: string): boolean {
  const principal = getPrincipal()
  // dev 无 token 维持既有宽松行为；production 无 token = 无权限
  if (!principal) return process.env.NODE_ENV !== 'production'
  return principal.permissions.includes(scope)
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// 无登录态/登录失效统一跳登录页（保留当前完整路径）
export function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  const redirect = window.location.pathname + window.location.search
  window.location.assign(`/login?redirect=${encodeURIComponent(redirect)}`)
}

// 登录成功写 token 并返回本地解码的 principal（后端 /auth/me 为准）
export async function login(username: string, password: string): Promise<Principal> {
  const response = await fetch(`${API_PREFIX}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })

  if (!response.ok) {
    let message = '账号或密码错误'
    try {
      const body: unknown = await response.json()
      if (isRecord(body) && isRecord(body.detail) && typeof body.detail.message === 'string') {
        message = body.detail.message
      }
    } catch {
      // 保持默认文案
    }
    throw new Error(message)
  }

  const body: unknown = await response.json()
  if (!isRecord(body) || typeof body.access_token !== 'string' || !body.access_token) {
    throw new Error('登录响应缺少 access_token')
  }
  setToken(body.access_token)
  return getPrincipal() ?? { user_id: '', roles: [], permissions: [], exp: 0 }
}

// 滑动续签：持当前 token 换新 token；失败返回 null（不抛出，交由 401 兜底路径处理）
export async function refreshToken(): Promise<Principal | null> {
  const token = getToken()
  if (!token) return null
  try {
    const response = await fetch(`${API_PREFIX}/auth/refresh`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) return null
    const body: unknown = await response.json()
    if (!isRecord(body) || typeof body.access_token !== 'string' || !body.access_token) {
      return null
    }
    setToken(body.access_token)
    return getPrincipal()
  } catch {
    return null
  }
}

// 登出：先清本地 token 再通知后端拉黑（失败不阻断，交由 token 自然过期兑底）
export async function logout(): Promise<void> {
  const token = getToken()
  clearToken()
  if (!token) return
  try {
    await fetch(`${API_PREFIX}/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    // 本地登录态已清除
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
