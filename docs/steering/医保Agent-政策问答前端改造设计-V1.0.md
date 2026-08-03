# 医保 Agent · 政策问答前端改造设计（V1.0）— 从「一次性查询」到「持续对话」

> **版本**：V1.0 ｜ **日期**：2026-08-03 ｜ **状态**：设计评审稿
> **定位**：政策问答前端（`src/apps/portal/app/policy-qa/`）改造设计，对齐 Runtime 建设思路，把当前「一次性表单查询」升级为「跨轮持续对话」。
> **设计依据**：
> - `docs/steering/医保Agent-Runtime设计-V1.0.md`（Runtime 六模块，**核心依据**）
> - `docs/steering/医保Agent-Runtime设计-V1.0-评估报告.md`（ADR-007/008/009 + 三层管道）
> - `src/runtime/policy_qa/runtime_bridge.py`（已实现的 Runtime 增强桥 + SSE 事件契约）
> **配套**：`src/apps/portal/src/components/`（现有 chat 组件族）、`src/runtime/api/policy_qa_routes.py`（SSE 端点）

---

## 〇、一句话结论

> **后端 Runtime 桥已就绪并已在 SSE 流里发出 `context_need` / `memory_update` / `reasoning_step` / `result.reasoning_chain` 四类事件，但当前前端是一张「单号+问题→结果→结束」的一次性表单，既不保持 `session_id` 跨轮，也不消费这些事件——Runtime 的会话/记忆/推理能力在 UI 上完全不可见、不可用。本设计把前端改造成「持续对话」形态，把这四类事件可视化，让 Runtime 真正"用起来"。**

---

## 一、背景与目标

### 1.1 为什么改

Runtime 设计文档反复强调的典型医保导办场景 [来源: 医保Agent-Runtime设计-V1.0.md §二]：

```
查询住院费用          → 沉淀 Patient / Visit / Settlement 记忆
为什么统筹支付这么少？ → 复用 Settlement，仅补 Policy / Rule（不重查）
这个药为什么没报？     → 补 Drug，Settlement 继续复用
如果退掉这个药呢？     → 基于已有推理链继续推演，不从头来
查询李四              → 主体切换，失效 Patient/Settlement，保留 Policy/Rule
```

这是**同一个 Settlement 上的一连串追问**。Runtime 六模块（Session / Memory / Memory Manager / Context Planner / Context Composer / Reasoning State）的存在意义，就是支撑这种持续推理，而不是每轮从零检索 [来源: 同上 §一、§八]。

### 1.2 当前前端的三个致命缺陷

| # | 缺陷 | 后果 | 证据 |
|---|---|---|---|
| 1 | **不传 `session_id`** | 后端用 `sess-{id(request)}` 每轮新建，Memory 无法跨轮复用 | `policy_qa_routes.py` 第 158 行；前端 `policy-qa-chat.tsx` grep 无 `session_id` |
| 2 | **表单式交互**（单号+问题→结果→结束） | 无法连续追问，每次都是孤立查询 | `policy-qa-chat.tsx` 单次 `handleSubmit`，无对话历史 |
| 3 | **不消费 Runtime SSE 事件** | Session/Memory/Reasoning 能力全丢失 | 前端只解析 `step`/`result`，忽略 `context_need`/`memory_update`/`reasoning_step` |

### 1.3 设计目标

1. **持续对话**：多轮 Chat，`session_id` 跨轮保持，连续追问复用上文。
2. **Runtime 可视化**：把 Session（业务主体锚点）、Memory（已理解事实）、Reasoning（推理链）三模块在 UI 上"看得见"。
3. **复用现成基建**：基于现有 `components/chat/` 组件族 + `useChatStream`，不重造轮子。
4. **低风险渐进**：分阶段落地，每阶段可独立验证、可回退。

---

## 二、设计原则

