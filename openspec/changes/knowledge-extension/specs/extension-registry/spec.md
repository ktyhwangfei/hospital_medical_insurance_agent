## ADDED Requirements

### Requirement: Extension registry must describe callable capabilities
系统 MUST 为 Tool、Skill、MCP 和 A2A 扩展能力建立统一注册模型，模型 MUST 包含扩展标识、扩展类型、能力名称、描述、适用场景、输入 schema、输出 schema、风险等级、权限要求、超时策略、重试策略、审计策略、调用端点标识、健康状态和启用状态。

#### Scenario: Register tool capability
- **WHEN** 平台注册一个费用明细分析 Tool
- **THEN** 扩展注册表 MUST 保存其能力元数据、输入输出 schema、权限要求和风险等级

#### Scenario: Register MCP capability
- **WHEN** 平台注册一个 MCP 工具服务
- **THEN** 扩展注册表 MUST 保存连接标识、工具列表摘要、权限要求和审计策略

#### Scenario: Register duplicate extension id
- **WHEN** 平台注册已存在的扩展标识
- **THEN** 扩展注册表 MUST 拒绝重复注册或创建显式新版本
- **AND** 审计事件 MUST 记录重复注册处理结果

### Requirement: Extension selection must enforce permissions and risk controls
系统 MUST 在运行时选择扩展能力前校验用户角色权限、场景范围、风险等级和高风险动作边界。

#### Scenario: User lacks extension permission
- **WHEN** 运行时计划请求调用用户无权使用的扩展能力
- **THEN** 系统 MUST 拒绝选择该扩展能力
- **AND** 系统 MUST 记录权限拒绝审计事件

#### Scenario: Extension is high risk
- **WHEN** 扩展能力声明为可触发退费、冲正、正式结算、病案修改或申诉最终确认等高风险动作
- **THEN** 系统 MUST NOT 自动执行该扩展能力
- **AND** 系统 MUST 创建人工确认任务或返回高风险拦截响应

#### Scenario: Extension outside scenario scope
- **WHEN** 运行时计划在不匹配的业务场景中选择扩展能力
- **THEN** 系统 MUST 拒绝选择该扩展能力
- **AND** workflow MUST 记录扩展场景范围不匹配的降级或拒绝原因

### Requirement: Extension registry must support health and availability state
系统 MUST 跟踪扩展能力的启用状态、健康状态、最近检查时间和不可用原因。

#### Scenario: Extension unavailable
- **WHEN** 扩展能力处于停用或健康检查失败状态
- **THEN** 运行时 MUST NOT 将其作为可调用能力
- **AND** 运行时 MUST 记录能力不可用的降级原因

#### Scenario: Extension health is stale
- **WHEN** 扩展能力的最近健康检查时间超过注册表声明的有效窗口
- **THEN** 运行时 MUST 将该能力视为健康状态未知或不可用
- **AND** 系统 MUST 记录健康状态过期原因

### Requirement: Extension calls must be auditable
系统 MUST 对扩展能力的选择和调用记录审计事件，审计事件 MUST 包含 workflow、step、扩展标识、能力名称、调用用户、输入摘要、输出摘要、状态和耗时。

#### Scenario: Audit successful extension call
- **WHEN** 运行时调用一个已注册扩展能力并成功返回
- **THEN** 系统 MUST 记录扩展调用审计事件
- **AND** 审计事件 MUST 关联当前 workflow 和 step

#### Scenario: Audit failed extension call
- **WHEN** 扩展能力调用失败、超时或返回不可用
- **THEN** 系统 MUST 记录失败审计事件
- **AND** 运行时 MUST 将失败原因纳入 workflow 状态或响应不确定性

#### Scenario: Audit denied extension selection
- **WHEN** 扩展能力因权限、场景范围、风险等级或健康状态被拒绝选择
- **THEN** 系统 MUST 记录拒绝选择审计事件
- **AND** 审计事件 MUST 包含拒绝原因和脱敏后的输入摘要
