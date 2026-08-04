/**
 * usePolicyQAStream hook 集成测试
 *
 * 用 mock fetch（ReadableStream 构造 SSE 文本）驱动 hook：
 * - session_id 跨轮复用（首帧生成，后续轮次沿用）
 * - context_need / memory_update / reasoning_step / step / result / done 事件
 *   正确映射到会话状态（§6.1 事件→状态映射表）
 * - 主体切换：context_need.subject_changed=true → 顶栏横幅 + TOPIC 记忆清除
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, cleanup } from '@testing-library/react'
import { usePolicyQAStream } from '@/lib/use-policy-qa-stream'

// ── 工具：把事件数组拼成 SSE 文本 ──────────────────────────────

function sseText(events: Array<[string, unknown]>): string {
  return events
    .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join('')
}

/** 构造一个可被 fetch 消费的 SSE Response 形状 */
function sseResponse(text: string): Response {
  const encoder = new TextEncoder()
  return {
    ok: true,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(text))
        controller.close()
      },
    }),
  } as unknown as Response
}

// ── 基础事件序列（首轮：锚定结算 + 沉淀记忆 + 推理）──────────────

function firstTurnEvents() {
  return [
    [
      'context_need',
      {
        session_id: 'sess-1',
        settlement_id: '1671213',
        object_types: ['Settlement', 'Policy'],
        memory_ids: [],
        must_query_semantic: true,
        topic_changed: false,
        subject_changed: false,
      },
    ],
    ['step', { step: 'settlement_query', status: 'running', public_message: '查询结算数据…' }],
    ['memory_update', { action: 'upsert', memory: { memory_id: 'm-settle', type: 'settlement', ref_id: '1671213', importance: 0.9, expire_policy: 'topic', snapshot_keys: ['settlement_id', 'total_fee'], snapshot: { settlement_id: '1671213', total_fee: 189085.85 } } }],
    ['reasoning_step', { step_id: 'step-1', claim: '已获取结算单 1671213 的结算数据', kind: 'fact', depends_on: [], confidence: 0.95, citations: [], source_memory_ids: ['m-settle'] }],
    ['step', { step: 'settlement_query', status: 'done', public_message: '结算数据获取完成' }],
    ['step', { step: 'answer_assembly', status: 'running', public_message: '生成回答…' }],
    ['step', { step: 'answer_assembly', status: 'done', public_message: '回答生成完成' }],
    ['result', { result: { patient_view: '本次住院统筹自付 4962.67 元。', office_view: '本次结算统筹自付金额为 4962.67 元。', can_answer: true, reasoning_steps: [{ step_id: 'step-1', claim: '已获取结算单 1671213 的结算数据', kind: 'fact', depends_on: [], confidence: 0.95, citations: [], source_memory_ids: ['m-settle'] }], memory_count: 2 } }],
    ['done', {}],
  ] as Array<[string, unknown]>
}