| 原则 | 说明 |
|---|---|
| **对话流为主体** | 主区是 Chat，不是表单。结算单号从「每次必填」降级为「首次锚定、可切换」。 |
| **Runtime 事件驱动 UI** | 三区状态由 `context_need` / `memory_update` / `reasoning_step` / `result` 四类 SSE 事件驱动，不另造数据源。 |
| **会话级状态，请求级请求** | 前端持有会话级状态（messages / memories / reasoning / session 锚点）；每轮只发一个带 `session_id` 的请求。 |
| **降级友好** | Runtime 事件缺失/异常时，对话仍可进行（与后端 `runtime_bridge` 「增强失败绝不阻塞主流式响应」原则一致）。 |
| **复用而非重写** | 对话气泡、流式、执行时间线复用 `components/chat/`；只新增 Runtime 可视化组件。 |

---

## 三、整体架构：三区布局

```
┌──────────────────────────────────────────────────────────────────┐
│  顶栏 · 业务主体锚点带（SessionAnchor）—— BusinessSession 可视化    │
│  [👤 张三] [🏥 就诊 E001] [💳 结算 1671213 ★] [💬 话题:统筹自付偏少] │
│  ⚠ 主体切换横幅：「已切换到 李四，旧结算/患者上下文已清除」          │
├─────────────────────┬────────────────────────────────────────────┤
│ 左栏 · 会话记忆       │  主区 · 对话流（ChatStream）—— 持续对话主体   │
│ (MemoryPanel)        │                                            │
│ ┌─────────────────┐  │  👤 查询住院费用                            │
│ │ 💳 结算 1671213 │  │  ─────────────────────────────             │
│ │  起付线 650      │  │  🤖 本次统筹自付 4962.67 元…                │
│ │  统筹自付 4962.67│  │  📎 推理链 ▼  [fact→inference→inference]    │
│ │  ✓ 来自记忆      │  │  💭 引用: 结算记忆✓ 政策记忆✓               │
│ ├─────────────────┤  │                                            │
│ │ 📜 政策·城镇职工 │  │  👤 那起付线呢？   ← 连续追问（省略单号）    │
│ │  📌 跨话题保留   │  │  🤖 基于上文，起付线为 650 元…              │
│ ├─────────────────┤  │     （复用 Settlement 记忆，未重查）         │
│ │ 💊 药品 XX       │  │                                            │
│ │  ✨ 本轮新查      │  │  [ChatInput: 输入框 + 发送]                 │
│ └─────────────────┘  │                                            │
│  记忆随对话增长       │                                            │
└─────────────────────┴────────────────────────────────────────────┘
```

| 区 | 对应 Runtime 模块 | 数据来源（SSE 事件） | 复用组件 |
|---|---|---|---|
| 顶栏 SessionAnchor | BusinessSession | `context_need`（subject_changed / object_types） | 新建（轻量） |
| 左栏 MemoryPanel | BusinessMemory + MemoryManager | `memory_update` + `result.memory_count` | 新建 |
| 主区 ChatStream | 持续对话 + ReasoningState | `step` / `result` / `reasoning_step` / `result.reasoning_chain` | 复用 `chat/message-list` + `chat/chat-input` + `chat/streaming-bubble` |

> **布局响应式**：桌面三区；窄屏折叠为「顶栏锚点 + 单列对话流」，MemoryPanel 收为可展开抽屉。

---

## 四、组件设计

### 4.1 组件树

```
app/policy-qa/page.tsx                      ← 容器，提供 PolicyQASessionProvider
└── <PolicyQAWorkspace>                     ← 新建：三区布局编排
    ├── <SessionAnchorBar>                  ← 新建：业务主体锚点带
    │   ├── <SubjectBadge> × N              ← 患者/就诊/结算/话题 徽标
    │   └── <SubjectChangeBanner>           ← 主体切换横幅（条件渲染）
    ├── <MemoryPanel>                       ← 新建：会话记忆面板
    │   ├── <MemoryCard> × N                ← 单条记忆卡（按 type 分组）
    │   └── <ContextNeedIndicator>          ← 本轮加载来源指示
    └── <ChatStream>                        ← 新建：对话流（封装 chat 基建）
        ├── <ChatMessageList>               ← 复用 chat/message-list（扩展）
        │   └── <ReasoningChainCollapsible> ← 新建：每条 AI 回复的推理链折叠
        ├── <StreamingBubble>               ← 复用 chat/streaming-bubble
        └── <PolicyQAChatInput>             ← 封装 chat/chat-input（+ @指令）
```

