# Security Contracts Runtime Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `fix-security-contracts-and-runtime-decoupling` OpenSpec 变更覆盖的安全契约、流式异常、适配器基础层、运行时执行闭环和审计视图技术债。

**Architecture:** 按阶段推进：先修 P0 安全契约与流式异常，再新增适配器基础层，然后引入运行时上下文与确定性计划，最后接入顺序编排、workflow/task 状态、审计视图、前端和文档验证。实现期间保留现有 `AgentResponse` 顶层字段、现有 API 路由和两个 MVP 场景主响应结构。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、httpx、pytest、OpenSpec、内存仓储。

---

## 文件职责图

### 新增文件

- `src/shared/schemas/contracts.py`：通用 `Citation`、`AuditEvent`、`RuntimeTask`、`StreamErrorEvent`、`ErrorDetail` Pydantic 契约模型。
- `src/adapters/base/__init__.py`：导出适配器基础契约。
- `src/adapters/base/models.py`：`AdapterCallContext`、`AdapterCallResult`、`AdapterError`、`DataQualityStatus`、`AdapterAuditEvent`。
- `src/adapters/base/service.py`：构造成功/失败适配器调用结果、生成 citation、生成审计摘要。
- `src/runtime/context/__init__.py`：导出运行时上下文服务。
- `src/runtime/context/models.py`：`RuntimeContext`。
- `src/runtime/context/service.py`：从 `ChatRequest` 和 `IntentResult` 构建上下文。
- `src/runtime/planning/__init__.py`：导出计划模型与模板服务。
- `src/runtime/planning/models.py`：`ExecutionPlan`、`PlanStep`、`StepType`、`RiskLevel`。
- `src/runtime/planning/service.py`：三类计划模板生成。
- `src/runtime/orchestration/__init__.py`：导出顺序编排器。
- `src/runtime/orchestration/service.py`：顺序执行器与兼容场景处理器。
- `src/runtime/runtime_state/store.py`：内存 workflow 状态仓储。
- `src/security/audit/service.py`：审计事件记录与审计视图聚合。
- `src/tests/security/test_security_contracts.py`：安全契约测试。
- `src/tests/model_service/test_streaming_errors.py`：流式异常规范化测试。
- `src/tests/adapters/test_adapter_contracts.py`：适配器基础契约测试。
- `src/tests/unit/test_runtime_context_and_planning.py`：上下文与计划测试。
- `src/tests/integration/test_runtime_execution_loop.py`：编排、状态、任务闭环、审计视图集成测试。

### 修改文件

- `src/shared/schemas/responses.py`：保留 `error_detail()`，改为基于 `ErrorDetail` 输出标准 dict。
- `src/runtime/api/schemas.py`：扩展 workflow/task 响应字段，保持现有字段兼容。
- `src/security/risk_control/service.py`：高风险响应补来源/不确定性、任务模型和审计事件。
- `src/runtime/scheduling/service.py`：降级响应补不确定性、受影响来源和审计事件。
- `src/model_service/exceptions.py`：补充流式协议错误类或复用 `ModelServerError`。
- `src/model_service/providers/openai_compatible.py`：规范化 `invoke_stream()` 异常。
- `src/model_service/gateway.py`：`generate_stream()` 记录日志后向上抛出。
- `src/runtime/api/routes.py`：Chat 入口接上下文/计划/编排；stream error 结构化；workflow/task 状态返回真实状态。
- `src/runtime/task_closure/service.py`：模型化任务记录与状态变更。
- `src/security/audit/in_memory.py`：扩展内存审计日志能力。
- `src/static/index.html`：展示结构化流式错误。
- `AGENTS.md`：更新已修复和剩余技术债。

---

### Task 1: 通用契约模型与标准错误结构

**Files:**
- Create: `src/shared/schemas/contracts.py`
- Modify: `src/shared/schemas/responses.py`
- Test: `src/tests/security/test_security_contracts.py`

- [ ] **Step 1: 编写失败测试**

在 `src/tests/security/test_security_contracts.py` 新增：

```python
from src.shared.schemas.contracts import AuditEvent, Citation, ErrorDetail, RuntimeTask, StreamErrorEvent
from src.shared.schemas.responses import error_detail


def test_contract_models_dump_to_api_compatible_dicts():
    citation = Citation(source_type="risk_control_policy", source_id="HIGH_RISK_ACTIONS", summary="高风险动作黑名单")
    audit = AuditEvent(event_type="high_risk_action_blocked", workflow_id="wf-001", step_id="risk_control")
    task = RuntimeTask(task_id="task-001", task_type="human_confirmation", status="pending", description="请人工确认高风险动作")
    stream_error = StreamErrorEvent(error_code="MODEL_STREAM_ERROR", message="模型流式响应失败", audit_event=audit)

    assert citation.model_dump()["source_type"] == "risk_control_policy"
    assert audit.model_dump()["event_type"] == "high_risk_action_blocked"
    assert task.model_dump()["status"] == "pending"
    assert stream_error.model_dump()["audit_event"]["workflow_id"] == "wf-001"


def test_error_detail_uses_standard_error_model():
    detail = error_detail("PERMISSION_DENIED", "角色无权访问该场景", {"event_type": "permission_denied"})

    assert detail == {
        "error_code": "PERMISSION_DENIED",
        "message": "角色无权访问该场景",
        "audit_event": {"event_type": "permission_denied"},
    }
    assert ErrorDetail(**detail).error_code == "PERMISSION_DENIED"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/security/test_security_contracts.py -v`

Expected: FAIL，提示 `ModuleNotFoundError: No module named 'src.shared.schemas.contracts'`。

- [ ] **Step 3: 新增契约模型**

创建 `src/shared/schemas/contracts.py`：

```python
from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_type: str
    source_id: str
    summary: str


class AuditEvent(BaseModel):
    event_type: str
    workflow_id: str | None = None
    step_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeTask(BaseModel):
    task_id: str
    task_type: str
    status: str
    description: str
    responsible_role: str | None = None
    workflow_id: str | None = None
    updated_at: str | None = None


class StreamErrorEvent(BaseModel):
    error_code: str
    message: str
    audit_event: AuditEvent = Field(default_factory=lambda: AuditEvent(event_type="stream_error"))


class ErrorDetail(BaseModel):
    error_code: str
    message: str
    audit_event: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: 更新标准错误函数**

修改 `src/shared/schemas/responses.py`：

```python
from typing import Any

from src.shared.schemas.contracts import ErrorDetail


def error_detail(error_code: str, message: str, audit_event: dict[str, Any] | None = None) -> dict[str, Any]:
    return ErrorDetail(error_code=error_code, message=message, audit_event=audit_event or {}).model_dump()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest src/tests/security/test_security_contracts.py -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/shared/schemas/contracts.py src/shared/schemas/responses.py src/tests/security/test_security_contracts.py
