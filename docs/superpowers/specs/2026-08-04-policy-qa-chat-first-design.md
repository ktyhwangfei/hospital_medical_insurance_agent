# Policy QA Chat-first 重构设计

日期：2026-08-04
实施同步：2026-08-05
状态：核心实现完成，R4 性能与 E2E 证据待补充
风险等级：R4（修改 Policy QA 核心响应契约与结算解释链路）

## 1. 背景

重构前的 `policy-qa` 页面把查询表单、执行步骤、双视角答案、结算来源、费用分解和政策证据同时铺在页面上。主要问题不是功能不足，而是产品模型混杂：页面既像业务查询看板，又像 Agent 运行监控，还试图承担患者沟通界面。

最终实现链路是 `PolicyQAWorkspace` → `PolicyConversation` / `usePolicyQAStream` → `parseSseBlock`；Hook 按空行缓冲完整 SSE 帧，再进行递归安全过滤和运行时结果映射。旧 `PolicyQAChat`、双视角组件及其测试已删除。

本次设计将页面重新定位为院端专业 Chat-first 产品：Agent 在后台自动完成结算核对与政策检索，前台优先呈现答案、政策引用和连续追问。执行细节采用渐进披露，不再作为主视觉。

## 2. 产品判断依据

当前主流 AI 产品会根据任务复杂度选择交互模型：

- 即时咨询使用 Chat-first，回答和来源是主内容。
- 可独立编辑、复用或导出的长内容才进入 Canvas/Artifact。
- 分钟级长任务、后台执行和人工审批才持续展示任务进度。

Policy QA 是高频、短时、可连续追问的专业咨询，不是后台长任务。因此不采用任务看板、常驻步骤栏或左右监控布局。

参考：

- OpenAI：Chat 与 Work 的产品分工，<https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex>
- OpenAI：搜索回答的行内引用与来源入口，<https://help.openai.com/en/articles/9237897-connectors-in-chatgpt>
- Anthropic：Artifacts 仅承载独立、可复用的重要内容，<https://support.anthropic.com/en/articles/9487310-what-are-artifacts-and-how-do-i-use-them>
- Google：Canvas 用于协作编辑和导出独立成果，<https://support.google.com/gemini/answer/16047321>

## 3. 目标与成功标准

### 3.1 目标

1. 将 `policy-qa` 重构为单列、居中、连续追问的 Chat-first 页面。
2. 建立浅色医疗专业内容区，同时保留 Portal 现有深色全局导航。
3. 将会话状态、SSE 解析、安全过滤和展示组件拆分为清晰边界。
4. 将双视角输出统一为面向当前院端角色的单一答案。
5. 从公开响应和 UI 删除结算数据表名、字段名和来源明细；保留现有任务、工作流与内部运行标识追溯。
6. 保留结构化费用、计算过程、政策证据、引用和不确定性。

### 3.2 成功标准

- 1280–1920px 桌面端中，问题、回答和输入框沿单一阅读轴排列。
- 空闲状态以 Agent 能力和示例问题引导用户，不出现传统顶部查询表单。
- 结算单号作为 Composer 上下文标签存在，可继续用于请求。
- 执行中只显示一句用户可理解的动态状态；完成后收敛为查证摘要。
- 唯一答案字段为 `answer`，不再返回或渲染 `patient_view`、`office_view`。
- 公开响应不再返回或渲染 `settlement_evidence`。
- 政策结论携带引用；无法形成可靠结论时携带 `uncertainties`。
- SSE 事件在分块、跨行、畸形帧和 `done` 场景下均有自动化测试。
- 单元测试、API 测试、Flow 测试、性能测试和 E2E 按治理要求通过。

## 4. 范围

### 4.1 本次包含

- Portal `policy-qa` 内容区视觉与布局重构。
- 前端组件化、会话 reducer、SSE 帧解析和安全映射。
- 后端 Policy QA 单答案生成和输出校验。
- Policy QA 响应契约更新。
- 删除双视角和公开结算来源相关前后端代码。
- 对应单元、API、Flow、性能和 E2E 验证。

### 4.2 本次不包含

