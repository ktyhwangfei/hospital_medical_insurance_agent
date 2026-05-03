# Model Test Error Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 [`/model-test`](src/runtime/api/routes.py:92) 建立统一的结构化错误响应，并让 [`testModel()`](src/static/index.html:276) 在非 JSON 响应下仍能展示友好错误提示，消除页面 `Unexpected token` 报错。

**Architecture:** 采用后端与前端双侧修复方案。后端在 [`model_test()`](src/runtime/api/routes.py:92) 中拦截模型服务异常并映射为统一错误体；前端在 [`testModel()`](src/static/index.html:276) 中实现“优先 JSON、失败回退文本”的解析链路。测试按 TDD 拆分为后端接口异常映射、配置缺失提示与前端容错路径三个层次。

**Tech Stack:** Python, FastAPI, Pydantic, pytest, 原生 HTML/JavaScript, httpx

---

### Task 1: 为 model-test 路由补充失败测试并固定接口契约

**Files:**
- Modify: `src/tests/integration/test_openapi_contract.py`
- Modify: `src/tests/model_service/test_gateway.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 在 [`src/tests/integration/test_openapi_contract.py`](src/tests/integration/test_openapi_contract.py) 新增 model-test 鉴权失败用例**

```python
from fastapi.testclient import TestClient
from src.model_service.exceptions import ModelAuthError
from src.runtime.api.app import create_app


def test_model_test_returns_json_error_when_gateway_auth_fails(monkeypatch):
    from src.runtime.api import routes

    def fake_generate(self, messages, model_type, scene):
        raise ModelAuthError("Auth error: missing api key")

    monkeypatch.setattr(routes.ModelGateway, "generate", fake_generate)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-test",
        json={"message": "你好", "scene": "default"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["detail"]["error_code"] == "MODEL_CONFIG_ERROR"
    assert "MODEL_API_KEY" in body["detail"]["message"]
```

- [ ] **Step 2: 运行新增接口测试并确认先失败**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_model_test_returns_json_error_when_gateway_auth_fails -v`

Expected: FAIL，当前 [`model_test()`](src/runtime/api/routes.py:92) 未捕获 [`ModelAuthError`](src/model_service/exceptions.py:15) 或返回的不是约定 JSON 错误体。

- [ ] **Step 3: 在 [`src/tests/model_service/test_gateway.py`](src/tests/model_service/test_gateway.py) 补充配置缺失判断的单元测试**

```python
from src.model_service.exceptions import ModelAuthError
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message


def test_generate_auth_error_can_be_classified_as_missing_api_key(monkeypatch):
    gateway = ModelGateway()
    monkeypatch.setattr(gateway._config, "api_key", "")

    def fake_call_provider(request, model_name):
        raise ModelAuthError("Auth error: missing api key", model_name=model_name)

    monkeypatch.setattr(gateway, "_call_provider", fake_call_provider)

    try:
        gateway.generate(messages=[Message(role="user", content="hi")], model_type="llm", scene="default")
    except ModelAuthError as exc:
        assert "missing api key" in str(exc)
    else:
        raise AssertionError("expected ModelAuthError")
```

- [ ] **Step 4: 运行目标单元测试并确认先失败或保持红灯预期**

Run: `python -m pytest src/tests/model_service/test_gateway.py::test_generate_auth_error_can_be_classified_as_missing_api_key -v`

Expected: 若实现尚未引入额外分类逻辑，则此测试用于固定当前异常上下文，至少可通过异常内容断言；如需调整测试以适配最终设计，应在后续实现后更新为最终断言。

- [ ] **Step 5: 提交测试基线**

```bash
git add src/tests/integration/test_openapi_contract.py src/tests/model_service/test_gateway.py
git commit -m "test: add model-test error handling coverage"
```

### Task 2: 在后端统一 model-test 错误映射

**Files:**
- Modify: `src/runtime/api/routes.py`
- Modify: `src/shared/schemas/responses.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: 先阅读当前错误体构造函数并确认可复用边界**

Read [`error_detail()`](src/shared/schemas/responses.py) 并确认返回结构包含 `error_code`、`message`、`audit_event`，避免在 [`model_test()`](src/runtime/api/routes.py:92) 手写不一致字典。

- [ ] **Step 2: 在 [`src/runtime/api/routes.py`](src/runtime/api/routes.py) 中新增 model-test 异常映射实现**

```python
from src.config.model_service import ModelServiceConfig
from src.model_service.exceptions import (
    ModelAuthError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
)


@router.post('/model-test')
def model_test(request: ModelTestRequest) -> ModelTestResponse:
    gateway = ModelGateway()
    messages = [Message(role='user', content=request.message)]
    start = time.time()
    try:
        result = gateway.generate(messages=messages, model_type='llm', scene=request.scene)
    except ModelAuthError as exc:
        config = ModelServiceConfig()
        if not config.api_key:
            raise HTTPException(
                status_code=503,
                detail=error_detail(
                    'MODEL_CONFIG_ERROR',
                    '模型服务未配置 API Key，请先设置环境变量 MODEL_API_KEY',
                    {'event_type': 'model_config_error'},
                ),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=error_detail(
                'MODEL_AUTH_ERROR',
                '模型服务鉴权失败，请检查 API Key 是否有效',
                {'event_type': 'model_auth_error'},
            ),
        ) from exc
    except ModelRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=error_detail(
                'MODEL_RATE_LIMITED',
                '模型服务请求过于频繁，请稍后重试',
                {'event_type': 'model_rate_limited'},
            ),
        ) from exc
    except ModelServerError as exc:
        raise HTTPException(
            status_code=502,
            detail=error_detail(
                'MODEL_UPSTREAM_ERROR',
                '模型服务上游暂时不可用，请稍后重试',
                {'event_type': 'model_upstream_error'},
            ),
        ) from exc
    except ModelExhaustedError as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                'MODEL_EXHAUSTED',
                '模型服务回退链已耗尽，请稍后重试',
                {'event_type': 'model_exhausted'},
            ),
        ) from exc

    latency_ms = int((time.time() - start) * 1000)
    return ModelTestResponse(
        content=result.content,
        model_name=result.model_name,
        latency_ms=latency_ms,
        prompt_tokens=result.usage.prompt_tokens,
        completion_tokens=result.usage.completion_tokens,
    )
