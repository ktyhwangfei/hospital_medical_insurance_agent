# Model Network Error Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 [`OpenAICompatibleProvider`](src/model_service/providers/openai_compatible.py) 中的 `httpx` 超时与网络异常统一转换为模型服务领域异常，避免 [`/model-test`](src/runtime/api/routes.py:92) 返回裸 `500 Internal Server Error`。

**Architecture:** 在 provider 边界执行异常归一化，把 `httpx.TimeoutException` 映射为 [`ModelTimeoutError`](src/model_service/exceptions.py:7)，把 `httpx.NetworkError` 与其余 `httpx.HTTPError` 映射为 [`ModelServerError`](src/model_service/exceptions.py:19)。[`ModelGateway.generate()`](src/model_service/gateway.py:27) 复用已有重试与 fallback 链，最终由 [`model_test()`](src/runtime/api/routes.py:92) 返回结构化 JSON 错误。

**Tech Stack:** Python, httpx, FastAPI, pytest, pytest monkeypatch/respx

---

### Task 1: 为 provider 超时异常归一化补充失败测试

**Files:**
- Modify: `src/tests/model_service/test_openai_provider.py`
- Test: `src/tests/model_service/test_openai_provider.py`

- [ ] **Step 1: 阅读现有 provider 测试结构**

查看 [`src/tests/model_service/test_openai_provider.py`](src/tests/model_service/test_openai_provider.py)，确认当前使用 `respx` 或 `monkeypatch` 模拟 [`httpx.Client.post()`](src/model_service/providers/openai_compatible.py:19) 的方式。

- [ ] **Step 2: 添加 `httpx.ReadTimeout` 转换测试**

在 [`src/tests/model_service/test_openai_provider.py`](src/tests/model_service/test_openai_provider.py) 追加：

```python
import httpx
import pytest

from src.model_service.exceptions import ModelTimeoutError
from src.model_service.models import Message, ModelRequest
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider


def test_invoke_converts_read_timeout_to_model_timeout(monkeypatch):
    def fake_post(self, url, json, headers):
        raise httpx.ReadTimeout('read timeout')

    monkeypatch.setattr(httpx.Client, 'post', fake_post)
    provider = OpenAICompatibleProvider(base_url='https://example.test/v1', api_key='key', timeout=1)
    request = ModelRequest(
        messages=[Message(role='user', content='你好')],
        model_type='gpt-test',
        scene='default',
        temperature=0.3,
        max_tokens=128,
    )

    with pytest.raises(ModelTimeoutError) as exc_info:
        provider.invoke(request)

    assert 'read timeout' in str(exc_info.value)
```

- [ ] **Step 3: 运行新增测试并确认失败**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py::test_invoke_converts_read_timeout_to_model_timeout -v`

Expected: FAIL，当前 [`OpenAICompatibleProvider.invoke()`](src/model_service/providers/openai_compatible.py:16) 会直接抛出 `httpx.ReadTimeout`，而不是 [`ModelTimeoutError`](src/model_service/exceptions.py:7)。

### Task 2: 实现 provider 层 httpx 异常归一化

**Files:**
- Modify: `src/model_service/providers/openai_compatible.py`
- Test: `src/tests/model_service/test_openai_provider.py`

- [ ] **Step 1: 在 provider 中导入领域异常**

修改 [`src/model_service/providers/openai_compatible.py`](src/model_service/providers/openai_compatible.py) 顶部导入：

```python
from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
```

- [ ] **Step 2: 在 [`invoke()`](src/model_service/providers/openai_compatible.py:16) 中捕获 httpx 异常并转换**

替换 [`invoke()`](src/model_service/providers/openai_compatible.py:16) 中的请求代码为：

```python
    def invoke(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request, stream=False)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Model provider timeout: {exc}", model_name=request.model_type) from exc
        except httpx.NetworkError as exc:
            raise ModelServerError(f"Model provider network error: {exc}", model_name=request.model_type) from exc
        except httpx.HTTPError as exc:
            raise ModelServerError(f"Model provider http error: {exc}", model_name=request.model_type) from exc
        return self._handle_response(response)
```

- [ ] **Step 3: 运行超时转换测试并确认通过**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py::test_invoke_converts_read_timeout_to_model_timeout -v`

Expected: PASS。

### Task 3: 覆盖 network error 与 embedding 调用异常归一化

**Files:**
- Modify: `src/tests/model_service/test_openai_provider.py`
- Modify: `src/model_service/providers/openai_compatible.py`
- Test: `src/tests/model_service/test_openai_provider.py`

- [ ] **Step 1: 添加 `httpx.ConnectError` 转换测试**

在 [`src/tests/model_service/test_openai_provider.py`](src/tests/model_service/test_openai_provider.py) 追加：