git commit -m "feat: add shared response contract models"
```

---

### Task 2: 高风险动作与降级响应可追溯

**Files:**
- Modify: `src/security/risk_control/service.py`
- Modify: `src/runtime/scheduling/service.py`
- Test: `src/tests/security/test_security_contracts.py`

- [ ] **Step 1: 编写失败测试**

追加到 `src/tests/security/test_security_contracts.py`：

```python
from src.runtime.scheduling.service import degraded_response
from src.security.risk_control.service import build_human_confirmation_response


def test_high_risk_response_has_traceability_and_task():
    response = build_human_confirmation_response(["退费", "冲正"])

    assert response.status == "waiting_human_confirmation"
    assert response.tasks[0]["task_type"] == "human_confirmation"
    assert response.citations or response.uncertainties
    assert response.audit["event_type"] == "high_risk_action_blocked"
    assert "退费" in response.blocked_actions


def test_degraded_response_has_uncertainty_source_and_audit_event():
    response = degraded_response("P002", "E001", "医保接口调用失败，当前结论存在不确定性")

    assert response.status == "degraded"
    assert response.uncertainties
    assert response.citations
    assert response.audit["event_type"] == "degraded_response_returned"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/security/test_security_contracts.py -v`

Expected: FAIL，高风险响应缺少 `audit.event_type` 或降级响应缺少 citations。

- [ ] **Step 3: 更新高风险响应**

修改 `src/security/risk_control/service.py` 的 `build_human_confirmation_response()`：

```python
def build_human_confirmation_response(actions: list[str]) -> AgentResponse:
    actions_key = '-'.join(sorted(actions))
    task_id = f'task-confirm-{hashlib.md5(actions_key.encode()).hexdigest()[:8]}'
    workflow_id = f'wf-high-risk-{task_id}'
    return AgentResponse(
        scenario='high_risk_action_confirmation',
        status='waiting_human_confirmation',
        result={'message': '命中高风险动作，需人工在既有业务系统确认后执行'},
        citations=[{'source_type': 'risk_control_policy', 'source_id': 'HIGH_RISK_ACTIONS', 'summary': '高风险动作黑名单'}],
        tasks=[{'task_id': task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '请人工确认高风险动作', 'workflow_id': workflow_id}],
        missing_fields=[],
        uncertainties=['AI 不会自动执行高风险动作，需人工确认并在既有业务系统处理'],
        blocked_actions=actions,
        audit={'event_type': 'high_risk_action_blocked', 'workflow_id': workflow_id, 'steps': ['detect_high_risk_action', 'create_human_confirmation_task']},
    )
```

- [ ] **Step 4: 更新降级响应**

修改 `src/runtime/scheduling/service.py`：

```python
from src.runtime.api.schemas import AgentResponse


def degraded_response(patient_id: str, encounter_id: str, reason: str) -> AgentResponse:
    workflow_id = f'wf-{patient_id}-{encounter_id}'
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='degraded',
        result={},
        citations=[{'source_type': 'adapter_failure', 'source_id': f'{patient_id}:{encounter_id}', 'summary': reason}],
        tasks=[],
        missing_fields=[],
        uncertainties=[reason],
        blocked_actions=[],
        audit={'event_type': 'degraded_response_returned', 'workflow_id': workflow_id, 'steps': ['query_transaction_failed', 'return_degraded_result']},
    )
```

- [ ] **Step 5: 运行安全测试**

Run: `python -m pytest src/tests/security/test_security_contracts.py src/tests/security/test_high_risk_and_permission.py -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/security/risk_control/service.py src/runtime/scheduling/service.py src/tests/security/test_security_contracts.py
git commit -m "fix: make high risk and degraded responses traceable"
```

---

### Task 3: 模型流式 Provider 异常规范化

**Files:**
- Modify: `src/model_service/providers/openai_compatible.py`
- Test: `src/tests/model_service/test_streaming_errors.py`

- [ ] **Step 1: 编写失败测试**

创建 `src/tests/model_service/test_streaming_errors.py`：

```python
import httpx
import pytest

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import Message, ModelRequest
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider


def _request() -> ModelRequest:
    return ModelRequest(messages=[Message(role="user", content="hello")], model_type="test-model", scene="default")


def test_invoke_stream_converts_timeout(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def stream(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(ModelTimeoutError):
        list(provider.invoke_stream(_request()))


def test_invoke_stream_converts_network_error(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def stream(self, *args, **kwargs):
            raise httpx.NetworkError("network")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(ModelServerError):
        list(provider.invoke_stream(_request()))


def test_invoke_stream_converts_malformed_json(respx_mock):
    route = respx_mock.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text="data: {bad-json}\n\ndata: [DONE]\n")
    )
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(ModelServerError):
        list(provider.invoke_stream(_request()))
    assert route.called


@pytest.mark.parametrize(
    (status_code, error_type),
    [(401, ModelAuthError), (403, ModelAuthError), (429, ModelRateLimitError), (500, ModelServerError)],
)
def test_invoke_stream_converts_status_errors(respx_mock, status_code, error_type):
    respx_mock.post("https://example.test/v1/chat/completions").mock(return_value=httpx.Response(status_code, text="error"))
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(error_type):
        list(provider.invoke_stream(_request()))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/model_service/test_streaming_errors.py -v`

Expected: FAIL，流式异常未规范化或 malformed JSON 直接抛 `JSONDecodeError`。

- [ ] **Step 3: 修改 Provider**

更新 `src/model_service/providers/openai_compatible.py` 的 `invoke_stream()`：

```python
    def invoke_stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        payload = self._build_payload(request, stream=True)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    self._check_status(response)
                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise ModelServerError(f"Malformed stream JSON: {exc}", model_name=request.model_type) from exc
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        finish_reason = chunk["choices"][0].get("finish_reason")
                        usage = None
                        if "usage" in chunk:
                            usage = TokenUsage(
                                prompt_tokens=chunk["usage"].get("prompt_tokens", 0),
                                completion_tokens=chunk["usage"].get("completion_tokens", 0),
                            )
                        yield StreamChunk(content=content, finish_reason=finish_reason, usage=usage)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Model provider timeout: {exc}", model_name=request.model_type) from exc
        except httpx.NetworkError as exc:
            raise ModelServerError(f"Model provider network error: {exc}", model_name=request.model_type) from exc
        except httpx.HTTPError as exc:
            raise ModelServerError(f"Model provider http error: {exc}", model_name=request.model_type) from exc
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/tests/model_service/test_streaming_errors.py src/tests/model_service/test_openai_provider.py -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/model_service/providers/openai_compatible.py src/tests/model_service/test_streaming_errors.py
git commit -m "fix: normalize streaming provider errors"
```

---

### Task 4: 模型流式 Gateway 与 API 错误事件

**Files:**
- Modify: `src/model_service/gateway.py`
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/model_service/test_gateway.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 编写 Gateway 失败测试**

追加到 `src/tests/model_service/test_gateway.py`：

```python
def test_generate_stream_reraises_provider_error(gateway):
    messages = [Message(role="user", content="Hello")]

    with patch.object(gateway, "_get_provider") as mock_get_provider:
        provider = MagicMock()
        provider.invoke_stream.side_effect = ModelServerError("stream failed", model_name="test-model")
        mock_get_provider.return_value = provider

        with pytest.raises(ModelServerError):
            list(gateway.generate_stream(messages, "llm", "default"))
```

- [ ] **Step 2: 编写 API 流式错误测试**

追加到 `src/tests/integration/test_openapi_contract.py`：

```python
def test_model_test_stream_returns_structured_error_and_done(monkeypatch):
    from src.model_service.exceptions import ModelServerError
    from src.runtime.api import routes

    def fake_generate_stream(self, messages, model_type, scene):
        raise ModelServerError("stream failed", model_name="test-model")
        yield

    monkeypatch.setattr(routes.ModelGateway, "generate_stream", fake_generate_stream)
    client = TestClient(create_app())

    response = client.post("/api/v1/medical-insurance-ai-agent/model-test/stream", json={"message": "hello", "scene": "default"})

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "MODEL_UPSTREAM_ERROR" in response.text
    assert "event: done" in response.text
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest src/tests/model_service/test_gateway.py::test_generate_stream_reraises_provider_error src/tests/integration/test_openapi_contract.py::test_model_test_stream_returns_structured_error_and_done -v`

Expected: FAIL，Gateway 未向上抛异常或 API 错误码仍为 `MODEL_STREAM_ERROR`。

- [ ] **Step 4: 更新 Gateway**

修改 `src/model_service/gateway.py` 的异常分支：

```python
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.error("model_stream_interrupted", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms, "error": str(e)})
            raise
