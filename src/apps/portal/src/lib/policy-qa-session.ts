/**
 * 政策问答持续对话 —— 会话级状态模型与纯函数逻辑
 *
 * 设计依据：docs/steering/医保Agent-政策问答前端改造设计-V1.0.md §五/§六/§八
 *
 * 本模块只做纯数据处理，不依赖 React：
 * - 后端 SSE payload（snake_case）→ 前端 camelCase 类型转换（§6.3 跨层一致性）
 * - 会话记忆 / 推理链 / 锚点 的事件应用逻辑（可单测）
 * - @ 指令解析（@换结算 / @换患者 / @新会话）
 */

import type { ChatMessage } from '@/components/chat/helpers'
import type { SettlementExplanationData } from '@/lib/settlement-explanation-types'

// ── 前端会话级状态类型（camelCase，组件层只见这一套）──────────────

/** 业务主体锚点（顶栏 SessionAnchorBar） */
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

/** 会话记忆卡（左栏 MemoryPanel） */
export interface MemoryCard {
  memoryId: string
  type: string
  refId: string | null
  importance: number
  expirePolicy: 'session' | 'topic' | 'sticky' | 'time' | string
  snapshotKeys: string[]
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
}

/** 推理链步骤（reasoning_step 事件 / result.reasoning_steps） */
export interface ReasoningStep {
  stepId: string
  claim: string
  kind: 'fact' | 'inference' | 'hypothesis' | 'verified' | string
  dependsOn: string[]
  confidence: number
  citations: string[]
  sourceMemoryIds: string[]
}

/** 扩展 ChatMessage（向后兼容：新增字段均可选） */
export interface PolicyQAChatMessage extends ChatMessage {
  /** 本轮推理链（reasoning_step 累积 + result.reasoning_steps 定稿） */
  reasoning?: ReasoningStep[]
  /** 本轮引用的记忆 ID */
  citedMemoryIds?: string[]
  /** 本轮上下文规划（仅 assistant 消息） */
  contextNeed?: ContextNeedSnapshot
  /** 结构化结果（费用分解等，首轮复用 SettlementExplanationPage 渲染） */
  richResult?: SettlementExplanationData
  /** 院端视角文本（result.office_view） */
  officeView?: string
}

// ── 后端 SSE payload 类型（snake_case，与 runtime_bridge.py 对齐）──

export interface RawContextNeed {
  session_id?: string
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
}

export interface RawMemoryUpdate {
  action?: string
  memory?: RawMemoryCard
}

export interface RawReasoningStep {
  step_id?: string
  claim?: string
  kind?: string
  depends_on?: string[]
  confidence?: number
  citations?: string[]
  source_memory_ids?: string[]
}

/** SSE 事件（保留后端原始事件名） */
export interface PolicyQASseEvent {
  event: string
  data: unknown
}

// ── snake → camel 转换（§6.3：统一在 hook 层完成）────────────────

export function toContextNeed(raw: RawContextNeed): ContextNeedSnapshot {
  return {
    objectTypes: Array.isArray(raw.object_types) ? raw.object_types : [],
    memoryIds: Array.isArray(raw.memory_ids) ? raw.memory_ids : [],
    mustQuerySemantic: raw.must_query_semantic === true,
    topicChanged: raw.topic_changed === true,
    subjectChanged: raw.subject_changed === true,
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
    hitThisTurn: false,
    isNewThisTurn: true,
  }
}

export function toReasoningStep(raw: RawReasoningStep): ReasoningStep {
  return {
    stepId: String(raw.step_id ?? ''),
    claim: String(raw.claim ?? ''),
    kind: String(raw.kind ?? 'fact'),
    dependsOn: Array.isArray(raw.depends_on) ? raw.depends_on : [],
    confidence: typeof raw.confidence === 'number' ? raw.confidence : 0,
    citations: Array.isArray(raw.citations) ? raw.citations : [],
    sourceMemoryIds: Array.isArray(raw.source_memory_ids) ? raw.source_memory_ids : [],
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

/**
 * 合并推理链：流式累积的 reasoning_step 与 result.reasoning_steps 定稿去重。
 * 定稿步骤优先（后端 finalize_turn 返回完整链）。
 */
export function mergeReasoningSteps(
  accumulated: ReasoningStep[],
  finalSteps: ReasoningStep[],
): ReasoningStep[] {
  if (finalSteps.length === 0) return accumulated
  const seen = new Set(finalSteps.map((s) => s.stepId))
  const extra = accumulated.filter((s) => s.stepId && !seen.has(s.stepId))
  return [...finalSteps, ...extra]
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

/** 从自然语言中提取结算单号（首帧锚定兜底：6 位以上数字串） */
export function extractSettlementId(text: string): string | null {
  const m = text.match(/\d{6,}/)
  return m ? m[0] : null
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

/** 费用解释类问题判定（命中时才拉取 richResult，与旧 policy-qa-chat 行为一致） */
export const FEE_QUESTION_PATTERN = /统筹自付|分段计算|起付线|报销比例|个人负担|住院费用|费用构成/

// ── SSE 解析（保留后端原始事件名；readSseStream 的 SseEventType 白名单
//    不含 context_need 等 Runtime 事件，故此处自解析）────────────────

/** 解析单个 SSE 块（event: + data: 行） */
export function parseSseBlock(block: string): PolicyQASseEvent | null {
  const lines = block.replace(/\r\n/g, '\n').split('\n')
  let event = ''
  const dataLines: string[] = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }
  if (!event || dataLines.length === 0) return null
  const raw = dataLines.join('\n').trim()
  if (!raw) return { event, data: {} }
  try {
    return { event, data: JSON.parse(raw) as unknown }
  } catch {
    return null
  }
}
