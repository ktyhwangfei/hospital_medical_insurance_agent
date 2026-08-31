/**
 * Issue #30：轨迹恢复与挂起/升级/恢复前端纯函数 + 交互测试
 */
import { beforeAll, describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  clearPersistedSessionId,
  loadPersistedSessionId,
  persistSessionId,
  restoreSessionState,
  type TrajectoryResponseDTO,
} from '../../lib/policy-qa-session'
import PolicyConversation from '../../components/policy-qa/policy-conversation'
import type { UsePolicyQAStreamReturn } from '../../lib/use-policy-qa-stream'

// jsdom 不实现 scrollIntoView，组件 useEffect 会调用
beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
})

// jsdom localStorage
beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

describe('sessionId 持久化', () => {
  it('persist 后可 load，clear 后为空', () => {
    expect(loadPersistedSessionId()).toBeNull()
    persistSessionId('sess-1')
    expect(loadPersistedSessionId()).toBe('sess-1')
    clearPersistedSessionId()
    expect(loadPersistedSessionId()).toBeNull()
  })
})

describe('restoreSessionState', () => {
  const trajectory: TrajectoryResponseDTO = {
    session_id: 'sess-1',
    status: 'active',
    turns: [
      {
        qa_turn_id: 'qat_1',
        question: '统筹自付为什么这么多？',
        answer_status: 'complete',
        settlement_id: 'S123',
        payload: {
          context_need: {
            session_id: 'sess-1',
            settlement_id: 'S123',
            topic: '统筹自付',
            memory_ids: ['m-1'],
          },
          memory_updates: [
            {
              action: 'upsert',
              memory: {
                memory_id: 'm-1',
                type: 'settlement',
                importance: 0.9,
                expire_policy: 'session',
                snapshot: { settlement_id: 'S123' },
              },
            },
          ],
          result: {
            answer: '统筹自付按政策分段计算。',
            answer_status: 'complete',
            calculation_steps: [],
            citations: [{ title: '政策', excerpt: '条款' }],
            uncertainties: [],
            verification_summary: {
              settlement_checked: true,
              calculation_checked: true,
              policy_count: 1,
              message: '已核对。',
            },
          },
        },
      },
      {
        qa_turn_id: 'qat_2',
        question: '大额自付怎么算？',
        answer_status: 'unavailable',
        payload: { halt_reason: 'stalled' },
      },
    ],
  }

  it('重建消息序列：成功轮带完整结果，失败轮给降级文案', () => {
    const state = restoreSessionState(trajectory)
    expect(state.messages).toHaveLength(4) // 2 轮 × user+assistant
    expect(state.messages[0]).toMatchObject({ role: 'user', content: '统筹自付为什么这么多？' })
    expect(state.messages[1]).toMatchObject({
      role: 'assistant',
      content: '统筹自付按政策分段计算。',
      qaTurnId: 'qat_1',
    })
    expect(state.messages[1].verificationSummary?.message).toBe('已核对。')
    // 失败轮：unavailable 降级文案 + qaTurnId 保留（可反馈）
    expect(state.messages[3]).toMatchObject({ role: 'assistant', answerStatus: 'unavailable', qaTurnId: 'qat_2' })
    expect(state.messages[3].content).toContain('未能获得答案')
  })

  it('重建锚点与记忆卡', () => {
    const state = restoreSessionState(trajectory)
    expect(state.anchor.settlementId).toBe('S123')
    expect(state.anchor.topic).toBe('统筹自付')
    expect(state.memories).toHaveLength(1)
    expect(state.memories[0]).toMatchObject({ memoryId: 'm-1', type: 'settlement' })
  })
})

// ── 会话生命周期 UI ─────────────────────────────────────────────

function makeStream(partial: Partial<UsePolicyQAStreamReturn> = {}): UsePolicyQAStreamReturn {
  return {
    sessionId: 'sess-test',
    anchor: {
      patientId: null,
      patientName: null,
      encounterId: null,
      settlementId: 'S123',
      topic: null,
      subjectChanged: false,
      subjectChangeMsg: null,
    },
    memories: [],
    messages: [
      { role: 'user', content: '第一问' },
      { role: 'assistant', content: '回答', qaTurnId: 'qat_1' },
    ],
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
    updateAnchor: vi.fn(),
    dismissSubjectChange: vi.fn(),
    appendLocalMessage: vi.fn(),
    ...partial,
  }
}

describe('PolicyConversation 会话生命周期 UI', () => {
  it('active 且有对话时显示挂起与升级操作', async () => {
    const stream = makeStream()
    render(<PolicyConversation stream={stream} />)
    await userEvent.click(screen.getByRole('button', { name: /挂起/ }))
    expect(stream.suspendSession).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: /升级医保办/ }))
    // 无输入框内容时取最近一轮用户问题
    expect(stream.escalateSession).toHaveBeenCalledWith('第一问')
  })

  it('suspended 显示横幅、禁用输入并可恢复', async () => {
    const stream = makeStream({ sessionStatus: 'suspended', statusReason: '等材料' })
    render(<PolicyConversation stream={stream} />)
    expect(screen.getByTestId('policy-qa-suspended-banner')).toHaveTextContent('等材料')
    expect(
      screen.getByPlaceholderText('会话已挂起或升级中，恢复后可继续提问'),
    ).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /恢复对话/ }))
    expect(stream.resumeSession).toHaveBeenCalledOnce()
  })

  it('escalated 显示升级横幅与医保办回复', () => {
    const stream = makeStream({
      sessionStatus: 'active',
      escalation: {
        taskId: 'esc_1',
        status: 'completed',
        reply: '请携带材料到医保办窗口。',
        reason: '',
      },
    })
    render(<PolicyConversation stream={stream} />)
    expect(screen.getByTestId('policy-qa-escalation-reply')).toHaveTextContent(
      '请携带材料到医保办窗口。',
    )
  })
})