```

- [ ] **Step 5: 增加 API 错误映射 helper**

在 `src/runtime/api/routes.py` 中新增：

```python
def model_error_detail(exc: Exception) -> dict:
    if isinstance(exc, ModelAuthError):
        return error_detail('MODEL_AUTH_ERROR', '模型服务鉴权失败，请检查 API Key 是否有效', {'event_type': 'model_auth_error'})
    if isinstance(exc, ModelRateLimitError):
        return error_detail('MODEL_RATE_LIMITED', '模型服务请求过于频繁，请稍后重试', {'event_type': 'model_rate_limited'})
    if isinstance(exc, ModelExhaustedError):
        return error_detail('MODEL_EXHAUSTED', '模型服务回退链已耗尽，请稍后重试', {'event_type': 'model_exhausted'})
    if isinstance(exc, ModelServerError):
        return error_detail('MODEL_UPSTREAM_ERROR', '模型服务上游暂时不可用，请稍后重试', {'event_type': 'model_upstream_error'})
    return error_detail('MODEL_STREAM_ERROR', '模型流式响应失败，请稍后重试', {'event_type': 'model_stream_error'})
```

并将 `model_test_stream()` 的异常分支改为：

```python
        except Exception as exc:
            yield sse_event('error', model_error_detail(exc))
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest src/tests/model_service/test_gateway.py src/tests/integration/test_openapi_contract.py -v`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/model_service/gateway.py src/runtime/api/routes.py src/tests/model_service/test_gateway.py src/tests/integration/test_openapi_contract.py
git commit -m "fix: surface streaming model errors to api"
```

---

### Task 5: 适配器基础契约模型

**Files:**
- Create: `src/adapters/base/__init__.py`
- Create: `src/adapters/base/models.py`
- Create: `src/adapters/base/service.py`
- Test: `src/tests/adapters/test_adapter_contracts.py`

- [ ] **Step 1: 编写失败测试**

创建 `src/tests/adapters/test_adapter_contracts.py`：

```python
from src.adapters.base.models import AdapterCallContext, AdapterCallResult, DataQualityStatus
from src.adapters.base.service import adapter_citation, failed_result, successful_result


def test_successful_adapter_result_contains_source_and_citation():
    context = AdapterCallContext(workflow_id="wf-001", step_id="query_transaction", user_id="U001", role="medical_office")
    result = successful_result(
        context=context,
        source_system="insurance_interface",
        source_record_id="P001:E001",
        capability="query_transaction",
        data={"settlement_status": "failed"},
    )

    citation = adapter_citation(result)

    assert result.status == "success"
    assert result.data_quality == DataQualityStatus.COMPLETE
    assert citation["source_type"] == "insurance_interface"
    assert citation["source_id"] == "P001:E001"


def test_failed_adapter_result_has_error_and_no_sensitive_input():
    context = AdapterCallContext(workflow_id="wf-001", step_id="query_emr", user_id="U001", role="doctor", input_summary={"patient_id": "P001"})
    result = failed_result(context=context, source_system="emr", capability="query_record_summary", error_type="timeout", message="病历系统超时")

    assert result.status == "failed"
    assert result.error_type == "timeout"
    assert result.message == "病历系统超时"
    assert "name" not in result.input_summary
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/adapters/test_adapter_contracts.py -v`

Expected: FAIL，`src.adapters.base` 不存在。

- [ ] **Step 3: 创建适配器模型**

创建 `src/adapters/base/models.py`：

```python
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DataQualityStatus(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    MISSING = "missing"


class AdapterCallContext(BaseModel):
    workflow_id: str | None = None
    step_id: str | None = None
    user_id: str | None = None
    role: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)


class AdapterCallResult(BaseModel):
    status: str
    source_system: str
    source_record_id: str | None = None
    capability: str
    data: dict[str, Any] = Field(default_factory=dict)
    data_quality: DataQualityStatus = DataQualityStatus.COMPLETE
    collected_at: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    message: str | None = None


class AdapterError(Exception):
    def __init__(self, message: str, error_type: str, source_system: str):
        super().__init__(message)
        self.error_type = error_type
        self.source_system = source_system
```

- [ ] **Step 4: 创建适配器服务函数**

创建 `src/adapters/base/service.py`：

