# Model Service 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增统一模型服务层，支持 LLM/Embedding 调用、路由降级、流式响应

**Architecture:** Protocol 接口 + ModelGateway(重试/日志) + ModelRouter(路由/降级) + OpenAICompatibleProvider(HTTP 调用)，配置通过 pydantic-settings 管理

**Tech Stack:** Python 3.12, pydantic-settings, httpx, pytest

---

## 文件结构

```
src/model_service/
├── __init__.py
├── models.py
├── exceptions.py
├── ports.py
├── router.py
├── gateway.py
└── providers/
    ├── __init__.py
    └── openai_compatible.py

src/config/
├── model_service.py
└── model_routing.py

src/tests/model_service/
├── __init__.py
├── test_gateway.py
├── test_router.py
└── test_openai_provider.py
```

---

### Task 1: 目录结构 + 基础数据类型

**Files:**
- Create: `src/model_service/__init__.py`
- Create: `src/model_service/models.py`
- Create: `src/model_service/exceptions.py`
- Create: `src/model_service/providers/__init__.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p src/model_service/providers
mkdir -p src/tests/model_service
```

- [ ] **Step 2: 创建 __init__.py 文件**

```bash
touch src/model_service/__init__.py
touch src/model_service/providers/__init__.py
touch src/tests/model_service/__init__.py
```

- [ ] **Step 3: 编写 models.py 数据结构**

```python
# src/model_service/models.py
from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class ModelRequest:
    messages: list[Message]
    model_type: str
    scene: str
    temperature: float = 0.7
    max_tokens: int = 2048


@dataclass
class ModelResponse:
    content: str
    model_name: str
    usage: TokenUsage
    finish_reason: str


@dataclass
class StreamChunk:
    content: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
```

- [ ] **Step 4: 编写 exceptions.py 异常层次**

```python
# src/model_service/exceptions.py
class ModelError(Exception):
    def __init__(self, message: str, model_name: str = ""):
        super().__init__(message)
        self.model_name = model_name


class ModelTimeoutError(ModelError):
    pass


class ModelRateLimitError(ModelError):
    pass


class ModelAuthError(ModelError):
    pass


class ModelServerError(ModelError):
    pass


class ModelExhaustedError(ModelError):
    def __init__(self, message: str, failures: list[dict]):
        super().__init__(message)
        self.failures = failures
```

- [ ] **Step 5: 验证 import 正常**

Run: `python -c "from src.model_service.models import Message, ModelRequest, ModelResponse, StreamChunk, TokenUsage; from src.model_service.exceptions import ModelError, ModelTimeoutError, ModelRateLimitError, ModelAuthError, ModelServerError, ModelExhaustedError; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/model_service/ src/tests/model_service/
git commit -m "feat(model-service): add data models and exception hierarchy"
```

---

### Task 2: Protocol 接口

**Files:**
- Create: `src/model_service/ports.py`

- [ ] **Step 1: 编写 ports.py**

```python
# src/model_service/ports.py
from typing import Iterator, Protocol

from src.model_service.models import ModelRequest, ModelResponse, StreamChunk


class ModelProviderProtocol(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        raise NotImplementedError


class ModelGatewayProtocol(Protocol):
    def generate(self, messages: list, model_type: str, scene: str) -> ModelResponse:
        raise NotImplementedError

    def generate_stream(self, messages: list, model_type: str, scene: str) -> Iterator[StreamChunk]:
        raise NotImplementedError
```

- [ ] **Step 2: 验证 import 正常**

Run: `python -c "from src.model_service.ports import ModelProviderProtocol, ModelGatewayProtocol; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/model_service/ports.py
git commit -m "feat(model-service): add Protocol interfaces"
```

---

### Task 3: 配置模块

**Files:**
- Create: `src/config/model_service.py`
- Create: `src/config/model_routing.py`

- [ ] **Step 1: 安装 pydantic-settings**

Run: `pip install pydantic-settings`
Expected: Successfully installed

- [ ] **Step 2: 编写 model_service.py 配置**

```python
# src/config/model_service.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelServiceConfig(BaseSettings):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    default_timeout: int = 30
    max_retries: int = 3

    model_config = SettingsConfigDict(env_prefix="MODEL_")
```

- [ ] **Step 3: 编写 model_routing.py 路由配置**

