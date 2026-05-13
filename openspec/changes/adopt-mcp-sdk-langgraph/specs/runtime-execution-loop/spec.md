## MODIFIED Requirements

### Requirement: Runtime must generate deterministic execution plans
系统 MUST 为医保结算异常导办、出院前联合质控和高风险动作请求生成确定性执行计划，计划 MUST 包含目标、场景、步骤、依赖、风险等级、人工确认标记、输出要求和审计信息。执行计划 MAY 映射为 LangGraph 图或子图，但图结构 MUST 保留确定性步骤边界、依赖关系、风险等级、人工确认标记和输出追溯要求。

#### Scenario: Settlement exception plan
- **WHEN** 意图识别结果为医保结算异常导办
- **THEN** 系统 MUST 生成包含交易查询、错误码知识检索、收费状态查询、异常归因和结果组装步骤的执行计划
- **AND** 若该计划映射为 LangGraph 子图，每个图节点 MUST 对应可审计的业务步骤或结果组装步骤

#### Scenario: Pre-discharge quality control plan
- **WHEN** 意图识别结果为出院前联合质控
- **THEN** 系统 MUST 生成包含费用医嘱查询、医保接口状态查询、事前审核查询、DRG/DIP 查询、病案查询、规则解释检索、风险清单生成和任务创建步骤的执行计划
- **AND** 若该计划映射为 LangGraph 子图，图状态 MUST 保留每个节点的输入引用、输出引用和降级原因

#### Scenario: High risk action plan
- **WHEN** 请求命中高风险动作
- **THEN** 系统 MUST 生成人工确认计划
- **AND** 计划 MUST 标记禁止自动执行和等待人工确认
- **AND** 若使用 LangGraph 执行，图 MUST 在高风险节点前中断并返回 waiting_human_confirmation 或等价状态

#### Scenario: Skill metadata maps to graph template
- **WHEN** 系统根据 skill_id 或 scenario 选择执行流程
- **THEN** 系统 MUST 将 skill 元数据解析为受控 LangGraph 图模板或已注册图引用
- **AND** 系统 MUST 校验图模板引用的工具、角色、权限和风险策略
- **AND** 系统 MUST NOT 将 skill 元数据当作可绕过治理的任意脚本执行

### Requirement: Runtime must execute plans with state tracking
系统 MUST 按执行计划顺序执行步骤，并记录 workflow、step、输入输出引用、状态、错误和审计引用。当执行计划由 LangGraph 承载时，系统 MUST 将图节点、图状态、checkpoint、中断恢复和节点输出映射到现有 workflow 与 task 状态模型。

#### Scenario: Successful workflow execution
- **WHEN** 执行计划的所有步骤成功完成
- **THEN** 系统 MUST 将 workflow 状态置为 completed
- **AND** API 响应 MUST 包含 workflow_id 和已执行步骤摘要
- **AND** 若由 LangGraph 执行，响应 MUST 能追溯 graph_id、node_id 和 checkpoint 引用

#### Scenario: Workflow waits for human confirmation
- **WHEN** 执行计划包含人工确认步骤且需要人工处理
- **THEN** 系统 MUST 将 workflow 状态置为 waiting_human_confirmation
- **AND** 系统 MUST 创建可查询的待办任务
- **AND** 若由 LangGraph 执行，图执行 MUST 可在人工确认后按 workflow_id 或 checkpoint 恢复

#### Scenario: Step failure records degraded workflow state
- **WHEN** 非关键步骤失败但系统可返回部分结果
- **THEN** 系统 MUST 将步骤状态记录为 failed 或 degraded
- **AND** workflow MUST 保留已完成步骤的输出引用
- **AND** API 响应 MUST 包含不确定性提示

#### Scenario: Governed graph node execution
- **WHEN** LangGraph 节点准备调用适配器、知识服务、模型服务或 MCP 工具
- **THEN** 节点执行前 MUST 经过统一权限校验、风险评估、最小必要字段检查和调用策略检查
- **AND** 节点执行后 MUST 记录审计事件、citations 或 uncertainties
- **AND** 节点输出 MUST 按角色进行脱敏或字段裁剪

#### Scenario: MCP SDK adapter invocation in graph node
- **WHEN** 图节点需要调用低风险且已授权的 MCP 工具
- **THEN** 系统 MUST 通过 MCP SDK adapter 或等价受控客户端执行 initialize、tools/list 或 tools/call
- **AND** workflow MUST 记录 server_id、capability_id、tool name、调用状态、延迟、错误归一化结果和审计引用
- **AND** 图节点 MUST NOT 直接绕过 MCP 注册服务连接外部 MCP Server

### Requirement: Workflow and task status endpoints must return real state
系统 MUST 让流程状态和任务状态查询接口返回运行时状态仓储或任务闭环记录中的真实状态，而不是固定占位值。当流程由 LangGraph 执行时，状态接口 MUST 返回图执行状态与现有 workflow/task 状态的统一视图。

#### Scenario: Query existing workflow
- **WHEN** 用户查询已创建的 workflow_id
- **THEN** 系统 MUST 返回 workflow 当前状态、当前步骤和步骤状态摘要
- **AND** 若 workflow 关联 LangGraph 执行，系统 MUST 返回 graph_id、当前 node_id、checkpoint 状态和可恢复性说明

#### Scenario: Query missing workflow
- **WHEN** 用户查询不存在的 workflow_id
- **THEN** 系统 MUST 返回统一结构化错误
- **AND** 错误 MUST 包含 `WORKFLOW_NOT_FOUND` 或等价错误码

#### Scenario: Query existing task
- **WHEN** 用户查询已创建的 task_id
- **THEN** 系统 MUST 返回任务状态、责任角色、描述、关联 workflow 和最近更新时间

#### Scenario: Confirm task updates workflow state
- **WHEN** 用户确认或拒绝人工确认任务
- **THEN** 系统 MUST 更新任务状态、确认人、确认时间和原因
- **AND** 系统 MUST 将该事件写入 workflow 审计轨迹
- **AND** 若 workflow 关联 LangGraph 中断状态，系统 MUST 根据确认结果恢复或终止图执行

### Requirement: Runtime must expose an audit view
系统 MUST 提供导办流程审计视图，能够还原一次导办流程的请求用户、角色、请求内容、执行计划、步骤状态、能力调用、输入输出引用、人工确认和最终结果。当流程由 LangGraph 承载时，审计视图 MUST 展示图节点执行轨迹和治理节点决策。

#### Scenario: Audit view for completed guidance
- **WHEN** 审计人员按 workflow_id 查询导办流程
- **THEN** 系统 MUST 返回完整审计视图
- **AND** 审计视图 MUST 包含用户、角色、请求时间、计划步骤、适配器调用、模型调用、任务事件和最终响应摘要
- **AND** 若由 LangGraph 执行，审计视图 MUST 包含 graph_id、node sequence、checkpoint 引用和节点治理结果

#### Scenario: Audit view for blocked high risk action
- **WHEN** 审计人员查询高风险动作拦截 workflow
- **THEN** 审计视图 MUST 展示命中的高风险动作、拦截策略来源、人工确认任务和未自动执行说明
- **AND** 若由 LangGraph 执行，审计视图 MUST 展示中断节点、阻断原因和恢复条件