```python
from datetime import UTC, datetime
from typing import Any

from src.adapters.base.models import AdapterCallContext, AdapterCallResult, DataQualityStatus


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def successful_result(context: AdapterCallContext, source_system: str, source_record_id: str, capability: str, data: dict[str, Any]) -> AdapterCallResult:
    return AdapterCallResult(
        status="success",
        source_system=source_system,
        source_record_id=source_record_id,
        capability=capability,
        data=data,
        data_quality=DataQualityStatus.COMPLETE,
        collected_at=_now(),
        workflow_id=context.workflow_id,
        step_id=context.step_id,
        input_summary=context.input_summary,
        output_summary={"keys": sorted(data.keys())},
    )


def failed_result(context: AdapterCallContext, source_system: str, capability: str, error_type: str, message: str) -> AdapterCallResult:
    return AdapterCallResult(
        status="failed",
        source_system=source_system,
        capability=capability,
        data_quality=DataQualityStatus.DEGRADED,
        collected_at=_now(),
        workflow_id=context.workflow_id,
        step_id=context.step_id,
        input_summary=context.input_summary,
        error_type=error_type,
        message=message,
    )


def adapter_citation(result: AdapterCallResult) -> dict[str, str]:
    return {
        "source_type": result.source_system,
        "source_id": result.source_record_id or result.capability,
        "summary": result.message or result.capability,
    }
```

创建 `src/adapters/base/__init__.py`：

```python
from src.adapters.base.models import AdapterCallContext, AdapterCallResult, AdapterError, DataQualityStatus
from src.adapters.base.service import adapter_citation, failed_result, successful_result

__all__ = [
    "AdapterCallContext",
    "AdapterCallResult",
    "AdapterError",
    "DataQualityStatus",
    "adapter_citation",
    "failed_result",
    "successful_result",
]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest src/tests/adapters/test_adapter_contracts.py -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/adapters/base src/tests/adapters/test_adapter_contracts.py
git commit -m "feat: add adapter foundation contracts"
```

---

### Task 6: 迁移内存适配器并保持场景兼容

**Files:**
- Modify: `src/adapters/*/in_memory.py`
- Modify: `src/business_scenarios/pre_discharge_joint_qc/service.py`
- Modify: `src/business_scenarios/settlement_exception_guide/service.py`
- Test: `src/tests/adapters/test_adapter_contracts.py`
- Test: `src/tests/e2e/test_pre_discharge_joint_qc.py`
- Test: `src/tests/e2e/test_settlement_exception.py`

- [ ] **Step 1: 编写适配器返回契约测试**

追加到 `src/tests/adapters/test_adapter_contracts.py`：

```python
from src.adapters.base.models import AdapterCallResult
from src.adapters.billing.in_memory import InMemoryBillingAdapter
from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.emr.in_memory import InMemoryEmrAdapter
from src.adapters.his.in_memory import InMemoryHisAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter


def test_in_memory_adapters_return_adapter_call_result():
    adapters = [
        InMemoryBillingAdapter().query_billing_status("P001", "E001"),
        InMemoryDrgDipAdapter().query_group_result("P001", "E001"),
        InMemoryEmrAdapter().query_record_summary("P001", "E001"),
        InMemoryHisAdapter().query_orders("P001", "E001"),
        InMemoryMedicalRecordAdapter().query_homepage("P001", "E001"),
        InMemoryPreAuditAdapter().query_audit_result("P001", "E001"),
    ]

    assert all(isinstance(result, AdapterCallResult) for result in adapters)
    assert {result.status for result in adapters} == {"success"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/adapters/test_adapter_contracts.py::test_in_memory_adapters_return_adapter_call_result -v`

Expected: FAIL，适配器仍返回裸 dict。

- [ ] **Step 3: 迁移简单 dict 适配器**

以 `src/adapters/pre_audit/in_memory.py` 为模板，其他 dict 适配器按同样结构迁移：

```python
from src.adapters.base import AdapterCallContext, successful_result


class InMemoryPreAuditAdapter:
    def query_audit_result(self, patient_id: str, encounter_id: str):
        data = {'risk': '合规拒付风险', 'patient_id': patient_id, 'encounter_id': encounter_id}
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='pre_audit',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_audit_result',
            data=data,
        )
```

迁移以下文件：

- `src/adapters/billing/in_memory.py`
- `src/adapters/drg_dip/in_memory.py`
- `src/adapters/emr/in_memory.py`
- `src/adapters/his/in_memory.py`
- `src/adapters/medical_record/in_memory.py`
- `src/adapters/pre_audit/in_memory.py`

- [ ] **Step 4: 迁移医保接口适配器**

修改 `src/adapters/insurance_interface/in_memory.py`，保留现有交易对象兼容：

```python
from src.adapters.base import AdapterCallContext, successful_result
from src.data_platform.data_access.in_memory import build_sample_store


class InMemoryInsuranceInterfaceAdapter:
    def query_transaction(self, patient_id: str, encounter_id: str):
        tx = build_sample_store().get_insurance_transaction(patient_id, encounter_id)
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='insurance_interface',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_transaction',
            data=tx.model_dump() if hasattr(tx, 'model_dump') else tx.__dict__,
        )
```

- [ ] **Step 5: 更新业务场景读取方式**

在 `src/business_scenarios/pre_discharge_joint_qc/service.py` 中把 `pre_audit['risk']` 改为 `pre_audit.data['risk']`，`drg['risk']` 改为 `drg.data['risk']`，`mr['risk']` 改为 `mr.data['risk']`，并用 `source_system/source_record_id` 生成 citations。

在 `src/business_scenarios/settlement_exception_guide/service.py` 中把 `tx = adapter.query_transaction(...)` 改为：

```python
    tx_result = InMemoryInsuranceInterfaceAdapter().query_transaction(patient_id, encounter_id)
    tx_data = tx_result.data
    error_code = tx_data['error_code']
    settlement_status = tx_data['settlement_status']
    knowledge = ERROR_CODE_KNOWLEDGE[error_code]
```

并同步把 `tx.error_code` 改为 `error_code`，`tx.settlement_status` 改为 `settlement_status`。

- [ ] **Step 6: 运行适配器和场景测试**

Run: `python -m pytest src/tests/adapters/test_adapter_contracts.py src/tests/e2e/test_pre_discharge_joint_qc.py src/tests/e2e/test_settlement_exception.py -v`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/adapters src/business_scenarios src/tests/adapters/test_adapter_contracts.py
git commit -m "refactor: migrate in-memory adapters to unified contract"
```

---

### Task 7: 运行时上下文与计划模型

**Files:**
- Create: `src/runtime/context/__init__.py`
- Create: `src/runtime/context/models.py`
- Create: `src/runtime/context/service.py`
- Create: `src/runtime/planning/__init__.py`
- Create: `src/runtime/planning/models.py`
- Create: `src/runtime/planning/service.py`
- Test: `src/tests/unit/test_runtime_context_and_planning.py`

- [ ] **Step 1: 编写失败测试**

创建 `src/tests/unit/test_runtime_context_and_planning.py`：

```python
from src.runtime.api.schemas import ChatRequest
from src.runtime.context.service import build_runtime_context
from src.runtime.intent.models import IntentResult
from src.runtime.planning.service import build_execution_plan


