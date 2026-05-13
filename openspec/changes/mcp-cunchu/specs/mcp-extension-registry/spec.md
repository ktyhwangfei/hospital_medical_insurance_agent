## ADDED Requirements

### Requirement: MCP registry must model services and capabilities
系统 MUST 使用类型化模型表示 MCP 服务、能力、策略、状态和审计元数据，且 MUST NOT 使用裸 `dict` 作为 MCP 注册服务返回类型。

#### Scenario: Register MCP server with capabilities
- **WHEN** 系统注册一个 MCP 服务及其工具、资源或提示能力
- **THEN** 注册结果 MUST 包含 server_id、server_name、transport、capabilities、status、required_permissions、risk_level 和 audit metadata
- **AND** 每个能力 MUST 具有稳定 capability_id、capability_type、description、supported_scenarios 和 citation source

#### Scenario: Reject invalid MCP capability
- **WHEN** MCP 能力缺少 capability_id、capability_type、所属 server_id 或风险等级
- **THEN** 系统 MUST 拒绝注册
- **AND** 系统 MUST 返回结构化错误或可审计的失败结果

### Requirement: MCP registry must query and filter capabilities
系统 MUST 支持按场景、角色、权限、能力类型、风险等级和服务状态查询 MCP 能力。

#### Scenario: Filter capabilities for runtime scenario
- **WHEN** 运行时为医保结算异常导办或出院前联合质控查询可用 MCP 能力
- **THEN** MCP 注册服务 MUST 仅返回匹配当前场景、用户角色、权限集合和启用状态的能力
- **AND** 返回结果 MUST 包含被排除能力的可审计原因或可用于生成 uncertainties 的说明

#### Scenario: Exclude disabled or unhealthy server
- **WHEN** MCP 服务状态为 disabled、degraded 或 unhealthy 且策略不允许降级使用
- **THEN** MCP 注册服务 MUST NOT 将该服务下的能力作为可自动选择能力返回
- **AND** 系统 MUST 保留不可用状态说明

### Requirement: MCP registry must govern high risk capabilities
系统 MUST 将声明为高风险或具备外部副作用的 MCP 能力标记为需要人工确认，且 MUST NOT 在运行时自动执行该能力。

#### Scenario: High risk MCP tool selected by user intent
- **WHEN** 用户请求触发退费、冲正、正式结算、病案修改或其他高风险 MCP 工具
- **THEN** 系统 MUST 返回 waiting_human_confirmation 或等价待人工确认状态
- **AND** 系统 MUST 创建可审计任务或审计事件
- **AND** 系统 MUST NOT 执行真实 MCP 工具调用

### Requirement: MCP registry must expose traceable selection results
系统 MUST 在 MCP 能力选择结果中提供 citations 或 uncertainties，以支持运行时响应可追溯。

#### Scenario: MCP capability selected successfully
- **WHEN** 运行时成功选择 MCP 能力辅助导办
- **THEN** 选择结果 MUST 包含注册来源、能力描述、策略来源或审计引用
- **AND** 最终响应 MUST 能够引用这些来源

#### Scenario: No MCP capability available
- **WHEN** 没有任何 MCP 能力满足当前场景、权限或状态约束
- **THEN** 选择结果 MUST 包含 uncertainties
- **AND** 系统 MUST 继续使用既有确定性降级路径完成导办