- Portal 其他页面浅色化或全局主题迁移。
- 手机和平板专项布局。
- 新增患者端页面或“生成患者沟通说明”动作。
- 修改政策检索算法、结算计算规则或模型路由策略。
- 展示内部推理、原始工具响应、数据库表名或字段名。

## 5. 交互设计

### 5.1 页面结构

页面保留深色全局导航，内容区使用浅色背景。主内容最大宽度 840px，沿单一阅读轴排列：

1. 页面标题和轻量会话操作。
2. 用户消息。
3. Agent 查证摘要。
4. Agent 答案正文。
5. 结构化金额与按需展开的计算明细。
6. 行内政策引用和“来源”入口。
7. 建议追问。
8. 底部持续可用的 Composer。

不使用常驻左右栏、数据驾驶舱、顶部业务表单或大面积步骤卡。

### 5.2 空闲状态

- 居中展示 Agent 能力说明和三个到四个示例问题。
- Composer 是主要操作入口。
- 结算单号显示为上下文标签，而非独立表单区。

### 5.3 执行中

- 用户消息立即进入对话。
- Agent 区域显示一条来自 `public_message` 的动态状态，例如“正在核对结算数据”。
- 不展示内部推理、工具参数、数据库结构或完整执行时间线。
- 当前请求完成前禁用重复提交，避免并发状态污染。

### 5.4 完成状态

- 先展示结论，再展示解释。
- “已核对当前结算单与 6 条政策依据”作为轻量摘要，可按需展开公开、可追溯的步骤摘要。
- 金额结构使用简洁列表或表格，不使用多指标仪表盘。
- 计算过程和费用明细使用折叠区。
- 政策引用进入正文或答案尾部；完整来源通过临时 Dialog 打开，不形成常驻分栏。
- 答案后提供自然的建议追问。

### 5.5 部分回答与失败

- `partial`：保留已确认内容，显式列出缺失信息和不确定性。
- `unavailable`：不生成确定性结论，提供重试和人工咨询建议。
- 政策未命中：说明未找到足够政策依据。
- 网络中断或畸形 SSE：保留已接收内容，标记流中断并允许重试。

## 6. 前端架构

已实现结构：

```text
policy-qa/page.tsx
└─ PolicyQAWorkspace
   └─ PolicyConversation
      ├─ PolicyQAEmptyState
      ├─ PolicyMessageList
      │  ├─ UserMessage
      │  └─ PolicyAgentAnswer
      │     ├─ VerificationSummary
      │     ├─ CalculationDisclosure
      │     └─ PolicySourcesDialog
      └─ PolicyComposer

usePolicyQAStream
├─ 会话状态与请求生命周期
├─ send / resetSession
└─ policy-qa-session 辅助映射

policy-qa-stream
├─ SSE frame parser
├─ forbidden-field filter
├─ backend-field mapper
└─ typed session events
```

### 6.1 职责边界

- `PolicyQAWorkspace` 创建流式会话状态并把页面编排交给 `PolicyConversation`。
- `PolicyConversation` 组合空闲态、消息列表和 Composer，不解析网络数据。
- `usePolicyQAStream` 管理查询生命周期、完整 SSE 帧缓冲和会话状态，不包含视觉代码。
- `policy-qa-stream` 是纯逻辑模块，负责完整 SSE 帧解析、安全过滤和类型映射。
- `PolicyAgentAnswer` 组合现有结构化金额、费用和政策展示能力，不解析网络数据。
- `PolicySourcesDialog` 仅展示政策依据，不展示结算表名和字段名。

避免为每个小块创建单独抽象；仅拆分具有独立职责、状态或测试价值的单元。

## 7. 后端契约

公开结果结构：

```text
Policy QA result
├─ answer
├─ answer_status             complete / partial / unavailable
├─ case_context
├─ calculation_steps
├─ definition
├─ warnings
├─ policy_evidence
├─ citations
├─ uncertainties
└─ verification_summary
```

