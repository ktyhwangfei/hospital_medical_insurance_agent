## MODIFIED Requirements

### Requirement: Runtime must execute plans with state tracking
系统 MUST 按执行计划顺序执行步骤，并记录 workflow、step、输入输出引用、状态、错误、MCP 能力选择结果和审计引用。

#### Scenario: Successful workflow execution
- **WHEN** 执行计划的所有步骤成功完成
- **THEN** 系统 MUST 将 workflow 状态置为 completed
- **AND** API 响应 MUST 包含 workflow_id 和已执行步骤摘要

#### Scenario: Workflow waits for human confirmation
- **WHEN** 执行计划包含人工确认步骤且需要人工处理
- **THEN** 系统 MUST 将 workflow 状态置为 waiting_human_confirmation
- **AND** 系统 MUST 创建可查询的待办任务

#### Scenario: Step failure records degraded workflow state
- **WHEN** 非关键步骤失败但系统可返回部分结果
- **THEN** 系统 MUST 将步骤状态记录为 failed 或 degraded
- **AND** workflow MUST 保留已完成步骤的输出引用
- **AND** API 响应 MUST 包含不确定性提示

#### Scenario: Runtime selects MCP capability for a plan step
- **WHEN** 执行计划步骤需要查询 MCP 扩展能力
- **THEN** 运行时 MUST 通过 MCP 扩展注册服务筛选当前场景、角色、权限和风险等级允许的能力
- **AND** workflow MUST 记录 selected_capabilities、excluded_capabilities、选择原因、引用或不确定性提示

#### Scenario: Runtime invokes authorized remote MCP capability
- **WHEN** 执行计划步骤选择了低风险只读 MCP 能力且调用前评估通过
- **THEN** 运行时 MUST 通过 MCP Client Gateway 执行真实远程 MCP 调用
- **AND** workflow MUST 记录 request_id、server_id、capability_id、stream events summary、result citations、latency 和 audit_event

#### Scenario: MCP registry unavailable during workflow
- **WHEN** MCP 扩展注册服务不可用或没有匹配能力
- **THEN** 运行时 MUST 将相关步骤标记为 degraded 或 skipped
- **AND** workflow MUST 保留不确定性提示
- **AND** 既有医保导办主流程 MUST 继续使用可用的确定性路径返回结果
