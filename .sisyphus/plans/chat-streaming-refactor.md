# 对话导办模块 SSE 流式重构 — 工作计划

## TL;DR

> **目标**: 将对话导办模块从同步 HTTP 请求 + 伪流式响应，重构为真正的 SSE 流式通信，实现 LLM token 级流式输出 + MCP/Skill 调用过程的实时可视化，解决 TTFB 过长问题。
>
> **核心改动**: 后端 `chat/stream` 从"同步处理→一次性发出"改为"异步回调→逐事件推送"；前端从"等待完整响应"改为"增量渲染 + 执行步骤时间轴"。
>
> **预计工期**: 2-3 周（5 个 Wave，约 25 个任务）

---

## Context

### 原始请求
用户要求重构对话导办模块，核心三点：
1. **底层通信**: HTTP → SSE/WebSocket 流式
2. **后端流式**: `stream: true` + 拦截 Agent 执行过程，MCP/Skill 调用实时推送
3. **前端渲染**: SSE 解析 + 执行步骤展示 UI + 打字机效果

### 当前架构问题
- `/chat/stream` 端点本质是同步处理 + 分阶段 SSE 包装，LLM 响应一次性发出
- `SkillExecutionEngine._execute_sequential()` 同步顺序执行，无事件发射
- LangGraph `graph.invoke()` 同步阻塞，无法中途返回
- 前端已有 SSE 解析基础设施但未利用真正的流式能力

### 现有基础
- `ModelGateway.generate_stream()` 已实现真正的 LLM token 流式
- `/model-test/stream` 是可参考的正确流式模式
- 前端 `readSseStream()` / `parseSseChunk()` 已能解析 SSE
- `settlement-chat.tsx` 已有 `token`/`delta` 事件处理逻辑（但从未收到）

---

## Work Objectives

### 核心交付物
- **后端**: 支持真正流式的 `chat/stream` 端点，带回调机制的 `SkillExecutionEngine`，LangGraph 流式节点
- **前端**: 实时执行步骤时间轴组件，增量渲染的聊天消息，SSE 流式连接管理
- **类型**: 前后端统一的流式事件协议类型定义

### Definition of Done
- [ ] 用户发送消息后 200ms 内收到第一个 SSE 事件（TTFB < 200ms）
- [ ] LLM token 以 `delta` 事件逐块到达前端并实时渲染
- [ ] MCP/Skill 调用以 `tool_call`/`tool_result` 事件流式推送
- [ ] 前端展示可折叠的执行步骤时间轴，包含调用发起→参数→结果
- [ ] 完整的错误处理、超时处理、连接重试机制
- [ ] 所有现有功能回归测试通过

### Must NOT Have
- ❌ 不改变现有 `/chat` 同步端点（向后兼容）
- ❌ 不使用 WebSocket（保持 SSE 的简单性和 HTTP/2 兼容性）
- ❌ 不引入新的第三方依赖库
- ❌ 不破坏现有的 mock 降级机制

---

## 验证策略

### 测试策略
- **基础设施**: 已有（Mocha + Supertest 用于 API 测试，Playwright 用于 E2E）
- **自动化测试**: YES — 后端 API 测试 + 前端到 E2E 测试
- **Agent-Executed QA**: 每个任务均包含

### 性能基准
- TTFB P99 < 500ms（当前约 2-5s）
- 流式端到端延迟 < 100ms per token
- 内存占用增量 < 50MB

---

## Execution Strategy — 并行执行 Waves