`verification_summary` 是结算、计算与政策核对摘要，包含 `settlement_checked`、`calculation_checked`、`policy_count` 和公开说明。`citations` 是可展示政策依据；无法形成可靠结论时，`uncertainties` 必须明确说明缺失信息或证据限制。公开模型及其嵌套对象采用严格白名单，拒绝额外字段。

### 7.1 删除字段

- `patient_view`
- `office_view`
- `settlement_evidence`

不保留兼容字段。当前唯一前端消费者 Portal 与后端在同一变更中同步升级。

`patient_view`、`office_view`、`settlement_evidence` 的删除是破坏性契约升级，后端与 Portal 必须同步发布、同步回滚。`GET /policy-qa/settlement-explanation` 仅作为路径兼容入口保留，返回与流式主入口相同的安全公开契约；Portal 不再调用该路径。

### 7.2 单答案生成

- 答案面向请求中现有的院端角色；本次不新增认证、角色推断或权限逻辑。
- 结算金额与政策结论在一份答案中表达。
- 结构化金额、计算步骤和政策依据继续独立返回，避免从自然语言反向解析。
- “生成患者沟通说明”未来如有真实需求，应作为独立业务动作设计。

### 7.3 输出校验

删除双视角专用校验，统一检查：

- 不包含模拟数据标记。
- 不包含原始 JSON、模板变量、`undefined`、`null` 或 `NaN` 泄漏。
- 金额结论已通过内部结算数据核对。
- 政策结论包含可展示引用。
- 无法可靠回答时包含 `uncertainties`，且不输出伪确定结论。
- 完整 SQL、检索轨迹和内部来源明细不进入公开答案；当前持久化范围是公开步骤，以及任务摘要 `answer_excerpt`、`answer_status`、`evidence_count`、`internal_run_id`，不声称完整内部轨迹已审计落库。
- `answer_status=unavailable` 时不得用旧字段或内部载荷兜底生成答案。

## 8. 数据流

```text
Composer submit
→ usePolicyQAStream.send
→ POST /policy-qa/stream
→ parse complete SSE frames
→ strip forbidden fields
→ map typed session event
→ session reducer
→ SessionViewModel
→ Chat-first UI
```

SSE 解析以空行作为帧边界，正确关联 `event:` 与随后的一个或多个 `data:` 行。`done` 明确结束当前请求。畸形事件被隔离并记录，不清空已接收的安全内容。

## 9. 安全与审计

- 所有流式数据先过滤禁止字段，再进入前端状态。
- 禁止展示 reasoning、chain-of-thought、prompt、raw response、tool calls 和 agent trace。
- SQL、数据库表名、字段名和完整检索轨迹不得进入公开响应或前端状态；当前不声称这些完整内部轨迹已写入审计库。
- 前端递归删除禁止键，后端公开模型对白名单外字段和嵌套额外字段拒绝输出；两层边界互为纵深防御。
- `step` 事件只消费最新一条 `public_message`，`reasoning_step` 与内部运行标识不得进入会话状态或 UI。
- 现有追溯使用工作流公开步骤、任务摘要和 `internal_run_id`；后续如扩展完整内部审计，仍须遵循权限与脱敏边界。
- 用户答案必须携带政策引用或不确定性。
- 页面固定显示“回答仅供解释参考，不作为报销或结算依据”。

## 10. 测试与验证

本次修改核心 API 契约并涉及结算解释链路，按 R4 执行人工设计和完整验证。

### 10.1 契约先行测试

先补失败测试固定新的单答案契约：公开结果必须包含 `answer` 与 `answer_status`，且不得包含 `patient_view`、`office_view`、`settlement_evidence`。同时扩展现有 SSE 解析回归测试，覆盖跨行、多 `data:`、畸形 JSON 与 `done`；这部分用于保持当前正确行为，不把它误判为现行缺陷。

### 10.2 单元测试

后端：

- 单答案生成。
- `complete`、`partial`、`unavailable` 输出校验。
- 政策引用或不确定性门禁。
- 公开结果不包含被删除字段。

前端 Vitest：

- SSE 分块、跨行、多 `data:`、畸形 JSON 和 `done`。
- 禁止字段递归过滤。
- reducer 状态迁移与 retry。
- Chat-first 核心组件的空闲、执行中、完成和受限状态。