def test_build_runtime_context_preserves_intent_result():
    request = ChatRequest(user_id="U001", role="medical_office", message="医保结算失败", patient_id="P001", encounter_id="E001")
    intent = IntentResult(intent="settlement_exception_guidance", confidence=0.8, entities={"error_code": "ERR001"}, citations=["LLM意图识别"], raw_message=request.message)

    context = build_runtime_context(request, intent)

    assert context.user_id == "U001"
    assert context.intent == "settlement_exception_guidance"
    assert context.intent_confidence == 0.8
    assert context.intent_citations == ["LLM意图识别"]
    assert context.workflow_id.startswith("wf-")


def test_build_settlement_exception_plan():
    request = ChatRequest(user_id="U001", role="medical_office", message="医保结算失败", patient_id="P001", encounter_id="E001")
    intent = IntentResult(intent="settlement_exception_guidance", confidence=0.8, entities={}, citations=["关键词匹配降级"], raw_message=request.message)
    context = build_runtime_context(request, intent)

    plan = build_execution_plan(context)

    assert plan.scenario == "settlement_exception_guidance"
    assert [step.step_id for step in plan.steps] == ["query_transaction", "retrieve_error_code", "query_billing_status", "build_result"]


def test_build_high_risk_plan_requires_confirmation():
    request = ChatRequest(user_id="U001", role="medical_office", message="请退费", patient_id="P001", encounter_id="E001")
    intent = IntentResult(intent="high_risk_action_confirmation", confidence=1, entities={}, citations=["风控策略"], raw_message=request.message)
    context = build_runtime_context(request, intent)

    plan = build_execution_plan(context)

    assert plan.scenario == "high_risk_action_confirmation"
    assert plan.steps[-1].requires_human_confirmation is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/unit/test_runtime_context_and_planning.py -v`

Expected: FAIL，`src.runtime.context` 不存在。

- [ ] **Step 3: 创建上下文模型与服务**

创建 `src/runtime/context/models.py`：

```python
from typing import Any

from pydantic import BaseModel, Field


class RuntimeContext(BaseModel):
    request_id: str
    workflow_id: str
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None
    intent: str
    intent_confidence: float
    intent_entities: dict[str, Any] = Field(default_factory=dict)
    intent_citations: list[str] = Field(default_factory=list)
    requested_at: str
```

创建 `src/runtime/context/service.py`：

```python
from datetime import UTC, datetime
from hashlib import md5

from src.runtime.api.schemas import ChatRequest
from src.runtime.context.models import RuntimeContext
from src.runtime.intent.models import IntentResult


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_runtime_context(request: ChatRequest, intent_result: IntentResult) -> RuntimeContext:
    requested_at = _now()
    key = f"{request.user_id}:{request.patient_id}:{request.encounter_id}:{request.message}:{requested_at}"
    suffix = md5(key.encode()).hexdigest()[:8]
    return RuntimeContext(
        request_id=f"req-{suffix}",
        workflow_id=f"wf-{suffix}",
        user_id=request.user_id,
        role=request.role,
        message=request.message,
        patient_id=request.patient_id,
        encounter_id=request.encounter_id,
        intent=intent_result.intent,
        intent_confidence=intent_result.confidence,
        intent_entities=intent_result.entities,
        intent_citations=intent_result.citations,
        requested_at=requested_at,
    )
```

创建 `src/runtime/context/__init__.py`：

```python
from src.runtime.context.models import RuntimeContext
from src.runtime.context.service import build_runtime_context

__all__ = ["RuntimeContext", "build_runtime_context"]
```

- [ ] **Step 4: 创建计划模型与模板服务**

创建 `src/runtime/planning/models.py`：

```python
from enum import Enum

from pydantic import BaseModel, Field


class StepType(str, Enum):
    ADAPTER_CALL = "adapter_call"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    RESULT_BUILDING = "result_building"
    TASK_CREATION = "task_creation"
    HUMAN_CONFIRMATION = "human_confirmation"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStep(BaseModel):
    step_id: str
    step_type: StepType
    capability: str
    depends_on: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_confirmation: bool = False


class ExecutionPlan(BaseModel):
    workflow_id: str
    scenario: str
    goal: str
    steps: list[PlanStep]
    output_requirements: list[str] = Field(default_factory=list)
```

创建 `src/runtime/planning/service.py`：

```python
from src.runtime.context.models import RuntimeContext
from src.runtime.planning.models import ExecutionPlan, PlanStep, RiskLevel, StepType


def build_execution_plan(context: RuntimeContext) -> ExecutionPlan:
    if context.intent == "settlement_exception_guidance":
        steps = [
            PlanStep(step_id="query_transaction", step_type=StepType.ADAPTER_CALL, capability="insurance_interface.query_transaction"),
            PlanStep(step_id="retrieve_error_code", step_type=StepType.KNOWLEDGE_RETRIEVAL, capability="knowledge.error_code", depends_on=["query_transaction"]),
            PlanStep(step_id="query_billing_status", step_type=StepType.ADAPTER_CALL, capability="billing.query_billing_status", depends_on=["query_transaction"]),
            PlanStep(step_id="build_result", step_type=StepType.RESULT_BUILDING, capability="settlement_exception.build_result", depends_on=["retrieve_error_code", "query_billing_status"]),
        ]
    elif context.intent == "pre_discharge_quality_control":
        steps = [
            PlanStep(step_id="query_orders", step_type=StepType.ADAPTER_CALL, capability="his.query_orders"),
            PlanStep(step_id="query_insurance_status", step_type=StepType.ADAPTER_CALL, capability="insurance_interface.query_status"),
            PlanStep(step_id="query_pre_audit", step_type=StepType.ADAPTER_CALL, capability="pre_audit.query_audit_result"),
            PlanStep(step_id="query_drg_dip", step_type=StepType.ADAPTER_CALL, capability="drg_dip.query_group_result"),
            PlanStep(step_id="query_medical_record", step_type=StepType.ADAPTER_CALL, capability="medical_record.query_homepage"),
            PlanStep(step_id="retrieve_rule_explanation", step_type=StepType.KNOWLEDGE_RETRIEVAL, capability="knowledge.rule_explanation"),
            PlanStep(step_id="build_risk_list", step_type=StepType.RESULT_BUILDING, capability="pre_discharge_qc.build_risk_list"),
            PlanStep(step_id="create_tasks", step_type=StepType.TASK_CREATION, capability="task_closure.create_tasks"),
        ]
    elif context.intent == "high_risk_action_confirmation":
        steps = [
            PlanStep(step_id="detect_high_risk_action", step_type=StepType.RESULT_BUILDING, capability="risk_control.detect"),
            PlanStep(step_id="create_human_confirmation_task", step_type=StepType.HUMAN_CONFIRMATION, capability="task_closure.human_confirmation", risk_level=RiskLevel.HIGH, requires_human_confirmation=True),
        ]
    else:
        steps = [PlanStep(step_id="build_unknown_intent_response", step_type=StepType.RESULT_BUILDING, capability="response.unknown_intent")]
    return ExecutionPlan(workflow_id=context.workflow_id, scenario=context.intent, goal=context.message, steps=steps, output_requirements=["citations_or_uncertainties"])
