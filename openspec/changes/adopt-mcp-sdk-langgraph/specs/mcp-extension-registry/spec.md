## MODIFIED Requirements

### Requirement: MCP registry must model services and capabilities
系统 MUST 使用类型化模型表示 MCP 服务、能力、策略、状态和审计元数据，且 MUST NOT 使用裸 `dict` 作为 MCP 注册服务返回类型。MCP 注册模型 MUST 能与 MCP SDK 或 FastMCP 返回的 server、tool、resource、prompt 和 annotations 元数据进行稳定映射。

#### Scenario: Register MCP server with capabilities
- **WHEN** 系统注册一个 MCP 服务及其工具、资源或提示能力
- **THEN** 注册结果 MUST 包含 server_id、server_name、transport、capabilities、status、required_permissions、risk_level 和 audit metadata
- **AND** 每个能力 MUST 具有稳定 capability_id、capability_type、description、supported_scenarios 和 citation source
- **AND** 若能力来自 MCP SDK 或 FastMCP 自动发现，系统 MUST 保存原始发现 payload 或可审计引用

#### Scenario: Reject invalid MCP capability
- **WHEN** MCP 能力缺少 capability_id、capability_type、所属 server_id 或风险等级
- **THEN** 系统 MUST 拒绝注册
- **AND** 系统 MUST 返回结构化错误或可审计的失败结果

#### Scenario: Map MCP SDK tool metadata
- **WHEN** MCP SDK adapter 发现 tool name、description、inputSchema、annotations 或 outputSchema
- **THEN** 系统 MUST 将其映射为平台 McpCapability 字段
- **AND** 系统 MUST 根据 annotations 和平台策略推导只读性、副作用、幂等性和默认风险等级
- **AND** 平台策略 MUST 优先于 MCP tool 自声明的低风险提示

### Requirement: MCP registry must query and filter capabilities
系统 MUST 支持按场景、角色、权限、能力类型、风险等级和服务状态查询 MCP 能力。运行时和 LangGraph 节点 MUST 只能通过 MCP 注册服务查询可用能力，不得直接扫描外部 MCP Server 作为调用依据。

#### Scenario: Filter capabilities for runtime scenario
- **WHEN** 运行时为医保结算异常导办或出院前联合质控查询可用 MCP 能力
- **THEN** MCP 注册服务 MUST 仅返回匹配当前场景、用户角色、权限集合和启用状态的能力
- **AND** 返回结果 MUST 包含被排除能力的可审计原因或可用于生成 uncertainties 的说明

#### Scenario: Exclude disabled or unhealthy server
- **WHEN** MCP 服务状态为 disabled、degraded 或 unhealthy 且策略不允许降级使用
- **THEN** MCP 注册服务 MUST NOT 将该服务下的能力作为可自动选择能力返回
- **AND** 系统 MUST 保留不可用状态说明

#### Scenario: Graph node requests MCP capability
- **WHEN** LangGraph 节点请求选择 MCP 能力
- **THEN** 节点 MUST 提供 scenario、role、permissions、capability_type 和 max_risk_level
- **AND** 注册服务 MUST 返回 selected_capabilities、excluded_capabilities、citations 或 uncertainties

### Requirement: MCP registry must govern high risk capabilities
系统 MUST 将声明为高风险或具备外部副作用的 MCP 能力标记为需要人工确认，且 MUST NOT 在运行时自动执行该能力。该约束 MUST 同时适用于传统业务服务路径和 LangGraph 图节点路径。

#### Scenario: High risk MCP tool selected by user intent
- **WHEN** 用户请求触发退费、冲正、正式结算、病案修改或其他高风险 MCP 工具
- **THEN** 系统 MUST 返回 waiting_human_confirmation 或等价待人工确认状态
- **AND** 系统 MUST 创建可审计任务或审计事件
- **AND** 系统 MUST NOT 执行真实 MCP 工具调用

#### Scenario: MCP annotations imply external side effects
- **WHEN** MCP SDK adapter 发现 tool annotations 声明 destructiveHint、非只读能力或平台无法确认其副作用
- **THEN** 系统 MUST 将能力标记为 medium 或 high 风险
- **AND** 未经人工确认或管理员策略覆盖前，运行时 MUST NOT 自动调用该能力

### Requirement: MCP registry must expose traceable selection results
系统 MUST 在 MCP 能力选择结果中提供 citations 或 uncertainties，以支持运行时响应可追溯。通过 MCP SDK 或 FastMCP 发现和调用的能力 MUST 保留 server、tool、schema、策略和调用结果引用。

#### Scenario: MCP capability selected successfully
- **WHEN** 运行时成功选择 MCP 能力辅助导办
- **THEN** 选择结果 MUST 包含注册来源、能力描述、策略来源或审计引用
- **AND** 最终响应 MUST 能够引用这些来源

#### Scenario: No MCP capability available
- **WHEN** 没有任何 MCP 能力满足当前场景、权限或状态约束
- **THEN** 选择结果 MUST 包含 uncertainties
- **AND** 系统 MUST 继续使用既有确定性降级路径完成导办

#### Scenario: MCP SDK invocation failure is traceable
- **WHEN** MCP SDK adapter 在 initialize、tools/list 或 tools/call 阶段失败
- **THEN** 系统 MUST 将协议错误、连接错误、超时、鉴权失败或上游错误归一化为可审计结果
- **AND** 最终响应 MUST 包含 uncertainties 或失败引用

