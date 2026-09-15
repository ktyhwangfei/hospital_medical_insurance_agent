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
    mode: 'policy_chat',
    anchor: makeAnchor(),
    memories: [],
    messages: [],
    lastContextNeed: null,
    steps: [],
    isStreaming: false,
    error: null,
    restoring: false,
    sessionStatus: 'active',
    statusReason: '',
    escalation: null,
    send: vi.fn(async () => true),
    resetSession: vi.fn(),
    suspendSession: vi.fn(async () => {}),
    resumeSession: vi.fn(async () => {}),
    escalateSession: vi.fn(async () => {}),
    resolveEscalation: vi.fn(async () => true),
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

  // ── V4.0 智能体中心：切换器 + 三工作区分发 ──────────────────────

  it('renders the agent switcher with policy agent active by default', () => {
    render(<PolicyQAWorkspace />)

    expect(screen.getByTestId('agent-switcher')).toBeInTheDocument()
    expect(screen.getByTestId('agent-switcher-policy')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('agent-workspace-policy')).toBeInTheDocument()
  })

  it('switches to the settlement workspace without leaving the page', () => {
    render(<PolicyQAWorkspace />)

    fireEvent.click(screen.getByTestId('agent-switcher-settlement'))

    expect(screen.getByTestId('agent-workspace-settlement')).toBeInTheDocument()
    expect(screen.queryByTestId('agent-workspace-policy')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '结算解释' })).toBeInTheDocument()
  })

  it('switches to the ops workspace and back to policy', () => {
    render(<PolicyQAWorkspace />)

    fireEvent.click(screen.getByTestId('agent-switcher-ops'))
    expect(screen.getByTestId('agent-workspace-ops')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '运营问数' })).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('agent-switcher-policy'))
    expect(screen.getByTestId('agent-workspace-policy')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '政策问答' })).toBeInTheDocument()
  })

  it('keeps a persistent new-session action in the workspace header', () => {
    render(<PolicyQAWorkspace />)

    expect(screen.getByRole('button', { name: '新会话' })).toBeInTheDocument()
  })

  it('starts with the policy-agent empty state and composer', () => {
    render(<PolicyQAWorkspace />)

    expect(screen.getByRole('heading', { name: '政策问答' })).toBeInTheDocument()
    // V4.0 §4.1：政策问答智能体无结算单锚点，空状态直接引导问政策
    expect(screen.getByText('直接问政策问题')).toBeInTheDocument()
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

  it('places the scroll anchor after the composer and reference disclaimer', () => {
    render(<PolicyConversation stream={makeStream()} />)

    const composer = screen.getByRole('textbox', { name: '政策问题' })
    const disclaimer = screen.getByText('回答仅供解释参考，不作为报销或结算依据。')
    expect(composer.compareDocumentPosition(disclaimer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(disclaimer.nextElementSibling).toHaveAttribute('aria-hidden', 'true')
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

  // Issue #33 前端无锚定放行（docs/dispatch/T2-noanchor-dispatch.md v2 规格）：
  // 无单号政策问题不再被前端本地挡回，放行到后端路由层
  it('passes an anchorless broad policy question to the backend router', () => {
    const stream = makeStream()
    render(<PolicyConversation stream={stream} />)

    fireEvent.change(screen.getByRole('textbox', { name: '政策问题' }), {
      target: { value: '上海在职职工门诊报销比例是多少' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(stream.send).toHaveBeenCalledWith('上海在职职工门诊报销比例是多少')
    expect(stream.appendLocalMessage).not.toHaveBeenCalled()
  })

  it('still sends an anchorless-input question when an anchor is active', () => {
    const stream = makeStream({ anchor: makeAnchor({ settlementId: '1671213' }) })
    render(<PolicyConversation stream={stream} />)

    fireEvent.change(screen.getByRole('textbox', { name: '政策问题' }), {
      target: { value: '上海在职职工门诊报销比例是多少' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(stream.send).toHaveBeenCalledWith('上海在职职工门诊报销比例是多少')
    expect(stream.appendLocalMessage).not.toHaveBeenCalled()
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