```

创建 `src/runtime/planning/__init__.py`：

```python
from src.runtime.planning.models import ExecutionPlan, PlanStep, RiskLevel, StepType
from src.runtime.planning.service import build_execution_plan

__all__ = ["ExecutionPlan", "PlanStep", "RiskLevel", "StepType", "build_execution_plan"]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest src/tests/unit/test_runtime_context_and_planning.py -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/runtime/context src/runtime/planning src/tests/unit/test_runtime_context_and_planning.py
git commit -m "feat: add runtime context and planning models"
```

---

### Task 8: Workflow 状态仓储与任务闭环模型化

**Files:**
- Modify: `src/runtime/runtime_state/models.py`
- Create: `src/runtime/runtime_state/store.py`
- Modify: `src/runtime/task_closure/service.py`
- Modify: `src/runtime/api/schemas.py`
- Test: `src/tests/integration/test_runtime_execution_loop.py`

- [ ] **Step 1: 编写失败测试**

创建 `src/tests/integration/test_runtime_execution_loop.py`：

```python
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.runtime.runtime_state.store import RuntimeStateStore
from src.runtime.task_closure.service import create_task, update_task_confirmation


def test_runtime_state_store_saves_and_returns_workflow():
    store = RuntimeStateStore()
    workflow = WorkflowInstance(workflow_id="wf-001", scenario="settlement_exception_guidance", status="running", steps=[StepState(step_id="query_transaction", status="completed")])

    store.save_workflow(workflow)
    saved = store.get_workflow("wf-001")

    assert saved.workflow_id == "wf-001"
    assert saved.steps[0].step_id == "query_transaction"


def test_task_closure_creates_and_confirms_task():
    task = create_task(task_id="task-001", task_type="human_confirmation", description="请人工确认", responsible_role="医保办", workflow_id="wf-001")
    confirmed = update_task_confirmation(task, action="confirm", user_id="U001", reason="已处理")

    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_by == "U001"
    assert confirmed.confirmed_at.endswith("Z")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py -v`

Expected: FAIL，状态仓储和新任务函数不存在。

- [ ] **Step 3: 扩展状态模型**

修改 `src/runtime/runtime_state/models.py`：

```python
from typing import Any

from pydantic import BaseModel, Field


class StepState(BaseModel):
    step_id: str
    status: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    error: str | None = None
    audit_refs: list[str] = Field(default_factory=list)


class WorkflowInstance(BaseModel):
    workflow_id: str
    scenario: str
    status: str
    current_step: str | None = None
    steps: list[StepState] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: 创建状态仓储**

创建 `src/runtime/runtime_state/store.py`：

```python
from src.runtime.runtime_state.models import WorkflowInstance


class RuntimeStateStore:
    def __init__(self):
        self._workflows: dict[str, WorkflowInstance] = {}

    def save_workflow(self, workflow: WorkflowInstance) -> WorkflowInstance:
        self._workflows[workflow.workflow_id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowInstance | None:
        return self._workflows.get(workflow_id)


runtime_state_store = RuntimeStateStore()
```

- [ ] **Step 5: 扩展任务闭环服务**

修改 `src/runtime/task_closure/service.py`：

```python
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_task(task_id: str, task_type: str, description: str, responsible_role: str, workflow_id: str | None = None) -> dict[str, Any]:
    return {
        'task_id': task_id,
        'task_type': task_type,
        'status': 'pending',
        'description': description,
        'responsible_role': responsible_role,
        'workflow_id': workflow_id,
        'updated_at': _now(),
    }


def update_task_confirmation(task: dict[str, Any], action: str, user_id: str, reason: str | None = None) -> dict[str, Any]:
    updated = dict(task)
    updated['status'] = 'confirmed' if action == 'confirm' else 'rejected'
    updated['confirmed_by'] = user_id
    updated['confirmed_at'] = _now()
    updated['reason'] = reason
    updated['updated_at'] = updated['confirmed_at']
    return updated


def build_pending_task(task_id: str, task_type: str, description: str, responsible_role: str) -> dict[str, Any]:
    return create_task(task_id, task_type, description, responsible_role)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py -v`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/runtime/runtime_state src/runtime/task_closure/service.py src/tests/integration/test_runtime_execution_loop.py
git commit -m "feat: add runtime state store and task lifecycle"
```

---

### Task 9: 顺序编排器与 Chat 兼容接入

**Files:**
- Create: `src/runtime/orchestration/__init__.py`
- Create: `src/runtime/orchestration/service.py`
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/integration/test_runtime_execution_loop.py`
- Test: `src/tests/integration/test_intent_routing.py`

- [ ] **Step 1: 编写编排接入测试**

追加到 `src/tests/integration/test_runtime_execution_loop.py`：

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_chat_creates_workflow_audit_and_preserves_response_shape():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "医保结算失败", "patient_id": "P001", "encounter_id": "E001"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["scenario"] == "settlement_exception_guidance"
    assert body["status"] == "completed"
    assert body["audit"]["workflow_id"].startswith("wf-")
    assert "steps" in body["audit"]


