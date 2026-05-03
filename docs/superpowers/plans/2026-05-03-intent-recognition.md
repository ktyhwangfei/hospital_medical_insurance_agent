# Intent Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将硬编码关键词匹配升级为 LLM 驱动的智能意图识别，支持结构化输出、置信度评分、实体提取，保持向后兼容。

**Architecture:** 自底向上四阶段实施——Phase 1 定义数据模型和配置，Phase 2 实现 LLM 解析器和降级策略，Phase 3 集成到路由层，Phase 4 文档收尾。每阶段独立可测试。

**Tech Stack:** Python 3.12, Pydantic, FastAPI, OpenAI-compatible API (DeepSeek)

---

## File Structure

| 文件 | 职责 | Phase |
|------|------|-------|
| `src/runtime/intent/models.py` | IntentResult Pydantic 模型 | 1 |
| `src/runtime/intent/registry.py` | 意图注册表（意图列表、优先级、查询） | 1 |
| `src/config/model_routing.py` | 新增 intent_recognition 场景路由 | 1 |
| `src/runtime/intent/prompts.py` | LLM 提示词模板 | 2 |
| `src/runtime/intent/parser.py` | parse_intent 核心函数（LLM + 降级） | 2 |
| `src/runtime/intent/service.py` | detect_intent 向后兼容包装 | 2 |
| `src/runtime/intent/__init__.py` | 模块导出 | 3 |
| `src/runtime/api/routes.py` | /chat 端点集成 IntentResult | 3 |
| `src/tests/unit/test_intent_models.py` | IntentResult 单元测试 | 1 |
| `src/tests/unit/test_intent_registry.py` | 注册表单元测试 | 1 |
| `src/tests/unit/test_intent_parser.py` | 解析器单元测试 | 2 |
| `src/tests/integration/test_intent_routing.py` | 路由集成测试 | 3 |

---

## Phase 1: 基础结构

### Task 1: IntentResult Pydantic 模型

**Files:**
- Create: `src/runtime/intent/models.py`
- Test: `src/tests/unit/test_intent_models.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_intent_models.py
from src.runtime.intent.models import IntentResult


def test_intent_result_has_required_fields():
    result = IntentResult(
        intent='settlement_exception_guidance',
        confidence=0.9,
        entities={'patient_id': 'P001'},
        citations=['LLM推理'],
        raw_message='结算失败',
    )
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.9
    assert result.entities == {'patient_id': 'P001'}
    assert result.citations == ['LLM推理']
    assert result.raw_message == '结算失败'


def test_intent_result_defaults():
    result = IntentResult(
        intent='unknown',
        confidence=0.5,
        raw_message='test',
    )
    assert result.entities == {}
    assert result.citations == []


def test_intent_result_confidence_bounds():
    result = IntentResult(intent='test', confidence=0.0, raw_message='test')
    assert result.confidence == 0.0
    result = IntentResult(intent='test', confidence=1.0, raw_message='test')
    assert result.confidence == 1.0


def test_intent_result_model_dump():
    result = IntentResult(intent='test', confidence=0.5, raw_message='test')
    data = result.model_dump()
    assert isinstance(data, dict)
    assert 'intent' in data
    assert 'confidence' in data
    assert 'entities' in data
    assert 'citations' in data
    assert 'raw_message' in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/unit/test_intent_models.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.runtime.intent.models'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/intent/models.py
from typing import Any

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    raw_message: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/unit/test_intent_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/runtime/intent/models.py src/tests/unit/test_intent_models.py
git commit -m "feat: add IntentResult Pydantic model"
```

---

### Task 2: 意图注册表

**Files:**
- Create: `src/runtime/intent/registry.py`
- Test: `src/tests/unit/test_intent_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_intent_registry.py
from src.runtime.intent.registry import (
    get_intent_by_id,
    get_intent_registry,
)


def test_registry_has_two_intents():
    registry = get_intent_registry()
    assert len(registry) == 2


def test_registry_contains_settlement_intent():
    entry = get_intent_by_id('settlement_exception_guidance')
    assert entry is not None
    assert entry.intent_id == 'settlement_exception_guidance'
    assert entry.priority == 1


def test_registry_contains_pre_discharge_intent():
    entry = get_intent_by_id('pre_discharge_quality_control')
    assert entry is not None
    assert entry.intent_id == 'pre_discharge_quality_control'
    assert entry.priority == 2


def test_registry_returns_none_for_unknown():
    entry = get_intent_by_id('nonexistent_intent')
    assert entry is None


def test_registry_entries_have_examples():
    for entry in get_intent_registry():
        assert len(entry.examples) > 0
        assert all(isinstance(e, str) for e in entry.examples)


def test_registry_priority_ordering():
    registry = get_intent_registry()
    priorities = [e.priority for e in registry]
    assert priorities == sorted(priorities)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/unit/test_intent_registry.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.runtime.intent.registry'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/intent/registry.py
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/unit/test_intent_registry.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/runtime/intent/registry.py src/tests/unit/test_intent_registry.py
git commit -m "feat: add intent registry with two intents"
```

