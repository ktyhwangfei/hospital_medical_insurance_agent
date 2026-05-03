# Intent Recognition Development Plan

## Overview

基于 OpenSpec 变更 `enhance-intent-recognition` 的四阶段自底向上开发计划。将硬编码关键词匹配升级为 LLM 驱动的智能意图识别，保持向后兼容。

## Strategy: 自底向上（方案 A）

从基础结构开始逐层构建，每阶段独立可测试，风险最低。

```
Phase 1 (基础) → Phase 2 (核心) → Phase 3 (集成) → Phase 4 (收尾)
  models.py        parser.py        routes.py        AGENTS.md
  registry.py      prompts.py       __init__.py      全量测试
  model_routing.py service.py改造    实体提取
```

---

## Phase 1: 基础结构

**目标**：定义数据模型、意图注册表、模型路由配置。不改变运行时行为。

### 产出文件

| 文件 | 说明 |
|------|------|
| `src/runtime/intent/models.py` | IntentResult Pydantic 模型 |
| `src/runtime/intent/registry.py` | 意图注册表 |
| `src/config/model_routing.py` | 新增 intent_recognition 场景 |

### IntentResult 模型

```python
from typing import Any
from pydantic import BaseModel, Field

class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    raw_message: str
```

### 意图注册表

```python
from dataclasses import dataclass, field

@dataclass
class IntentEntry:
    intent_id: str
    description: str
    examples: list[str]
    priority: int
    scenario_route: str

INTENT_REGISTRY: list[IntentEntry] = [
    IntentEntry(
        intent_id='settlement_exception_guidance',
        description='医保结算失败、结算异常相关问题',
        examples=['结算失败怎么办', '医保结算报错', '结算异常'],
        priority=1,
        scenario_route='guide_settlement_exception',
    ),
    IntentEntry(
        intent_id='pre_discharge_quality_control',
        description='出院前联合质控、医保风险检查',
        examples=['出院前检查', '医保风险', '质控问题'],
        priority=2,
        scenario_route='run_pre_discharge_qc',
    ),
]

def get_intent_registry() -> list[IntentEntry]:
    return INTENT_REGISTRY

def get_intent_by_id(intent_id: str) -> IntentEntry | None:
    return next((e for e in INTENT_REGISTRY if e.intent_id == intent_id), None)
```

### 模型路由配置

在 `src/config/model_routing.py` 中新增：

```python
# ROUTING_TABLE 新增
("intent_recognition", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",

# MODEL_PARAMS 新增（注意：MODEL_PARAMS 按 model_name 查找，会影响所有使用该模型的场景）
# 当前 DeepSeek-V3.2 不在 MODEL_PARAMS 中（使用默认值 temperature=0.7, max_tokens=2048）
# 新增后所有使用 DeepSeek-V3.2 的场景都会使用 temperature=0.1
# 如果需要场景隔离，需修改 ModelRouter 支持 per-scene 参数（不在本次范围内）
"deepseek-ai/DeepSeek-V3.2": {"temperature": 0.1, "max_tokens": 512},
```

**已知限制**：`MODEL_PARAMS` 按模型名而非场景名查找。新增的低温度配置会影响 `settlement_exception_guidance` 和 `pre_discharge_quality_control` 场景。MVP 阶段可接受（低温度对这些场景也有利），后续如需隔离可扩展 `ModelRouter` 支持 per-scene 参数。

### 验证

- IntentResult 序列化/反序列化测试
- 注册表查询测试（get_intent_by_id、优先级排序）
- 模型路由 resolve 测试（intent_recognition 场景）

---

## Phase 2: LLM 解析器 + 降级策略

**目标**：实现核心意图解析逻辑，包含 LLM 调用、JSON 解析、关键词降级。

### 产出文件

| 文件 | 说明 |
|------|------|
| `src/runtime/intent/prompts.py` | 提示词模板 |
| `src/runtime/intent/parser.py` | parse_intent 核心函数 |
| `src/runtime/intent/service.py` | 改造 detect_intent |

### parse_intent 流程

```python
def parse_intent(message: str) -> IntentResult:
    try:
        return _parse_via_llm(message)
    except Exception:
        return _parse_via_keywords(message)
```

### LLM 调用

```python
def _parse_via_llm(message: str) -> IntentResult:
    gateway = ModelGateway()
    registry = get_intent_registry()
    prompt = build_intent_prompt(message, registry)
    messages = [Message(role='user', content=prompt)]
    response = gateway.generate(
        messages=messages,
        model_type='llm',
        scene='intent_recognition',
    )
    return _parse_llm_json(response.content, message)
```

### 提示词模板

```
你是医保智能体的意图识别模块。请分析用户消息，返回 JSON。

可用意图：
{动态生成：intent_id - description，含 examples}

用户消息：{message}

返回格式（仅返回 JSON，不要其他内容）：
{"intent": "<意图标识>", "confidence": <0-1>, "entities": {}, "citations": ["LLM意图推理"]}
```

### JSON 解析与降级