def test_workflow_status_returns_real_state_after_chat():
    client = TestClient(create_app())
    chat = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "医保结算失败", "patient_id": "P001", "encounter_id": "E001"},
    )
    workflow_id = chat.json()["audit"]["workflow_id"]

    response = client.get(f"/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}")

    assert response.status_code == 200
    assert response.json()["workflow_id"] == workflow_id
    assert response.json()["status"] in ["completed", "degraded", "waiting_human_confirmation"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py::test_chat_creates_workflow_audit_and_preserves_response_shape src/tests/integration/test_runtime_execution_loop.py::test_workflow_status_returns_real_state_after_chat -v`

Expected: FAIL，workflow 状态仍是 `not_implemented` 或没有存储。

- [ ] **Step 3: 创建顺序编排器**

创建 `src/runtime/orchestration/service.py`：

```python
from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc
from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception
from src.runtime.api.schemas import AgentResponse
from src.runtime.context.models import RuntimeContext
from src.runtime.planning.models import ExecutionPlan
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.runtime.runtime_state.store import runtime_state_store
from src.security.risk_control.service import build_human_confirmation_response, detect_blocked_actions


def execute_plan(context: RuntimeContext, plan: ExecutionPlan) -> AgentResponse:
    steps = [StepState(step_id=step.step_id, status="completed") for step in plan.steps]
    if plan.scenario == "settlement_exception_guidance":
        response = guide_settlement_exception(context.patient_id, context.encounter_id)
    elif plan.scenario == "pre_discharge_quality_control":
        response = run_pre_discharge_qc(context.patient_id, context.encounter_id)
    elif plan.scenario == "high_risk_action_confirmation":
        response = build_human_confirmation_response(detect_blocked_actions(context.message))
    else:
        response = AgentResponse(status="not_implemented", uncertainties=[f"未识别的意图: {context.message}"])
    workflow = WorkflowInstance(workflow_id=context.workflow_id, scenario=plan.scenario, status=response.status, current_step=steps[-1].step_id if steps else None, steps=steps)
    runtime_state_store.save_workflow(workflow)
    response.audit["workflow_id"] = context.workflow_id
    response.audit["steps"] = [step.step_id for step in steps]
    return response
```

创建 `src/runtime/orchestration/__init__.py`：

```python
from src.runtime.orchestration.service import execute_plan

__all__ = ["execute_plan"]
```

- [ ] **Step 4: 接入 Chat 路由**

在 `src/runtime/api/routes.py` 导入：

```python
from src.runtime.context.service import build_runtime_context
from src.runtime.orchestration.service import execute_plan
from src.runtime.planning.service import build_execution_plan
from src.runtime.runtime_state.store import runtime_state_store
```

在 `process_chat_request()` 中解析 intent 后替换场景直连分支为：

```python
    if scenario in ('settlement_exception_guidance', 'pre_discharge_quality_control'):
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        context = build_runtime_context(request, intent_result)
        plan = build_execution_plan(context)
        response = execute_plan(context, plan)
        response.citations.extend(
            {'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in intent_result.citations
        )
        return response
```

更新 `workflow_status()`：

```python
def workflow_status(workflow_id: str) -> WorkflowStatusResponse:
    workflow = runtime_state_store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=error_detail('WORKFLOW_NOT_FOUND', 'workflow 不存在', {'event_type': 'workflow_not_found'}))
    return WorkflowStatusResponse(workflow_id=workflow.workflow_id, status=workflow.status)
```

- [ ] **Step 5: 运行相关测试**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py src/tests/integration/test_intent_routing.py src/tests/e2e -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/runtime/orchestration src/runtime/api/routes.py src/tests/integration/test_runtime_execution_loop.py
git commit -m "feat: route chat through runtime execution loop"
```

---

### Task 10: Task 状态接口与人工确认更新

**Files:**
- Modify: `src/runtime/task_closure/service.py`
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/integration/test_human_confirmation.py`
- Test: `src/tests/integration/test_runtime_execution_loop.py`

- [ ] **Step 1: 编写失败测试**

追加到 `src/tests/integration/test_runtime_execution_loop.py`：

```python
def test_task_status_returns_real_task_after_high_risk_chat():
    client = TestClient(create_app())
    chat = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "请自动退费并冲正", "patient_id": "P001", "encounter_id": "E001"},
    )
    task_id = chat.json()["tasks"][0]["task_id"]

    response = client.get(f"/api/v1/medical-insurance-ai-agent/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id
    assert response.json()["status"] == "pending"


def test_confirm_task_uses_runtime_time_not_hardcoded_value():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/tasks/confirm",
        json={"task_id": "task-manual-001", "action": "confirm", "user_id": "U001", "reason": "已在系统处理"},
    )

    assert response.status_code == 200
    assert response.json()["confirmed_at"] != "2026-05-02T00:00:00Z"
    assert response.json()["confirmed_at"].endswith("Z")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py::test_task_status_returns_real_task_after_high_risk_chat src/tests/integration/test_runtime_execution_loop.py::test_confirm_task_uses_runtime_time_not_hardcoded_value -v`

Expected: FAIL，task 状态未存储或确认时间硬编码。

- [ ] **Step 3: 增加内存任务仓储**

在 `src/runtime/task_closure/service.py` 增加：

```python
TASKS: dict[str, dict[str, Any]] = {}


def save_task(task: dict[str, Any]) -> dict[str, Any]:
    TASKS[task['task_id']] = task
    return task


def get_task(task_id: str) -> dict[str, Any] | None:
    return TASKS.get(task_id)
```

并让 `create_task()` 调用 `save_task(task)` 后返回。

- [ ] **Step 4: 保存高风险任务**

在 `src/security/risk_control/service.py` 中导入并使用 `create_task()`：

```python
from src.runtime.task_closure.service import create_task
```

将任务创建替换为：

```python
        tasks=[create_task(task_id, 'human_confirmation', '请人工确认高风险动作', '医保办', workflow_id)],
```

- [ ] **Step 5: 更新 task 路由与 confirm 路由**

在 `src/runtime/api/routes.py` 导入：

```python
from src.runtime.task_closure.service import get_task, update_task_confirmation, save_task
```

更新 `task_status()`：

```python
def task_status(task_id: str) -> TaskStatusResponse:
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=error_detail('TASK_NOT_FOUND', 'task 不存在', {'event_type': 'task_not_found'}))
    return TaskStatusResponse(task_id=task_id, status=task['status'])
```

更新 `confirm_task()` 中返回逻辑：

```python
    task = get_task(request.task_id) or {'task_id': request.task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '人工确认任务'}
    updated = save_task(update_task_confirmation(task, request.action, request.user_id, request.reason))
    return TaskConfirmResponse(
        task_id=request.task_id,
        status=updated['status'],
        confirmed_by=request.user_id,
        confirmed_at=updated['confirmed_at'],
        reason=request.reason,
        result={} if request.action == 'confirm' else {'blocked': True, 'message': '用户拒绝执行该操作'},
    )
```

- [ ] **Step 6: 运行任务相关测试**

Run: `python -m pytest src/tests/integration/test_human_confirmation.py src/tests/integration/test_runtime_execution_loop.py -v`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/runtime/task_closure/service.py src/security/risk_control/service.py src/runtime/api/routes.py src/tests/integration/test_runtime_execution_loop.py
git commit -m "feat: persist task status and runtime confirmations"
```

---

### Task 11: 审计日志与审计视图

