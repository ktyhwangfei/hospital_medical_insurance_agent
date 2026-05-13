## MODIFIED Requirements

### Requirement: High risk actions must never be auto-executed
系统 MUST 将退费、冲正、正式结算、撤销结算、病案首页修改、费用明细修改、最终申诉结论确认以及具备同类外部副作用的高风险 MCP 能力转换为人工确认任务，且 MUST NOT 调用任何执行类适配器或 MCP 工具完成真实业务变更。

#### Scenario: Refund request creates confirmation task only
- **WHEN** 用户请求自动退费或冲正
- **THEN** 系统 MUST 创建人工确认任务
- **AND** 系统 MUST NOT 调用退费、冲正或正式结算执行接口
- **AND** 响应 MUST 说明需要人工在既有业务系统执行

#### Scenario: High risk MCP capability creates confirmation task only
- **WHEN** 用户请求命中声明为高风险或具备真实业务副作用的 MCP 能力
- **THEN** 系统 MUST 创建人工确认任务或返回 waiting_human_confirmation 状态
- **AND** 系统 MUST NOT 执行真实 MCP 工具调用
- **AND** 响应 MUST 包含风控策略来源、MCP 能力注册引用或不确定性提示

### Requirement: MCP extension operations must be authorized and audited
系统 MUST 对 MCP 注册、查询、状态变更、调用前评估和调用结果记录执行权限校验、风险评估和审计记录。

#### Scenario: Unauthorized MCP status update
- **WHEN** 用户角色缺少 MCP 管理权限却请求启用、禁用或修改 MCP 服务
- **THEN** 系统 MUST 拒绝该操作
- **AND** 错误 MUST 使用统一错误结构
- **AND** 系统 MUST 记录权限拒绝审计事件

#### Scenario: MCP capability selection audited
- **WHEN** 运行时为导办流程筛选 MCP 能力
- **THEN** 系统 MUST 记录候选能力、选中能力、排除原因、权限结果和风险等级
- **AND** 记录 MUST 可关联到 workflow_id 或 audit_event
