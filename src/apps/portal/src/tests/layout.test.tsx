import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('next/navigation', () => ({ usePathname: () => '/skills' }))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}))
vi.mock('@/lib/api-context', () => ({
  ApiProvider: ({ children }: { children: ReactNode }) => children,
  useApiContext: () => ({ connectionStatus: 'connected' }),
}))
vi.mock('@/components/role-switcher', () => ({ default: () => <button type="button">切换角色</button> }))

import { LayoutShell } from '../../app/layout'

describe('LayoutShell responsive sidebar', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: true,
        media: '(max-width: 767px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
  })

  it('uses a zero-width mobile drawer, keyboard controls, and leaves the page with one H1', async () => {
    const user = userEvent.setup()
    render(<LayoutShell><h1>Skill 日常治理</h1></LayoutShell>)

    const sidebar = screen.getByRole('complementary')
    const toggle = await screen.findByRole('button', { name: '打开导航菜单' })
    expect(sidebar).toHaveClass('-translate-x-full')
    expect(sidebar).toHaveClass('fixed')
    expect(screen.getByRole('link', { name: '技能' })).toBeVisible()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)

    toggle.focus()
    await user.keyboard('{Enter}')
    const close = screen.getByRole('button', { name: '关闭导航菜单' })
    expect(close).toBeVisible()
    expect(sidebar).toHaveClass('w-56')
    expect(screen.getByText('导航菜单')).toBeVisible()
    expect(screen.getByRole('button', { name: '关闭导航菜单遮罩' })).toBeVisible()

    close.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('button', { name: '打开导航菜单' })).toBeVisible()
    expect(sidebar).toHaveClass('-translate-x-full')
  })
})