```

- [ ] **Step 3: 如有必要，在 [`src/shared/schemas/responses.py`](src/shared/schemas/responses.py) 中补足错误体辅助函数的类型声明，但不要改变既有契约**

```python
def error_detail(error_code: str, message: str, audit_event: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error_code": error_code,
        "message": message,
        "audit_event": audit_event or {},
    }
```

- [ ] **Step 4: 运行接口测试验证后端错误 JSON 化**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py::test_model_test_returns_json_error_when_gateway_auth_fails -v`

Expected: PASS，返回 `503` 与 `application/json`，且错误码为 `MODEL_CONFIG_ERROR`。

- [ ] **Step 5: 提交后端错误映射实现**

```bash
git add src/runtime/api/routes.py src/shared/schemas/responses.py src/tests/integration/test_openapi_contract.py
git commit -m "fix: unify model-test error responses"
```

### Task 3: 为前端模型测试增加非 JSON 容错解析

**Files:**
- Modify: `src/static/index.html`
- Test: `src/static/index.html`

- [ ] **Step 1: 先在 [`src/static/index.html`](src/static/index.html) 中抽取响应解析辅助函数，便于最小化测试与复用**

```javascript
async function parseApiResponse(resp) {
  const contentType = (resp.headers.get('content-type') || '').toLowerCase();
  if (contentType.includes('application/json')) {
    try {
      return { kind: 'json', data: await resp.json() };
    } catch (e) {
      return { kind: 'text', data: await resp.text() };
    }
  }
  return { kind: 'text', data: await resp.text() };
}
```

- [ ] **Step 2: 运行页面手工复现，确认当前仍会报 `Unexpected token` 作为红灯基线**

Run: 在浏览器点击 [`LLM 基础调用`](src/static/index.html:94)

Expected: 当前实现会在 [`resp.json()`](src/static/index.html:284) 遇到非 JSON 时显示 `Unexpected token`。

- [ ] **Step 3: 用最小改动重写 [`testModel()`](src/static/index.html:276) 的错误分支**