```
Wave 1 (基础 — 后端事件协议 + 类型系统):
├── T1: 定义流式事件协议 + 前端类型扩展
├── T2: 创建 StreamingEmitter 工具类
├── T3: 后端 SSE 事件工具增强
└── T4: 前端 SSE 客户端重构

Wave 2 (核心 — 执行引擎流式化):
├── T5: SkillExecutionEngine 回调机制改造
├── T6: LangGraph 流式节点改造
├── T7: UnifiedScenarioExecutor 流式适配
└── T8: chat_stream 端点重构为真正流式

Wave 3 (前端 — 实时渲染):
├── T9: ExecutionStepTimeline 组件
├── T10: 聊天消息增量渲染优化
├── T11: 流式连接状态管理 (useSSE hook)
└── T12: 打字机效果 + 光标动画

Wave 4 (集成 — 串联端到端):
├── T13: MCP 工具调用流式事件
├── T14: 前端 IntentTraceCard 流式更新
├── T15: 错误处理与重试机制完善
└── T16: Mock 数据流式化

Wave FINAL (验证与清理):
├── F1: 全流程端到端测试
├── F2: 性能基准测试
├── F3: 代码审查与文档更新
└── F4: 回归测试套件运行
```

**关键路径**: T1 → T2 → T5 → T8 → T9 → T13 → F1
**最大并行度**: 4（Waves 1-2 各 4 个并行任务）

---

## TODOs

---

### Wave 1 — 基础建设

- [x] **T1. 定义流式事件协议 + 前端类型扩展**

  **What to do**:
  - 在 `src/runtime/api/streaming.py` 中定义完整的流式事件协议，包含以下事件类型:
    - `stream:start` — 流开始（包含 intent 预估、请求 ID）
    - `stream:step` — 处理阶段（intent_detection, risk_control, authorization, scenario_processing）
    - `stream:intent_trace` — 意图识别结果
    - `stream:delta` — LLM token 增量
    - `stream:tool_call` — MCP/Skill 调用发起（包含 tool_name, params, call_id）
    - `stream:tool_result` — MCP/Skill 调用结果（包含 call_id, result, duration_ms）
    - `stream:final` — 完整响应
    - `stream:error` — 错误
    - `stream:done` — 流结束
  - 在 `src/apps/portal/src/lib/types.ts` 中扩展类型:
    - 新增 `StreamingEvent` 联合类型
    - 新增 `ToolCallPayload`, `ToolResultPayload` 接口
    - 新增 `StreamStep` 接口（步骤 ID、标签、状态、时间戳）
    - 扩展 `SseEventType` 为 union type
  - 在 `src/apps/portal/src/lib/api-client.ts` 中:
    - 升级 `parseSseChunk()` 支持新的事件类型
    - 添加 `StreamingEvent` 类型守卫函数

  **Must NOT do**:
  - 不要修改现有的 `event: step` / `event: final` 格式（向后兼容）
  - 不要移除 `SseEvent` 旧类型

  **References**:
  - `src/runtime/api/streaming.py:1-13` — 现有 SSE 工具
  - `src/apps/portal/src/lib/types.ts:175-202` — 现有 SSE 类型
  - `src/apps/portal/src/lib/api-client.ts:499-548` — 现有 SSE 解析

  **Acceptance Criteria**:
  - [ ] `streaming.py` 导出的 `sse_event()` 支持所有新事件类型
  - [ ] 前端 `types.ts` 的 `SseEventType` union 包含所有新类型
  - [ ] `api-client.ts` 的 `parseSseChunk()` 能正确解析新事件

  **Recommended Agent Profile**:
  - Category: `quick` — 类型定义和工具函数
  - Skills: `typescript`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 1
  - Blocks: T2, T5, T8

