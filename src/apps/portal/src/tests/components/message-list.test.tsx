import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import ChatMessageList from '@/components/chat/message-list'

// Cleanup DOM between tests to avoid leakage from StrictMode double-render
afterEach(() => cleanup())

// Mock sub-components used by ChatMessageList
vi.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children, viewportRef, className }: any) => {
    // jsdom doesn't implement scrollTo on elements, so we patch the ref
    const setViewportRef = (el: HTMLDivElement | null) => {
      if (el) {
        el.scrollTo = vi.fn()
        if (viewportRef) viewportRef.current = el
      }
    }
    return (
      <div data-testid="scroll-area" className={className}>
        <div data-testid="chat-viewport" ref={setViewportRef}>
          {children}
        </div>
      </div>
    )
  },
}))

vi.mock('@/components/ui/avatar', () => ({
  Avatar: ({ children, className }: any) => (
    <div data-testid="avatar" className={className}>
      {children}
    </div>
  ),
  AvatarFallback: ({ children }: any) => (
    <div data-testid="avatar-fallback">{children}</div>
  ),
}))

vi.mock('@/components/intent-trace-card', () => ({
  default: (_props: any) => (
    <div data-testid="intent-trace-card">IntentTrace</div>
  ),
}))

vi.mock('@/components/chat/typewriter', () => ({
  Typewriter: ({ text }: any) => <span>{text}</span>,
}))

describe('ChatMessageList', () => {
  const baseProps = {
    messages: [{ role: 'user' as const, content: 'Hello' }],
    isStreaming: false,
    streamingContent: '',
    isLoading: false,
    steps: [],
    intentTrace: null,
    intentLabelStr: '等待识别',
    intentConfidenceText: '0%',
    intentStatusStr: '等待',
    connectionStatus: 'connected',
    statusLabel: '已连接',
    onConfirm: vi.fn(),
    pendingConfirmation: null,
  }

  it('renders user message content', () => {
    render(<ChatMessageList {...baseProps} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('shows loading indicator when isLoading is true', () => {
    render(<ChatMessageList {...baseProps} isLoading={true} />)
    expect(screen.getByTestId('loading-indicator')).toBeInTheDocument()
    expect(screen.getByText('识别中')).toBeInTheDocument()
  })

  it('does not show loading indicator when isLoading is false', () => {
    render(<ChatMessageList {...baseProps} />)
    expect(screen.queryByTestId('loading-indicator')).toBeNull()
    expect(screen.queryByText('识别中')).toBeNull()
  })

  it('renders streaming bubble when isStreaming and streamingContent are present', () => {
    render(
      <ChatMessageList
        {...baseProps}
        isStreaming={true}
        streamingContent="你好，我是AI助手"
      />,
    )
    expect(screen.getByText('你好，我是AI助手')).toBeInTheDocument()
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument()
  })

  it('shows intent trace card when intentTrace is provided', () => {
    render(
      <ChatMessageList
        {...baseProps}
        intentTrace={
          {
            intent: 'test',
            confidence: 0.9,
            status: 'routed',
            top_candidates: [],
          } as any
        }
      />,
    )
    const cards = screen.getAllByTestId('intent-trace-card')
    expect(cards.length).toBeGreaterThanOrEqual(1)
  })

  it('renders viewport element for auto-scroll', () => {
    render(<ChatMessageList {...baseProps} />)
    // React 19 StrictMode double-mounts, so there may be >1 viewport elements
    const viewports = screen.getAllByTestId('chat-viewport')
    expect(viewports.length).toBeGreaterThanOrEqual(1)
  })

  it('renders both user and assistant messages with correct roles', () => {
    const messages = [
      { role: 'user' as const, content: '用户消息' },
      { role: 'assistant' as const, content: 'AI回复' },
    ]
    render(<ChatMessageList {...baseProps} messages={messages} />)
    expect(screen.getByText('用户消息')).toBeInTheDocument()
    expect(screen.getByText('AI回复')).toBeInTheDocument()
  })
})
