## Purpose

定义业务系统适配器基座，统一医保接口、收费、事前审核、DRG/DIP、HIS、EMR 和病案等适配器的调用契约、审计、替换、脱敏权限与失败降级边界。

## Requirements

### Requirement: Adapters must expose a unified call contract
系统 MUST 为业务系统适配器定义统一调用契约，覆盖调用上下文、来源系统、能力名称、输入摘要、输出摘要、数据质量、调用状态、耗时和审计事件。

#### Scenario: Successful adapter call
- **WHEN** 业务场景调用医保接口、收费、事前审核、DRG/DIP、HIS、EMR 或病案适配器
- **THEN** 适配器 MUST 返回统一调用结果
- **AND** 调用结果 MUST 包含来源系统、来源记录标识、调用能力和数据质量状态
- **AND** 调用结果 MUST 能转换为业务场景所需领域数据

#### Scenario: Adapter returns unavailable source
- **WHEN** 外部系统不可用、超时或返回失败
- **THEN** 适配器 MUST 返回统一适配器异常或失败结果
- **AND** 失败结果 MUST 包含可审计的失败类型和用户可读原因

#### Scenario: Adapter call result carries raw source reference
- **WHEN** 适配器成功返回业务数据
- **THEN** 调用结果 MUST 包含 source_system、source_record_id、capability 和 collected_at
- **AND** 业务响应中的 citation MUST 能由这些字段生成

### Requirement: Adapter calls must be auditable
系统 MUST 对所有业务系统适配器调用记录审计事件，审计事件 MUST 能还原调用时间、调用能力、来源系统、操作用户、输入摘要和输出摘要。

#### Scenario: Audit event for adapter call
- **WHEN** 运行时编排步骤调用任一业务适配器
- **THEN** 系统 MUST 创建适配器调用审计事件
- **AND** 审计事件 MUST 关联当前 workflow、step 和 request

#### Scenario: Adapter call input summary excludes sensitive values
- **WHEN** 系统记录适配器调用审计事件
- **THEN** 输入摘要 MUST 使用患者标识、就诊标识和能力名称等最小必要字段
- **AND** 输入摘要 MUST NOT 记录未脱敏姓名、证件号、联系方式或完整病历文本

### Requirement: Adapter foundation must support replacement by real systems
系统 MUST 通过适配器基础契约隔离业务场景和真实外部系统接口，业务场景 MUST NOT 直接依赖真实系统 SDK、HTTP 客户端或数据库连接。

#### Scenario: Replace in-memory adapter with real adapter
- **WHEN** 后续将内存医保接口适配器替换为真实医保接口适配器
- **THEN** 业务场景调用代码 MUST 保持统一契约不变
- **AND** 新适配器 MUST 复用统一异常、审计、脱敏和权限钩子

### Requirement: Adapter outputs must respect desensitization and permissions
系统 MUST 在适配器输出进入 API 响应前执行最小必要字段和敏感信息脱敏策略。

#### Scenario: Adapter returns patient sensitive fields
- **WHEN** 适配器返回患者姓名、证件号、联系方式或其他敏感字段
- **THEN** 系统 MUST 根据用户角色过滤字段并脱敏
- **AND** API 响应 MUST NOT 暴露角色不可见字段

### Requirement: Adapter failures must integrate with runtime degradation
系统 MUST 将适配器失败结果传递给运行时调度与响应组装逻辑，使最终导办结果能够展示降级状态、受影响来源和不确定性提示。

#### Scenario: Adapter timeout produces degraded guidance
- **WHEN** 编排步骤调用业务适配器发生超时且没有可用替代数据源
- **THEN** workflow MUST 记录该步骤失败
- **AND** API 响应 MUST 包含 degraded 状态或不确定性提示
- **AND** 审计视图 MUST 展示该适配器调用失败原因
