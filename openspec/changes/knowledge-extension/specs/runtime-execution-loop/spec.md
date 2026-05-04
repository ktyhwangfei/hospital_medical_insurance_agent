## MODIFIED Requirements

### Requirement: Runtime must generate deterministic execution plans
系统 MUST 为医保结算异常导办、出院前联合质控和高风险动作请求生成确定性执行计划，计划 MUST 包含目标、场景、步骤、依赖、风险等级、人工确认标记、输出要求和审计信息。计划步骤 MUST 能表达知识检索、规则解释、提示词模板选择和扩展能力选择等知识与扩展服务调用。

#### Scenario: Settlement exception plan
- **WHEN** 意图识别结果为医保结算异常导办
- **THEN** 系统 MUST 生成包含交易查询、错误码知识检索、收费状态查询、异常归因和结果组装步骤的执行计划
- **AND** 错误码知识检索步骤 MUST 记录知识检索输出要求和引用要求

#### Scenario: Pre-discharge quality control plan
- **WHEN** 意图识别结果为出院前联合质控
- **THEN** 系统 MUST 生成包含费用医嘱查询、医保接口状态查询、事前审核查询、DRG/DIP 查询、病案查询、规则解释检索、风险清单生成和任务创建步骤的执行计划
- **AND** 规则解释检索步骤 MUST 记录规则解释输出要求和引用要求

#### Scenario: High risk action plan
- **WHEN** 请求命中高风险动作
- **THEN** 系统 MUST 生成人工确认计划
- **AND** 计划 MUST 标记禁止自动执行和等待人工确认

#### Scenario: Knowledge extension plan step
- **WHEN** 意图需要医保政策解释、规则解释、申诉模板检索或扩展能力选择
- **THEN** 系统 MUST 在执行计划中创建知识与扩展服务步骤
- **AND** 步骤 MUST 声明 citations 或 uncertainties 输出要求

#### Scenario: Knowledge extension plan keeps adapter boundary
- **WHEN** 执行计划包含知识检索、规则解释、提示词模板选择或扩展选择步骤
- **THEN** 步骤 MUST 只声明知识与扩展服务输入输出契约
- **AND** 步骤 MUST NOT 要求知识服务直接访问 HIS、EMR、医保接口、收费、事前审核、DRG/DIP 或病案适配器

### Requirement: Runtime must execute plans with state tracking
系统 MUST 按执行计划顺序执行步骤，并记录 workflow、step、输入输出引用、状态、错误和审计引用。知识检索、规则解释、提示词模板选择和扩展能力选择步骤的结果 MUST 记录来源引用、降级状态、不确定性和审计事件。

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

#### Scenario: Knowledge service step degrades workflow
- **WHEN** 知识检索、规则解释或模板选择步骤失败且业务场景可返回部分结果
- **THEN** workflow MUST 记录对应步骤为 degraded 或 failed
- **AND** API 响应 MUST 包含知识来源不可用、无命中或模板缺失的不确定性提示

#### Scenario: Knowledge evidence is merged once
- **WHEN** 多个运行时步骤返回相同知识资产、规则证据或切片引用
- **THEN** 结果组装 MUST 去重合并 citations
- **AND** workflow MUST 保留每个步骤原始引用和最终响应引用之间的映射

### Requirement: Runtime must expose an audit view
系统 MUST 提供导办流程审计视图，能够还原一次导办流程的请求用户、角色、请求内容、执行计划、步骤状态、能力调用、输入输出引用、人工确认和最终结果。审计视图 MUST 包含知识检索、规则解释、提示词模板选择和扩展能力调用事件。

#### Scenario: Audit view for completed guidance
- **WHEN** 审计人员按 workflow_id 查询导办流程
- **THEN** 系统 MUST 返回完整审计视图
- **AND** 审计视图 MUST 包含用户、角色、请求时间、计划步骤、适配器调用、模型调用、任务事件和最终响应摘要
- **AND** 审计视图 MUST 包含知识检索、规则解释和模板选择事件摘要

#### Scenario: Audit view for blocked high risk action
- **WHEN** 审计人员查询高风险动作拦截 workflow
- **THEN** 审计视图 MUST 展示命中的高风险动作、拦截策略来源、人工确认任务和未自动执行说明

#### Scenario: Audit view for extension call
- **WHEN** 审计人员查询包含扩展能力调用的 workflow
- **THEN** 审计视图 MUST 展示扩展标识、能力名称、权限校验结果、调用状态和输入输出摘要

#### Scenario: Audit view for knowledge degradation
- **WHEN** 审计人员查询发生知识无命中、模板缺失、规则未知或扩展不可用的 workflow
- **THEN** 审计视图 MUST 展示对应步骤状态、降级原因、不确定性提示和可用引用