---

### Task 3: 模型路由配置

**Files:**
- Modify: `src/config/model_routing.py`

- [ ] **Step 1: Read current config**

Read `src/config/model_routing.py` to understand current structure.

- [ ] **Step 2: Add intent_recognition scene**

```python
# src/config/model_routing.py — 在 ROUTING_TABLE 中新增一行
ROUTING_TABLE = {
    ("settlement_exception_guidance", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("pre_discharge_quality_control", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("intent_recognition", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("default", ModelType.LLM): "deepseek-ai/DeepSeek-V3.2",
    ("default", ModelType.EMBEDDING): "text-embedding-3-small",
}

# MODEL_PARAMS 中新增（注意：按 model_name 查找，影响所有使用该模型的场景）
MODEL_PARAMS = {
    "deepseek-ai/DeepSeek-V3.2": {"temperature": 0.1, "max_tokens": 512},
    "deepseek-ai/DeepSeek-V4-Flash": {"temperature": 0.3, "max_tokens": 2048},
    "Pro/zai-org/GLM-5": {"temperature": 0.5, "max_tokens": 1024},
}
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `python -m pytest src/tests -v`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add src/config/model_routing.py
git commit -m "feat: add intent_recognition scene to model routing config"
```

---

## Phase 2: LLM 解析器 + 降级策略

### Task 4: 提示词模板

**Files:**
- Create: `src/runtime/intent/prompts.py`
- Test: `src/tests/unit/test_intent_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_intent_prompts.py
from src.runtime.intent.prompts import build_intent_prompt
from src.runtime.intent.registry import get_intent_registry


def test_prompt_contains_message():
    registry = get_intent_registry()
    prompt = build_intent_prompt('结算失败', registry)
    assert '结算失败' in prompt


def test_prompt_contains_all_intent_ids():
    registry = get_intent_registry()
    prompt = build_intent_prompt('test', registry)
    for entry in registry:
        assert entry.intent_id in prompt


def test_prompt_contains_intent_descriptions():
    registry = get_intent_registry()
    prompt = build_intent_prompt('test', registry)
    for entry in registry:
        assert entry.description in prompt


def test_prompt_contains_json_format_instruction():
    registry = get_intent_registry()
    prompt = build_intent_prompt('test', registry)
    assert '"intent"' in prompt
    assert '"confidence"' in prompt
    assert '"entities"' in prompt
    assert '"citations"' in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/unit/test_intent_prompts.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.runtime.intent.prompts'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/intent/prompts.py
from src.runtime.intent.registry import IntentEntry


def build_intent_prompt(message: str, registry: list[IntentEntry]) -> str:
    intent_lines = []
    for entry in registry:
        examples = '、'.join(entry.examples)
        intent_lines.append(
            f'- {entry.intent_id}: {entry.description}（示例：{examples}）'
        )
    intents_text = '\n'.join(intent_lines)

    return (
        '你是医保智能体的意图识别模块。请分析用户消息，返回 JSON。\n\n'
        '可用意图：\n'
        f'{intents_text}\n\n'
        f'用户消息：{message}\n\n'
        '返回格式（仅返回 JSON，不要其他内容）：\n'
        '{"intent": "<意图标识>", "confidence": <0-1>, "entities": {}, '
        '"citations": ["LLM意图推理"]}'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/unit/test_intent_prompts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/runtime/intent/prompts.py src/tests/unit/test_intent_prompts.py
git commit -m "feat: add intent recognition prompt template"
```

---

### Task 5: parse_intent 核心函数（LLM + 降级）

