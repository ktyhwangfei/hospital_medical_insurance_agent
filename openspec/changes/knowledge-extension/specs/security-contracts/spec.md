## MODIFIED Requirements

### Requirement: AI outputs must be traceable or explicitly uncertain
系统 MUST 保证所有通过医保智能体 API 返回给用户的 AI 导办结果、高风险拦截结果、降级结果、知识检索结果、规则解释结果、扩展能力调用结果和流式最终结果至少包含一个来源引用或一个不确定性提示。

#### Scenario: High risk action blocked with traceability
- **WHEN** 用户请求退费、冲正、正式结算、撤销结算、病案首页修改或费用明细修改等高风险动作
- **THEN** 系统 MUST 返回 `waiting_human_confirmation` 状态
- **AND** 响应 MUST 包含风控策略来源引用或人工确认不确定性提示
- **AND** 响应 MUST 包含待人工确认任务和审计事件

#### Scenario: Degraded result contains uncertainty
- **WHEN** 业务系统适配器、模型服务或知识服务不可用导致导办降级
- **THEN** 系统 MUST 返回 `degraded` 或可解释失败状态
- **AND** 响应 MUST 包含受影响来源、失败原因或不确定性提示

#### Scenario: Stream final result remains traceable
- **WHEN** 流式 Chat 请求成功完成并发送 SSE `final` 事件
- **THEN** `final` 事件中的响应 MUST 包含 citations 或 uncertainties
- **AND** `done` 事件 MUST 在 `final` 事件之后发送

#### Scenario: Rule explanation response is traceable
- **WHEN** API 响应包含规则解释或知识检索生成的导办内容
- **THEN** 响应 MUST 包含对应知识资产、规则条目或检索切片生成的 citations
- **AND** 如果证据不足，响应 MUST 包含 uncertainties

#### Scenario: Knowledge-only response with no evidence
- **WHEN** 用户请求政策解释、规则说明或申诉模板检索但知识服务没有可用证据
- **THEN** 系统 MUST NOT 返回确定性政策结论
- **AND** 响应 MUST 包含不确定性提示、人工复核建议或可审计失败原因

### Requirement: High risk actions must never be auto-executed
系统 MUST 将退费、冲正、正式结算、撤销结算、病案首页修改、费用明细修改和最终申诉结论确认等高风险动作转换为人工确认任务，且 MUST NOT 调用任何执行类适配器或扩展能力完成真实业务变更。

#### Scenario: Refund request creates confirmation task only
- **WHEN** 用户请求自动退费或冲正
- **THEN** 系统 MUST 创建人工确认任务
- **AND** 系统 MUST NOT 调用退费、冲正或正式结算执行接口
- **AND** 响应 MUST 说明需要人工在既有业务系统执行

#### Scenario: High risk extension is blocked
- **WHEN** Tool、Skill、MCP 或 A2A 扩展能力声明可触发高风险业务动作
- **THEN** 系统 MUST NOT 自动调用该扩展完成业务变更
- **AND** 系统 MUST 返回人工确认任务或高风险拦截响应

#### Scenario: Knowledge service cannot bypass risk control
- **WHEN** 知识检索、规则解释或提示词模板内容包含退费、冲正、正式结算、病案修改或最终申诉确认建议
- **THEN** 运行时 MUST 继续执行高风险动作识别和拦截
- **AND** 系统 MUST NOT 因知识来源存在该建议而自动执行业务变更

### Requirement: Knowledge and extension services must protect sensitive data
系统 MUST 在知识切片、检索上下文、规则解释证据、模板变量和扩展输入输出摘要中执行最小必要字段和脱敏约束，禁止向无权角色或 API 响应泄露患者敏感信息、内部文件路径、凭据、Token 或未经授权的院内运营数据。

#### Scenario: Retrieved chunk contains sensitive patient sample
- **WHEN** 检索命中的知识切片包含患者姓名、证件号、联系方式或费用明细样例
- **THEN** 系统 MUST 在面向用户响应和模型上下文中使用脱敏内容或拒绝该切片
- **AND** 审计事件 MUST 记录敏感字段处理结果

#### Scenario: Extension input summary is audited
- **WHEN** 运行时记录扩展能力选择或调用审计事件
- **THEN** 输入摘要和输出摘要 MUST 脱敏
- **AND** 审计事件 MUST NOT 包含凭据、Token、Authorization 头或完整敏感原文
