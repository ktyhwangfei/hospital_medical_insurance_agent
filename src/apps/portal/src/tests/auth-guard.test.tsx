// 路由守卫测试（P2）：无登录态跳登录页；登录页自身与已登录用户不跳。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'

import { AuthProvider } from '@/components/auth-provider'
import { setToken } from '@/lib/auth'

function encodeBase64Url(payload: Record<string, unknown>): string {
  return btoa(JSON.stringify(payload)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
}

function makeToken(payload: Record<string, unknown>): string {
  return `header.${encodeBase64Url(payload)}.signature`
}

let pathname = '/policy-qa'
vi.mock('next/navigation', () => ({ usePathname: () => pathname }))

const assignMock = vi.fn()

describe('AuthProvider 路由守卫', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, pathname: '/policy-qa', assign: assignMock },
      writable: true,
    })
    assignMock.mockClear()
  })

  afterEach(() => {
    cleanup()
    window.sessionStorage.clear()
  })

  it('未登录访问业务页：跳登录页并带回跳路径', async () => {
    render(<AuthProvider><div>page</div></AuthProvider>)

    await waitFor(() => {
      expect(assignMock).toHaveBeenCalledWith('/login?redirect=%2Fpolicy-qa')
    })
  })

  it('登录页自身：不跳转（避免循环重定向）', async () => {
    pathname = '/login'
    render(<AuthProvider><div>login</div></AuthProvider>)

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(assignMock).not.toHaveBeenCalled()
  })

  it('已登录（有效 token）：正常渲染不跳转', async () => {
    pathname = '/policy-qa'
    setToken(makeToken({
      sub: 'zhangsan',
      roles: ['ops_admin'],
      permissions: ['policy_qa:ask'],
      exp: Math.floor(Date.now() / 1000) + 3600,
    }))
    render(<AuthProvider><div>page</div></AuthProvider>)

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(assignMock).not.toHaveBeenCalled()
  })
})
