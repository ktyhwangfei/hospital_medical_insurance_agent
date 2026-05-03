## ADDED Requirements

### Requirement: Runtime must build a request context
系统 MUST 在处理 Chat 请求时构建运行时上下文，聚合用户、角色、患者、就诊、意图、权限、数据质量和审计引用。

#### Scenario: Chat request with complete patient context
- **WHEN** 用户提交包含 patient_id 和 encounter_id 的 Chat 请求
- **THEN** 系统 MUST 构建运行时上下文
- **AND** 上下文 MUST 包含用户身份、角色、患者标识、就诊标识、请求消息、请求时间和初始审计引用

#### Scenario: Chat request records intent result
- **WHEN** 意图识别完成
- **THEN** 运行时上下文 MUST 记录 intent、confidence、entities 和 intent citations
- **AND** 后续响应 MUST 保留意图识别来源引用

#### Scenario: Chat request missing patient context
- **WHEN** 用户提交缺少关键患者或就诊信息的 Chat 请求
- **THEN** 系统 MUST 返回澄清响应
- **AND** 系统 MUST NOT 编造患者、就诊或业务数据

### Requirement: Runtime must generate deterministic execution plans
系统 MUST 为医保结算异常导办、出院前联合质控和高风险动作请求生成确定性执行计划，计划 MUST 包含目标、场景、步骤、依赖、风险等级、人工确认标记、输出要求和审计信息。

#### Scenario: Settlement exception plan
- **WHEN** 意图识别结果为医保结算异常导办
- **THEN** 系统 MUST 生成包含交易查询、错误码知识检索、收费状态查询、异常归因和结果组装步骤的执行计划

#### Scenario: Pre-discharge quality control plan
- **WHEN** 意图识别结果为出院前联合质控
- **THEN** 系统 MUST 生成包含费用医嘱查询、医保接口状态查询、事前审核查询、DRG/DIP 查询、病案查询、规则解释检索、风险清单生成和任务创建步骤的执行计划

#### Scenario: High risk action plan
- **WHEN** 请求命中高风险动作
- **THEN** 系统 MUST 生成人工确认计划
- **AND** 计划 MUST 标记禁止自动执行和等待人工确认

### Requirement: Runtime must execute plans with state tracking
系统 MUST 按执行计划顺序执行步骤，并记录 workflow、step、输入输出引用、状态、错误和审计引用。

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

### Requirement: Workflow and task status endpoints must return real state
系统 MUST 让流程状态和任务状态查询接口返回运行时状态仓储或任务闭环记录中的真实状态，而不是固定占位值。

#### Scenario: Query existing workflow
- **WHEN** 用户查询已创建的 workflow_id
- **THEN** 系统 MUST 返回 workflow 当前状态、当前步骤和步骤状态摘要

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

### Requirement: Runtime must expose an audit view
系统 MUST 提供导办流程审计视图，能够还原一次导办流程的请求用户、角色、请求内容、执行计划、步骤状态、能力调用、输入输出引用、人工确认和最终结果。

#### Scenario: Audit view for completed guidance
- **WHEN** 审计人员按 workflow_id 查询导办流程
- **THEN** 系统 MUST 返回完整审计视图
- **AND** 审计视图 MUST 包含用户、角色、请求时间、计划步骤、适配器调用、模型调用、任务事件和最终响应摘要

#### Scenario: Audit view for blocked high risk action
- **WHEN** 审计人员查询高风险动作拦截 workflow
- **THEN** 审计视图 MUST 展示命中的高风险动作、拦截策略来源、人工确认任务和未自动执行说明
