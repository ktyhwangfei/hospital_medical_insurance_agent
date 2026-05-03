## Why

当前 MVP 已具备医保结算异常导办、出院前联合质控、意图识别和模型服务等核心能力，但安全与契约边界仍存在技术债：高风险拦截响应缺少来源或不确定性，流式模型异常处理不一致，适配器缺少统一基座，运行时上下文、规划、编排和审计视图仍未形成闭环。现在修复这些问题，可以让系统从演示型内存实现逐步过渡到可接真实院内系统的稳定运行时架构。

## What Changes

- 规范高风险动作、模型流式调用、降级返回和错误响应的可追溯契约，确保所有 AI 输出携带来源引用或不确定性提示。
- 统一模型服务流式异常语义，使 Provider、Gateway 和 API 对超时、网络错误、上游错误、鉴权错误和回退链耗尽返回一致的结构化事件。
- 新增适配器基础能力，定义适配器调用结果、异常、审计、重试、脱敏和权限钩子，现有内存适配器逐步迁移到统一契约。
- 新增运行时上下文、计划、编排和审计视图的最小闭环，使 Chat API 能记录用户身份、角色、请求内容、请求时间、执行步骤、能力调用和最终结果。
- 将流程状态和任务状态查询从占位响应改为读取运行时状态与任务闭环记录。
- 明确本次只修复现有 MVP 场景和模型测试链路的安全契约与运行时闭环，不新增拒付申诉助手、运营驾驶舱等新业务场景。
- 将现有硬编码降级、硬编码确认时间和流式错误吞噬行为纳入验收边界，避免以“测试通过但行为不可追溯”的方式完成实现。

## Capabilities

### New Capabilities
- `security-contracts`: 约束高风险拦截、降级响应、流式错误和 AI 输出来源追溯的统一安全契约。
- `adapter-foundation`: 定义业务系统适配器基座，包括调用结果、异常、审计、重试、脱敏和权限钩子。
- `runtime-execution-loop`: 定义运行时上下文、计划、编排、状态查询和审计视图的最小执行闭环。

### Modified Capabilities

无。当前 `openspec/specs/` 下没有已发布能力规格，本变更以新增能力规格承载。

## Impact

- 影响后端运行时：`src/runtime/api/`、`src/runtime/runtime_state/`、`src/runtime/scheduling/`、`src/runtime/task_closure/`，并新增 `src/runtime/context/`、`src/runtime/planning/`、`src/runtime/orchestration/` 的最小实现。
- 影响安全模块：`src/security/risk_control/`、`src/security/audit/`。
- 影响模型服务：`src/model_service/gateway.py`、`src/model_service/providers/openai_compatible.py`、`src/model_service/models.py`。
- 影响业务适配层：新增 `src/adapters/base/`，并迁移 `src/adapters/*/in_memory.py` 的返回契约和调用审计。
- 影响 API 契约：`POST /chat`、`POST /chat/stream`、`POST /model-test/stream`、`GET /workflows/{workflow_id}`、`GET /tasks/{task_id}` 的结构化输出和审计字段。
- 影响测试：新增或更新安全、模型服务、适配器契约、运行时编排和端到端测试。
- 兼容要求：现有 `AgentResponse` 顶层字段、前端演示页入口和两个 MVP 场景的主要结果字段必须保持向后兼容。