- [x] **T2. 创建 StreamingEmitter 工具类**

  **What to do**:
  - 在 `src/runtime/api/` 下创建 `streaming_emitter.py`
  - 实现 `StreamingEmitter` 类，封装 SSE 事件生成逻辑:
    ```python
    class StreamingEmitter:
        def __init__(self, yield_fn: Callable[[str], None]):
            self._yield = yield_fn
            self._step_count = 0
        
        async def emit_start(self, ...)
        async def emit_step(self, step: str, message: str)
        async def emit_intent_trace(self, trace: dict)
        async def emit_delta(self, content: str)
        async def emit_tool_call(self, tool_name: str, params: dict, call_id: str)
        async def emit_tool_result(self, call_id: str, result: dict, duration_ms: int)
        async def emit_final(self, response: dict)
        async def emit_error(self, error: dict)
        async def emit_done(self)
    ```
  - 每个方法内部调用 `self._yield(sse_event(event_name, data))`
  - 添加类型注解和文档字符串

  **Must NOT do**:
  - 不要在此处实现业务逻辑，只做事件封装

  **References**:
  - `src/runtime/api/streaming.py:5-7` — 现有 `sse_event()`
  - `src/runtime/api/routes.py:147-171` — 现有 `events()` 生成器

  **Acceptance Criteria**:
  - [ ] `StreamingEmitter` 可被 `chat_stream` 端点导入和使用
  - [ ] 所有事件类型有对应的 emit 方法

  **Recommended Agent Profile**:
  - Category: `quick` — 工具类封装
  - Skills: `python`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 1
  - Blocks: T8

- [x] **T3. 后端 SSE 事件工具增强**

  **What to do**:
  - 升级 `src/runtime/api/streaming.py`:
    - 添加 `ensure_streaming_fields()` 确保流式响应包含必要字段
    - 添加 `format_tool_call_event()` / `format_tool_result_event()` 快捷函数
    - 支持 JSONL 格式输出选项（可选）
  - 添加请求上下文追踪:
    - 每个流式请求生成唯一 `request_id`
    - 每个 `tool_call` 事件包含 `call_id`，后续 `tool_result` 引用相同 `call_id`

  **Must NOT do**:
  - 不要改变现有 `sse_event()` 的签名

  **References**:
  - T1 的流式事件协议定义
  - `src/runtime/api/streaming.py` 现有代码

  **Acceptance Criteria**:
  - [ ] `request_id` 随 `stream:start` 事件发出
  - [ ] `tool_call` → `tool_result` 通过 `call_id` 关联

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: `python`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 1
  - Blocks: T8, T13

- [x] **T4. 前端 SSE 客户端重构**

  **What to do**:
  - 重构 `src/apps/portal/src/lib/api-client.ts`:
    - `sendChatStream()` 改为返回 `{ cancel: () => void }`，支持取消
    - 添加连接超时自动重试逻辑（指数退避，最多 3 次）
    - 添加 `AbortController` 支持
  - 创建 `src/apps/portal/src/lib/sse-hooks.ts`:
    - `useSSEConnection()` — 管理 SSE 连接生命周期
    - `useChatStream()` — 高阶 hook，封装 `sendChatStream` 并管理状态
  - 拆分 `SseEvent` 处理逻辑为独立的 handler map

  **Must NOT do**:
  - 不要改变外部 API 签名（`sendChatStream` 仍接受 `onEvent` 回调）

  **References**:
  - `src/apps/portal/src/lib/api-client.ts:224-259` — 现有 `sendChatStream`
  - `src/apps/portal/src/lib/api-client.ts:447-548` — 现有 SSE 解析

  **Acceptance Criteria**:
  - [ ] 支持 `AbortController` 取消流式请求
  - [ ] 30 秒超时后自动重试（最多 3 次）
  - [ ] `useChatStream` hook 可被 `settlement-chat.tsx` 直接使用

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: `typescript`, `react`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 1
  - Blocks: T10, T11, T12

---

### Wave 2 — 执行引擎流式化

