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

  it('defaults to an accessible collapsed sidebar on mobile and keeps the keyboard toggle usable', async () => {
    const user = userEvent.setup()
    render(<LayoutShell><div>页面内容</div></LayoutShell>)

    const sidebar = screen.getByRole('complementary')
    const toggle = await screen.findByRole('button', { name: '展开侧栏' })
    expect(sidebar).toHaveClass('w-16')
    expect(screen.getByRole('link', { name: '技能' })).toBeVisible()
    expect(screen.queryByText('导航菜单')).not.toBeInTheDocument()

    toggle.focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('button', { name: '收起侧栏' })).toBeVisible()
    expect(sidebar).toHaveClass('w-56')
    expect(screen.getByText('导航菜单')).toBeVisible()
  })
})
