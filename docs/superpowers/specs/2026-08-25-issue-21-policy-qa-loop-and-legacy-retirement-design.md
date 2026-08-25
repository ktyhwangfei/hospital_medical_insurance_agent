# Issue #21 Policy QA Loop 与旧场景退役设计

日期：2026-08-25  
状态：已确认方案 A，待实施  
风险等级：R4（删除旧业务入口与运行时，并修改 Policy QA 核心执行链路）

## 1. 背景与问题

当前实际产品入口已经是 `/policy-qa`，但仓库仍保留结算异常导办、出院前联合质控及旧 Chat 编排代码、页面组件、测试和说明文档。虽然 FastAPI 当前没有注册这些旧业务路由，它们仍通过包初始化、静态构建范围、测试和文档影响开发判断与维护成本。

业务边界已经确认：

- `policy-qa` 是唯一业务入口。
- 政策问答必须依赖真实结算单。
- `settlement_explain_skill` 是当前唯一运行时业务 Skill。
- 结算异常导办和出院前联合质控不再属于产品范围。
- `/settlement`、`/qc` 和旧 `/chat` 不保留兼容跳转，访问应返回 404。

Issue #21 依据 `docs/research/LoopEngineering.md` 提出 Gather → Act → Verify → Repeat 的工程闭环。本次只把 Loop 落到现行 Policy QA 主链，不复活或复用任何旧场景编排器。

## 2. 目标与成功标准

### 2.1 目标

1. 从运行时、Portal、测试和现行文档中彻底退役结算异常导办与出院前联合质控。
2. 消除旧模块通过 Python 包初始化、Next.js 构建范围或测试入口影响现行产品的可能。
3. 保持真实结算数据 Provider、结算领域模型和 `settlement_explain_skill` 正常工作。
4. 在 Policy QA 中补齐有界、可验证、可停止的最小 Loop。

### 2.2 成功标准

- FastAPI 只暴露现行管理能力和 Policy QA，不暴露 `/chat`、`/settlement`、`/qc` 或旧场景 API。
- Portal 只保留 `/policy-qa` 业务入口；三个旧地址均为 404。
- 应用启动不再导入旧场景执行器、旧 LangGraph、旧业务场景服务或退役 Policy QA 编排器。
- SkillLoader 的现行业务执行仍只加载 `settlement_explain_skill`。
- Policy QA 每轮都经过确定性验证，达到成功条件立即停止。
- 确定性缺少证据时返回 `partial` 或 `unavailable`，不重复执行相同工作。
- 瞬时基础设施错误最多额外重试一次；非重试错误、重复失败或达到两轮上限立即停止。
- 单元测试、API 测试、Flow 测试按顺序通过；Portal lint、类型检查和生产构建通过。

## 3. 选择的方案

采用方案 A：硬退役旧业务 + 在现行 Policy QA 内实现最小 Loop。

未采用：

- 归档旧代码：仍会保留维护、搜索和构建噪声。
- 只断开路由：这正是当前不完整退役状态，不能消除旧代码影响。
- 新建通用 Agent Loop 框架：当前只有一个业务入口和一个运行时 Skill，没有第二个消费者，属于不必要抽象。
- 复用旧 LangGraph：旧图服务于已退役场景，会重新引入错误业务边界。

## 4. 保留与删除边界

### 4.1 必须保留

- `src/runtime/api/policy_qa_routes.py` 的正式 `/policy-qa` 路由。
- `src/runtime/policy_qa/settlement_data_provider.py` 及真实结算单查询能力。
- `skills/settlement_explain_skill/`。
- SkillLoader、SkillRouter、政策检索、语义层、政策知识治理与模型治理能力。
- 被现行 Policy QA 或治理能力实际调用的共享领域模型、适配器、安全与持久化代码。

“settlement” 一词本身不是删除条件；只有专属于“结算异常导办”旧场景且无现行调用者的代码才删除。

### 4.2 必须退役

- `business_scenarios` 下的结算异常导办与出院前联合质控实现。
- `runtime` 下只服务于这两个场景的 scenario executor、旧 orchestrator、LangGraph 图、节点、检查点和已废弃 service。
- 已被现行路由明确标记退役、且仅由旧 scenario executor 调用的 `PolicyQAOrchestrator`。
- 旧 intent 注册项和由包级导入造成的旧场景启动依赖；Policy QA 所需 DTO 与 Runtime Bridge 保留。
- Portal 的 `/settlement`、`/qc` 页面，以及只服务于旧 Chat、结算异常、出院质控的组件、API 方法、类型和 mock。
- 只验证已退役业务的测试、性能脚本和 E2E 用例。
- AGENTS、PROGRESS 及相关说明中把旧场景描述为现行业务的内容。

删除前必须逐项检查调用者；共享文件内只删除旧场景分支，不顺带重构仍在使用的逻辑。

## 5. Policy QA Loop 设计

### 5.1 单轮流程

