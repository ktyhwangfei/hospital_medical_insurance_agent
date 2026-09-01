/**
 * 政策问答持续对话 —— 会话级状态模型与纯函数逻辑
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §五/§六/§八
 *
 * 本模块只做纯数据处理，不依赖 React：
 * - 后端 SSE payload（snake_case）→ 前端 camelCase 类型转换（§6.3 跨层一致性）
 * - 会话记忆 / 锚点 的事件应用逻辑（可单测）
 * - @ 指令解析（@换结算 / @换患者 / @新会话）
 */

import type {
  PolicyQACaseContext,
  PolicyQAResult,
  PolicyQAVerificationSummary,
} from '@/lib/policy-qa-stream'

// ── 前端会话级状态类型（camelCase，组件层只见这一套）──────────────

/** 业务主体锚点。 */
export interface SessionAnchor {
  patientId: string | null
  patientName: string | null
  encounterId: string | null
  /** 当前结算（政策问答核心锚点） */
  settlementId: string | null
  /** 当前话题，如「统筹自付偏少」 */
  topic: string | null
  /** 本轮是否发生主体切换 */
  subjectChanged: boolean
  subjectChangeMsg: string | null
}

/** 会话记忆卡。 */
export interface MemoryCard {
  memoryId: string
  type: string
  refId: string | null
  importance: number
  expirePolicy: 'session' | 'topic' | 'sticky' | 'time' | string
  snapshotKeys: string[]
  /** 记忆快照业务值（后端脱敏后的小标量，如 settlement_id/total_fee） */
  snapshot?: Record<string, string | number | boolean>
  /** 本轮 context_need.memory_ids 是否命中 */
  hitThisTurn: boolean
  /** 本轮是否新沉淀 */
  isNewThisTurn: boolean
}

/** 本轮上下文规划快照（context_need 事件） */
export interface ContextNeedSnapshot {
  objectTypes: string[]
  memoryIds: string[]
  mustQuerySemantic: boolean
  topicChanged: boolean
  subjectChanged: boolean
  /** 当前结算单（后端回显，用于锚点同步） */
  settlementId?: string | null
  /** 当前话题标签（后端从问题推导） */
  topic?: string | null
}

/** Policy QA 对话仅持有安全公开结果；不保存院端视角或推理轨迹。 */
export interface PolicyQAChatMessage {
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  kind?: 'normal' | 'clarification' | 'confirmation'
  /** 本轮上下文规划（仅 assistant 消息） */
  contextNeed?: ContextNeedSnapshot
  answerStatus?: PolicyQAResult['answerStatus']
  citations?: PolicyQAResult['citations']
  uncertainties?: string[]
  verificationSummary?: PolicyQAVerificationSummary
  calculationSteps?: PolicyQAResult['calculationSteps']
  definition?: PolicyQAResult['definition']
  warnings?: string[]
  caseContext?: PolicyQACaseContext
  scenarioId?: PolicyQAResult['scenarioId']
  settlementFields?: PolicyQAResult['settlementFields']
  /** 服务端为本轮生成的稳定 ID（result/done 共享）；仅该 ID 提交给反馈接口 */
  qaTurnId?: string
  /** 仅来自具备评测权限的历史 DTO；SSE 禁止携带，不得从流式响应中读取 */
  selectedSkillId?: string
  /** 本轮“回答有误”反馈状态（前端本地标记，仅依据 qaTurnId 提交） */
  feedbackState?: 'idle' | 'submitted' | 'error'
}

// ── 后端 SSE payload 类型（snake_case，与 runtime_bridge.py 对齐）──

export interface RawContextNeed {
  session_id?: string
  settlement_id?: string | null
  topic?: string | null
  object_types?: string[]
  memory_ids?: string[]
  must_query_semantic?: boolean
  topic_changed?: boolean
  subject_changed?: boolean
}

export interface RawMemoryCard {
  memory_id: string
  type?: string
  ref_id?: string | null
  importance?: number
  expire_policy?: string
  version?: number
  snapshot_keys?: string[]
  snapshot?: Record<string, string | number | boolean>
}

export interface RawMemoryUpdate {
  action?: string
  memory?: RawMemoryCard
}

// ── snake → camel 转换（§6.3：统一在 hook 层完成）────────────────

