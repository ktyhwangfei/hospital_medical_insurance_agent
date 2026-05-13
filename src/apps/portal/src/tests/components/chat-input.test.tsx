import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatInput from '@/components/chat/chat-input'

describe('ChatInput', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  const baseProps = {
    input: '',
    setInput: vi.fn(),
    isLoading: false,
    onSend: vi.fn(),
  }

  it('renders input field and send button', () => {
    render(<ChatInput {...baseProps} />)
    expect(screen.getByTestId('chat-input')).toBeInTheDocument()
    expect(screen.getByTestId('send-button')).toBeInTheDocument()
  })

  it('calls onSend when send button clicked', async () => {
    const onSend = vi.fn()
    render(<ChatInput {...baseProps} onSend={onSend} input="hello" />)
    await userEvent.click(screen.getByTestId('send-button'))
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('calls onSend when Enter pressed', async () => {
    const onSend = vi.fn()
    render(<ChatInput {...baseProps} onSend={onSend} />)
    const input = screen.getByTestId('chat-input')
    await userEvent.type(input, '{Enter}')
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('disables send button when loading', () => {
    render(<ChatInput {...baseProps} isLoading={true} />)
    expect(screen.getByTestId('send-button')).toBeDisabled()
  })

  it('shows loader icon in button when loading', () => {
    render(<ChatInput {...baseProps} isLoading={true} />)
    expect(screen.getByTestId('loader-icon')).toBeInTheDocument()
  })

  it('calls setInput when typing', async () => {
    const setInput = vi.fn()
    render(<ChatInput {...baseProps} setInput={setInput} />)
    const input = screen.getByTestId('chat-input')
    await userEvent.type(input, 'a')
    expect(setInput).toHaveBeenCalled()
  })
})