**Files:**
- Create: `src/runtime/intent/parser.py`
- Test: `src/tests/unit/test_intent_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_intent_parser.py
import json
from unittest.mock import MagicMock, patch

from src.runtime.intent.models import IntentResult
from src.runtime.intent.parser import parse_intent


def _mock_model_response(content: str):
    mock = MagicMock()
    mock.content = content
    mock.model_name = 'test-model'
    mock.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    mock.finish_reason = 'stop'
    return mock


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_via_llm_success(mock_gateway_cls):
    llm_output = json.dumps({
        'intent': 'settlement_exception_guidance',
        'confidence': 0.95,
        'entities': {'patient_id': 'P001'},
        'citations': ['LLM推理'],
    })
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response(llm_output)
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('张三的医保结算失败了')

    assert isinstance(result, IntentResult)
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.95
    assert result.entities.get('patient_id') == 'P001'
    assert result.raw_message == '张三的医保结算失败了'


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_llm_timeout_fallback(mock_gateway_cls):
    mock_gateway = MagicMock()
    mock_gateway.generate.side_effect = TimeoutError('timeout')
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('结算失败')

    assert isinstance(result, IntentResult)
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.5
    assert '关键词匹配降级' in result.citations


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_llm_invalid_json_fallback(mock_gateway_cls):
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response('not json')
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('结算失败')

    assert isinstance(result, IntentResult)
    assert result.intent == 'settlement_exception_guidance'
    assert result.confidence == 0.5


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_unknown_intent(mock_gateway_cls):
    llm_output = json.dumps({
        'intent': 'unknown',
        'confidence': 0.3,
        'entities': {},
        'citations': ['无匹配'],
    })
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response(llm_output)
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('今天天气怎么样')

    assert result.intent == 'unknown'


@patch('src.runtime.intent.parser.ModelGateway')
def test_parse_intent_llm_invalid_intent_id_fallback(mock_gateway_cls):
    llm_output = json.dumps({
        'intent': 'nonexistent_intent',
        'confidence': 0.9,
        'entities': {},
        'citations': ['LLM'],
    })
    mock_gateway = MagicMock()
    mock_gateway.generate.return_value = _mock_model_response(llm_output)
    mock_gateway_cls.return_value = mock_gateway

    result = parse_intent('test')

    assert result.intent == 'unknown'


def test_parse_intent_keyword_fallback_settlement():
    with patch('src.runtime.intent.parser.ModelGateway') as mock_cls:
        mock_cls.side_effect = Exception('model unavailable')
        result = parse_intent('结算失败怎么办')
        assert result.intent == 'settlement_exception_guidance'
        assert result.confidence == 0.5


def test_parse_intent_keyword_fallback_pre_discharge():
    with patch('src.runtime.intent.parser.ModelGateway') as mock_cls:
        mock_cls.side_effect = Exception('model unavailable')
        result = parse_intent('出院前检查')
        assert result.intent == 'pre_discharge_quality_control'
        assert result.confidence == 0.5


def test_parse_intent_keyword_fallback_unknown():
    with patch('src.runtime.intent.parser.ModelGateway') as mock_cls:
        mock_cls.side_effect = Exception('model unavailable')
        result = parse_intent('今天天气')
        assert result.intent == 'unknown'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/unit/test_intent_parser.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.runtime.intent.parser'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/intent/parser.py
import json
import logging

from src.model_service import Message, ModelGateway
from src.runtime.intent.models import IntentResult
from src.runtime.intent.prompts import build_intent_prompt
from src.runtime.intent.registry import get_intent_by_id, get_intent_registry

logger = logging.getLogger(__name__)


def parse_intent(message: str) -> IntentResult:
    try:
        return _parse_via_llm(message)
    except Exception:
        logger.warning('intent_llm_fallback', exc_info=True)
        return _parse_via_keywords(message)


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


def _parse_llm_json(content: str, raw_message: str) -> IntentResult:
    try:
        data = json.loads(content)
        intent = data.get('intent', 'unknown')
        if get_intent_by_id(intent) is None and intent != 'unknown':
            intent = 'unknown'
        return IntentResult(
            intent=intent,
            confidence=float(data.get('confidence', 0.5)),
            entities=data.get('entities', {}),
            citations=data.get('citations', []),
            raw_message=raw_message,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/unit/test_intent_parser.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/runtime/intent/parser.py src/tests/unit/test_intent_parser.py
git commit -m "feat: add parse_intent with LLM and keyword fallback"
```

---

### Task 6: 向后兼容 — detect_intent 改造

