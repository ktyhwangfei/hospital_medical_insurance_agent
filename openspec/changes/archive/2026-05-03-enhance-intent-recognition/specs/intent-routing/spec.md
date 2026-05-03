## ADDED Requirements

### Requirement: Intent-to-scenario routing
系统 SHALL 根据识别的意图路由到对应的业务场景处理函数。

#### Scenario: Route to settlement exception guidance
- **WHEN** 意图为 "settlement_exception_guidance"
- **THEN** 调用 `guide_settlement_exception(patient_id, encounter_id)` 处理

#### Scenario: Route to pre-discharge quality control
- **WHEN** 意图为 "pre_discharge_quality_control"
- **THEN** 调用 `run_pre_discharge_qc(patient_id, encounter_id)` 处理

### Requirement: Unknown intent handling
系统 SHALL 优雅处理未知意图，返回 `not_implemented` 状态而非抛出异常。

#### Scenario: Unknown intent returns not_implemented
- **WHEN** 用户输入无法识别意图的消息 "今天天气怎么样"
- **THEN** 系统返回 AgentResponse(status='not_implemented')

#### Scenario: LLM parsing failure returns not_implemented
- **WHEN** LLM 解析失败且关键词匹配也无法识别
- **THEN** 系统返回 AgentResponse(status='not_implemented')

### Requirement: Intent priority ordering
系统 SHALL 定义意图优先级，当消息匹配多个意图时返回最高优先级意图。

#### Scenario: Priority defined in registry
- **WHEN** 意图注册表中定义了意图优先级
- **THEN** parse_intent 返回优先级最高的意图

#### Scenario: settlement_exception_guidance has higher priority
- **WHEN** 消息同时匹配 settlement_exception_guidance 和 pre_discharge_quality_control
- **THEN** 系统返回 settlement_exception_guidance

### Requirement: Model routing for intent recognition
系统 SHALL 使用专用的 `intent_recognition` 场景调用模型服务。

#### Scenario: Intent recognition uses dedicated scene
- **WHEN** 调用 ModelGateway 进行意图识别
- **THEN** 使用 scene="intent_recognition"，模型配置为低温度（0.1）确保输出稳定

#### Scenario: Fallback to default scene
- **WHEN** intent_recognition 场景未配置
- **THEN** 回退到 ("default", ModelType.LLM) 的模型配置
