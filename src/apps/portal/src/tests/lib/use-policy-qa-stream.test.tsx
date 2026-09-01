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

// ── 基础事件序列（首轮：锚定结算 + 沉淀记忆 + 安全单答案）────────

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
    ['reasoning_step', { step_id: 'step-1', claim: '不得进入前端状态', kind: 'fact', depends_on: [], confidence: 0.95, citations: [], source_memory_ids: ['m-settle'] }],
    ['step', { step: 'settlement_query', status: 'done', public_message: '结算数据获取完成' }],
    ['step', { step: 'answer_assembly', status: 'running', public_message: '生成回答…' }],
    ['step', { step: 'answer_assembly', status: 'done', public_message: '回答生成完成' }],
    ['result', { result: {
      answer: '本次住院统筹自付 4962.67 元。',
      answer_status: 'complete',
      case_context: { person_type: '在职', deductible: 1300 },
      calculation_steps: [{ step_name: '核对结算', description: '已核对结算数据' }],
      definition: { name: '统筹自付', plain_text: '统筹范围内个人承担金额', excludes: ['全自费'] },
      warnings: ['本回答仅供参考'],
      policy_evidence: [{ title: '原始政策证据', excerpt: '不存入消息', score: 0.98 }],
      citations: [{ title: '基本医疗保险政策', excerpt: '统筹支付后个人按规定承担。' }],
      uncertainties: [],
      verification_summary: { settlement_checked: true, calculation_checked: true, policy_count: 1, message: '已完成核对' },
      office_view: '不得回退的旧字段',
      reasoning_steps: [{ step_id: 'step-1', claim: '不得进入前端状态' }],
      query_trace: { tables: ['yb_zyfdxx'] },
    } }],
    ['done', {}],
  ] as Array<[string, unknown]>
}

describe('usePolicyQAStream', () => {
  // streamQueue：每次 /stream 请求依次消费；settlement-explanation 请求返回空 JSON
  let streamQueue: string[] = []
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    window.localStorage.clear() // Issue #30：避免挂载恢复 effect 读到残留 sessionId
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

  it('consumes context_need / memory_update / result 并只映射安全单答案状态', async () => {
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

    // 最后一条 assistant 消息：只保留公开结果，不接收推理/院端视角
    const last = result.current.messages[result.current.messages.length - 1]
    expect(last.role).toBe('assistant')
    expect(last.content).toContain('本次住院统筹自付 4962.67 元')
    expect(last).toMatchObject({
      answerStatus: 'complete',
      citations: [{ title: '基本医疗保险政策', excerpt: '统筹支付后个人按规定承担。' }],
      uncertainties: [],
      verificationSummary: {
        settlementChecked: true,
        calculationChecked: true,
        policyCount: 1,
        message: '已完成核对',
      },
    })
    expect(last).not.toHaveProperty('officeView')
    expect(last).not.toHaveProperty('reasoning')
    expect(last).not.toHaveProperty('policyEvidence')
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
        ['result', { result: {
          answer: '已切换到新结算。',
          answer_status: 'complete',
          citations: [],
          uncertainties: ['本轮未检索政策'],
          verification_summary: { settlement_checked: true, calculation_checked: false, policy_count: 0, message: '已核对结算' },
        } }],
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

  it('结果契约缺失必填字段时生成安全 unavailable，不回退旧字段', async () => {
    streamQueue = [sseText([
      ['context_need', { session_id: 'sess-1', settlement_id: '1671213' }],
      ['result', { result: {
        patient_view: '旧患者答案不得展示',
        office_view: '旧院端答案不得展示',
        answer_status: 'complete',
      } }],
      ['done', {}],
    ])]
    const { result } = renderHook(() => usePolicyQAStream())

    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })

    const last = result.current.messages.at(-1)!
    expect(last.answerStatus).toBe('unavailable')
    expect(last.content).not.toContain('旧患者答案')
    expect(last.content).not.toContain('旧院端答案')
    expect(last.verificationSummary).toMatchObject({
      settlementChecked: false,
      calculationChecked: false,
      policyCount: 0,
    })
  })

  it.each([
    [
      'result JSON 损坏',
      'event: result\ndata: {broken\n\nevent: done\ndata: {}\n\n',
    ],
    [
      '流结束前没有 result',
      sseText([
        ['step', { status: 'done', public_message: '处理结束' }],
        ['done', {}],
      ]),
    ],
  ])('%s 时把 assistant 占位消息统一降级为安全 unavailable', async (_name, stream) => {
    streamQueue = [stream]
    const { result } = renderHook(() => usePolicyQAStream())

    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })

    const last = result.current.messages.at(-1)!
    expect(last.content).not.toBe('')
    expect(last.answerStatus).toBe('unavailable')
    expect(last.uncertainties).not.toHaveLength(0)
    expect(last.verificationSummary).toEqual({
      settlementChecked: false,
      calculationChecked: false,
      policyCount: 0,
      message: '公开结果不完整，未展示未经核验的内容。',
    })
  })

  /** 构造一份通过公开契约校验的完整 result */
  function validCompleteResult() {
    return {
      answer: '本次住院统筹自付 4962.67 元。',
      answer_status: 'complete',
      calculation_steps: [{ step_name: '核对结算', description: '已核对结算数据' }],
      definition: { name: '统筹自付', plain_text: '统筹范围内个人承担金额', excludes: [] },
      warnings: [],
      citations: [{ title: '基本医疗保险政策', excerpt: '统筹支付后个人按规定承担。' }],
      uncertainties: [],
      verification_summary: {
        settlement_checked: true,
        calculation_checked: true,
        policy_count: 1,
        message: '已完成核对',
      },
    }
  }

  it('result 与 done 携带同一 qa_turn_id 并保留到 assistant 消息', async () => {
    streamQueue = [
      sseText([
        ['context_need', { session_id: 'sess-1', settlement_id: '1671213' }],
        ['result', { qa_turn_id: 'qat-1', result: validCompleteResult() }],
        ['done', { qa_turn_id: 'qat-1', answer_status: 'complete', success: true }],
      ]),
    ]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })

    expect(result.current.messages.at(-1)).toMatchObject({
      role: 'assistant',
      qaTurnId: 'qat-1',
    })
  })

  it('result 与 done 的 qa_turn_id 不一致时不覆盖消息已锁定的 qaTurnId', async () => {
    streamQueue = [
      sseText([
        ['context_need', { session_id: 'sess-1', settlement_id: '1671213' }],
        ['result', { qa_turn_id: 'qat-locked', result: validCompleteResult() }],
        ['done', { qa_turn_id: 'qat-other', answer_status: 'complete', success: true }],
      ]),
    ]
    const { result } = renderHook(() => usePolicyQAStream())
    await act(async () => {
      await result.current.send('查询住院费用', { settlementId: '1671213' })
    })

    expect(result.current.messages.at(-1)?.qaTurnId).toBe('qat-locked')
  })
})