```python
from src.model_service.exceptions import ModelServerError


def test_invoke_converts_network_error_to_model_server_error(monkeypatch):
    def fake_post(self, url, json, headers):
        raise httpx.ConnectError('connect failed')

    monkeypatch.setattr(httpx.Client, 'post', fake_post)
    provider = OpenAICompatibleProvider(base_url='https://example.test/v1', api_key='key', timeout=1)
    request = ModelRequest(
        messages=[Message(role='user', content='你好')],
        model_type='gpt-test',
        scene='default',
        temperature=0.3,
        max_tokens=128,
    )

    with pytest.raises(ModelServerError) as exc_info:
        provider.invoke(request)

    assert 'connect failed' in str(exc_info.value)
```

- [ ] **Step 2: 添加 embedding 超时转换测试**

```python
def test_invoke_embedding_converts_timeout_to_model_timeout(monkeypatch):
    def fake_post(self, url, json, headers):
        raise httpx.ReadTimeout('embedding timeout')

    monkeypatch.setattr(httpx.Client, 'post', fake_post)
    provider = OpenAICompatibleProvider(base_url='https://example.test/v1', api_key='key', timeout=1)

    with pytest.raises(ModelTimeoutError) as exc_info:
        provider.invoke_embedding('医保政策', 'embedding-test')

    assert 'embedding timeout' in str(exc_info.value)
```

- [ ] **Step 3: 运行新增测试并确认 embedding 测试失败**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py::test_invoke_embedding_converts_timeout_to_model_timeout -v`

Expected: FAIL，当前 [`invoke_embedding()`](src/model_service/providers/openai_compatible.py:58) 仍直接抛出 `httpx.ReadTimeout`。

- [ ] **Step 4: 在 [`invoke_embedding()`](src/model_service/providers/openai_compatible.py:58) 中增加同样的异常归一化**

```python
    def invoke_embedding(self, text: str, model: str) -> ModelResponse:
        payload = {"input": text, "model": model}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/embeddings",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Model provider timeout: {exc}", model_name=model) from exc
        except httpx.NetworkError as exc:
            raise ModelServerError(f"Model provider network error: {exc}", model_name=model) from exc
        except httpx.HTTPError as exc:
            raise ModelServerError(f"Model provider http error: {exc}", model_name=model) from exc
        self._check_status(response)
        data = response.json()
        embedding = data["data"][0]["embedding"]
        return ModelResponse(
            content=json.dumps(embedding),
            model_name=model,
            usage=TokenUsage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=0,
            ),
            finish_reason="stop",
        )
```

- [ ] **Step 5: 运行 provider 测试文件**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py -v`

Expected: PASS，provider 层鉴权、限流、服务端错误、timeout、network error 测试全部通过。

### Task 4: 补充 API 层重试耗尽结构化错误测试

**Files:**
- Modify: `src/tests/integration/test_openapi_contract.py`
- Modify: `src/runtime/api/routes.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 添加 [`ModelExhaustedError`](src/model_service/exceptions.py:23) JSON 返回测试**

在 [`src/tests/integration/test_openapi_contract.py`](src/tests/integration/test_openapi_contract.py) 追加：

```python
from src.model_service.exceptions import ModelExhaustedError


def test_model_test_returns_exhausted_error(monkeypatch):
    def fake_generate(self, messages, model_type, scene):
        raise ModelExhaustedError(
            'All models in fallback chain failed',
            failures=[{'model_name': 'gpt-test', 'error_type': 'ModelTimeoutError', 'error_message': 'read timeout'}],
        )

    monkeypatch.setattr(routes.ModelGateway, 'generate', fake_generate)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 503
    assert response.headers['content-type'].startswith('application/json')
    assert response.json()['detail']['error_code'] == 'MODEL_EXHAUSTED'
```

- [ ] **Step 2: 运行 API 契约测试**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py -v`

Expected: PASS。

### Task 5: 完整验证与页面复测

**Files:**
- Test: `src/tests`
- Manual: `src/static/index.html`

- [ ] **Step 1: 运行 provider 定向测试**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py -v`

Expected: PASS。

- [ ] **Step 2: 运行 API 契约测试**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py -v`

Expected: PASS。

- [ ] **Step 3: 运行完整测试**

Run: `python -m pytest src/tests -v`

Expected: 记录真实输出。若仍存在 [`src/tests/model_service/test_router.py`](src/tests/model_service/test_router.py) 既有配置失败，需要明确标注与本次网络异常修复无关。

- [ ] **Step 4: 页面手工复测**

Run: `uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 18080 --factory`

Then: 打开 [`http://127.0.0.1:18080/`](src/runtime/api/app.py:17)，点击 [`LLM 基础调用`](src/static/index.html:94)。

Expected: 上游超时或网络失败时，页面展示结构化错误消息，不再展示裸 `Internal Server Error`。

## 自检结果

- 规格覆盖：已覆盖 provider 层 `httpx.TimeoutException`、`httpx.NetworkError`、其余 `httpx.HTTPError` 转换，gateway 重试链路，API 结构化 JSON，测试与页面验证。
- 占位符扫描：未保留 `TBD`、`TODO` 或缺少具体代码的步骤。
- 类型一致性：计划中使用的 [`ModelTimeoutError`](src/model_service/exceptions.py:7)、[`ModelServerError`](src/model_service/exceptions.py:19)、[`ModelExhaustedError`](src/model_service/exceptions.py:23) 与现有类型一致。
