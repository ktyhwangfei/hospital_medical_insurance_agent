## Purpose

定义医保智能体 API 的安全契约，约束 AI 输出可追溯或显式不确定、流式模型错误归一化、标准错误详情与高风险动作禁止自动执行。

## Requirements

### Requirement: AI outputs must be traceable or explicitly uncertain
系统 MUST 保证所有通过医保智能体 API 返回给用户的 AI 导办结果、高风险拦截结果、降级结果和流式最终结果至少包含一个来源引用或一个不确定性提示。

#### Scenario: High risk action blocked with traceability
- **WHEN** 用户请求退费、冲正、正式结算、撤销结算、病案首页修改或费用明细修改等高风险动作
- **THEN** 系统 MUST 返回 `waiting_human_confirmation` 状态
- **AND** 响应 MUST 包含风控策略来源引用或人工确认不确定性提示
- **AND** 响应 MUST 包含待人工确认任务和审计事件

#### Scenario: Degraded result contains uncertainty
- **WHEN** 业务系统适配器、模型服务或知识服务不可用导致导办降级
- **THEN** 系统 MUST 返回 `degraded` 或可解释失败状态
- **AND** 响应 MUST 包含受影响来源、失败原因或不确定性提示

#### Scenario: Stream final result remains traceable
- **WHEN** 流式 Chat 请求成功完成并发送 SSE `final` 事件
- **THEN** `final` 事件中的响应 MUST 包含 citations 或 uncertainties
- **AND** `done` 事件 MUST 在 `final` 事件之后发送

### Requirement: Streaming model errors must be normalized
系统 MUST 对流式模型调用中的超时、网络错误、HTTP 错误、鉴权错误、限流错误、上游服务错误和回退链耗尽进行统一异常归一化，并通过 SSE `error` 事件返回结构化错误。

#### Scenario: Streaming provider timeout
- **WHEN** 流式模型 Provider 发生超时
- **THEN** Provider MUST 将底层异常转换为模型超时错误
- **AND** Gateway MUST 记录模型名、场景、已输出分片数、耗时和错误类型
- **AND** API MUST 返回包含标准错误码和用户可读消息的 SSE `error` 事件
- **AND** API MUST 最终发送 SSE `done` 事件

#### Scenario: Streaming provider authentication failure
- **WHEN** 流式模型 Provider 收到 401 或 403 响应
- **THEN** 系统 MUST 返回模型鉴权失败错误事件
- **AND** 错误事件 MUST NOT 泄露 API Key、Authorization 头或原始敏感请求内容

#### Scenario: Streaming provider emits malformed JSON
- **WHEN** 流式模型 Provider 收到非 `[DONE]` 且无法解析为 JSON 的 SSE 数据行
- **THEN** Provider MUST 转换为模型上游错误或模型协议错误
- **AND** API MUST 返回结构化 SSE `error` 事件

### Requirement: API errors must use standard error details
系统 MUST 使用统一错误结构返回 API 错误，错误结构 MUST 包含 `error_code`、`message` 和 `audit_event` 字段。

#### Scenario: Permission denied response
- **WHEN** 用户角色无权访问目标医保业务场景
- **THEN** 系统 MUST 返回 403 HTTP 状态码
- **AND** 响应 detail MUST 使用统一错误结构
- **AND** `audit_event` MUST 标识权限拒绝事件

#### Scenario: Model service exhausted response
- **WHEN** 模型服务回退链全部失败
- **THEN** 系统 MUST 返回结构化模型耗尽错误
- **AND** 错误 MUST 可被前端展示为可读失败原因

### Requirement: High risk actions must never be auto-executed
系统 MUST 将退费、冲正、正式结算、撤销结算、病案首页修改、费用明细修改和最终申诉结论确认等高风险动作转换为人工确认任务，且 MUST NOT 调用任何执行类适配器完成真实业务变更。

#### Scenario: Refund request creates confirmation task only
- **WHEN** 用户请求自动退费或冲正
- **THEN** 系统 MUST 创建人工确认任务
- **AND** 系统 MUST NOT 调用退费、冲正或正式结算执行接口
- **AND** 响应 MUST 说明需要人工在既有业务系统执行