**Files:**
- Modify: `src/runtime/intent/service.py`
- Test: `src/tests/unit/test_intent_service_compat.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/unit/test_intent_service_compat.py
from unittest.mock import patch

from src.runtime.intent.service import detect_intent


def test_detect_intent_returns_string():
    with patch('src.runtime.intent.service.parse_intent') as mock_parse:
        mock_parse.return_value = MagicMock(intent='settlement_exception_guidance')
        result = detect_intent('结算失败')
        assert isinstance(result, str)
        assert result == 'settlement_exception_guidance'


def test_detect_intent_backward_compat_keywords():
    """确保原有关键词匹配行为不变"""
    assert detect_intent('结算失败') == 'settlement_exception_guidance'
    assert detect_intent('医保结算') == 'settlement_exception_guidance'
    assert detect_intent('出院前') == 'pre_discharge_quality_control'
    assert detect_intent('医保风险') == 'pre_discharge_quality_control'
    assert detect_intent('今天天气') == 'unknown'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/unit/test_intent_service_compat.py -v`
Expected: FAIL (import error or function signature mismatch)

- [ ] **Step 3: Write minimal implementation**

```python
# src/runtime/intent/service.py
from src.runtime.intent.parser import parse_intent


def detect_intent(message: str) -> str:
    result = parse_intent(message)
    return result.intent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/unit/test_intent_service_compat.py -v`
Expected: 2 passed

- [ ] **Step 5: Run all existing tests to confirm no regression**

Run: `python -m pytest src/tests -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/runtime/intent/service.py src/tests/unit/test_intent_service_compat.py
git commit -m "refactor: detect_intent delegates to parse_intent"
```

---

## Phase 3: 路由集成

### Task 7: 模块导出

**Files:**
- Modify: `src/runtime/intent/__init__.py`

- [ ] **Step 1: Update __init__.py**

```python
# src/runtime/intent/__init__.py
from src.runtime.intent.models import IntentResult
from src.runtime.intent.parser import parse_intent
from src.runtime.intent.service import detect_intent

__all__ = ['IntentResult', 'parse_intent', 'detect_intent']
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from src.runtime.intent import parse_intent, IntentResult, detect_intent; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/runtime/intent/__init__.py
git commit -m "feat: export parse_intent and IntentResult from intent module"
```

---

### Task 8: routes.py 集成

**Files:**
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/integration/test_intent_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# src/tests/integration/test_intent_routing.py
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _chat_payload(message: str = '结算失败'):
    return {
        'user_id': 'U001',
        'role': 'physician',
        'message': message,
        'patient_id': 'P001',
        'encounter_id': 'E001',
    }


def test_chat_uses_parse_intent():
    app = create_app()
    client = TestClient(app)
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json=_chat_payload())
    assert response.status_code == 200
    data = response.json()
    assert data['status'] != 'error'


def test_chat_unknown_intent():
    app = create_app()
    client = TestClient(app)
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json=_chat_payload('今天天气'))
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'not_implemented'


def test_chat_response_contains_citations():
    app = create_app()
    client = TestClient(app)
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json=_chat_payload())
    assert response.status_code == 200
    data = response.json()
    assert 'citations' in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/integration/test_intent_routing.py -v`
Expected: FAIL or tests pass but don't exercise new code path

- [ ] **Step 3: Update routes.py**

```python
# src/runtime/api/routes.py — 修改 chat() 函数

# 替换 import
from src.runtime.intent.parser import parse_intent

# 替换 chat() 函数体中的意图识别部分
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
            raise HTTPException(
                status_code=403,
                detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}),
            )
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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/integration/test_intent_routing.py -v`
Expected: 3 passed

- [ ] **Step 5: Run all existing tests to confirm no regression**

Run: `python -m pytest src/tests -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/runtime/api/routes.py src/tests/integration/test_intent_routing.py
git commit -m "feat: integrate parse_intent into /chat endpoint"
```

---

## Phase 4: 收尾

### Task 9: 文档更新

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Update AGENTS.md**

在 `### 目录职责映射` 表格中更新 `runtime/intent/` 行：

```
| `runtime/intent/` | 意图识别：LLM 解析 + 关键词降级 + 注册表 | 已实现（intent-parsing, intent-routing） |
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest src/tests -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update intent recognition status in AGENTS.md"
```

---

## Verification Checklist

| 检查项 | 命令 | 预期 |
|--------|------|------|
| 全量测试通过 | `python -m pytest src/tests -v` | All pass |
| 向后兼容 | `python -c "from src.runtime.intent import detect_intent; print(detect_intent('结算失败'))"` | `settlement_exception_guidance` |
| LLM 路径可用 | 运行 test_intent_parser.py 中 LLM 成功测试 | PASS |
| 降级路径可用 | 运行 test_intent_parser.py 中降级测试 | PASS |
| /chat 端点可用 | 运行 test_intent_routing.py | PASS |
