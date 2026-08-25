import type { MouseEvent, ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('next/navigation', () => ({ usePathname: () => '/skills' }))
vi.mock('next/link', () => ({
  default: ({ children, href, onClick, ...props }: {
    children: ReactNode
    href: string
    onClick?: (event: MouseEvent<HTMLAnchorElement>) => void
  }) => (
    <a href={href} {...props} onClick={(event) => { event.preventDefault(); onClick?.(event) }}>{children}</a>
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

  it('keeps the mobile header compact and prevents product or connection labels from character wrapping', async () => {
    const { container } = render(<LayoutShell><h1>Skill 日常治理</h1></LayoutShell>)

    await screen.findByRole('button', { name: '打开导航菜单' })
    const header = container.querySelector('header')!
    expect(within(header).getByText('医保AI导办平台')).toHaveClass('hidden', 'whitespace-nowrap', 'sm:block')
    expect(within(header).getByText('已连接')).toHaveClass('hidden', 'whitespace-nowrap', 'sm:inline-flex')
  })

  it('makes the main area inert, loops drawer focus, and closes the drawer from navigation', async () => {
    const user = userEvent.setup()
    render(<LayoutShell><h1>Skill 日常治理</h1></LayoutShell>)

    const mainArea = screen.getByRole('main').parentElement!
    await user.click(await screen.findByRole('button', { name: '打开导航菜单' }))
    const close = screen.getByRole('button', { name: '关闭导航菜单' })
    await waitFor(() => expect(close).toHaveFocus())
    expect(mainArea).toHaveAttribute('inert')
    expect(mainArea).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('button', { name: '关闭导航菜单遮罩' })).toHaveAttribute('tabindex', '-1')

    await user.tab({ shift: true })
    expect(screen.getByRole('link', { name: '后台管理' })).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()

    await user.click(screen.getByRole('link', { name: '技能' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '打开导航菜单' })).toHaveFocus())
    expect(mainArea).not.toHaveAttribute('inert')
    expect(mainArea).not.toHaveAttribute('aria-hidden')
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