- [x] **T5. SkillExecutionEngine 回调机制改造**

  **What to do**:
  - 将 `SkillExecutionEngine` 的构造函数增加 `on_event` 回调参数:
    ```python
    class SkillExecutionEngine:
        def __init__(self, ..., on_event: Callable[[str, dict], None] | None = None)
    ```
  - 在 `_execute_sequential()` 的每个关键节点调用回调:
    - 步骤开始前: `on_event('tool_call', {tool_id, step_id, params})`
    - 步骤完成后: `on_event('tool_result', {tool_id, step_id, result, duration_ms})`
    - 错误时: `on_event('error', {...})`
  - 修改 `src/runtime/scenario_executor.py` 中 `_try_mention_execution()` 和 `_try_skill_matching()`，将回调传递给 `SkillExecutionEngine`

  **Must NOT do**:
  - 不要改变 `execute_skill()` 的返回类型

  **References**:
  - `src/runtime/skill_registry/engine.py:62-234` — 现有 SkillExecutionEngine
  - `src/runtime/scenario_executor.py:197-296` — 现有执行路径

  **Acceptance Criteria**:
  - [ ] `SkillExecutionEngine` 在每个步骤执行前后发射事件
  - [ ] 事件包含 `call_id`、`tool_id`、`params`、`result`、`duration_ms`
  - [ ] 不影响现有同步返回的 `AgentResponse`

  **Recommended Agent Profile**:
  - Category: `deep` — 需要理解执行引擎内部逻辑
  - Skills: `python`

  **Parallelization**:
  - Can Run In Parallel: YES (within Wave 2)
  - Parallel Group: Wave 2
  - Blocks: T8 (需要此改造完成才能流式推送 tool 事件)

- [x] **T6. LangGraph 流式节点改造**

  **What to do**:
  - 研究 LangGraph 的 `interrupt()` 机制和流式 API
  - 在 `src/runtime/langgraph/` 下创建 `streaming.py`:
    - 包装 `graph.stream()` 方法以支持流式输出
    - 每个节点执行前后发射 `stream:step` 事件
    - 关键: 支持 `graph.stream()` 的 `stream_mode="updates"` 逐节点返回
  - 修改 `src/runtime/scenario_executor.py` 的 `_execute_scenario_langgraph()`:
    - 接受 `on_event` 回调
    - 使用新的 `StreamingLangGraph` 包装器
    - 在每个 LangGraph 节点完成后推送事件

  **Must NOT do**:
  - 不要破坏现有的非流式路径

  **References**:
  - `src/runtime/scenario_executor.py:298-375` — 现有 LangGraph 执行
  - `src/runtime/langgraph/settlement_exception.py` — 结算异常图
  - `src/runtime/langgraph/pre_discharge_qc.py` — 质控图
  - LangGraph 官方文档: `graph.stream()` API

  **Acceptance Criteria**:
  - [ ] LangGraph 执行过程可通过回调逐节点推送
  - [ ] 节点状态变更实时推送 (`stream:step`)
  - [ ] `human_confirmation` 中断仍正常工作

  **Recommended Agent Profile**:
  - Category: `deep` — LangGraph 流式 API
  - Skills: `python`, `langgraph`

  **Parallelization**:
  - Can Run In Parallel: YES (within Wave 2)
  - Parallel Group: Wave 2
  - Blocks: T8

- [x] **T7. UnifiedScenarioExecutor 流式适配

  **What to do**:
  - 修改 `UnifiedScenarioExecutor` 的执行方法签名，接受 `on_event` 回调
  - 在每个执行分支（mention/skill/langgraph/mcp）中注入回调
  - 创建 `src/runtime/scenario_executor.py` 的流式版本入口: `execute_streaming()`
  - 确保回调在正确的协程上下文中被调用

  **Must NOT do**:
  - 不要移除现有的同步 `execute()` 方法

  **References**:
  - `src/runtime/scenario_executor.py:176-401` — 现有 UnifiedScenarioExecutor
  - T5、T6 的改造结果

  **Acceptance Criteria**:
  - [ ] `execute_streaming()` 存在且可工作
  - [ ] 所有执行路径（mention/skill/langgraph/mcp）均触发事件回调

  **Recommended Agent Profile**:
  - Category: `deep`
  - Skills: `python`

  **Parallelization**:
  - Can Run In Parallel: YES (within Wave 2)
  - Parallel Group: Wave 2
  - Blocks: T8