```python
import json

def _parse_llm_json(content: str, raw_message: str) -> IntentResult:
    try:
        data = json.loads(content)
        intent = data.get('intent', 'unknown')
        # 验证 intent 是否在注册表中
        if get_intent_by_id(intent) is None and intent != 'unknown':
            intent = 'unknown'
        return IntentResult(
            intent=intent,
            confidence=float(data.get('confidence', 0.5)),
            entities=data.get('entities', {}),
            citations=data.get('citations', []),
            raw_message=raw_message,
        )
    except (json.JSONDecodeError, ValueError):
        return _parse_via_keywords(raw_message)

def _parse_via_keywords(message: str) -> IntentResult:
    if '结算失败' in message or '医保结算' in message:
        intent = 'settlement_exception_guidance'
    elif '出院前' in message or '医保风险' in message:
        intent = 'pre_discharge_quality_control'
    else:
        intent = 'unknown'
    return IntentResult(
        intent=intent,
        confidence=0.5,
        entities={},
        citations=['关键词匹配降级'],
        raw_message=message,
    )
```

### 向后兼容

```python
# service.py
from src.runtime.intent.parser import parse_intent

def detect_intent(message: str) -> str:
    result = parse_intent(message)
    return result.intent
```

### 验证

- LLM 成功路径：mock ModelGateway，验证 IntentResult 字段
- LLM 超时路径：mock 抛出异常，验证降级到关键词匹配
- JSON 解析失败路径：mock 返回非 JSON，验证降级
- 向后兼容：detect_intent 返回字符串

---

## Phase 3: 路由集成 + 实体提取

**目标**：将 IntentResult 接入 `/chat` 端点，实体提取逻辑落地，citations 传递到 AgentResponse。

### 产出文件

| 文件 | 说明 |
|------|------|
| `src/runtime/intent/__init__.py` | 导出 parse_intent, IntentResult |
| `src/runtime/intent/parser.py` | 增强实体提取 |
| `src/runtime/api/routes.py` | chat() 使用 parse_intent |

### routes.py 改造

```python
from src.runtime.intent.parser import parse_intent

@router.post('/chat')
def chat(request: ChatRequest) -> AgentResponse:
    missing = missing_context_fields(request.patient_id, request.encounter_id)
    if missing:
        return AgentResponse(status='needs_clarification', missing_fields=missing)
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)

    intent_result = parse_intent(request.message)
    scenario = intent_result.intent

    if scenario in ('settlement_exception_guidance', 'pre_discharge_quality_control'):
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail(...))
        handler = (guide_settlement_exception if scenario == 'settlement_exception_guidance'
                   else run_pre_discharge_qc)
        response = handler(request.patient_id, request.encounter_id)
        response.citations.extend(
            {'source': c, 'type': 'intent_recognition'} for c in intent_result.citations
        )
        return response

    return AgentResponse(
        status='not_implemented',
        uncertainties=[f'未识别的意图: {request.message}'],
        citations=[{'source': c, 'type': 'intent_recognition'} for c in intent_result.citations],
    )
```

### 实体提取增强

```python
import re

def _extract_entities_regex(message: str) -> dict[str, Any]:
    entities: dict[str, Any] = {}
    patient_match = re.search(r'P\d{3}', message)
    if patient_match:
        entities['patient_id'] = patient_match.group()
    name_match = re.search(r'患者(\S{2,4})', message)
    if name_match:
        entities['patient_name'] = name_match.group(1)
    error_match = re.search(r'错误码[：:]?\s*(\w+)', message)
    if error_match:
        entities['error_code'] = error_match.group(1)
    return entities

def _parse_via_llm(message: str) -> IntentResult:
    # ... existing LLM call ...
    llm_result = _parse_llm_json(response.content, message)
    # 合并正则提取的实体
    regex_entities = _extract_entities_regex(message)
    merged_entities = {**regex_entities, **llm_result.entities}
    llm_result.entities = merged_entities
    return llm_result
```

### __init__.py 导出

```python
from src.runtime.intent.parser import parse_intent
from src.runtime.intent.models import IntentResult
from src.runtime.intent.service import detect_intent

__all__ = ['parse_intent', 'IntentResult', 'detect_intent']
```

### 验证

- 集成测试：/chat 端点 3 条路径（成功路由、未知意图、权限拒绝）
- 实体提取测试：patient_id、patient_name、error_code
- Citations 传递测试：AgentResponse.citations 包含 intent_recognition 来源

---

## Phase 4: 收尾 — 文档 + 回归验证

**目标**：更新文档，全量测试确认无回归。

### 产出

- `AGENTS.md` 更新 runtime/intent 描述
- `python -m pytest src/tests -v` 全量通过
- 手动验证 3 条路径

### 验证清单

| 输入 | 预期 intent | 预期 confidence |
|------|-------------|-----------------|
| "结算失败" | settlement_exception_guidance | ≥ 0.8 |
| "出院前检查" | pre_discharge_quality_control | ≥ 0.8 |
| "今天天气" | unknown | - |

---

## File Change Summary

| 文件 | Phase | 操作 |
|------|-------|------|
| `src/runtime/intent/models.py` | 1 | 新增 |
| `src/runtime/intent/registry.py` | 1 | 新增 |
| `src/config/model_routing.py` | 1 | 修改 |
| `src/runtime/intent/prompts.py` | 2 | 新增 |
| `src/runtime/intent/parser.py` | 2 | 新增 |
| `src/runtime/intent/service.py` | 2 | 修改 |
| `src/runtime/intent/__init__.py` | 3 | 修改 |
| `src/runtime/api/routes.py` | 3 | 修改 |
| `AGENTS.md` | 4 | 修改 |
| `src/tests/unit/test_intent_*.py` | 1-3 | 新增 |
