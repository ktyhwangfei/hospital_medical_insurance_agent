# fix-security-contracts-and-runtime-decoupling 开发计划设计

## 背景

本设计基于 OpenSpec 变更 [`fix-security-contracts-and-runtime-decoupling`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling)，目标是为后续实施生成一份按阶段推进、每阶段可独立验证的开发计划。

该变更覆盖三类能力：

- [`security-contracts`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/specs/security-contracts/spec.md)：AI 输出可追溯、高风险动作不自动执行、流式模型错误规范化、统一 API 错误结构。
- [`adapter-foundation`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/specs/adapter-foundation/spec.md)：适配器统一调用契约、调用审计、真实系统替换边界、脱敏和权限约束、失败降级集成。
- [`runtime-execution-loop`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/specs/runtime-execution-loop/spec.md)：运行时上下文、确定性计划、顺序编排、workflow/task 状态查询、审计视图。

现有代码已经具备两个 MVP 场景、意图识别、模型服务和基础 API，但仍存在以下关键约束：

- 必须保持 [`AgentResponse`](../../src/runtime/api/schemas.py) 顶层字段兼容。
- 必须保持 [`POST /chat`](../../src/runtime/api/routes.py)、[`POST /chat/stream`](../../src/runtime/api/routes.py)、[`POST /model-test/stream`](../../src/runtime/api/routes.py) 的现有调用入口。
- 不接入真实 PostgreSQL、Redis、Milvus 或院内系统。
- 不新增拒付申诉助手、运营驾驶舱等新业务场景。
- 代码实现前必须先通过开发计划审查。

## 推荐计划组织方式

采用“按阶段组织”的开发计划，而不是严格按 OpenSpec [`tasks.md`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/tasks.md) 原顺序执行。

原因：

1. P0 安全与流式异常属于硬性契约风险，必须先消除。
2. 适配器基础层会影响多个场景，应在运行时闭环接入前稳定契约。
3. 运行时上下文、计划、编排、状态和审计视图存在强依赖，适合在基础契约稳定后推进。
4. 前端、OpenAPI、文档验证应放在最后，以避免反复更新。

## 阶段划分

```text
P0 安全与流式异常
  ↓
P1 适配器基础层
  ↓
P2 运行时上下文与计划
  ↓
P3 顺序编排、状态、任务闭环与审计视图
  ↓
P4 API、前端、文档与最终验证
```

## P0：安全契约与模型流式异常

### 目标

先修复最直接的安全与契约问题，确保所有返回给用户的 AI 导办结果、高风险拦截结果、降级结果和流式结果都具备可追溯来源或不确定性提示。

### 涉及模块

- [`src/shared/schemas/responses.py`](../../src/shared/schemas/responses.py)
- [`src/runtime/api/schemas.py`](../../src/runtime/api/schemas.py)
- [`src/security/risk_control/service.py`](../../src/security/risk_control/service.py)
- [`src/runtime/scheduling/service.py`](../../src/runtime/scheduling/service.py)
- [`src/model_service/providers/openai_compatible.py`](../../src/model_service/providers/openai_compatible.py)
- [`src/model_service/gateway.py`](../../src/model_service/gateway.py)
- [`src/runtime/api/routes.py`](../../src/runtime/api/routes.py)
- [`src/runtime/api/streaming.py`](../../src/runtime/api/streaming.py)

### 核心设计

新增最小响应契约模型，优先承载新增链路：

- `Citation`：`source_type`、`source_id`、`summary`。
- `AuditEvent`：`event_type`、`workflow_id`、`step_id`、`metadata`。
- `RuntimeTask`：`task_id`、`task_type`、`status`、`description`、`responsible_role`。
- `StreamErrorEvent`：`error_code`、`message`、`audit_event`。

不在 P0 一次性重写 [`AgentResponse`](../../src/runtime/api/schemas.py) 内部所有 `dict` 字段，而是通过 `.model_dump()` 与兼容转换保证现有 API 响应结构不破坏。

流式异常处理采用三层职责：

```text
OpenAICompatibleProvider.invoke_stream
  → 将 httpx / JSON / status 错误转换为 ModelError
ModelGateway.generate_stream
  → 记录 model_stream_interrupted 后继续抛出
routes.model_test_stream / routes.chat_stream
  → 映射为 SSE error 事件，并最终发送 done
```

### 验收