- [x] **T8. chat_stream 端点重构为真正流式**

  **What to do**:
  - 重写 `src/runtime/api/routes.py` 的 `chat_stream()` 函数:
    - 使用 `StreamingEmitter` 替代手动 `yield sse_event()`
    - 意图检测后立即 `yield stream:intent_trace`（已有）
    - 场景执行使用新的流式执行器，实时推送 `stream:step` / `stream:tool_call` / `stream:tool_result`
    - LLM 生成部分集成 `ModelGateway.generate_stream()`，逐 token 推送 `stream:delta`
    - 最终汇总生成 `stream:final`
  - 修改 `process_chat_request()` 或创建新的 `process_chat_stream()` 支持回调
  - 添加超时控制: 5 分钟流式超时

  **Must NOT do**:
  - 不要修改 `/chat` 同步端点
  - 不要引入新的外部依赖

  **References**:
  - `src/runtime/api/routes.py:133-171` — 现有 `chat_stream`
  - `src/runtime/api/streaming.py` — StreamingEmitter (T2)
  - `src/runtime/scenario_executor.py` — 流式执行器 (T5/T6/T7)
  - `src/model_service/gateway.py:76-99` — 现有 `generate_stream()`

  **Acceptance Criteria**:
  - [ ] `chat/stream` 在 200ms 内发出第一个事件
  - [ ] LLM token 通过 `stream:delta` 逐块推送
  - [ ] 工具调用通过 `stream:tool_call`/`stream:tool_result` 实时推送
  - [ ] 最终通过 `stream:final` 发送完整响应
  - [ ] 错误通过 `stream:error` 推送

  **Recommended Agent Profile**:
  - Category: `deep` — 端到端集成
  - Skills: `python`, `fastapi`

  **Parallelization**:
  - Can Run In Parallel: NO (depends on T1, T2, T5, T6, T7)
  - Sequential after Wave 1 + Wave 2

---

### Wave 3 — 前端实时渲染

- [x] **T9. ExecutionStepTimeline 组件**

  **What to do**:
  - 在 `src/apps/portal/src/components/chat/` 下创建 `execution-timeline.tsx`:
    - 垂直时间轴布局，左侧显示步骤节点，右侧显示详细信息
    - 步骤类型: 意图识别 → 安全检查 → 授权校验 → 场景执行 → 工具调用 → 结果生成
    - 每个步骤有 4 种状态: `pending` / `running` / `completed` / `error`
    - 工具调用步骤可展开折叠面板，显示调用参数和返回结果
    - 使用 CSS 动画实现节点间的连接线动态绘制效果
    - 支持实时更新（新事件到达时自动更新对应步骤状态）
  - 样式: 暗色主题，与聊天区域协调
  - 引用 `src/apps/portal/src/components/ui/` 的基础组件

  **Must NOT do**:
  - 不要做成独立页面，只作为聊天页面的内嵌组件

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:755-779` — 现有意图追踪 UI
  - `src/apps/portal/src/components/intent-trace-card.tsx` — 现有意图卡片

  **Acceptance Criteria**:
  - [ ] 时间轴实时更新，步骤状态变化带动画
  - [ ] 工具调用可折叠，展开显示参数和结果
  - [ ] 至少 5 个步骤节点的完整展示

  **Recommended Agent Profile**:
  - Category: `visual-engineering`
  - Skills: `typescript`, `react`, `css`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 3
  - Blocks: T10

- [x] **T10. 聊天消息增量渲染优化**

  **What to do**:
  - 修改 `settlement-chat.tsx`:
    - 维护 `streamingSteps` state，实时更新执行步骤
    - `stream:delta` 事件到来时，追加到当前流式消息的 `content`
    - `stream:tool_call` 事件到来时，在聊天区域显示工具调用提示
    - `stream:tool_result` 事件到来时，更新对应工具调用的结果展示
    - 最终 `stream:final` 到来时，确认消息完成，更新 intentTrace
  - 优化消息列表渲染:
    - 流式消息使用 `useRef` + `innerHTML` 追加而非全量重渲染
    - 长列表虚拟滚动（考虑使用 `react-window` 或原生方案）

  **Must NOT do**:
  - 不要改变现有消息数据结构

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:321-555` — 现有聊天处理逻辑
  - T9 的 ExecutionStepTimeline

  **Acceptance Criteria**:
  - [ ] 消息内容随 token 到达逐字显示（打字机效果）
  - [ ] 工具调用消息在流式过程中实时显示
  - [ ] 滚动自动跟随最新消息
  - [ ] 不出现消息闪烁或重排

  **Recommended Agent Profile**:
  - Category: `visual-engineering`
  - Skills: `typescript`, `react`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 3
  - Blocks: T11