### 4.2 新建组件职责

| 组件 | 职责 | 主要 props / 消费事件 |
|---|---|---|
| `PolicyQAWorkspace` | 三区编排 + 持有会话级状态（见 §五） | 顶层状态容器 |
| `SessionAnchorBar` | 显示当前业务主体；主体切换时弹横幅 | `session` state；`context_need.subject_changed` |
| `MemoryPanel` | 渲染会话记忆列表；标注来源（记忆命中/本轮新查/跨话题保留） | `memories` state；`memory_update`；`context_need.memory_ids` |
| `ChatStream` | 对话流主体；每轮发请求、解析 SSE、更新 messages/memories/reasoning | `usePolicyQAStream` hook（见 §六） |
| `ReasoningChainCollapsible` | 在 AI 回复下折叠展示推理链（fact/inference/...） | `message.reasoning`；`reasoning_step` / `result.reasoning_chain` |
| `PolicyQAChatInput` | 输入框 + 发送 + `@` 指令（`@换结算 1671214` / `@换患者 P002`） | 复用 `ChatInput`，叠加指令解析 |

### 4.3 复用现有组件（不修改或最小扩展）

| 现有组件 | 复用方式 | 是否扩展 |
|---|---|---|
| `chat/chat-input.tsx` | 作为 `PolicyQAChatInput` 内核 | 包一层（指令解析） |
| `chat/message-list.tsx` | 作为 `ChatMessageList` 内核 | 扩展：渲染 `ReasoningChainCollapsible` 插槽 |
| `chat/streaming-bubble.tsx` | 流式文本气泡 | 不改 |
| `chat/execution-timeline.tsx` | 可选：对话流顶部 trace 折叠 | 不改 |
| `chat/helpers.ts`（`ChatMessage`） | 扩展字段（见 §五） | 扩展 |
| `@/lib/sse-hooks`（`useChatStream`） | 参考其模式新建 `usePolicyQAStream` | 新建（见 §六） |

---

## 五、数据模型（前端会话级状态）

### 5.1 会话状态容器

```ts
// PolicyQASessionState —— 整个会话期间驻留（跨轮保持）
interface PolicyQASessionState {
  sessionId: string              // ★ 跨轮不变（首帧生成，后续复用）
  anchor: SessionAnchor          // 业务主体锚点（顶栏）
  memories: MemoryCard[]         // 已沉淀的业务记忆（左栏）
  messages: PolicyQAChatMessage[]// 对话流（主区）
  lastContextNeed: ContextNeedSnapshot | null  // 本轮上下文规划结果
}

interface SessionAnchor {
  patientId: string | null
  patientName: string | null
  encounterId: string | null
  settlementId: string | null    // ★ 当前结算（政策问答核心锚点）
  topic: string | null           // 当前话题，如「统筹自付偏少」
  subjectChanged: boolean        // 本轮是否发生主体切换
  subjectChangeMsg: string | null
}

interface MemoryCard {
  memoryId: string
  type: 'settlement' | 'policy' | 'rule' | 'drug' | 'patient' | 'visit' | 'conversation' | ...
  refId: string | null
  importance: number
  expirePolicy: 'session' | 'topic' | 'sticky' | 'time'
  snapshotKeys: string[]
  hitThisTurn: boolean           // 本轮 context_need.memory_ids 是否命中
  isNewThisTurn: boolean         // 本轮是否新沉淀
}

interface ContextNeedSnapshot {
  objectTypes: string[]
  memoryIds: string[]
  mustQuerySemantic: boolean
  topicChanged: boolean
  subjectChanged: boolean
}
```

### 5.2 扩展 ChatMessage

现有 `ChatMessage`（`chat/helpers.ts`）：