- 高风险动作返回 `waiting_human_confirmation`，且包含 citation 或 uncertainty。
- 降级响应包含受影响来源或 uncertainty。
- 流式 Provider 超时、网络错误、鉴权失败、限流、上游错误、malformed JSON 均返回结构化 SSE `error`。
- [`ModelGateway.generate_stream()`](../../src/model_service/gateway.py) 不再吞掉异常。
- P0 完成后运行与安全、流式、模型服务相关测试。

## P1：适配器基础层

### 目标

新增轻量适配器基础层，统一内存适配器的调用结果、来源引用、调用审计、失败语义、脱敏和权限钩子，为后续真实院内系统替换建立边界。

### 涉及模块

- 新增 [`src/adapters/base/`](../../src/adapters)
- [`src/adapters/insurance_interface/in_memory.py`](../../src/adapters/insurance_interface/in_memory.py)
- [`src/adapters/billing/in_memory.py`](../../src/adapters/billing/in_memory.py)
- [`src/adapters/pre_audit/in_memory.py`](../../src/adapters/pre_audit/in_memory.py)
- [`src/adapters/drg_dip/in_memory.py`](../../src/adapters/drg_dip/in_memory.py)
- [`src/adapters/his/in_memory.py`](../../src/adapters/his/in_memory.py)
- [`src/adapters/emr/in_memory.py`](../../src/adapters/emr/in_memory.py)
- [`src/adapters/medical_record/in_memory.py`](../../src/adapters/medical_record/in_memory.py)
- [`src/business_scenarios/settlement_exception_guide/service.py`](../../src/business_scenarios/settlement_exception_guide/service.py)
- [`src/business_scenarios/pre_discharge_joint_qc/service.py`](../../src/business_scenarios/pre_discharge_joint_qc/service.py)

### 核心设计

新增 `AdapterCallContext`、`AdapterCallResult`、`AdapterError`、`DataQualityStatus` 等模型。

适配器迁移采用兼容包装策略：

```text
业务场景调用适配器方法
  → 适配器内部构造 AdapterCallResult
  → 场景可读取 result.data 保持原字段语义
  → citations/audit 从 source_system/source_record_id/capability 生成
```

P1 不要求所有业务数据都建立独立领域模型，避免范围失控；只要求每个适配器返回值可追溯、可审计、可降级。

### 验收

- 7 个内存适配器均能返回统一调用结果或可转换领域数据。
- 适配器调用结果包含 `source_system`、`source_record_id`、`capability`、`collected_at`、`data_quality`。
- 适配器失败能进入运行时降级响应。
- 审计输入摘要不包含未脱敏姓名、证件号、联系方式或完整病历文本。

## P2：运行时上下文与计划

### 目标

在不重写两个 MVP 场景的前提下，引入运行时上下文和确定性计划模板，为后续顺序编排和审计视图提供统一数据结构。

### 涉及模块

- 新增 [`src/runtime/context/`](../../src/runtime)
- 新增 [`src/runtime/planning/`](../../src/runtime)
- [`src/runtime/intent/models.py`](../../src/runtime/intent/models.py)
- [`src/runtime/intent/parser.py`](../../src/runtime/intent/parser.py)
- [`src/runtime/api/routes.py`](../../src/runtime/api/routes.py)

### 核心设计

上下文模型聚合：

- `request_id`
- `workflow_id`
- `user_id`
- `role`
- `message`
- `patient_id`
- `encounter_id`
- `intent`
- `intent_confidence`
- `intent_entities`
- `intent_citations`
- `requested_at`
- `audit_refs`

计划模型保留未来 DAG 演进字段，但 P2 只生成顺序计划：

```text
ExecutionPlan
  ├── workflow_id
  ├── scenario
  ├── goal
  ├── steps: list[PlanStep]
  └── output_requirements

PlanStep
  ├── step_id
  ├── step_type
  ├── capability
  ├── depends_on
  ├── risk_level
  └── requires_human_confirmation
```

计划模板：

- 医保结算异常导办：交易查询、错误码知识检索、收费状态查询、异常归因、结果组装。
- 出院前联合质控：费用医嘱查询、医保接口状态查询、事前审核查询、DRG/DIP 查询、病案查询、规则解释检索、风险清单生成、任务创建。
- 高风险动作：动作识别、策略引用、人工确认任务创建、等待确认响应。

### 验收

- 完整 Chat 请求能构建上下文。
- 缺少 `patient_id` 或 `encounter_id` 时仍走澄清，不编造数据。
- IntentResult 的 confidence、entities、citations 被保留并进入最终响应引用。
- 三类计划模板都有单元测试。

## P3：顺序编排、状态、任务闭环与审计视图

### 目标

