## 1. 安全契约与通用响应模型

- [ ] 1.1 在 `src/shared/schemas/responses.py` 或新增 schema 文件中定义最小 `Citation`、`AuditEvent`、`StreamErrorEvent`、`RuntimeTask` Pydantic 模型
- [ ] 1.2 调整 `src/security/risk_control/service.py` 的高风险拦截响应，补充风控策略 citation 或人工确认 uncertainty
- [ ] 1.3 调整降级响应构建逻辑，确保业务系统失败时返回受影响来源或 uncertainty
- [ ] 1.4 为高风险拦截、降级响应和权限拒绝补充审计事件字段
- [ ] 1.5 增加安全契约测试，覆盖所有 AI 输出至少包含 citations 或 uncertainties
- [ ] 1.6 增加高风险动作禁止自动执行测试，验证不调用任何执行类适配器

## 2. 模型流式异常契约

- [ ] 2.1 在 `src/model_service/providers/openai_compatible.py` 为 `invoke_stream` 增加 timeout、network、HTTP、状态码和 JSON 解析异常规范化
- [ ] 2.2 调整 `src/model_service/gateway.py` 的 `generate_stream`，记录流式失败审计日志后向上抛出模型服务异常
- [ ] 2.3 调整 `src/runtime/api/routes.py` 的 `model_test_stream`，将模型异常映射为结构化 SSE `error` 事件并保证发送 `done`
- [ ] 2.4 调整 `src/runtime/api/routes.py` 的 `chat_stream`，确保业务处理异常返回标准 SSE `error` 事件
- [ ] 2.5 增加模型服务流式测试，覆盖超时、网络错误、鉴权失败、限流、上游错误和回退链耗尽
- [ ] 2.6 增加流式 malformed JSON 测试，验证 Provider 转换为结构化错误事件

## 3. 适配器基础层

- [ ] 3.1 新增 `src/adapters/base/` 目录及 `__init__.py`
- [ ] 3.2 定义适配器调用上下文、调用结果、数据质量、适配器异常、重试策略和审计事件模型
- [ ] 3.3 定义适配器基础 Protocol 或基类，包含调用审计、脱敏钩子和权限钩子
- [ ] 3.4 迁移医保接口、收费、事前审核、DRG/DIP、HIS、EMR、病案内存适配器，使其返回统一调用结果或可转换领域数据
- [ ] 3.5 在业务场景中通过统一适配器结果读取来源系统、来源记录、数据质量和业务数据
- [ ] 3.6 增加适配器契约测试，覆盖成功调用、失败调用、审计字段、脱敏和替换兼容性
- [ ] 3.7 增加适配器失败降级集成测试，验证 workflow、uncertainties 和审计视图均记录失败原因

## 4. 运行时上下文与计划

- [ ] 4.1 新增 `src/runtime/context/`，实现 Chat 请求运行时上下文模型和构建服务
- [ ] 4.2 新增 `src/runtime/planning/`，定义 ExecutionPlan、PlanStep、步骤类型、风险等级和输出要求模型
- [ ] 4.3 为医保结算异常导办实现确定性计划模板
- [ ] 4.4 为出院前联合质控实现确定性计划模板
- [ ] 4.5 为高风险动作请求实现人工确认计划模板
- [ ] 4.6 增加上下文与计划单元测试，覆盖完整上下文、缺失上下文、未知意图和高风险动作
- [ ] 4.7 在上下文中保留 IntentResult 的 confidence、entities 和 citations，并验证响应继承意图来源

## 5. 顺序编排、状态和任务闭环

- [ ] 5.1 新增 `src/runtime/orchestration/`，实现顺序执行器和步骤执行注册机制
- [ ] 5.2 将医保结算异常导办和出院前联合质控场景接入顺序执行器，保持现有 API 响应兼容
- [ ] 5.3 扩展 `src/runtime/runtime_state/`，记录 workflow 状态、当前步骤、步骤输入输出引用、错误和审计引用
- [ ] 5.4 扩展 `src/runtime/task_closure/`，使用模型化任务记录待办、人工确认、确认、拒绝和关闭状态
- [ ] 5.5 将 `GET /workflows/{workflow_id}` 改为返回真实 workflow 状态摘要
- [ ] 5.6 将 `GET /tasks/{task_id}` 改为返回真实任务状态摘要
- [ ] 5.7 将 `POST /tasks/confirm` 的确认时间改为运行时时间并写入任务状态与审计事件
- [ ] 5.8 增加 workflow 和 task 未找到时的统一结构化错误测试

## 6. 审计视图

- [ ] 6.1 扩展 `src/security/audit/` 内存审计日志，支持请求、计划、步骤、适配器、模型、任务和响应事件类型
- [ ] 6.2 实现按 workflow_id 聚合导办流程审计视图的服务
- [ ] 6.3 在 Chat API 入口记录用户身份、角色、请求内容和请求时间
- [ ] 6.4 在编排执行过程中记录每个步骤的输入输出引用、能力调用和错误事件
- [ ] 6.5 增加审计视图集成测试，验证可还原一次完整导办流程
- [ ] 6.6 增加高风险动作拦截审计视图测试，验证命中动作、策略来源和未自动执行说明

## 7. API、前端兼容与验证

- [ ] 7.1 更新 OpenAPI 契约测试，覆盖新增或增强后的 workflow、task、stream error 和 audit 字段
- [ ] 7.2 更新端到端测试，验证结算异常导办和联合质控在接入运行时闭环后响应结构保持兼容
- [ ] 7.3 更新 `src/static/index.html` 的流式错误展示逻辑，确保结构化错误可读
- [ ] 7.4 执行 `python -m pytest src/tests -v` 并修复失败用例
- [ ] 7.5 执行 `npx openspec validate "fix-security-contracts-and-runtime-decoupling" --strict` 并修复规格问题
- [ ] 7.6 更新 `AGENTS.md` 中已知技术债状态，移除已修复项并记录剩余边界
- [ ] 7.7 检查 `openspec/changes/archive/2026-05-03-enhance-intent-recognition/tasks.md` 与现有代码状态不一致问题，并在文档中记录过程债处理结论