export function toContextNeed(raw: RawContextNeed): ContextNeedSnapshot {
  return {
    objectTypes: Array.isArray(raw.object_types) ? raw.object_types : [],
    memoryIds: Array.isArray(raw.memory_ids) ? raw.memory_ids : [],
    mustQuerySemantic: raw.must_query_semantic === true,
    topicChanged: raw.topic_changed === true,
    subjectChanged: raw.subject_changed === true,
    settlementId: raw.settlement_id ?? null,
    topic: raw.topic ?? null,
  }
}

export function toMemoryCard(raw: RawMemoryCard): MemoryCard {
  return {
    memoryId: String(raw.memory_id ?? ''),
    type: String(raw.type ?? 'conversation'),
    refId: raw.ref_id ?? null,
    importance: typeof raw.importance === 'number' ? raw.importance : 0.5,
    expirePolicy: String(raw.expire_policy ?? 'session'),
    snapshotKeys: Array.isArray(raw.snapshot_keys) ? raw.snapshot_keys : [],
    snapshot: raw.snapshot,
    hitThisTurn: false,
    isNewThisTurn: true,
  }
}

// ── 会话状态纯函数（事件 → 状态，可单测）──────────────────────────

/** upsert 一条记忆卡（按 memoryId；同 type+refId 的旧卡视为被后端覆盖，一并替换） */
export function upsertMemory(memories: MemoryCard[], card: MemoryCard): MemoryCard[] {
  const idx = memories.findIndex(
    (m) => m.memoryId === card.memoryId || (m.type === card.type && m.refId === card.refId),
  )
  if (idx >= 0) {
    const next = [...memories]
    next[idx] = card
    return next
  }
  return [...memories, card]
}

/**
 * 应用 context_need：标注本轮命中的记忆；主体切换时清除 TOPIC 记忆（STICKY 政策保留）。
 * [来源: 设计文档 §6.1 / runtime_bridge.prepare_turn]
 */
export function applyContextNeed(
  memories: MemoryCard[],
  cn: ContextNeedSnapshot,
): MemoryCard[] {
  const hitSet = new Set(cn.memoryIds)
  let next = memories.map((m) => ({ ...m, hitThisTurn: hitSet.has(m.memoryId) }))
  if (cn.subjectChanged) {
    // 后端已清理 TOPIC 记忆（expire_on_topic_change），前端同步移除展示
    next = next.filter((m) => m.expirePolicy !== 'topic')
  }
  return next
}

/** 新一轮开始时清除所有「本轮」标记 */
export function resetTurnFlags(memories: MemoryCard[]): MemoryCard[] {
  return memories.map((m) => ({ ...m, hitThisTurn: false, isNewThisTurn: false }))
}

// ── @ 指令解析（§八：结算单号从必填降级）─────────────────────────

export type PolicyQACommand =
  | { kind: 'new_session' }
  | { kind: 'switch_settlement'; settlementId: string; question: string }
  | { kind: 'switch_patient'; patientId: string }
  | { kind: 'question'; question: string }

/** 解析用户输入中的 @ 指令 */
export function parsePolicyQACommand(input: string): PolicyQACommand {
  const text = input.trim()
  const switchSettlement = text.match(/^@换结算\s*(\S+)\s*([\s\S]*)$/)
  if (switchSettlement) {
    return {
      kind: 'switch_settlement',
      settlementId: switchSettlement[1],
      question: switchSettlement[2].trim(),
    }
  }
  const switchPatient = text.match(/^@换患者\s*(\S+)\s*$/)
  if (switchPatient) {
    return { kind: 'switch_patient', patientId: switchPatient[1] }
  }
  if (/^@新会话\s*$/.test(text)) {
    return { kind: 'new_session' }
  }
  return { kind: 'question', question: text }
}

/** 从自然语言中提取结算单号（首帧锚定兜底：6 位以上字母数字串） */
export function extractSettlementId(text: string): string | null {
  return text.match(/[A-Za-z0-9]{6,}/g)?.find((value) => /\d/.test(value)) ?? null
}

/** 生成新会话 ID（首帧生成，跨轮复用） */
export function newSessionId(): string {
  return `sess-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 空锚点（新会话初始状态） */
export function emptyAnchor(): SessionAnchor {
  return {
    patientId: null,
    patientName: null,
    encounterId: null,
    settlementId: null,
    topic: null,
    subjectChanged: false,
    subjectChangeMsg: null,
  }
}
