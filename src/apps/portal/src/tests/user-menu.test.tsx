// Header 登录态出口测试（Issue #75 A1）：当前用户展示 / 登出 / 未登录入口。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { AuthProvider } from '@/components/auth-provider'
import { UserMenu } from '@/components/user-menu'
import { setToken } from '@/lib/auth'

vi.mock('next/navigation', () => ({ usePathname: () => '/ops' }))

function encodeBase64Url(payload: Record<string, unknown>): string {
  return btoa(JSON.stringify(payload)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
}

function makeToken(payload: Record<string, unknown>): string {
  return `header.${encodeBase64Url(payload)}.signature`
}

const assignMock = vi.fn()

describe('UserMenu（Header 登录态出口）', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, pathname: '/ops', assign: assignMock },
      writable: true,
    })
    assignMock.mockClear()
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    window.sessionStorage.clear()
  })

  it('已登录：展示账号与角色中文名，登出按钮可点', () => {
    setToken(makeToken({
      sub: 'zhangsan',
      roles: ['knowledge_admin'],
      permissions: ['question_library:read'],
      exp: Math.floor(Date.now() / 1000) + 3600,
    }))
    render(<AuthProvider><UserMenu /></AuthProvider>)

    expect(screen.getByText('zhangsan')).toBeTruthy()
    expect(screen.getByText('知识管理员')).toBeTruthy()
    expect(screen.getByRole('button', { name: '退出登录' })).toBeTruthy()
  })

  it('登出：拉黑后端 token、清本地登录态并跳登录页（带回跳）', async () => {
    setToken(makeToken({
      sub: 'lisi',
      roles: ['admin'],
      permissions: ['ops:read'],
      exp: Math.floor(Date.now() / 1000) + 3600,
    }))
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<AuthProvider><UserMenu /></AuthProvider>)
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }))

    await waitFor(() => {
      expect(assignMock).toHaveBeenCalledWith('/login?redirect=%2Fops')
    })
    await waitFor(() => {
      const [url, init] = fetchMock.mock.calls[0]
      expect(String(url)).toContain('/api/v1/medical-insurance-ai-agent/auth/logout')
      expect(init.headers.Authorization).toMatch(/^Bearer header\./)
    })
    expect(window.sessionStorage.getItem('portal-token')).toBeNull()
  })

  it('未登录：展示登录入口，无登出按钮', () => {
    render(<AuthProvider><UserMenu /></AuthProvider>)

    const loginLink = screen.getByText('登录').closest('a')
    expect(loginLink?.getAttribute('href')).toBe('/login')
    expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull()
  })

  it('未知角色回退展示原始角色码', () => {
    setToken(makeToken({
      sub: 'wangwu',
      roles: ['new_role'],
      permissions: [],
      exp: Math.floor(Date.now() / 1000) + 3600,
    }))
    render(<AuthProvider><UserMenu /></AuthProvider>)

    expect(screen.getByText('new_role')).toBeTruthy()
  })
})
