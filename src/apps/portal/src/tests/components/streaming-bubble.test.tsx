import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import StreamingBubble from '@/components/chat/streaming-bubble'

// Mock Typewriter to a simple span so we can verify text prop is passed through
vi.mock('@/components/chat/typewriter', () => ({
  Typewriter: ({ text }: { text: string }) => <span>{text}</span>,
}))

describe('StreamingBubble', () => {
  const baseProps = {
    isStreaming: false,
    streamingContent: '',
    steps: [],
  }

  it('renders streaming indicator container', () => {
    render(<StreamingBubble {...baseProps} />)
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument()
  })

  it('passes streaming content to Typewriter', () => {
    render(
      <StreamingBubble
        {...baseProps}
        isStreaming={true}
        streamingContent="正在为您查询医保信息..."
      />,
    )
    expect(screen.getByText('正在为您查询医保信息...')).toBeInTheDocument()
  })

  it('renders Typewriter with empty string when no content', () => {
    const { container } = render(
      <StreamingBubble {...baseProps} isStreaming={true} streamingContent="" />,
    )
    // Typewriter receives empty string → our mock renders an empty <span>
    const indicator = container.querySelector('[data-testid="streaming-indicator"]')
    expect(indicator?.textContent).toBe('')
  })

  it('renders bot avatar', () => {
    const { container } = render(<StreamingBubble {...baseProps} />)
    // Avatar renders inside the streaming bubble — verify component output exists
    expect(container.querySelector('.shrink-0')).toBeInTheDocument()
  })
})
