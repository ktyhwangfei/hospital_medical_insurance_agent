## ADDED Requirements

### Requirement: Prompt templates must be versioned assets
系统 MUST 将场景模板、角色模板、输出格式模板和安全约束模板作为版本化资产管理，模板元数据 MUST 包含模板标识、类型、适用场景、适用角色、语言、输出格式、风险等级、版本、状态、变量 schema、安全约束、创建时间、更新时间和审计事件。

#### Scenario: Register scenario prompt template
- **WHEN** 系统注册医保结算异常导办提示词模板
- **THEN** 模板 MUST 包含场景、版本、状态和变量 schema
- **AND** 模板注册 MUST 产生审计事件

#### Scenario: Inactive prompt template is not selected
- **WHEN** 模板处于草稿、停用或过期状态
- **THEN** 运行时 MUST NOT 将该模板作为默认生成模板

#### Scenario: Template variable schema is invalid
- **WHEN** 模板声明的变量 schema 缺少必填变量、类型不匹配或包含未允许变量
- **THEN** 模板服务 MUST 拒绝注册或拒绝选择该模板
- **AND** 审计事件 MUST 记录变量 schema 校验失败原因

### Requirement: Runtime must select templates by context
系统 MUST 支持运行时根据业务场景、用户角色、输出格式、语言、风险等级和安全要求选择提示词模板。

#### Scenario: Select template for role-specific response
- **WHEN** 医保办用户请求生成结算异常导办结果
- **THEN** 模板服务 MUST 返回匹配医保办角色和结算异常场景的模板

#### Scenario: Missing template degrades safely
- **WHEN** 没有可用模板匹配当前上下文
- **THEN** 模板服务 MUST 返回模板缺失状态
- **AND** 运行时 MUST 使用确定性兜底响应或返回不确定性提示

#### Scenario: Template selection is deterministic
- **WHEN** 多个模板同时匹配当前上下文
- **THEN** 模板服务 MUST 按场景匹配度、角色匹配度、风险等级、安全约束完整性、版本和更新时间稳定排序
- **AND** 相同上下文 MUST 选择同一个模板

### Requirement: Prompt templates must enforce output safety constraints
系统 MUST 让提示词模板声明输出安全约束，包括必须引用来源、必须声明不确定性、禁止自动执行高风险动作和禁止泄露敏感信息。

#### Scenario: Template requires citations
- **WHEN** 模板用于生成面向用户的导办结论
- **THEN** 模板元数据 MUST 声明 citations 或 uncertainties 输出要求
- **AND** 运行时 MUST 在响应组装阶段校验该要求

#### Scenario: Template handles high risk action
- **WHEN** 模板用于高风险动作请求
- **THEN** 模板 MUST 指示模型说明人工确认边界
- **AND** 模板 MUST NOT 指示模型生成已执行业务变更的表述

#### Scenario: Rendered prompt preserves safety constraints
- **WHEN** 模板被变量渲染为模型提示词
- **THEN** 渲染结果 MUST 保留 citations 或 uncertainties、高风险动作边界和敏感信息保护要求
- **AND** 用户输入变量 MUST NOT 覆盖模板的系统级安全约束
