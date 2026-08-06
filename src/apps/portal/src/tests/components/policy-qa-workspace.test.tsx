import { cleanup, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import PolicyQAWorkspace from '@/components/policy-qa/policy-qa-workspace'

afterEach(() => cleanup())

beforeAll(() => {
  vi.stubGlobal('scrollTo', vi.fn())
  Element.prototype.scrollIntoView = vi.fn()
})

afterAll(() => vi.unstubAllGlobals())

describe('PolicyQAWorkspace', () => {
  it('uses a single centered reading column', () => {
    const { container } = render(<PolicyQAWorkspace />)

    expect(container.querySelector('[data-testid="policy-qa-reading-column"]')).toHaveClass(
      'max-w-[840px]',
    )
    expect(screen.queryByText('会话记忆')).not.toBeInTheDocument()
    expect(screen.queryByText('本轮执行链路')).not.toBeInTheDocument()
  })

  it('starts with the chat-first empty state and composer', () => {
    render(<PolicyQAWorkspace />)

    expect(screen.getByRole('heading', { name: '政策问答' })).toBeInTheDocument()
    expect(screen.getByText('先问一个与当前结算相关的问题')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect(screen.getByText('回答仅供解释参考，不作为报销或结算依据。')).toBeInTheDocument()
  })
})