- [x] **T11. 流式连接状态管理 (useSSE hook)**

  **What to do**:
  - 创建 `src/apps/portal/src/lib/hooks/use-sse.ts`:
    - `useSSE(url, options)` — 管理 EventSource 连接
    - 自动重连（指数退避）
    - 心跳检测（服务器端 keep-alive 每 15s）
    - 连接状态: `connecting` / `connected` / `reconnecting` / `closed` / `error`
    - 提供 `close()` 手动关闭
  - 创建 `src/apps/portal/src/lib/hooks/use-chat-stream.ts`:
    - 高阶 hook，包装 `useSSE` 并适配聊天场景
    - 管理 `messages`、`streamingContent`、`intentTrace`、`steps` 等状态
    - 内置超时处理（30s 无数据则报错）

  **Must NOT do**:
  - 不要用 EventSource 替代 fetch-based SSE（需要 POST 请求体支持）

  **References**:
  - `src/apps/portal/src/lib/api-client.ts:447-497` — 现有 SSE 读取
  - `src/apps/portal/src/lib/api-context.tsx` — 现有连接状态

  **Acceptance Criteria**:
  - [ ] `useSSE` 支持自动重连（最多 5 次）
  - [ ] `useChatStream` 封装所有聊天流状态管理
  - [ ] 连接状态实时反映到 UI

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: `typescript`, `react`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 3