```ts
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  kind?: 'normal' | 'clarification' | 'confirmation'
}
```

扩展为 `PolicyQAChatMessage`（**向后兼容**，新增字段可选）：

```ts
interface PolicyQAChatMessage extends ChatMessage {
  // Runtime 增强字段（来自 SSE 事件）
  reasoning?: ReasoningStep[]          // 本轮推理链（reasoning_step 累积 + result.reasoning_chain）
  citedMemoryIds?: string[]            // 本轮引用的记忆
  contextNeed?: ContextNeedSnapshot    // 本轮上下文规划（仅 assistant 消息）
  richResult?: SettlementExplanationData  // 首轮的结构化结果（费用分解等，复用现有类型）
}

interface ReasoningStep {
  stepId: string
  claim: string
  kind: 'fact' | 'inference' | 'hypothesis' | 'verified'
  dependsOn: string[]
  confidence: number
  citations: string[]
  sourceMemoryIds: string[]
}
```

---

## 六、SSE 事件消费契约（前端 ↔ 后端 ↔ Runtime）

### 6.1 事件 → 状态 映射表

> 后端事件 payload 定义见 `runtime_bridge.py`（`PolicyQARuntimeBridge.prepare_turn / record_step / finalize_turn`）与 `policy_qa_routes.py` 的 `_policy_qa_stream`。

| SSE event | 后端来源（Runtime 模块） | 前端消费动作 | 目标状态 |
|---|---|---|---|
| `context_need` | ContextPlanner（`prepare_turn`） | 更新 `lastContextNeed`；若 `subject_changed` 置 `anchor.subjectChanged=true` 并弹横幅；标注 `memories[].hitThisTurn` | `anchor` / `lastContextNeed` / `memories` |
| `memory_update` | MemoryManager（`record_step`） | upsert `memories`（按 memory_id），置 `isNewThisTurn=true` | `memories` |
| `reasoning_step` | ReasoningStateManager（`record_step`） | 追加到「当前进行中的 assistant 消息」的 `reasoning[]` | `messages[last].reasoning` |
| `step`（status=done） | orchestrator 各步骤 | 现有逻辑：更新执行链路 trace | `messages` / trace |
| `result` | orchestrator + `finalize_turn` | 完成当前 assistant 消息；合并 `result.reasoning_chain` / `result.reasoning_steps` / `result.memory_count`；首轮附带 `richResult`（费用分解） | `messages[last]` |
| `done` | 流结束 | 关闭 loading | — |

### 6.2 新建 Hook：`usePolicyQAStream`

参考现有 `useChatStream`（`@/lib/sse-hooks`）模式，新增一个专门消费 policy-qa SSE 的 hook：

```ts
function usePolicyQAStream() {
  // 返回：
  return {
    messages, memories, anchor, lastContextNeed,  // 响应式状态
    isStreaming,
    send(question: string, opts?: { settlementId?: string }),  // 发起一轮（带 session_id）
    resetSession(),  // 新建会话（生成新 sessionId）
  }
}
```

**关键实现要点**：
1. `send()` 发 POST `/policy-qa/stream`，body 含 `session_id`（跨轮复用）、`question`、`settlement_id`（仅首次或 `@换结算` 时提供）。
2. SSE 解析按 `event:` 分发：`context_need` / `memory_update` / `reasoning_step` / `step` / `result` / `done` 各自更新状态。
3. `reasoning_step` 在流式过程中累积到「当前 in-flight 的 assistant 消息」；`result` 到达时定稿。
4. 异常降级：任一 Runtime 事件解析失败，只记日志，不影响 `step`/`result` 主流程。

### 6.3 跨层一致性核对（AGENTS.md §跨层一致性）

