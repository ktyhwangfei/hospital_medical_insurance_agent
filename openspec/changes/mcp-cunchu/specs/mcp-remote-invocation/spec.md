## ADDED Requirements

### Requirement: MCP client gateway must connect and handshake with remote servers
系统 MUST 提供 MCP Client Gateway，用于连接真实远程 MCP Server、执行初始化握手、发现服务能力并记录连接状态。

#### Scenario: Successful MCP handshake
- **WHEN** 管理员配置远程 MCP Server 地址、传输方式和认证信息后执行连接测试
- **THEN** MCP Client Gateway MUST 建立连接并完成初始化握手
- **AND** 系统 MUST 保存 server capabilities、protocol version、connection status 和 audit_event

#### Scenario: MCP handshake failure
- **WHEN** 远程 MCP Server 不可达、鉴权失败或协议版本不兼容
- **THEN** MCP Client Gateway MUST 返回结构化错误
- **AND** 系统 MUST 将服务状态标记为 degraded 或 unhealthy
- **AND** 错误 MUST NOT 泄露密钥或 Authorization 头

### Requirement: MCP client gateway must support streaming protocol communication
系统 MUST 支持远程 MCP 协议流式通信，并将服务端事件、增量结果、错误和完成事件归一化为内部事件模型。

#### Scenario: Streaming MCP tool result
- **WHEN** 低风险 MCP 工具返回流式执行结果
- **THEN** MCP Client Gateway MUST 按顺序产出增量事件
- **AND** 最终事件 MUST 包含 completion status、citations 或 uncertainties

#### Scenario: Streaming MCP protocol error
- **WHEN** 流式 MCP 通信发生断连、超时、畸形消息或上游错误
- **THEN** MCP Client Gateway MUST 归一化为结构化错误事件
- **AND** 运行时 MUST 能将 workflow 步骤标记为 failed 或 degraded

### Requirement: MCP tools must execute only after authorization and risk evaluation
系统 MUST 在执行真实 MCP 工具前完成权限校验、风险评估、参数校验、超时设置和审计记录。

#### Scenario: Execute authorized low risk read-only MCP tool
- **WHEN** 用户角色具备所需权限且 MCP 工具声明为低风险只读能力
- **THEN** 系统 MAY 通过 MCP Client Gateway 执行真实工具调用
- **AND** 工具结果 MUST 经过脱敏、引用追踪和审计记录后进入响应

#### Scenario: Block high risk MCP tool execution
- **WHEN** MCP 工具声明为高风险或具有业务副作用
- **THEN** 系统 MUST NOT 执行真实 MCP 工具调用
- **AND** 系统 MUST 创建人工确认任务或返回 waiting_human_confirmation 状态