- [x] **T12. 打字机效果 + 光标动画**

  **What to do**:
  - 创建 `src/apps/portal/src/components/chat/typewriter.tsx`:
    - 可配置打字速度（默认 20-40ms/字符）
    - 支持暂停/恢复（当收到 `stream:tool_call` 时暂停，`stream:tool_result` 后恢复）
    - 光标闪烁动画（CSS `@keyframes`）
    - 支持富文本内容（保留 markdown 格式的粗体/列表等）
  - 优化现有光标样式:
    - 使用 `css` 变量控制颜色和动画时长
    - 与当前蓝白主题协调

  **Must NOT do**:
  - 不要引入第三方打字机库

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:861` — 现有光标实现
  - `src/apps/portal/app/globals.css` — 现有 CSS 变量

  **Acceptance Criteria**:
  - [ ] 每个字符有自然随机的微小延迟（15-45ms）
  - [ ] 工具调用时打字暂停
  - [ ] 光标与打字节奏同步

  **Recommended Agent Profile**:
  - Category: `visual-engineering`
  - Skills: `typescript`, `css`, `react`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 3

---

### Wave 4 — 集成与完善

- [x] **T13. MCP 工具调用流式事件**

  **What to do**:
  - 在 `src/runtime/orchestration/mcp_integration.py` 中:
    - 调用 MCP 工具时发射 `stream:tool_call` 事件
    - 工具返回结果时发射 `stream:tool_result` 事件
    - 工具调用失败时发射 `stream:error` 事件
  - 修改 `UnifiedScenarioExecutor._execute_mcp()`:
    - 接受 `on_event` 回调
    - 在计划构建和执行各阶段推送事件
  - 确保 MCP 工具的异步调用兼容流式（如果使用 asyncio）

  **Must NOT do**:
  - 不要改变 MCP 协议层的接口

  **References**:
  - `src/runtime/orchestration/mcp_integration.py` — 现有 MCP 集成
  - `src/runtime/scenario_executor.py:377-390` — 现有 MCP 执行路径
  - T7 的流式适配

  **Acceptance Criteria**:
  - [ ] MCP 工具调用以 `stream:tool_call` 事件实时推送
  - [ ] MCP 工具结果以 `stream:tool_result` 事件推送
  - [ ] 失败情况正确处理

  **Recommended Agent Profile**:
  - Category: `deep`
  - Skills: `python`

  **Parallelization**:
  - Can Run In Parallel: YES (within Wave 4)
  - Parallel Group: Wave 4

- [x] **T14. 前端 IntentTraceCard 流式更新**

  **What to do**:
  - 修改 `src/apps/portal/src/components/intent-trace-card.tsx`:
    - 支持流式接收 pipeline stage 状态更新
    - 每个阶段（recall → llm → verify → route）实时切换状态图标
    - 添加流式候选意图更新（当 `stream:intent_trace` 事件到达时）
  - 在 `settlement-chat.tsx` 中将流式事件路由到 IntentTraceCard

  **Must NOT do**:
  - 不要改变 IntentTraceCard 的外部 props 接口

  **References**:
  - `src/apps/portal/src/components/intent-trace-card.tsx` — 现有卡片
  - T9 的 ExecutionStepTimeline

  **Acceptance Criteria**:
  - [ ] Pipeline stages 随事件实时高亮
  - [ ] 候选意图分数实时更新
  - [ ] 整体与现有暗色主题一致

  **Recommended Agent Profile**:
  - Category: `visual-engineering`
  - Skills: `typescript`, `react`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 4

- [ ] **T15. 错误处理与重试机制完善**

  **What to do**:
  - 后端:
    - `chat_stream` 中捕获所有异常并发射 `stream:error`
    - 添加流式级别的超时（5 分钟无活动自动关闭）
    - 添加优雅降级: 流式失败时自动回退到 `/chat` 同步请求
  - 前端:
    - SSE 断连时显示重连提示
    - 3 次重连失败后降级为普通 HTTP 请求
    - 流式过程中出错，已接收的部分内容保留
    - 添加 `retry` 按钮允许用户手动重试

  **Must NOT do**:
  - 不要让错误状态导致页面崩溃

  **References**:
  - `src/apps/portal/src/lib/api-client.ts:193-196` — 现有降级
  - `src/apps/portal/src/components/settlement-chat.tsx:373-385` — 现有超时

  **Acceptance Criteria**:
  - [ ] 流式中断自动重试（最多 3 次）
  - [ ] 降级到同步模式时有明确提示
  - [ ] 部分接收的内容不丢失

  **Recommended Agent Profile**:
  - Category: `deep`
  - Skills: `typescript`, `python`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 4

- [x] **T16. Mock 数据流式化**

  **What to do**:
  - 修改 `src/apps/portal/src/lib/mock-data.ts`:
    - 添加流式 mock 数据生成函数 `mockStreamingChatResponse()`
    - 按时间间隔模拟 `stream:step` → `stream:delta` → `stream:tool_call` → `stream:tool_result` → `stream:final` → `stream:done`
    - 每个事件间隔 200-500ms，模拟真实流式体验
  - 修改 `emitFallbackChatStream()` 以使用新的流式 mock

  **Must NOT do**:
  - 不要改变 mock 数据的业务内容

  **References**:
  - `src/apps/portal/src/lib/mock-data.ts` — 现有 mock
  - T1-T3 的流式事件协议

  **Acceptance Criteria**:
  - [ ] 离线模式下也能体验流式效果
  - [ ] 流式 mock 事件间隔自然

  **Recommended Agent Profile**:
  - Category: `quick`
  - Skills: `typescript`

  **Parallelization**:
  - Can Run In Parallel: YES
  - Parallel Group: Wave 4

---

### Wave FINAL — 验证与发布

- [ ] **F1. 全流程端到端测试**

  **What to do**:
  - 编写端到端测试脚本，覆盖完整流式场景:
    - 普通对话（意图识别 → 文本生成）
    - 技能调用对话（@技能提及 → 工具调用 → 结果返回）
    - MCP 工具对话
    - 高风险动作（人工确认流程）
  - 验证每个 SSE 事件的正确性和时序

  **QA Scenarios**:
  ```
  Scenario: 普通对话流式体验
    Tool: Playwright
    Steps:
      1. 打开聊天页面
      2. 输入"为什么这个患者结算失败"
      3. 验证: 200ms 内出现第一个流式事件
      4. 验证: 意图识别面板实时更新
      5. 验证: 回复内容逐字出现（打字机效果）
      6. 验证: 最终消息完整显示

  Scenario: 技能调用流式展示
    Tool: Playwright
    Steps:
      1. 输入"查询这个患者的费用明细"
      2. 验证: 执行时间轴显示工具调用步骤
      3. 验证: 工具调用参数和结果实时展示
      4. 验证: 最终汇总消息正确
  ```

- [ ] **F2. 性能基准测试**

  **What to do**:
  - 测量 TTFB（首字节时间）
  - 测量流式端到端延迟
  - 测量内存占用
  - 与优化前数据对比

  **QA Scenarios**:
  ```
  Scenario: 性能基准
    Tool: curl + 自定义脚本
    Steps:
      1. curl -w "time_starttransfer: %{time_starttransfer}\n" 发送流式请求
      2. 验证 time_starttransfer < 0.2s
      3. 验证总流式时间与 token 数量成正比
  ```

- [ ] **F3. 代码审查与文档更新**

  **What to do**:
  - 审查所有新代码的命名、注释、错误处理
  - 更新 `docs/` 相关设计文档
  - 更新 `AGENTS.md` 开发指南

- [ ] **F4. 回归测试套件运行**

  **What to do**:
  - 运行全部现有单元测试
  - 运行全部现有 API 测试
  - 运行全部现有 Flow 测试
  - 确保无回归

---

## Commit Strategy

| Wave | Commit Message | Files |
|------|---------------|-------|
| W1 | `feat: add streaming event protocol and type definitions` | streaming_emitter.py, types.ts, api-client.ts (新增部分) |
| W2 | `feat: refactor skill engine and langgraph for streaming` | engine.py, scenario_executor.py, langgraph/streaming.py, routes.py |
| W3 | `feat: add real-time execution timeline and typewriter UI` | execution-timeline.tsx, typewriter.tsx, use-sse.ts, use-chat-stream.ts, settlement-chat.tsx |
| W4 | `feat: integrate MCP streaming and error resilience` | mcp_integration.py, intent-trace-card.tsx, mock-data.ts |
| FINAL | `test: full E2E regression for streaming refactor` | tests files only |

---

## Success Criteria

### 性能指标
- TTFB P50 < 100ms, P99 < 500ms
- Token 流式延迟 < 50ms/char
- 工具调用事件延迟 < 200ms

### 功能清单
- [ ] 消息发送后立即显示"正在识别意图"状态
- [ ] LLM 回复逐字流式渲染（打字机效果）
- [ ] 工具调用实时显示在执行时间轴中
- [ ] 工具参数和返回结果可展开查看
- [ ] 断连自动重连（≤3 次）
- [ ] 离线模式降级为流式 mock
- [ ] 高风险动作仍走人工确认流程
- [ ] 所有现有测试通过