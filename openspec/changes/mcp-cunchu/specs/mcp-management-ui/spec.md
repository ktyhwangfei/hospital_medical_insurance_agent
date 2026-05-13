## ADDED Requirements

### Requirement: MCP management UI must manage server registrations
系统 MUST 提供 MCP 管理 UI，用于新增、编辑、查看、启用、禁用和删除 MCP 服务注册。

#### Scenario: Register MCP server from UI
- **WHEN** 管理员在 MCP 管理 UI 提交服务名称、地址、传输方式、认证方式和安全策略
- **THEN** 系统 MUST 创建 MCP 服务注册
- **AND** UI MUST 展示脱敏后的连接配置、服务状态和审计事件引用

#### Scenario: Disable MCP server from UI
- **WHEN** 管理员在 UI 禁用 MCP 服务
- **THEN** 系统 MUST 更新服务状态
- **AND** 运行时 MUST 不再自动选择该服务下的能力

### Requirement: MCP management UI must test connections and browse capabilities
系统 MUST 允许管理员通过 UI 发起连接测试、查看握手结果、能力清单、工具参数模式、资源列表和提示模板列表。

#### Scenario: Test MCP connection from UI
- **WHEN** 管理员点击连接测试
- **THEN** UI MUST 展示握手状态、协议版本、发现的能力数量和错误详情
- **AND** 错误详情 MUST 不泄露密钥

#### Scenario: Browse discovered MCP capabilities
- **WHEN** 远程 MCP Server 能力发现成功
- **THEN** UI MUST 展示工具、资源、提示和服务能力清单
- **AND** 每个能力 MUST 展示风险等级、所需权限、支持场景和启用状态

### Requirement: MCP management UI must configure policies and view audits
系统 MUST 支持在 UI 中配置 MCP 能力策略，并查看注册、连接测试、状态变更、调用前评估和工具调用审计记录。

#### Scenario: Configure capability policy
- **WHEN** 管理员修改 MCP 能力的支持场景、角色、权限、风险等级或人工确认要求
- **THEN** 系统 MUST 保存策略变更
- **AND** 后续运行时筛选 MUST 使用新策略

#### Scenario: View MCP audit trail
- **WHEN** 管理员或审计人员查询 MCP 审计记录
- **THEN** UI MUST 展示操作类型、操作者、时间、对象、结果和 workflow_id 或 audit_event
- **AND** UI MUST 对敏感字段进行脱敏展示
