/**
 * policy-qa-session 纯函数单元测试
 *
 * 覆盖设计文档 §6.3 跨层一致性（snake→camel 转换）与 §6.1 事件→状态映射：
 * - toContextNeed / toMemoryCard / toReasoningStep 字段转换
 * - upsertMemory / applyContextNeed（主体切换清 TOPIC 留 STICKY）/ mergeReasoningSteps
 * - parsePolicyQACommand / extractSettlementId / parseSseBlock
 */

import { describe, it, expect } from 'vitest'
import {
  applyContextNeed,
  extractSettlementId,
  mergeReasoningSteps,
  parsePolicyQACommand,
  parseSseBlock,
  resetTurnFlags,
  toContextNeed,
  toMemoryCard,
  toReasoningStep,
  upsertMemory,
  type MemoryCard,
  type ReasoningStep,
} from '@/lib/policy-qa-session'

// ── snake → camel 转换 ─────────────────────────────────────────

describe('toContextNeed', () => {
  it('snake_case 字段正确映射为 camelCase', () => {
    const cn = toContextNeed({
      session_id: 'sess-1',
      settlement_id: '1671213',
      topic: '统筹自付/报销',
      object_types: ['Settlement', 'Policy'],
      memory_ids: ['m-1', 'm-2'],
      must_query_semantic: true,
      topic_changed: false,
      subject_changed: true,
    })
    expect(cn).toEqual({
      objectTypes: ['Settlement', 'Policy'],
      memoryIds: ['m-1', 'm-2'],
      mustQuerySemantic: true,
      topicChanged: false,
      subjectChanged: true,
      settlementId: '1671213',
      topic: '统筹自付/报销',
    })
  })

  it('字段缺失时给安全默认值', () => {
    const cn = toContextNeed({})
    expect(cn.objectTypes).toEqual([])
    expect(cn.memoryIds).toEqual([])
    expect(cn.mustQuerySemantic).toBe(false)
    expect(cn.subjectChanged).toBe(false)
    expect(cn.settlementId).toBeNull()
    expect(cn.topic).toBeNull()
  })
})

describe('toMemoryCard', () => {
  it('转换 memory_update 中的记忆卡（含 snapshot 业务值）', () => {
    const card = toMemoryCard({
      memory_id: 'm-abc',
      type: 'settlement',
      ref_id: '1671213',
      importance: 0.9,
      expire_policy: 'topic',
      snapshot_keys: ['settlement_id', 'total_fee'],
      snapshot: { settlement_id: '1671213', total_fee: 189085.85 },
    })
    expect(card.memoryId).toBe('m-abc')
    expect(card.type).toBe('settlement')
    expect(card.refId).toBe('1671213')
    expect(card.expirePolicy).toBe('topic')
    expect(card.snapshotKeys).toEqual(['settlement_id', 'total_fee'])
    expect(card.snapshot).toEqual({ settlement_id: '1671213', total_fee: 189085.85 })
    expect(card.isNewThisTurn).toBe(true)
    expect(card.hitThisTurn).toBe(false)
  })
})

describe('toReasoningStep', () => {
  it('转换 reasoning_step 事件', () => {
    const step = toReasoningStep({
      step_id: 'step-0-abc',
      claim: '已获取结算单 1671213 的结算数据',
      kind: 'fact',
      depends_on: [],
      confidence: 0.95,
      citations: [],
      source_memory_ids: ['m-abc'],
    })
    expect(step.stepId).toBe('step-0-abc')
    expect(step.kind).toBe('fact')
    expect(step.sourceMemoryIds).toEqual(['m-abc'])
    expect(step.confidence).toBe(0.95)
  })
})

// ── 会话状态纯函数 ─────────────────────────────────────────────

function makeCard(partial: Partial<MemoryCard>): MemoryCard {
  return {
    memoryId: 'm-x',
    type: 'settlement',
    refId: null,
    importance: 0.5,
    expirePolicy: 'session',
    snapshotKeys: [],
    hitThisTurn: false,
    isNewThisTurn: false,
    ...partial,
  }
}

describe('upsertMemory', () => {
  it('新记忆追加到列表', () => {
    const list = upsertMemory([], makeCard({ memoryId: 'm-1' }))
    expect(list).toHaveLength(1)
  })

  it('同 memoryId 覆盖', () => {
    const base = [makeCard({ memoryId: 'm-1', importance: 0.5 })]
    const next = upsertMemory(base, makeCard({ memoryId: 'm-1', importance: 0.9 }))
    expect(next).toHaveLength(1)
    expect(next[0].importance).toBe(0.9)
  })

  it('同 type+refId 的旧卡被替换（后端 upsert 语义）', () => {
    const base = [makeCard({ memoryId: 'm-old', type: 'settlement', refId: '1671213' })]
    const next = upsertMemory(base, makeCard({ memoryId: 'm-new', type: 'settlement', refId: '1671213' }))
    expect(next).toHaveLength(1)
    expect(next[0].memoryId).toBe('m-new')
  })
})