### 10.3 API 测试

- 流式端点返回 `answer` 和 `answer_status`。
- 不返回 `patient_view`、`office_view`、`settlement_evidence`。
- 政策结论包含引用；不可回答时包含不确定性。

### 10.4 Flow 测试

- 完整回答。
- 部分回答。
- 政策未命中。
- 模型降级。
- 流式结束与异常恢复。

### 10.5 性能与 E2E

API 响应结构发生变化，执行流式端点性能验证。E2E 覆盖：

- Chat-first 空闲状态和 Composer。
- 结算上下文标签。
- 流式回答。
- 政策引用 Dialog。
- 计算与费用明细折叠区。
- 连续追问。
- 部分回答和重试。

验证顺序严格为：单元测试 → API 测试 → Flow 测试；三者通过后执行性能与 E2E。

截至 2026-08-05 的核心实现验证：后端按 T1 → T2a → T2b 顺序分别通过 130、39、99 项；Portal 流契约聚焦测试通过 37 项，Chat-first 组件完成时全量 Vitest 通过 112 项，删除旧双视角测试后通过 94 项，`tsc --noEmit` 与 `next build` 通过。以上不等同于 R4 最终验收，也不声称全仓 lint 已通过；性能与 E2E 证据仍按本节要求补充。

## 11. 迁移与回滚

### 11.1 迁移

前后端在同一分支、同一交付单元中更新。先通过契约测试固定新响应，再切换 Portal 消费逻辑，最后删除旧字段和旧组件。

兼容策略仅保留 `GET /policy-qa/settlement-explanation` 路径；该入口同样返回 `PolicyQAPublicResult`，不返回任何旧字段，也不再由 Portal 调用。

### 11.2 回滚

变更集中在独立分支，按提交回滚。由于不保留旧契约兼容字段，后端与 Portal 必须整体回滚，不允许只回滚一侧。

## 12. 风险

- 删除字段会使旧前端无法正常渲染，必须同步发布。
- SSE 字段映射与会话状态重构可能改变事件时序，需以单元、API、Flow 和 E2E 固定现有完整帧行为。
- 后端单答案生成可能遗漏原双视角中的信息，需用政策引用与金额核对测试约束。
- 结构化回答内容较多时可能再次产生看板化倾向；实现评审应坚持单一阅读轴和渐进披露。

## 13. 最终决策摘要

- 产品模型：Chat-first。
- 视觉：深色全局导航 + 浅色内容区。
- 布局：桌面端单列居中，无常驻左右栏。
- Agent 表达：自动查证、引用、连续追问；执行过程弱化并按需展开。
- 回答：单一院端答案，不保留双视角。
- 数据来源：公开 UI 不展示 SQL、结算表名、字段名或完整检索轨迹；当前通过任务/工作流摘要与内部运行标识追溯。
- 架构：完整组件化重构，但避免无价值的细粒度抽象。
- 验证：R4，严格执行全链路验证。

## 14. 最终实现同步

- 后端以 `PolicyQAPublicResult` 作为流式与兼容入口的唯一公开结果模型；内部 Skill、结算查询和检索结果在公开映射前收敛为白名单字段。
- Portal 以 `policy-qa-stream.ts` 完成整帧 SSE 解析、递归过滤和运行时校验，再由会话 reducer 驱动 Chat-first 组件；畸形或不完整 `result` 安全降级为 `unavailable`。
- 页面采用最大 840px 单列阅读轴，无左右业务分栏和常驻步骤链；结算单号位于 Composer context chip，查证摘要、计算过程和政策来源按渐进披露展示。
- 旧双视角组件、字段映射和测试已删除；公开结果仍保留可核对的结构化金额、计算步骤、政策证据、引用和不确定性。
- 当前任务持久化仅记录 `answer_excerpt`、`answer_status`、`evidence_count`、`internal_run_id`，工作流保存公开步骤；公开回答不包含 SQL、表名、字段名、原始工具响应、推理内容或内部来源明细，且本文不声称完整 SQL/检索轨迹已审计落库。