```python
# src/config/model_routing.py
from enum import Enum


class ModelType(str, Enum):
    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    OCR = "ocr"


ROUTING_TABLE = {
    ("settlement_exception_guidance", ModelType.LLM): "gpt-4o-mini",
    ("pre_discharge_quality_control", ModelType.LLM): "gpt-4o-mini",
    ("default", ModelType.LLM): "gpt-4o-mini",
    ("default", ModelType.EMBEDDING): "text-embedding-3-small",
}

FALLBACK_CHAINS = {
    "gpt-4o-mini": ["gpt-3.5-turbo"],
    "text-embedding-3-small": [],
}

MODEL_PARAMS = {
    "gpt-4o-mini": {"temperature": 0.3, "max_tokens": 2048},
    "gpt-3.5-turbo": {"temperature": 0.5, "max_tokens": 1024},
}
```

- [ ] **Step 4: 验证配置加载**

Run: `python -c "from src.config.model_service import ModelServiceConfig; c = ModelServiceConfig(); print(f'base_url={c.base_url}'); from src.config.model_routing import ModelType, ROUTING_TABLE; print(f'type={ModelType.LLM}'); print('OK')"`
Expected: `base_url=https://api.openai.com/v1` 和 `OK`

- [ ] **Step 5: Commit**

```bash
git add src/config/model_service.py src/config/model_routing.py
git commit -m "feat(model-service): add config modules with pydantic-settings"
```

---

### Task 4: OpenAI Compatible Provider

**Files:**
- Create: `src/model_service/providers/openai_compatible.py`
- Create: `src/tests/model_service/test_openai_provider.py`

- [ ] **Step 1: 安装 httpx**

Run: `pip install httpx`
Expected: Successfully installed

- [ ] **Step 2: 编写 Provider 测试**

```python
# src/tests/model_service/test_openai_provider.py
import json
from unittest.mock import MagicMock, patch

import pytest

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import Message, ModelRequest, TokenUsage
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider


@pytest.fixture
def provider():
    return OpenAICompatibleProvider(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        timeout=10,
    )


@pytest.fixture
def sample_request():
    return ModelRequest(
        messages=[Message(role="user", content="Hello")],
        model_type="llm",
        scene="test",
        temperature=0.7,
        max_tokens=100,
    )


def test_invoke_success(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hi there"}, "finish_reason": "stop"}],
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    with patch("httpx.Client.post", return_value=mock_response):
        result = provider.invoke(sample_request)

    assert result.content == "Hi there"
    assert result.model_name == "gpt-4o-mini"
    assert result.finish_reason == "stop"
    assert result.usage == TokenUsage(prompt_tokens=10, completion_tokens=5)


def test_invoke_auth_error(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelAuthError):
            provider.invoke(sample_request)


def test_invoke_rate_limit_error(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "Rate limited"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelRateLimitError):
            provider.invoke(sample_request)


def test_invoke_server_error(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal error"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelServerError):
            provider.invoke(sample_request)
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 4: 实现 OpenAICompatibleProvider**

```python
# src/model_service/providers/openai_compatible.py
import json
from typing import Iterator

