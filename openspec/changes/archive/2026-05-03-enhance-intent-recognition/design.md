## Context

当前意图识别位于 `runtime/intent/service.py`，采用硬编码关键词匹配（6行代码），仅支持 `settlement_exception_guidance` 和 `pre_discharge_quality_control` 两种意图。业务流向：`runtime/api → runtime/intent → security/risk_control → security/authorization → business_scenarios`。

系统定位为 AI 导办与协同中枢，意图识别是智能编排的核心入口。现有 LLM 模型服务已就绪（`model_service/`），可直接复用。

## Goals / Non-Goals

**Goals:**
- 使用 LLM 进行智能意图识别，支持自然语言理解
- 输出结构化意图结果（意图、实体、置信度、来源引用）
- 保持 `detect_intent(message) -> str` 接口向后兼容
- 支持未知意图的优雅降级

**Non-Goals:**
- 不支持多意图识别（当前架构单路由，后续迭代）
- 不实现意图学习/训练（后续迭代）
- 不改变现有业务场景的内部逻辑
- 不引入外部 NLP 服务（使用现有模型服务）
- 不实现实时意图对话（单轮识别）

## Decisions

### 决策1：使用 LLM 进行意图识别

**选择**：调用现有模型服务（`ModelGateway`）进行意图识别

**理由**：
- 复用现有基础设施，无需引入新依赖
- LLM 能理解自然语言变体和上下文
- 支持结构化输出（prompt 约束）

**备选方案**：
- 增强关键词匹配：维护成本高，无法处理复杂查询
- 引入 NLP 库（spaCy/NLTK）：增加依赖，需训练模型

### 决策2：结构化意图输出格式

**选择**：定义 `IntentResult` Pydantic BaseModel，包含 `intent`、`confidence`、`entities`、`citations`

**理由**：
- 项目约定使用 Pydantic BaseModel（见 `schemas.py`），禁止裸 dict 返回
- 符合项目规范（AI 输出必须携带 citations）
- 支持置信度评分，便于降级策略
- 实体提取支持后续场景参数化

**格式**：
```python
from pydantic import BaseModel, Field

class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    raw_message: str
```

### 决策3：意图注册表机制

**选择**：采用配置驱动的意图注册表，定义意图标识、描述、示例、路由映射

**理由**：
- 解耦意图定义与识别逻辑
- 便于扩展新意图（无需修改识别代码）
- 支持 LLM 提示词自动生成

**位置**：`src/runtime/intent/registry.py`

### 决策4：向后兼容策略

**选择**：保持 `detect_intent(message) -> str` 签名，内部调用新逻辑

**理由**：
- 最小化对 `routes.py` 的修改
- 现有测试无需重写
- 渐进式迁移

**实现**：
```python
def detect_intent(message: str) -> str:
    result = parse_intent(message)
    return result.intent
```

### 决策5：降级策略

**选择**：LLM 识别失败时回退到关键词匹配，置信度标记为 0.5

**理由**：
- 保证系统可用性（模型服务不可用时）
- 降级结果可追踪（低置信度）

### 决策6：ModelGateway 场景配置

**选择**：新增 `intent_recognition` 场景，复用现有 DeepSeek 模型，使用低温度（0.1）确保输出稳定

**理由**：
- 意图识别需要确定性输出，低温度减少随机性
- 复用现有模型，无需额外配置
- 在 `config/model_routing.py` 的 `ROUTING_TABLE` 和 `MODEL_PARAMS` 中注册

**配置**：
```python
# ROUTING_TABLE 新增
("intent_recognition", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",

# MODEL_PARAMS 新增
"deepseek-ai/DeepSeek-V3.2": {"temperature": 0.1, "max_tokens": 512},
```

### 决策7：JSON 输出约束

**选择**：通过 prompt engineering 约束 LLM 输出 JSON，不依赖 OpenAI `response_format`

**理由**：
- 现有 `ModelGateway` 不支持 `response_format` 参数
- 在提示词中明确要求 JSON 输出并提供 schema 示例
- 解析失败时降级到关键词匹配

**实现**：
```
请分析以下用户消息，返回 JSON 格式：
{"intent": "<意图标识>", "confidence": <0-1>, "entities": {<实体>}, "citations": ["<来源>"]}

可用意图：{意图列表}
用户消息：{message}
```

## Risks / Trade-offs

- **[风险] LLM 调用延迟** → 意图识别 scene 使用低 max_tokens（512），控制响应时间
- **[风险] LLM 输出不稳定** → prompt 约束 + 低温度 + 解析失败降级
- **[风险] 意图识别成本** → 单次调用，无缓存（MVP 阶段）
- **[权衡] 准确性 vs 延迟** → 接受一定延迟以换取更好的识别效果
- **[权衡] 复杂度 vs 灵活性** → 引入注册表机制增加复杂度，但提升扩展性

## Migration Plan

1. 新增意图注册表和解析器（不影响现有逻辑）
2. 修改 `detect_intent` 内部实现，保持接口不变
3. 添加单元测试和集成测试
4. 验证所有现有场景仍正常工作
5. 逐步迁移业务场景使用新意图结果

## Open Questions

- 是否需要支持意图置信度阈值配置？
- 是否需要支持意图识别的审计日志？
