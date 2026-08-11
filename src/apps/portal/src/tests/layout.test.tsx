import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
  afterEach(cleanup)

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
    const { container } = render(<LayoutShell><h1>Skill 日常治理</h1></LayoutShell>)

    const sidebar = container.querySelector('aside')!
    const toggle = await screen.findByRole('button', { name: '打开导航菜单' })
    expect(sidebar).toHaveClass('-translate-x-full')
    expect(sidebar).toHaveClass('fixed')
    expect(sidebar).toHaveAttribute('inert')
    expect(sidebar).toHaveAttribute('aria-hidden', 'true')
    expect(screen.queryByRole('link', { name: '技能' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)

    toggle.focus()
    await user.keyboard('{Enter}')
    const close = screen.getByRole('button', { name: '关闭导航菜单' })
    await waitFor(() => expect(close).toHaveFocus())
    expect(close).toBeVisible()
    expect(sidebar).toHaveClass('w-56')
    expect(sidebar).not.toHaveAttribute('inert')
    expect(sidebar).not.toHaveAttribute('aria-hidden')
    expect(screen.getByText('导航菜单')).toBeVisible()
    expect(screen.getByRole('button', { name: '关闭导航菜单遮罩' })).toBeVisible()

    await user.keyboard('{Escape}')
    const restoredToggle = await screen.findByRole('button', { name: '打开导航菜单' })
    await waitFor(() => expect(restoredToggle).toHaveFocus())
    expect(sidebar).toHaveClass('-translate-x-full')
    expect(sidebar).toHaveAttribute('inert')
  })

  it('restores focus after button and overlay closes', async () => {
    const user = userEvent.setup()
    render(<LayoutShell><h1>Skill 日常治理</h1></LayoutShell>)

    const open = await screen.findByRole('button', { name: '打开导航菜单' })
    await user.click(open)
    const close = screen.getByRole('button', { name: '关闭导航菜单' })
    await waitFor(() => expect(close).toHaveFocus())
    await user.click(close)
    await waitFor(() => expect(screen.getByRole('button', { name: '打开导航菜单' })).toHaveFocus())

    await user.click(screen.getByRole('button', { name: '打开导航菜单' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '关闭导航菜单' })).toHaveFocus())
    await user.click(screen.getByRole('button', { name: '关闭导航菜单遮罩' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '打开导航菜单' })).toHaveFocus())
  })

  it('keeps desktop collapsed icon navigation in the keyboard accessibility tree', async () => {
    const user = userEvent.setup()
    vi.mocked(window.matchMedia).mockReturnValue({
      matches: false,
      media: '(max-width: 767px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList)
    render(<LayoutShell><h1>Skill 日常治理</h1></LayoutShell>)

    await user.click(screen.getByRole('button', { name: '收起侧栏' }))
    expect(screen.getByRole('link', { name: '技能' })).toBeVisible()
  })
})
