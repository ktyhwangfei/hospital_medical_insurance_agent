## ADDED Requirements

### Requirement: Rule explanation must provide deterministic explanations
系统 MUST 为错误码、医保政策规则、事前审核规则、DRG/DIP 规则和病案质控规则提供确定性解释能力，解释请求 MUST 包含规则类型、规则编码、业务场景、患者或就诊摘要、用户角色和可选证据列表；解释结果 MUST 包含规则含义、适用条件、处理建议、限制说明、影响范围、人工复核提示、引用来源和不确定性。

#### Scenario: Explain settlement error code
- **WHEN** 医保结算异常导办请求解释错误码
- **THEN** 规则解释服务 MUST 返回错误码含义、常见原因和处理建议
- **AND** 解释结果 MUST 包含错误码知识来源引用

#### Scenario: Explain pre-audit rule hit
- **WHEN** 出院前联合质控请求解释事前审核规则命中
- **THEN** 规则解释服务 MUST 返回规则含义、影响范围、建议核查材料和引用来源

#### Scenario: Explain rule with version mismatch
- **WHEN** 规则解释请求中的规则版本与当前知识资产版本不一致
- **THEN** 规则解释服务 MUST 返回版本不匹配提示
- **AND** 解释结果 MUST 包含不确定性和建议人工复核说明

### Requirement: Rule explanation must distinguish guidance from formal decisions
系统 MUST 明确规则解释结果是导办建议或风险提示，不得输出医保正式裁决、DRG/DIP 正式分组结论、病案最终修改结论或申诉最终结论。

#### Scenario: Explain high impact rule
- **WHEN** 规则解释涉及拒付、扣款、分组亏损或病案缺陷风险
- **THEN** 解释结果 MUST 声明需要人工在既有业务系统复核
- **AND** 解释结果 MUST NOT 声称已完成正式裁决或业务变更

#### Scenario: Explanation recommends business verification only
- **WHEN** 规则解释输出处理建议
- **THEN** 建议 MUST 表述为核查、补充材料、复核或在既有系统处理
- **AND** 建议 MUST NOT 表述为系统已执行结算、审核通过、病案已修改或申诉已确认

### Requirement: Rule explanation must integrate retrieved evidence
系统 MUST 支持将 RAG 检索到的政策、院内制度或规则条款作为规则解释证据，并保留引用链路。

#### Scenario: Explain rule with policy evidence
- **WHEN** 规则解释请求包含检索到的政策证据
- **THEN** 规则解释服务 MUST 将证据纳入解释结果
- **AND** 解释结果 MUST 保留原始检索引用

#### Scenario: Conflicting evidence
- **WHEN** 多条证据在适用条件、版本或处理建议上存在冲突
- **THEN** 规则解释服务 MUST 标记证据冲突
- **AND** 最终响应 MUST 包含不确定性和人工复核建议

### Requirement: Rule explanation must handle unknown rules safely
系统 MUST 在规则编码未知、规则版本不匹配或证据不足时返回不确定性提示。

#### Scenario: Unknown rule code
- **WHEN** 规则解释服务收到未知规则编码
- **THEN** 系统 MUST 返回未知规则状态
- **AND** 最终响应 MUST 包含不确定性提示和人工复核建议

#### Scenario: Evidence insufficient for explanation
- **WHEN** 规则解释服务只有规则编码但缺少规则含义、来源证据或适用条件
- **THEN** 系统 MUST 返回证据不足状态
- **AND** 系统 MUST NOT 生成确定性处理结论