| 前端字段（TS） | 后端 SSE payload（Pydantic / dict） | Runtime 模型 | 一致性 |
|---|---|---|---|
| `ContextNeedSnapshot.objectTypes` | `context_need.object_types: list[str]` | `ContextNeed.object_types` | ✅ snake→camel 需在 hook 转换 |
| `ContextNeedSnapshot.subjectChanged` | `context_need.subject_changed: bool` | `ContextNeed.subject_changed` | ✅ |
| `MemoryCard.expirePolicy` | `memory.expire_policy: str` | `ExpirePolicy` (StrEnum) | ✅ |
| `MemoryCard.snapshotKeys` | `memory.snapshot_keys: list[str]` | （bridge `_memory_card` 派生） | ✅ |
| `ReasoningStep.kind` | `reasoning_step.kind: str` | `ReasoningStep.kind`（字面量） | ✅ |
| `ReasoningStep.sourceMemoryIds` | `reasoning_step.source_memory_ids: list[str]` | `ReasoningStep.source_memory_ids` | ✅ |
| `PolicyQAChatMessage` 附加 | `result.reasoning_chain` / `reasoning_steps` / `memory_count` | `finalize_turn` 返回 | ✅ |

> ⚠️ **snake_case ↔ camelCase**：后端 SSE payload 为 snake_case，前端 TS 习惯 camelCase。转换统一在 `usePolicyQAStream` 内完成，组件层只见 camelCase。

---

## 七、关键交互时序

### 7.1 首轮（建立会话 + 锚定结算）

```
用户输入: "查询住院费用，结算单 1671213"
  │
  ├─ ChatStream.send(question, {settlementId:'1671213'})
  │    body: { question, settlement_id:'1671213', session_id: <新生成> }
  │
  ├─ SSE: context_need          → anchor 初始化（settlement 锚定）；must_query_semantic=true
  ├─ SSE: step(settlement_query,done)
  │    └ SSE: memory_update     → memories += Settlement(1671213) [✨本轮新查]
  │       SSE: reasoning_step   → 当前 AI msg.reasoning += [fact: 已获取结算数据]
  ├─ SSE: step(policy_rule_search,done)
  │    └ SSE: memory_update     → memories += Policy [✨本轮新查]
  │       SSE: reasoning_step   → += [fact: 检索到 N 条政策]
  ├─ SSE: step(answer_assembly,done)
  │    └ SSE: reasoning_step    → += [inference: 已生成结算解释]
  ├─ SSE: result                → AI msg 定稿；reasoning_chain/memories 定稿；richResult=费用分解
  └─ SSE: done
```

### 7.2 连续追问（复用记忆，不重查）

```
用户输入: "那起付线呢"   ← 无单号，复用 anchor.settlementId
  │
  ├─ ChatStream.send(question)   body: { question, session_id: <同上>, settlement_id: '1671213'(来自anchor) }
  │
  ├─ SSE: context_need          → memory_ids 命中 Settlement/Policy [✓来自记忆]；must_query_semantic 仍 true(RULE未沉淀)
  ├─ SSE: step(...)             → 本轮可能命中已有记忆，跳过 settlement_query
  ├─ SSE: result                → AI msg 定稿（推理链承接上文）
  └─ 顶栏不动（同一结算），MemoryPanel 命中项高亮
```

### 7.3 主体切换（`@换结算` 或自然语言"查询李四"）

```
用户输入: "@换结算 1671214"   或   "查询李四的费用"
  │
  ├─ PolicyQAChatInput 解析 @指令 / 后端 ContextPlanner 检测 subject_changed
  ├─ SSE: context_need.subject_changed=true
  │    → anchor.settlementId 更新；MemoryManager 已清理 TOPIC 记忆（后端 side）
  │    → 顶栏弹横幅「已切换到 1671214，旧结算上下文已清除」
  ├─ 后续流程同首轮（重新锚定 + 沉淀）
```

> 后端主体切换清理逻辑已实现：`runtime_bridge.prepare_turn` 检测到 `subject_changed` 调 `expire_on_topic_change` 清理 TOPIC 记忆，STICKY（政策）保留 [来源: runtime_bridge.py `prepare_turn`]。

---

## 八、`@` 指令设计（结算单号从必填降级）

当前结算单号是每次必填的表单项。改造后：

