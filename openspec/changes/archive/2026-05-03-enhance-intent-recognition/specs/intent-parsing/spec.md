## ADDED Requirements

### Requirement: Intent parsing via LLM
系统 SHALL 使用 LLM 解析用户消息，提取意图、实体和置信度。

#### Scenario: Successful LLM parsing
- **WHEN** 用户输入消息 "张三的医保结算失败了，错误码是401"
- **THEN** 系统返回 IntentResult，包含 intent="settlement_exception_guidance"、confidence≥0.8、entities 包含 patient_name="张三" 和 error_code="401"、citations 非空

#### Scenario: LLM timeout fallback
- **WHEN** LLM 调用超时或抛出异常
- **THEN** 系统降级到关键词匹配，返回 confidence=0.5 的 IntentResult，intent 仍为正确匹配的意图

### Requirement: Structured intent output
系统 SHALL 返回 Pydantic IntentResult 模型，包含 intent、confidence、entities、citations、raw_message 字段。

#### Scenario: Valid IntentResult structure
- **WHEN** 解析任意用户消息
- **THEN** 返回的 IntentResult 包含：intent (字符串，属于已注册意图之一或 "unknown")、confidence (0-1 浮点数)、entities (字典)、citations (列表)、raw_message (原始消息)

#### Scenario: IntentResult is Pydantic model
- **WHEN** 调用 parse_intent 函数
- **THEN** 返回值是 IntentResult 的实例，支持 .model_dump() 序列化

### Requirement: Confidence scoring
系统 SHALL 为每个识别结果提供置信度评分，范围 0-1。

#### Scenario: High confidence for explicit intent keywords
- **WHEN** 用户输入包含已注册意图的明确关键词（如 "结算失败"）
- **THEN** 系统返回 confidence ≥ 0.8

#### Scenario: Fallback confidence for keyword matching
- **WHEN** LLM 调用失败，降级到关键词匹配
- **THEN** 系统返回 confidence = 0.5

### Requirement: Entity extraction
系统 SHALL 从用户消息中提取与意图相关的实体信息。

#### Scenario: Extract patient identifier
- **WHEN** 用户提到 "患者张三" 或 "P001"
- **THEN** 系统在 entities 中包含 patient_id 或 patient_name 键

#### Scenario: Extract error code
- **WHEN** 用户提到 "错误码401" 或 "报错401"
- **THEN** 系统在 entities 中包含 error_code="401"

#### Scenario: Empty entities for no match
- **WHEN** 用户消息不包含可提取的实体
- **THEN** 系统返回 entities 为空字典 {}

### Requirement: Citation requirement
系统 SHALL 为每个意图识别结果提供来源引用，符合项目规范 "AI 输出必须携带 citations"。

#### Scenario: Include source reference
- **WHEN** 解析用户消息成功
- **THEN** IntentResult.citations 列表非空，包含至少一个来源引用

### Requirement: Backward compatibility
系统 SHALL 保持 `detect_intent(message: str) -> str` 接口签名不变。

#### Scenario: Existing caller works unchanged
- **WHEN** routes.py 调用 `detect_intent("结算失败")`
- **THEN** 返回字符串 "settlement_exception_guidance"，与原有行为一致

#### Scenario: Unknown intent returns "unknown"
- **WHEN** 调用 `detect_intent("今天天气怎么样")`
- **THEN** 返回字符串 "unknown"
