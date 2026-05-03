# 模型服务网络异常归一化修复设计

## 背景

页面调用 [`testModel()`](src/static/index.html:276) 时，后端 [`model_test()`](src/runtime/api/routes.py:92) 触发真实模型调用。用户提供的运行时 traceback 显示，异常根因是 [`OpenAICompatibleProvider.invoke()`](src/model_service/providers/openai_compatible.py:16) 中的 [`httpx.Client.post()`](src/model_service/providers/openai_compatible.py:19) 抛出了 `httpx.ReadTimeout`。

当前 [`ModelGateway.generate()`](src/model_service/gateway.py:27) 已经具备对 [`ModelTimeoutError`](src/model_service/exceptions.py:7) 和 [`ModelServerError`](src/model_service/exceptions.py:19) 的重试逻辑，但 provider 层没有把 `httpx` 网络异常转换成领域异常，导致 `httpx.ReadTimeout` 直接冒泡到 FastAPI，最终返回裸 `500 Internal Server Error`。

## 目标

1. 在 provider 边界统一归一化 `httpx` 网络异常，避免三方库异常穿透到 API 层。
2. 将 `httpx.TimeoutException` 转换为 [`ModelTimeoutError`](src/model_service/exceptions.py:7)，复用 [`ModelGateway.generate()`](src/model_service/gateway.py:67) 的既有重试逻辑。
3. 将 `httpx.NetworkError` 与其余 `httpx.HTTPError` 转换为可由网关或路由处理的领域异常。
4. [`/model-test`](src/runtime/api/routes.py:92) 在超时重试耗尽或网络失败时返回结构化 JSON 错误，不再返回裸 `Internal Server Error`。
5. 增加 timeout/network error 覆盖测试，并执行完整验证命令 [`python -m pytest src/tests -v`](AGENTS.md)。

## 非目标

1. 不改变模型路由策略与默认模型配置。
2. 不改变真实上游供应商或 API 协议。
3. 不新增异步客户端或流式调用架构重构。
4. 不在页面层隐藏后端错误，只保证后端返回结构化错误、前端展示友好消息。

## 方案对比

### 方案 A：只在 API 路由捕获 `httpx.ReadTimeout`

在 [`model_test()`](src/runtime/api/routes.py:92) 中直接捕获 `httpx.ReadTimeout` 并返回 JSON。

优点：改动最少。

缺点：三方库异常穿透业务层，绕过 [`ModelGateway.generate()`](src/model_service/gateway.py:27) 的重试机制，且其他调用入口仍可能裸 500。

### 方案 B：只在 gateway 捕获 `httpx` 异常

在 [`ModelGateway.generate()`](src/model_service/gateway.py:27) 中捕获 `httpx` 异常并转换。

优点：能复用重试逻辑。

缺点：provider 边界不清晰，未来其他 provider 调用方法仍会泄漏底层异常。

### 方案 C：provider 层统一转换为领域异常

在 [`OpenAICompatibleProvider`](src/model_service/providers/openai_compatible.py) 内将 `httpx.TimeoutException`、`httpx.NetworkError`、其余 `httpx.HTTPError` 归一化为领域异常，再由 gateway 和 API 层按已有职责处理。

优点：边界清晰、复用既有重试逻辑、后续扩展更稳健。

结论：采用方案 C。

## 详细设计

### provider 层异常归一化

在 [`OpenAICompatibleProvider.invoke()`](src/model_service/providers/openai_compatible.py:16) 与 [`OpenAICompatibleProvider.invoke_embedding()`](src/model_service/providers/openai_compatible.py:58) 中捕获 `httpx` 异常：

- `httpx.TimeoutException` → [`ModelTimeoutError`](src/model_service/exceptions.py:7)
- `httpx.NetworkError` → [`ModelServerError`](src/model_service/exceptions.py:19)
- 其他 `httpx.HTTPError` → [`ModelServerError`](src/model_service/exceptions.py:19)

转换后的异常消息保留可排查信息，但不泄露密钥或请求头。

### gateway 层重试行为

[`ModelGateway.generate()`](src/model_service/gateway.py:67) 已捕获 [`ModelTimeoutError`](src/model_service/exceptions.py:7) 与 [`ModelServerError`](src/model_service/exceptions.py:19)，并在重试耗尽后追加 failures，继续尝试 fallback 链。无需改变其核心算法。

当所有模型均失败时，继续抛出 [`ModelExhaustedError`](src/model_service/exceptions.py:23)。

### API 层错误返回

[`model_test()`](src/runtime/api/routes.py:92) 已对 [`ModelExhaustedError`](src/model_service/exceptions.py:23) 返回结构化 JSON。为提升用户可读性，可在 `MODEL_EXHAUSTED` 的消息中保持“模型服务回退链已耗尽，请稍后重试”。

如后续选择增加更细错误码，可扩展为 `MODEL_TIMEOUT` 或 `MODEL_NETWORK_ERROR`，但本次优先复用当前 `MODEL_EXHAUSTED`，因为超时会进入重试与 fallback 链，最终错误语义是“可用链路耗尽”。

### 前端行为

[`testModel()`](src/static/index.html:276) 已具备 JSON 与非 JSON 响应兜底解析。后端修复后，页面应展示后端结构化错误消息，不再展示裸 `Internal Server Error`。

## 测试设计

1. 在 [`src/tests/model_service/test_openai_provider.py`](src/tests/model_service/test_openai_provider.py) 中新增测试，模拟 `httpx.ReadTimeout`，断言 provider 抛出 [`ModelTimeoutError`](src/model_service/exceptions.py:7)。
2. 新增测试模拟 `httpx.ConnectError` 或 `httpx.NetworkError`，断言 provider 抛出 [`ModelServerError`](src/model_service/exceptions.py:19)。
3. 在 [`src/tests/integration/test_openapi_contract.py`](src/tests/integration/test_openapi_contract.py) 中新增测试，让 [`ModelGateway.generate()`](src/model_service/gateway.py:27) 抛出 [`ModelExhaustedError`](src/model_service/exceptions.py:23)，断言 [`/model-test`](src/runtime/api/routes.py:92) 返回结构化 JSON。
4. 执行定向测试与完整 [`pytest`](AGENTS.md) 验证。

## 验证计划

1. 运行 provider 定向测试：`python -m pytest src/tests/model_service/test_openai_provider.py -v`
2. 运行 API 契约测试：`python -m pytest src/tests/integration/test_openapi_contract.py -v`
3. 运行完整测试：[`python -m pytest src/tests -v`](AGENTS.md)
4. 页面手工验证：启动服务后点击 [`LLM 基础调用`](src/static/index.html:94)，上游超时时页面展示结构化错误消息，不再显示裸 `Internal Server Error`。

## 风险与边界条件

1. `httpx.TimeoutException` 包含连接超时、读超时、写超时与池超时，统一归为 [`ModelTimeoutError`](src/model_service/exceptions.py:7)。
2. `httpx.HTTPStatusError` 当前不会由现有代码主动抛出，因为状态码处理走 [`_check_status()`](src/model_service/providers/openai_compatible.py:109)，但仍可作为兜底归为 [`ModelServerError`](src/model_service/exceptions.py:19)。
3. 网络异常消息不应包含 Authorization header 或 API Key。
