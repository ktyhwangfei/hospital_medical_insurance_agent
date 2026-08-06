import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import PolicyConversation from '@/components/policy-qa/policy-conversation'
import PolicyQAWorkspace from '@/components/policy-qa/policy-qa-workspace'
import type { SessionAnchor } from '@/lib/policy-qa-session'
import type { UsePolicyQAStreamReturn } from '@/lib/use-policy-qa-stream'

afterEach(() => cleanup())

const scrollIntoViewMock = vi.fn()

beforeAll(() => {
  vi.stubGlobal('scrollTo', vi.fn())
  Element.prototype.scrollIntoView = scrollIntoViewMock
})

afterAll(() => vi.unstubAllGlobals())

beforeEach(() => scrollIntoViewMock.mockClear())

function makeAnchor(partial: Partial<SessionAnchor> = {}): SessionAnchor {
  return {
    patientId: null,
    patientName: null,
    encounterId: null,
    settlementId: null,
    topic: null,
    subjectChanged: false,
    subjectChangeMsg: null,
    ...partial,
  }
}

function makeStream(
  partial: Partial<UsePolicyQAStreamReturn> = {},
): UsePolicyQAStreamReturn {
  return {
    sessionId: 'sess-test',
    anchor: makeAnchor(),
    memories: [],
    messages: [],
    lastContextNeed: null,
    steps: [],
    isStreaming: false,
    error: null,
    send: vi.fn(async () => true),
    resetSession: vi.fn(),
    updateAnchor: vi.fn(),
    dismissSubjectChange: vi.fn(),
    appendLocalMessage: vi.fn(),
    ...partial,
  }
}

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

  it('scrolls to the conversation end when messages, public status, or streaming state changes', () => {
    const initial = makeStream()
    const { rerender } = render(<PolicyConversation stream={initial} />)
    scrollIntoViewMock.mockClear()

    const withMessage = {
      ...initial,
      messages: [{ role: 'user' as const, content: '查询住院费用' }],
    }
    rerender(<PolicyConversation stream={withMessage} />)
    expect(scrollIntoViewMock).toHaveBeenCalledTimes(1)
    scrollIntoViewMock.mockClear()

    const withPublicStatus = {
      ...withMessage,
      isStreaming: true,
      steps: [{ step: 'progress', status: 'running' as const, publicMessage: '正在核对结算单' }],
    }
    rerender(<PolicyConversation stream={withPublicStatus} />)
    expect(scrollIntoViewMock).toHaveBeenCalledTimes(1)
    scrollIntoViewMock.mockClear()

    rerender(<PolicyConversation stream={{ ...withPublicStatus, isStreaming: false }} />)
    expect(scrollIntoViewMock).toHaveBeenCalledTimes(1)
  })

  it('switches settlement with @换结算 and sends the default question', () => {
    const stream = makeStream()
    render(<PolicyConversation stream={stream} />)

    fireEvent.change(screen.getByRole('textbox', { name: '政策问题' }), {
      target: { value: '@换结算 7654321' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(stream.send).toHaveBeenCalledWith('查询该结算单的费用构成', {
      settlementId: '7654321',
    })
  })

  it('resets the session with @新会话 without sending a question', () => {
    const stream = makeStream({ anchor: makeAnchor({ settlementId: '1671213' }) })
    render(<PolicyConversation stream={stream} />)

    fireEvent.change(screen.getByRole('textbox', { name: '政策问题' }), {
      target: { value: '@新会话' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(stream.resetSession).toHaveBeenCalledTimes(1)
    expect(stream.send).not.toHaveBeenCalled()
  })

  it('shows only the latest public streaming message', () => {
    const stream = makeStream({
      isStreaming: true,
      steps: [
        { step: 'progress', status: 'done', publicMessage: '旧进度不应展示' },
        { step: 'progress', status: 'running', publicMessage: '正在核对政策依据' },
      ],
    })
    render(<PolicyConversation stream={stream} />)

    expect(screen.getByRole('status')).toHaveTextContent('正在核对政策依据')
    expect(screen.queryByText('旧进度不应展示')).not.toBeInTheDocument()
  })
})