| 指令 | 含义 | 前端处理 |
|---|---|---|
| `@换结算 <id>` | 切换当前结算锚点 | 更新 `anchor.settlementId`，下轮请求带新 id |
| `@换患者 <pid>` | 切换患者主体 | 更新 `anchor.patientId` |
| `@新会话` | 重置会话 | `resetSession()`，生成新 sessionId，清空 memories/messages |
| （无指令） | 连续追问 | 复用 `anchor`，请求带当前 settlementId |

**首帧兜底**：若 `anchor.settlementId` 为空且用户未提供，输入框 placeholder 提示「首次请提供结算单号，或用 @换结算 切换」。

---

## 九、落地路线（分阶段，低风险优先）

### 阶段一：对话流骨架 + session 跨轮（最高优先，跑通持续对话闭环）

| 任务 | 验证标准 |
|---|---|
| 1.1 新建 `usePolicyQAStream` hook，消费 `step`/`result`/`done`（暂忽略 Runtime 事件） | 多轮对话能连续进行，`session_id` 跨轮不变 |
| 1.2 `PolicyQAWorkspace` + `ChatStream`（复用 `chat/message-list` + `chat/chat-input`） | 对话气泡、流式正常 |
| 1.3 结算单号从必填表单项改为「首帧锚定 + @换结算」 | 首轮带 settlement_id，追问省略仍能答 |
| 1.4 保留首轮 `richResult`（费用分解）渲染（复用 `SettlementExplanationPage`） | 首轮结构化结果正常显示 |

**阶段一验证**：用户能连续问「查住院费用」→「那起付线呢」→「统筹支付多少」，三轮在同一 session，后端 Memory 复用（查日志 `memory_ids` 命中）。

### 阶段二：Runtime 可视化（消费 4 类 SSE 事件）

| 任务 | 验证标准 |
|---|---|
| 2.1 `usePolicyQAStream` 扩展消费 `context_need` / `memory_update` / `reasoning_step` | 事件正确映射到状态 |
| 2.2 `SessionAnchorBar`（顶栏锚点带） | 显示当前患者/就诊/结算/话题 |
| 2.3 `MemoryPanel`（左栏记忆面板） | 记忆随对话增长，命中/新查/跨话题标注正确 |
| 2.4 `ReasoningChainCollapsible`（推理链折叠） | 每条 AI 回复下可展开推理链 |

**阶段二验证**：左栏记忆随对话增长（Settlement→Policy→Drug），推理链可追溯，主体切换时顶栏弹横幅 + 左栏 TOPIC 记忆消失、POLICY 保留。

### 阶段三：增强（可选）

- 3.1 指代解析可视化（"这个药" → 高亮对应 Drug 记忆）
- 3.2 记忆快照下钻（点击 Settlement 记忆卡展开完整字段）
- 3.3 对比模式（同患者不同次结算，复用 `result.mode=compare`）
- 3.4 移动端响应式（MemoryPanel 收为抽屉）

### 验证流程（遵循 AGENTS.md 硬性流程）

- **单元**：`usePolicyQAStream` 的 SSE 解析（mock event stream → 状态断言）
- **组件**：`MemoryPanel` / `SessionAnchorBar` / `ReasoningChainCollapsible` 渲染测试（mock 数据）
- **Flow**：`policy-qa` 页面多轮对话 E2E（首轮→追问→主体切换），断言 session_id 跨轮、Memory 增长、推理链累积

---

## 十、与后端契约的对齐清单（落地前需确认/可能的后端微调）

