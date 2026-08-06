import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PolicyComposer from '@/components/policy-qa/policy-composer'

afterEach(() => cleanup())

describe('PolicyComposer', () => {
  it('shows settlement context inside the composer', () => {
    render(
      <PolicyComposer
        settlementId="1671213"
        value=""
        onChange={vi.fn()}
        onSend={vi.fn()}
      />,
    )

    expect(screen.getByText('结算单 1671213')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', '继续追问当前结算单…')
  })

  it('submits with Enter but keeps Shift+Enter for a new line', () => {
    const onSend = vi.fn()
    render(
      <PolicyComposer
        settlementId="1671213"
        value="统筹自付为什么这么多"
        onChange={vi.fn()}
        onSend={onSend}
      />,
    )
    const textbox = screen.getByRole('textbox')

    fireEvent.keyDown(textbox, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()

    fireEvent.keyDown(textbox, { key: 'Enter' })
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('disables sending empty input or while streaming', () => {
    const { rerender } = render(
      <PolicyComposer
        settlementId={null}
        value="  "
        onChange={vi.fn()}
        onSend={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()

    rerender(
      <PolicyComposer
        settlementId="1671213"
        value="继续追问"
        onChange={vi.fn()}
        onSend={vi.fn()}
        isStreaming
      />,
    )
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  })
})