**Files:**
- Modify: `src/security/audit/in_memory.py`
- Create: `src/security/audit/service.py`
- Modify: `src/runtime/api/schemas.py`
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/integration/test_runtime_execution_loop.py`

- [ ] **Step 1: 编写失败测试**

追加到 `src/tests/integration/test_runtime_execution_loop.py`：

```python
def test_audit_view_can_restore_high_risk_workflow():
    client = TestClient(create_app())
    chat = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "请自动退费", "patient_id": "P001", "encounter_id": "E001"},
    )
    workflow_id = chat.json()["audit"]["workflow_id"]

    response = client.get(f"/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == workflow_id
    assert body["status"] == "waiting_human_confirmation"
```

- [ ] **Step 2: 运行测试确认当前状态**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py::test_audit_view_can_restore_high_risk_workflow -v`

Expected: PASS 或 FAIL；若 PASS，继续补充审计字段，不改变行为。

- [ ] **Step 3: 扩展审计日志**

修改 `src/security/audit/in_memory.py`：

```python
from typing import Any


class InMemoryAuditLog:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def record(self, event_type: str, workflow_id: str | None = None, step_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {'event_type': event_type, 'workflow_id': workflow_id, 'step_id': step_id, 'payload': payload or {}}
        self.records.append(event)
        return event

    def by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records if record.get('workflow_id') == workflow_id]


audit_log = InMemoryAuditLog()
```

- [ ] **Step 4: 新增审计服务**

创建 `src/security/audit/service.py`：

```python
from src.runtime.runtime_state.store import runtime_state_store
from src.security.audit.in_memory import audit_log


def record_audit_event(event_type: str, workflow_id: str | None = None, step_id: str | None = None, payload: dict | None = None) -> dict:
    return audit_log.record(event_type, workflow_id, step_id, payload)


def build_workflow_audit_view(workflow_id: str) -> dict | None:
    workflow = runtime_state_store.get_workflow(workflow_id)
    if workflow is None:
        return None
    return {
        'workflow_id': workflow.workflow_id,
        'scenario': workflow.scenario,
        'status': workflow.status,
        'steps': [step.model_dump() for step in workflow.steps],
        'events': audit_log.by_workflow(workflow_id),
    }
```

- [ ] **Step 5: 在编排器记录审计事件**

在 `src/runtime/orchestration/service.py` 导入 `record_audit_event`，并在保存 workflow 后追加：

```python
    record_audit_event('workflow_executed', context.workflow_id, payload={'scenario': plan.scenario, 'status': response.status})
    for step in steps:
        record_audit_event('workflow_step_completed', context.workflow_id, step.step_id)
```

- [ ] **Step 6: 保持现有 workflow 响应兼容**

本阶段不新增公开审计 API，仅确保内部服务可聚合审计视图，后续如需公开 API 再扩展。

- [ ] **Step 7: 运行集成测试**

Run: `python -m pytest src/tests/integration/test_runtime_execution_loop.py src/tests/integration/test_audit_and_degradation.py -v`

Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add src/security/audit src/runtime/orchestration/service.py src/tests/integration/test_runtime_execution_loop.py
git commit -m "feat: add workflow audit view aggregation"
```

---

### Task 12: 前端流式错误展示、文档与全量验证

**Files:**
- Modify: `src/static/index.html`
- Modify: `AGENTS.md`
- Test: `src/tests/unit/test_streaming_events.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 更新前端错误展示**

在 `src/static/index.html` 的流式事件处理逻辑中，确保 `event: error` 的 JSON 能展示 `error_code` 和 `message`。如果现有逻辑已经展示完整 payload，则只补充可读格式：

```javascript
if (eventType === 'error') {
  const errorCode = data.error_code || data.detail?.error_code || 'STREAM_ERROR';
  const message = data.message || data.detail?.message || JSON.stringify(data);
  appendMessage('assistant', `流式错误 ${errorCode}: ${message}`);
}
```

- [ ] **Step 2: 更新 OpenAPI 测试断言**

确认 `src/tests/integration/test_openapi_contract.py` 覆盖以下路径：

```python
def test_workflow_and_task_paths_are_in_openapi():
    client = TestClient(create_app())
    schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    assert "/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}" in paths
    assert "/api/v1/medical-insurance-ai-agent/tasks/{task_id}" in paths
    assert "/api/v1/medical-insurance-ai-agent/model-test/stream" in paths
```

- [ ] **Step 3: 更新 AGENTS 技术债说明**

修改 `AGENTS.md` 的 MVP 技术债段落，移除已修复项，保留剩余边界。例如：

```markdown
### MVP 阶段的剩余技术债务

- `AgentResponse` 内部仍有部分 `dict[str, Any]` 字段，后续需逐步 Pydantic 化。
- 运行时编排当前为顺序执行器，尚未实现完整 DAG、并行执行、断点续执。
- 审计、workflow、task 状态当前为内存实现，重启后不保留。
- 真实院内系统适配器尚未接入，当前仍为内存适配器。
```

- [ ] **Step 4: 记录过程债处理结论**

在 `AGENTS.md` 添加过程债说明：

```markdown
### OpenSpec 过程债

- `openspec/changes/archive/2026-05-03-enhance-intent-recognition/tasks.md` 中任务勾选状态与当前代码存在不一致；后续归档或维护 OpenSpec 时应以代码和测试状态为准补齐记录。
```

- [ ] **Step 5: 运行 OpenSpec 校验**

Run: `npx openspec validate "fix-security-contracts-and-runtime-decoupling" --strict`

Expected: `Change 'fix-security-contracts-and-runtime-decoupling' is valid`。

- [ ] **Step 6: 运行全量测试**

Run: `python -m pytest src/tests -v`

Expected: 全部测试 PASS。

- [ ] **Step 7: 提交**

```bash
git add src/static/index.html AGENTS.md src/tests/integration/test_openapi_contract.py
git commit -m "docs: update security runtime debt status"
```

---

## 最终验收清单

- [ ] 高风险动作不会自动执行，并返回人工确认任务、citation/uncertainty 和审计事件。
- [ ] 降级响应包含受影响来源或 uncertainty。
- [ ] 流式 Provider/Gateway/API 对超时、网络、鉴权、限流、上游错误和 malformed JSON 返回结构化错误事件。
- [ ] 7 个内存适配器具备统一调用契约或可转换结果。
- [ ] Chat 请求生成 RuntimeContext 和 ExecutionPlan。
- [ ] workflow/task 查询返回真实内存状态，不再固定 `not_implemented`。
- [ ] 人工确认使用运行时时间并写入任务状态。
- [ ] 审计服务可按 workflow_id 聚合流程视图。
- [ ] 前端能展示结构化流式错误。
- [ ] `python -m pytest src/tests -v` 通过。
- [ ] `npx openspec validate "fix-security-contracts-and-runtime-decoupling" --strict` 通过。

## 自检

- 规格覆盖：覆盖 [`security-contracts`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/specs/security-contracts/spec.md)、[`adapter-foundation`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/specs/adapter-foundation/spec.md)、[`runtime-execution-loop`](../../openspec/changes/fix-security-contracts-and-runtime-decoupling/specs/runtime-execution-loop/spec.md) 的核心要求。
- 占位符扫描：未保留 `TBD`、`TODO` 或“自行处理”类任务描述。
- 类型一致性：计划中使用的 `Citation`、`AuditEvent`、`AdapterCallResult`、`RuntimeContext`、`ExecutionPlan`、`WorkflowInstance` 均在对应任务中先定义后使用。
- 范围控制：未新增真实外部系统依赖，未新增新业务场景，保留现有 API 入口和 `AgentResponse` 顶层兼容。