将 P2 的计划真正执行起来，并让 workflow/task 状态接口不再返回固定 `not_implemented`。

### 涉及模块

- 新增 [`src/runtime/orchestration/`](../../src/runtime)
- [`src/runtime/runtime_state/models.py`](../../src/runtime/runtime_state/models.py)
- [`src/runtime/task_closure/service.py`](../../src/runtime/task_closure/service.py)
- [`src/security/audit/in_memory.py`](../../src/security/audit/in_memory.py)
- [`src/runtime/api/routes.py`](../../src/runtime/api/routes.py)

### 核心设计

顺序编排器以兼容方式接入现有场景服务：

```text
process_chat_request
  → build_runtime_context
  → build_execution_plan
  → execute_plan_sequentially
  → scenario step handler 调用现有场景服务
  → persist workflow/task/audit
  → AgentResponse
```

状态仓储使用内存实现，优先支持同一应用实例内跨请求查询。

任务闭环扩展：

- 待办任务创建。
- 人工确认任务查询。
- 确认/拒绝更新状态。
- 使用运行时时间替代硬编码确认时间。
- 任务事件进入 workflow 审计轨迹。

审计视图聚合：

```text
workflow_id
  ├── request event
  ├── intent event
  ├── plan event
  ├── step events
  ├── adapter/model events
  ├── task events
  └── response summary
```

### 验收

- [`GET /workflows/{workflow_id}`](../../src/runtime/api/routes.py) 返回真实状态摘要。
- [`GET /tasks/{task_id}`](../../src/runtime/api/routes.py) 返回真实任务状态摘要。
- 不存在的 workflow/task 返回统一结构化错误。
- 人工确认更新任务状态、确认人、确认时间、原因和审计轨迹。
- 审计视图可还原完整导办流程和高风险拦截流程。

## P4：API、前端、文档与最终验证

### 目标

收敛所有兼容性、前端展示和文档验证问题，确保变更可交付。

### 涉及模块

- [`src/tests/integration/test_openapi_contract.py`](../../src/tests/integration/test_openapi_contract.py)
- [`src/tests/e2e/`](../../src/tests/e2e)
- [`src/static/index.html`](../../src/static/index.html)
- [`AGENTS.md`](../../AGENTS.md)
- [`openspec/changes/archive/2026-05-03-enhance-intent-recognition/tasks.md`](../../openspec/changes/archive/2026-05-03-enhance-intent-recognition/tasks.md)

### 核心设计

P4 不再引入新后端能力，只做验收闭环：

- OpenAPI 契约覆盖 workflow、task、stream error、audit 字段。
- 端到端测试验证两个 MVP 场景响应兼容。
- 前端能展示结构化流式错误。
- 文档记录已修复技术债和剩余边界。
- 记录归档任务状态与实际代码不一致的过程债处理结论。

### 验收

- [`python -m pytest src/tests -v`](../../AGENTS.md) 通过。
- [`npx openspec validate "fix-security-contracts-and-runtime-decoupling" --strict`](../../AGENTS.md) 通过。
- 前端非流式与流式演示路径均可用。
- [`AGENTS.md`](../../AGENTS.md) 的技术债说明与实际状态一致。

## 实施顺序总览

```text
Phase 0: 契约模型与安全/流式测试先行
Phase 1: P0 安全契约与流式异常实现
Phase 2: P1 适配器基础层与兼容迁移
Phase 3: P2 运行时上下文与计划模板
Phase 4: P3 顺序编排、状态、任务闭环
Phase 5: P3 审计视图
Phase 6: P4 API、前端、文档、全量验证
```

## 计划编写原则

后续实施计划应遵循以下原则：

1. 每个阶段先补测试，再改实现。
2. 每个阶段完成后运行相关子集测试。
3. P0 完成前不推进适配器迁移。
4. P1 完成前不将场景接入新编排器。
5. P2/P3 必须保留现有场景服务兼容路径。
6. 最终阶段必须运行全量 pytest 和 OpenSpec strict validate。

## 自检

- 无 `TBD`、`TODO` 或占位章节。
- 范围聚焦于 [`fix-security-contracts-and-runtime-decoupling`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling)，未新增业务场景。
- 阶段顺序符合依赖关系：安全契约 → 适配器契约 → 运行时计划 → 编排状态 → 审计与验证。
- 兼容性要求明确：保留 [`AgentResponse`](../../src/runtime/api/schemas.py) 顶层字段、现有 API 路由和两个 MVP 场景响应主结构。
- 每个阶段都有可验证验收标准。