describe('usePolicyQAStream', () => {
  // streamQueue：每次 /stream 请求依次消费；settlement-explanation 请求返回空 JSON
  let streamQueue: string[] = []
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    streamQueue = []
    fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url)
      if (u.includes('/policy-qa/stream')) {
        const text = streamQueue.shift() ?? sseText(firstTurnEvents())
        return sseResponse(text)
      }
      // settlement-explanation REST 端点
      return { ok: true, json: async () => ({}) } as unknown as Response
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  /** 提取 /stream 请求的 body（过滤 richResult 的 REST 调用） */
  function streamBodies(): Array<{ question: string; settlement_id: string; session_id: string }> {
    return fetchMock.mock.calls
      .filter((call) => String(call[0]).includes('/policy-qa/stream'))
      .map((call) => JSON.parse(String((call[1] as RequestInit | undefined)?.body)) as { question: string; settlement_id: string; session_id: string })
  }

  it('首轮生成 session_id，后续轮次复用同一 session_id', async () => {
    streamQueue = [sseText(firstTurnEvents()), sseText(firstTurnEvents())]
    const { result } = renderHook(() => usePolicyQAStream())
    const firstSessionId = result.current.sessionId

    // 首轮：带 settlementId 锚定
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0]).toMatchObject({ role: 'user', content: '查询住院费用' })

    // 第二轮：追问，无 settlementId（复用锚点）
    await act(async () => {
      await result.current.send('那起付线呢')
    })

    const bodies = streamBodies()
    expect(bodies).toHaveLength(2)
    // ★ 跨轮复用：两轮 session_id 一致，且等于 hook 持有值
    expect(bodies[1].session_id).toBe(bodies[0].session_id)
    expect(bodies[0].session_id).toBe(firstSessionId)
    expect(result.current.messages).toHaveLength(4)
  })

  it('首轮锚定后追问轮自动携带 anchor.settlementId', async () => {
    streamQueue = [sseText(firstTurnEvents()), sseText(firstTurnEvents())]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })
    await act(async () => {
      await result.current.send('那起付线呢')
    })

    const bodies = streamBodies()
    expect(bodies[1].settlement_id).toBe('1671213')
  })

  it('consumes context_need / memory_update / reasoning_step / result 并映射到状态', async () => {
    streamQueue = [sseText(firstTurnEvents())]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })

    // lastContextNeed：camelCase 转换完成（含 settlementId/topic 回显）
    expect(result.current.lastContextNeed).toMatchObject({
      objectTypes: ['Settlement', 'Policy'],
      mustQuerySemantic: true,
      subjectChanged: false,
      settlementId: '1671213',
    })

    // anchor：topic 从 context_need 同步到锚点
    expect(result.current.anchor.topic).toBeNull()

    // memories：memory_update upsert（含 snapshot 业务值）
    expect(result.current.memories).toHaveLength(1)
    expect(result.current.memories[0]).toMatchObject({
      memoryId: 'm-settle',
      type: 'settlement',
      refId: '1671213',
      expirePolicy: 'topic',
      isNewThisTurn: true,
      snapshot: { settlement_id: '1671213', total_fee: 189085.85 },
    })

    // 最后一条 assistant 消息：内容 + 推理链 + 引用记忆 + 院端视角 + answer_mode
    const last = result.current.messages[result.current.messages.length - 1]
    expect(last.role).toBe('assistant')
    expect(last.content).toContain('本次住院统筹自付 4962.67 元')
    expect(last.reasoning).toHaveLength(1)
    expect(last.reasoning![0]).toMatchObject({ stepId: 'step-1', kind: 'fact', claim: '已获取结算单 1671213 的结算数据' })
    expect(last.citedMemoryIds).toEqual(['m-settle'])
    expect(last.officeView).toContain('本次结算统筹自付金额为 4962.67 元')
    expect(last.answerMode).toBeUndefined() // mock 流未携带 answer_mode 时保持 undefined
  })

  it('流式结束后 isStreaming=false', async () => {
    streamQueue = [sseText(firstTurnEvents())]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })
    expect(result.current.isStreaming).toBe(false)
  })

  it('主体切换：context_need.subject_changed=true → 横幅 + TOPIC 记忆清除、STICKY 保留', async () => {
    // 第一轮：锚定（沉淀 TOPIC 结算记忆 + STICKY 政策记忆，同一流内）
    const turn1 = firstTurnEvents()
    turn1.splice(-2, 0, [
      'memory_update',
      { action: 'upsert', memory: { memory_id: 'm-policy', type: 'policy', ref_id: null, importance: 0.8, expire_policy: 'sticky', snapshot_keys: ['rules_count'] } },
    ])
    // 第二轮：主体切换
    streamQueue = [
      sseText(turn1),
      sseText([
        ['context_need', { session_id: 'sess-1', object_types: ['Settlement'], memory_ids: ['m-policy'], must_query_semantic: true, topic_changed: false, subject_changed: true }],
        ['memory_update', { action: 'upsert', memory: { memory_id: 'm-policy', type: 'policy', ref_id: null, importance: 0.8, expire_policy: 'sticky', snapshot_keys: ['rules_count'] } }],
        ['result', { result: { patient_view: '已切换到新结算。', can_answer: true, memory_count: 1 } }],
        ['done', {}],
      ]),
    ]

    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })
    await act(async () => {
      await result.current.send('查询李四的费用', { settlementId: '1671214' })
    })

    // 横幅触发
    expect(result.current.anchor.subjectChanged).toBe(true)
    expect(result.current.anchor.subjectChangeMsg).toContain('已切换业务主体')
    // TOPIC 结算记忆被清除，STICKY 政策记忆保留
    const types = result.current.memories.map((m) => m.type)
    expect(types).not.toContain('settlement')
    expect(types).toContain('policy')
  })

  it('解析 result.answer_mode 到消息（来源徽标数据）', async () => {
    const events = firstTurnEvents().map(([evt, data]) => {
      if (evt === 'result') {
        const payload = data as { result: Record<string, unknown> }
        return [evt, { ...payload, result: { ...payload.result, answer_mode: 'dummy' } }] as [string, unknown]
      }
      return [evt, data] as [string, unknown]
    })
    streamQueue = [sseText(events)]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })
    const last = result.current.messages[result.current.messages.length - 1]
    expect(last.answerMode).toBe('dummy')
  })

  it('无锚点时 send 返回 false 且不发请求', async () => {
    streamQueue = []
    const { result } = renderHook(() => usePolicyQAStream())
    let sent: boolean | undefined
    await act(async () => {
      sent = await result.current.send('那起付线呢')
    })
    expect(sent).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('resetSession 生成新 session_id 并清空状态', async () => {
    streamQueue = [sseText(firstTurnEvents())]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })
    const oldId = result.current.sessionId
    act(() => {
      result.current.resetSession()
    })
    expect(result.current.sessionId).not.toBe(oldId)
    expect(result.current.messages).toHaveLength(0)
    expect(result.current.memories).toHaveLength(0)
    expect(result.current.anchor.settlementId).toBeNull()
  })
})