| 项 | 现状 | 改造动作 | 归属 |
|---|---|---|---|
| `PolicyQARequest.session_id` | ✅ 已支持（`str \| None = None`） | 前端跨轮传入 | 前端 |
| `settlement_id` 必填 | `PolicyQARequest.settlement_id: str`（必填） | 追问轮前端从 `anchor` 补传，无需改后端 | 前端 |
| `context_need` 事件 | ✅ 已发 | 前端消费 | 前端 |
| `memory_update` 事件 | ✅ 已发 | 前端消费 | 前端 |
| `reasoning_step` 事件 | ✅ 已发 | 前端消费 | 前端 |
| `result.reasoning_chain/steps/memory_count` | ✅ 已附加 | 前端消费 | 前端 |
| 主体切换清理 | ✅ 后端 `prepare_turn` 已做 | 前端顶栏提示 | 前端 |
| `_on_calculate` 死分支 | ⚠️ orchestrator 不发 `calculate_explanation` 步骤（评估报告问题 A） | 可选：后端补发，或前端不依赖 | 后端（可选） |
| `output_groups.value` 金额映射 | ✅ 已修（`_FACT_FIELD_MAP`） | — | 已完成 |

> **结论**：后端 Runtime 桥 + SSE 契约**已就绪**，前端改造**无需后端必改项**（`calculate_explanation` 步骤为可选增强）。

---

## 十一、风险与回退

| 风险 | 应对 |
|---|---|
| 改造期间破坏现有「一次性查询」能力 | 阶段一与现有 `policy-qa-chat.tsx` 并存（新组件 `PolicyQAWorkspace`），验证通过后再替换 `page.tsx` 入口 |
| SSE 事件解析失败 | `usePolicyQAStream` 内每个事件独立 try/catch，失败记日志不阻塞主流程（与后端降级原则一致） |
| `session_id` 跨轮后 Memory 膨胀 | 后端 MemoryManager 已有 `compress` / `expire_by_policy`；前端 MemoryPanel 默认折叠低 importance 项 |
| 现有 `SettlementExplanationPage`（首轮费用分解）兼容 | 作为首轮 `richResult` 嵌入对话流首条 AI 消息，不丢弃 |

---

## 十二、与现有文档/代码的同步

| 文档/代码 | 同步内容 | 优先级 |
|---|---|---|
| `PROGRESS.md` | 新增「政策问答前端持续对话改造」条目 | P0（落地时） |
| `src/apps/portal/src/components/chat/helpers.ts` | `ChatMessage` 扩展可选 Runtime 字段（向后兼容） | P0 |
| `docs/steering/原型设计文档.md` | 补充政策问答持续对话原型 | P1 |
| `src/tests/AGENTS.md` | 新增前端组件/Flow 测试映射 | P1 |

---

## 附录 A：现有可复用资产清单

| 资产 | 路径 | 复用方式 |
|---|---|---|
| 对话输入 | `components/chat/chat-input.tsx` | `PolicyQAChatInput` 内核 |
| 消息列表 | `components/chat/message-list.tsx` | `ChatMessageList` 内核（扩展 reasoning 插槽） |
| 流式气泡 | `components/chat/streaming-bubble.tsx` | 直接复用 |
| 执行时间线 | `components/chat/execution-timeline.tsx` | 可选复用（trace 折叠） |
| SSE hook 范例 | `@/lib/sse-hooks`（`useChatStream`） | 参考，新建 `usePolicyQAStream` |
| 对话组件范例 | `components/settlement-chat.tsx` | 参考其 `useChatStream` 用法 |
| 消息类型 | `components/chat/helpers.ts`（`ChatMessage`） | 扩展 |
| 结构化结果渲染 | `components/settlement-explanation-page.tsx` | 首轮 `richResult` 复用 |

## 附录 B：术语对照（对齐 Runtime 设计 §十三）

| 前端概念 | Runtime 模块 | 后端来源 |
|---|---|---|
| 业务主体锚点（SessionAnchorBar） | BusinessSession | `context_need` + `RuntimeContext` |
| 会话记忆（MemoryPanel） | BusinessMemory + MemoryManager | `memory_update` + `MemoryManager` |
| 推理链（ReasoningChainCollapsible） | ReasoningState | `reasoning_step` + `result.reasoning_chain` |
| 本轮加载来源（ContextNeedIndicator） | ContextPlanner | `context_need` |
| 对话流（ChatStream） | （持续对话载体） | `step` / `result` |

---

*本设计评审通过后进入阶段一编码。编码遵循 AGENTS.md：最小可验证单元、先测试后实现、跨层一致性核对。*