```text
POST /policy-qa/stream（question + settlement_id）
  → Gather：读取真实结算单，检索适用政策证据
  → Act：执行 settlement_explain_skill，生成结构化解释
  → Verify：构建 PolicyQAPublicResult 并确定 answer_status
  → Halt 或 Recover
```

### 5.2 Verify

复用现有 `_build_public_result` 作为确定性外部验证器，不让生成步骤自行宣布成功。验证依据为：

- 已取得真实结算金额。
- 单项解释存在可公开的计算步骤。
- 单项政策状态为完整匹配且至少存在一条可展示引用。
- 回答通过公开字段白名单和内部实现信息过滤。
- 不能完整验证时必须给出 `uncertainties`。

费用总览不需要单项政策证据，继续按现有规则以真实结算金额完成核验。

### 5.3 Repeat 与 Recover

最多执行两轮，不新增配置项：

1. 第一轮正常执行 Gather → Act → Verify。
2. 仅当结算数据或政策检索遇到明确的瞬时基础设施错误时，执行一次恢复重试。
3. `SettlementNotFoundError`、输入/配置错误、安全失败和确定性的证据不足不重试。
4. 第二轮出现与第一轮相同的失败分类时，视为停滞并停止。
5. 达到两轮上限后停止，不继续调用外部系统。

当前正式路径不依赖模型生成，因此不增加“模型切换”。恢复失败后沿现有 SSE `error` + `done(success=false)` 契约返回；已形成安全的部分结果时返回 `partial` 或 `unavailable`，不得用模型猜测缺失政策或金额。

### 5.4 可观测性

- 公开步骤增加验证状态；发生重试时增加简短恢复状态，不暴露异常堆栈、SQL 或内部检索载荷。
- 任务摘要记录实际尝试次数与停止原因，供服务端审计和问题定位。
- 公开最终契约继续以 `answer_status`、`verification_summary`、`citations` 和 `uncertainties` 表达可信度，不引入第二套结果模型。

## 6. 错误处理与安全

- 结算单号继续是必填信任边界，空值由 API 在执行前拒绝。
- 真实结算单不存在时不重试、不降级到 mock。
- 无政策依据时不得输出确定性政策结论。
- 所有公开文本继续经过现有脱敏和内部实现信息过滤。
- Loop 不扩大外部动作范围，不新增正式结算、退费、冲正或病案修改能力。

## 7. 测试与验证

本变更按 R4 验证，缺陷修复先红后绿。

### 7.1 单元测试

- 瞬时错误首轮失败、第二轮成功。
- 非重试错误只执行一轮。
- 相同失败再次出现后以停滞原因停止。
- `complete`、`partial`、`unavailable` 的验证条件保持正确。
- 确定性证据不足不触发重试。
- 应用导入不再加载旧业务模块。

### 7.2 API 测试

- `/policy-qa/stream` 仍要求 `question` 和 `settlement_id`。
- 成功、部分回答、不可回答和恢复失败均发送正确的 `done` 事件。
- `/chat` 及所有旧场景 API 返回 404。

### 7.3 Flow 测试

- 真实结算单 → 政策检索 → Skill 执行 → 验证成功。
- 政策证据不足 → 安全部分回答或不可回答，且无重复执行。
- 瞬时外部故障 → 一次恢复 → 成功或有界失败。

### 7.4 Portal 验证

- `/policy-qa` 可构建并正常消费现有 SSE 结果。
- `/settlement`、`/qc` 页面文件不存在，生产路由返回 404。
- 删除旧组件后 lint、类型检查、组件测试和生产构建通过。

验证顺序严格为：单元测试 → API 测试 → Flow 测试；之后再执行 Portal 验证和与本变更相关的更高层检查。

## 8. 文档与迁移

- 将 Issue 引用的 `docs/research/LoopEngineering.md` 从 main 同步到当前分支，保持原文不改。
- 更新根 `AGENTS.md`、`src/runtime/AGENTS.md`、`src/tests/AGENTS.md`、`src/apps/portal/AGENTS.md` 和 `PROGRESS.md`，使其只描述现行 Policy QA 业务链。
- 历史设计文档保留为历史记录，不批量改写；当前状态文档不得继续把旧场景列为已实现入口。

## 9. 回滚

旧场景删除与 Loop 实现分成独立提交：

1. 旧场景退役及文档、测试收口。
2. Policy QA Loop 与对应测试。

如需回滚 Loop，只回滚第二个提交，不恢复旧场景。若业务未来重新提出结算异常或出院质控需求，应按新的业务需求和验收标准重新设计，不从已退役代码恢复。

## 10. 最终决策

- 方案：A，硬退役。
- 唯一入口：`/policy-qa`。
- 结算单：Policy QA 必填真实上下文，不是旧结算异常场景。
- Loop：局部、两轮上限、确定性验证、只重试瞬时错误。
- 实现原则：删除优先，复用现有验证器，不引入通用框架或新依赖。
