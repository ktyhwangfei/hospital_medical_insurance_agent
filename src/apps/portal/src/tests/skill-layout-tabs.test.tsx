import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

import SkillsLayout from '../../app/skills/layout'

const { mockPathname, mockPush } = vi.hoisted(() => ({
  mockPathname: vi.fn(() => '/skills'),
  mockPush: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname(),
  useRouter: () => ({ push: mockPush }),
}))

function tabs() {
  return {
    governance: screen.getByRole('button', { name: '治理待办' }),
    drafts: screen.getByRole('button', { name: '草稿' }),
  }
}

function renderAt(pathname: string) {
  mockPathname.mockReturnValue(pathname)
  render(<SkillsLayout><div /></SkillsLayout>)
  return tabs()
}

afterEach(cleanup)

describe('skills layout active tab', () => {
  it('/skills 高亮治理待办', () => {
    const { governance } = renderAt('/skills')
    expect(governance).toHaveAttribute('aria-current', 'page')
  })

  it('/skills/<skillId> 详情页高亮治理待办', () => {
    const { governance } = renderAt('/skills/settlement_explain_skill')
    expect(governance).toHaveAttribute('aria-current', 'page')
  })

  it('/skills/new 高亮草稿', () => {
    const { drafts } = renderAt('/skills/new')
    expect(drafts).toHaveAttribute('aria-current', 'page')
  })

  it('/skills/import 高亮草稿', () => {
    const { drafts } = renderAt('/skills/import')
    expect(drafts).toHaveAttribute('aria-current', 'page')
  })

  it('/skills/drafts 高亮草稿', () => {
    const { drafts } = renderAt('/skills/drafts')
    expect(drafts).toHaveAttribute('aria-current', 'page')
  })
})