describe('applyContextNeed', () => {
  it('按 memory_ids 标注本轮命中', () => {
    const memories = [makeCard({ memoryId: 'm-1' }), makeCard({ memoryId: 'm-2' })]
    const next = applyContextNeed(memories, {
      objectTypes: [],
      memoryIds: ['m-2'],
      mustQuerySemantic: false,
      topicChanged: false,
      subjectChanged: false,
    })
    expect(next.find((m) => m.memoryId === 'm-1')?.hitThisTurn).toBe(false)
    expect(next.find((m) => m.memoryId === 'm-2')?.hitThisTurn).toBe(true)
  })

  it('主体切换时清除 TOPIC 记忆、保留 STICKY 政策记忆', () => {
    const memories = [
      makeCard({ memoryId: 'm-settle', type: 'settlement', expirePolicy: 'topic' }),
      makeCard({ memoryId: 'm-policy', type: 'policy', expirePolicy: 'sticky' }),
      makeCard({ memoryId: 'm-conv', type: 'conversation', expirePolicy: 'sticky' }),
    ]
    const next = applyContextNeed(memories, {
      objectTypes: [],
      memoryIds: [],
      mustQuerySemantic: true,
      topicChanged: false,
      subjectChanged: true,
    })
    const ids = next.map((m) => m.memoryId)
    expect(ids).not.toContain('m-settle')
    expect(ids).toContain('m-policy')
    expect(ids).toContain('m-conv')
  })
})

describe('resetTurnFlags', () => {
  it('清除本轮命中/新查标记', () => {
    const memories = [makeCard({ hitThisTurn: true, isNewThisTurn: true })]
    const next = resetTurnFlags(memories)
    expect(next[0].hitThisTurn).toBe(false)
    expect(next[0].isNewThisTurn).toBe(false)
  })
})

describe('mergeReasoningSteps', () => {
  const s = (id: string, claim: string): ReasoningStep => ({
    stepId: id,
    claim,
    kind: 'fact',
    dependsOn: [],
    confidence: 0.9,
    citations: [],
    sourceMemoryIds: [],
  })

  it('定稿步骤优先，流式累积去重追加', () => {
    const accumulated = [s('a', '流式A'), s('b', '流式B')]
    const finalSteps = [s('b', '定稿B'), s('c', '定稿C')]
    const merged = mergeReasoningSteps(accumulated, finalSteps)
    expect(merged.map((x) => x.stepId)).toEqual(['b', 'c', 'a'])
    expect(merged[0].claim).toBe('定稿B')
  })

  it('定稿为空时保留流式累积', () => {
    const merged = mergeReasoningSteps([s('a', 'A')], [])
    expect(merged).toHaveLength(1)
  })
})

// ── @ 指令解析 ─────────────────────────────────────────────────

describe('parsePolicyQACommand', () => {
  it('@换结算 带问题', () => {
    const cmd = parsePolicyQACommand('@换结算 1671214 统筹支付多少')
    expect(cmd).toEqual({ kind: 'switch_settlement', settlementId: '1671214', question: '统筹支付多少' })
  })

  it('@换结算 不带问题', () => {
    const cmd = parsePolicyQACommand('@换结算 1671214')
    expect(cmd).toEqual({ kind: 'switch_settlement', settlementId: '1671214', question: '' })
  })

  it('@换患者', () => {
    expect(parsePolicyQACommand('@换患者 P002')).toEqual({ kind: 'switch_patient', patientId: 'P002' })
  })

  it('@新会话', () => {
    expect(parsePolicyQACommand('@新会话')).toEqual({ kind: 'new_session' })
  })

  it('普通问题', () => {
    expect(parsePolicyQACommand('那起付线呢')).toEqual({ kind: 'question', question: '那起付线呢' })
  })
})

describe('extractSettlementId', () => {
  it('从自然语言提取 6 位以上数字', () => {
    expect(extractSettlementId('查询住院费用，结算单 1671213')).toBe('1671213')
  })

  it('无数字时返回 null', () => {
    expect(extractSettlementId('那起付线呢')).toBeNull()
  })
})

// ── SSE 块解析 ─────────────────────────────────────────────────

describe('parseSseBlock', () => {
  it('解析 event + data', () => {
    const evt = parseSseBlock('event: context_need\ndata: {"session_id":"s1","subject_changed":false}')
    expect(evt).not.toBeNull()
    expect(evt!.event).toBe('context_need')
    expect((evt!.data as Record<string, unknown>).session_id).toBe('s1')
  })

  it('保留 Runtime 事件原始名（不被白名单丢弃）', () => {
    const evt = parseSseBlock('event: memory_update\ndata: {"action":"upsert"}')
    expect(evt!.event).toBe('memory_update')
  })

  it('无 event 行返回 null', () => {
    expect(parseSseBlock('data: {}')).toBeNull()
  })

  it('data JSON 损坏返回 null（降级）', () => {
    expect(parseSseBlock('event: result\ndata: {broken')).toBeNull()
  })
})
