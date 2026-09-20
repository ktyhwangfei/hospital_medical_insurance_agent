'use client'

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import {
  getPrincipal,
  hasPermission as authHasPermission,
  logout as revokeToken,
  redirectToLogin,
  refreshToken,
  type Principal,
} from '@/lib/auth'

// Issue #75 S3：全局登录态上下文。principal 以 portal-token 本地解码为准，
// 权限渲染仅为体验层，后端 401/403 仍是硬边界。
interface AuthContextValue {
  principal: Principal | null
  hasPermission: (scope: string) => boolean
  refresh: () => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// 滑动续签（D5）：token 剩余不足 10 分钟时每分钟尝试一次 /auth/refresh；
// 失败不强制跳转（避免打断填表中的用户），过期后由既有 401 兜底路径引导重登。
const REFRESH_THRESHOLD_MS = 10 * 60 * 1000
const REFRESH_INTERVAL_MS = 60 * 1000

export function AuthProvider({ children }: { children: ReactNode }) {
  const [principal, setPrincipal] = useState<Principal | null>(() => getPrincipal())
  const pathname = usePathname()

  // 路由守卫（P2）：非登录页且无有效登录态 → 跳登录页；后端 401/403 仍是硬边界
  useEffect(() => {
    if (pathname === '/login') return
    if (!getPrincipal()) redirectToLogin()
  }, [pathname])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (window.location.pathname === '/login') return
      const current = getPrincipal()
      // 登录态已失效（过期/清除）→ 跳登录页重登
      if (!current) {
        redirectToLogin()
        return
      }
      if (current.exp * 1000 - Date.now() > REFRESH_THRESHOLD_MS) return
      void refreshToken().then((next) => {
        if (next) setPrincipal(next)
      })
    }, REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [])

  const refresh = useCallback(() => {
    setPrincipal(getPrincipal())
  }, [])

  const logout = useCallback(() => {
    void revokeToken()
    setPrincipal(null)
    if (typeof window !== 'undefined') {
      const redirect = window.location.pathname
      window.location.assign(`/login?redirect=${encodeURIComponent(redirect)}`)
    }
  }, [])

  const value: AuthContextValue = {
    principal,
    hasPermission: authHasPermission,
    refresh,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