```javascript
async function testModel(msg) {
  addMsg('user', '[模型测试] ' + escapeHtml(msg));
  try {
    const resp = await fetch(API + '/model-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, scene: 'default' }),
    });

    const parsed = await parseApiResponse(resp);

    if (!resp.ok) {
      let message = '模型调用失败，请稍后重试';
      if (parsed.kind === 'json') {
        const detail = parsed.data.detail || {};
        message = detail.message || resp.statusText || message;
      } else if (parsed.data) {
        message = parsed.data || resp.statusText || message;
      }
      addMsg('bot', '<span style="color:#f53f3f">模型调用失败：' + escapeHtml(message) + '</span>');
      return;
    }

    const data = parsed.data;
    let html = '<h3>模型服务测试</h3>';
    html += '<div class="field"><span class="label">模型：</span><span class="value">' + escapeHtml(data.model_name) + '</span></div>';
    html += '<div class="field"><span class="label">耗时：</span><span class="value">' + data.latency_ms + 'ms</span></div>';
    html += '<div class="field"><span class="label">Token：</span><span class="value">输入 ' + data.prompt_tokens + ' / 输出 ' + data.completion_tokens + '</span></div>';
    html += '<div class="field" style="margin-top:8px;padding:12px;background:#f7f8fa;border-radius:6px;white-space:pre-wrap">' + escapeHtml(data.content) + '</div>';
    addMsg('bot', html);
  } catch (e) {
    addMsg('bot', '<span style="color:#f53f3f">请求失败：' + escapeHtml(e.message) + '</span>');
  }
}
```

- [ ] **Step 4: 手工验证页面失败路径不再展示 JSON 解析错误**

Run: 启动服务后点击 [`LLM 基础调用`](src/static/index.html:94)

Expected: 当后端返回 JSON 错误时，页面展示“模型服务未配置 API Key，请先设置环境变量 MODEL_API_KEY”；若后端仍返回纯文本，也只展示该文本，不再出现 `Unexpected token`。

- [ ] **Step 5: 提交前端容错逻辑**

```bash
git add src/static/index.html
git commit -m "fix: handle non-json model-test errors in page"
```

### Task 4: 完善异常分支测试并做完整验证

**Files:**
- Modify: `src/tests/integration/test_openapi_contract.py`
- Modify: `src/tests/model_service/test_gateway.py`
- Test: `src/tests`

- [ ] **Step 1: 在 [`src/tests/integration/test_openapi_contract.py`](src/tests/integration/test_openapi_contract.py) 增加限流与上游失败映射测试**

```python
from src.model_service.exceptions import ModelRateLimitError, ModelServerError


def test_model_test_returns_rate_limit_error(monkeypatch):
    from src.runtime.api import routes

    def fake_generate(self, messages, model_type, scene):
        raise ModelRateLimitError("Rate limited")

    monkeypatch.setattr(routes.ModelGateway, "generate", fake_generate)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-test",
        json={"message": "你好", "scene": "default"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["error_code"] == "MODEL_RATE_LIMITED"


def test_model_test_returns_upstream_error(monkeypatch):
    from src.runtime.api import routes

    def fake_generate(self, messages, model_type, scene):
        raise ModelServerError("Server error")

    monkeypatch.setattr(routes.ModelGateway, "generate", fake_generate)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-test",
        json={"message": "你好", "scene": "default"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["error_code"] == "MODEL_UPSTREAM_ERROR"
```

- [ ] **Step 2: 运行新增异常分支测试**

Run: `python -m pytest src/tests/integration/test_openapi_contract.py -v`

Expected: PASS，`/model-test` 的关键错误分支均返回结构化 JSON。

- [ ] **Step 3: 执行完整测试验证**

Run: `python -m pytest src/tests -v`

Expected: 如果存在与本任务无关的既有失败，应在结果记录中明确列出；若本次修改未引入回归，则与本任务相关测试全部通过。

- [ ] **Step 4: 记录人工页面验证结论**

Run: 浏览器打开 [`/`](src/runtime/api/app.py:17)，点击 [`LLM 基础调用`](src/static/index.html:94)

Expected: 页面展示结构化错误提示或文本错误提示，不再出现 `Unexpected token 'I'`。

- [ ] **Step 5: 提交验证与收尾变更**

```bash
git add src/tests/integration/test_openapi_contract.py src/tests/model_service/test_gateway.py src/runtime/api/routes.py src/static/index.html
git commit -m "test: verify model-test error handling"
```

## 自检结果

- 规格覆盖：已覆盖后端统一 JSON 错误响应、前端非 JSON 容错解析、配置缺失提示、测试补充与完整验证。
- 占位符扫描：计划中未保留 `TODO`、`TBD` 或“自行处理”类描述；每个任务都给出了具体文件、命令与代码片段。
- 一致性检查：错误码命名统一为 `MODEL_CONFIG_ERROR`、`MODEL_AUTH_ERROR`、`MODEL_RATE_LIMITED`、`MODEL_UPSTREAM_ERROR`、`MODEL_EXHAUSTED`，与设计文档保持一致。