import httpx

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import Message, ModelRequest, ModelResponse, StreamChunk, TokenUsage


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def invoke(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request, stream=False)
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
        return self._handle_response(response)

    def invoke_stream(self, request: ModelRequest) -> Iterator[StreamChunk]:
        payload = self._build_payload(request, stream=True)
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
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    finish_reason = chunk["choices"][0].get("finish_reason")
                    usage = None
                    if "usage" in chunk:
                        usage = TokenUsage(
                            prompt_tokens=chunk["usage"].get("prompt_tokens", 0),
                            completion_tokens=chunk["usage"].get("completion_tokens", 0),
                        )
                    yield StreamChunk(
                        content=content,
                        finish_reason=finish_reason,
                        usage=usage,
                    )

    def invoke_embedding(self, text: str, model: str) -> ModelResponse:
        payload = {"input": text, "model": model}
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self._base_url}/embeddings",
                json=payload,
                headers=self._headers(),
            )
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

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: ModelRequest, stream: bool) -> dict:
        return {
            "model": request.model_type,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }

    def _handle_response(self, response: httpx.Response) -> ModelResponse:
        self._check_status(response)
        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return ModelResponse(
            content=choice["message"]["content"],
            model_name=data.get("model", ""),
            usage=TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    def _check_status(self, response: httpx.Response) -> None:
        if response.status_code == 401 or response.status_code == 403:
            raise ModelAuthError(f"Auth error: {response.text}", model_name="")
        if response.status_code == 429:
            raise ModelRateLimitError(f"Rate limited: {response.text}", model_name="")
        if response.status_code >= 500:
            raise ModelServerError(f"Server error: {response.text}", model_name="")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest src/tests/model_service/test_openai_provider.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/model_service/providers/openai_compatible.py src/tests/model_service/test_openai_provider.py
git commit -m "feat(model-service): implement OpenAICompatibleProvider"
```

---

### Task 5: ModelRouter

**Files:**
- Create: `src/model_service/router.py`
- Create: `src/tests/model_service/test_router.py`

- [ ] **Step 1: 编写 Router 测试**

```python
# src/tests/model_service/test_router.py
import pytest

from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE, ModelType
from src.model_service.router import ModelRouter


@pytest.fixture
def router():
    return ModelRouter()


def test_resolve_known_scene(router):
    model_name, fallbacks = router.resolve("settlement_exception_guidance", ModelType.LLM)
    assert model_name == "gpt-4o-mini"
    assert "gpt-3.5-turbo" in fallbacks


def test_resolve_unknown_scene_defaults(router):
    model_name, fallbacks = router.resolve("unknown_scene", ModelType.LLM)
    assert model_name == "gpt-4o-mini"


def test_resolve_embedding(router):
    model_name, fallbacks = router.resolve("any_scene", ModelType.EMBEDDING)
    assert model_name == "text-embedding-3-small"
    assert fallbacks == []


def test_get_model_params(router):
    params = router.get_model_params("gpt-4o-mini")
    assert params["temperature"] == 0.3
    assert params["max_tokens"] == 2048


def test_get_model_params_defaults(router):
    params = router.get_model_params("unknown-model")
    assert params["temperature"] == 0.7
    assert params["max_tokens"] == 2048
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/model_service/test_router.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 实现 ModelRouter**

```python
# src/model_service/router.py
from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE


class ModelRouter:
    def resolve(self, scene: str, model_type: str) -> tuple[str, list[str]]:
        key = (scene, model_type)
        model_name = ROUTING_TABLE.get(key)
        if model_name is None:
            model_name = ROUTING_TABLE.get(("default", model_type))
        fallbacks = FALLBACK_CHAINS.get(model_name, [])
        return model_name, list(fallbacks)

    def get_model_params(self, model_name: str) -> dict:
        default = {"temperature": 0.7, "max_tokens": 2048}
        return MODEL_PARAMS.get(model_name, default)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/tests/model_service/test_router.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/model_service/router.py src/tests/model_service/test_router.py
git commit -m "feat(model-service): implement ModelRouter with fallback chain"
```

---

### Task 6: ModelGateway

**Files:**
- Create: `src/model_service/gateway.py`
- Create: `src/tests/model_service/test_gateway.py`

- [ ] **Step 1: 编写 Gateway 测试**

```python
# src/tests/model_service/test_gateway.py
from unittest.mock import MagicMock, patch
from typing import Iterator

import pytest

from src.model_service.exceptions import (
    ModelAuthError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message, ModelResponse, StreamChunk, TokenUsage


@pytest.fixture
def gateway():
    return ModelGateway()


def _make_response(content="ok", model="gpt-4o-mini"):
    return ModelResponse(
        content=content,
        model_name=model,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        finish_reason="stop",
    )


def test_generate_success(gateway):
    messages = [Message(role="user", content="Hello")]
    with patch.object(gateway, "_call_provider", return_value=_make_response("Hi")):
        result = gateway.generate(messages, "llm", "test")
    assert result.content == "Hi"


def test_generate_retries_on_timeout(gateway):
    messages = [Message(role="user", content="Hello")]
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ModelTimeoutError("timeout", model_name="gpt-4o-mini")
        return _make_response()

    with patch.object(gateway, "_call_provider", side_effect=side_effect):
        result = gateway.generate(messages, "llm", "test")

    assert result.content == "ok"
    assert call_count == 3


def test_generate_fallback_on_exhausted(gateway):
    messages = [Message(role="user", content="Hello")]
    call_count = 0

    def side_effect(request, model_name):
        nonlocal call_count
        call_count += 1
        if model_name == "gpt-4o-mini":
            raise ModelServerError("server error", model_name="gpt-4o-mini")
        return _make_response(model="gpt-3.5-turbo")

    with patch.object(gateway, "_call_provider", side_effect=side_effect):
        result = gateway.generate(messages, "llm", "settlement_exception_guidance")

    assert result.model_name == "gpt-3.5-turbo"


def test_generate_auth_error_no_fallback(gateway):
    messages = [Message(role="user", content="Hello")]

    with patch.object(gateway, "_call_provider", side_effect=ModelAuthError("auth", model_name="gpt-4o-mini")):
        with pytest.raises(ModelAuthError):
            gateway.generate(messages, "llm", "test")


def test_generate_exhausted_error(gateway):
    messages = [Message(role="user", content="Hello")]

    with patch.object(gateway, "_call_provider", side_effect=ModelServerError("error", model_name="gpt-4o-mini")):
        with pytest.raises(ModelExhaustedError):
            gateway.generate(messages, "llm", "settlement_exception_guidance")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/model_service/test_gateway.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 实现 ModelGateway**

```python
# src/model_service/gateway.py
import logging
import time
from typing import Iterator

from src.config.model_service import ModelServiceConfig
from src.model_service.exceptions import (
    ModelAuthError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.models import Message, ModelRequest, ModelResponse, StreamChunk
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider
from src.model_service.router import ModelRouter

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 10


class ModelGateway:
    def __init__(self, router: ModelRouter | None = None):
        self._router = router or ModelRouter()
        self._config = ModelServiceConfig()

    def generate(self, messages: list[Message], model_type: str, scene: str) -> ModelResponse:
        model_name, fallbacks = self._router.resolve(scene, model_type)
        chain = [model_name] + fallbacks
        failures = []

        for current_model in chain:
            params = self._router.get_model_params(current_model)
            request = ModelRequest(
                messages=messages,
                model_type=current_model,
                scene=scene,
                temperature=params["temperature"],
                max_tokens=params["max_tokens"],
            )

            for attempt in range(self._config.max_retries):
                try:
                    start = time.time()
                    result = self._call_provider(request, current_model)
                    latency_ms = int((time.time() - start) * 1000)
                    logger.info(
                        "model_call_success",
                        extra={
                            "model_name": current_model,
                            "scene": scene,
                            "latency_ms": latency_ms,
                            "token_usage": result.usage,
                        },
                    )
                    return result
                except ModelAuthError:
                    logger.error("model_auth_error", extra={"model_name": current_model, "scene": scene})
                    raise
                except ModelRateLimitError:
                    logger.warning("model_rate_limit", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1})
                    if attempt < self._config.max_retries - 1:
                        time.sleep(RATE_LIMIT_DELAY)
                        continue
                    failures.append({"model_name": current_model, "error_type": "rate_limit", "error_message": "rate limited"})
                    break
                except (ModelTimeoutError, ModelServerError) as e:
                    logger.warning("model_retry", extra={"model_name": current_model, "scene": scene, "attempt": attempt + 1, "error": str(e)})
                    if attempt < self._config.max_retries - 1:
                        continue
                    failures.append({"model_name": current_model, "error_type": type(e).__name__, "error_message": str(e)})
                    break

        raise ModelExhaustedError("All models in fallback chain failed", failures=failures)

    def generate_stream(self, messages: list[Message], model_type: str, scene: str) -> Iterator[StreamChunk]:
        model_name, _ = self._router.resolve(scene, model_type)
        params = self._router.get_model_params(model_name)
        request = ModelRequest(
            messages=messages,
            model_type=model_name,
            scene=scene,
            temperature=params["temperature"],
            max_tokens=params["max_tokens"],
        )

        start = time.time()
        total_chunks = 0
        try:
            provider = self._get_provider(model_name)
            for chunk in provider.invoke_stream(request):
                total_chunks += 1
                yield chunk
            latency_ms = int((time.time() - start) * 1000)
            logger.info("model_stream_success", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms})
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.error("model_stream_interrupted", extra={"model_name": model_name, "scene": scene, "total_chunks": total_chunks, "latency_ms": latency_ms, "error": str(e)})

    def _call_provider(self, request: ModelRequest, model_name: str) -> ModelResponse:
        provider = self._get_provider(model_name)
        return provider.invoke(request)

    def _get_provider(self, model_name: str) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            base_url=self._config.base_url,
            api_key=self._config.api_key,
            timeout=self._config.default_timeout,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/tests/model_service/test_gateway.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/model_service/gateway.py src/tests/model_service/test_gateway.py
git commit -m "feat(model-service): implement ModelGateway with retry and fallback"
```

---

### Task 7: 全量测试 + 清理

**Files:**
- Modify: `src/model_service/__init__.py`

- [ ] **Step 1: 运行全部 model_service 测试**

Run: `python -m pytest src/tests/model_service/ -v`
Expected: 14 passed (4 provider + 5 router + 5 gateway)

- [ ] **Step 2: 更新 __init__.py 导出**

```python
# src/model_service/__init__.py
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message, ModelRequest, ModelResponse, StreamChunk, TokenUsage
from src.model_service.router import ModelRouter

__all__ = [
    "ModelGateway",
    "ModelRouter",
    "Message",
    "ModelRequest",
    "ModelResponse",
    "StreamChunk",
    "TokenUsage",
]
```

- [ ] **Step 3: 运行全部测试确认无回归**

Run: `python -m pytest src/tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add src/model_service/__init__.py
git commit -m "feat(model-service): export public API from __init__"
```
