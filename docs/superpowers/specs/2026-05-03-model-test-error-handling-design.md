# model-test 错误处理修复设计

## 背景

页面中的 [`testModel()`](src/static/index.html:276) 调用 [`POST /api/v1/medical-insurance-ai-agent/model-test`](src/runtime/api/routes.py:92) 进行模型服务测试。当前实现默认对所有响应执行 JSON 解析；当后端出现未捕获异常时，FastAPI 返回纯文本 `Internal Server Error`，浏览器在解析阶段报出 `Unexpected token 'I'`，用户只能看到前端解析错误，而无法获得真实失败原因。

排查证据表明，当前模型配置中的 [`MODEL_API_KEY`](src/config/model_service.py:6) 为空时，模型调用链会在 [`OpenAICompatibleProvider._check_status()`](src/model_service/providers/openai_compatible.py:109) 抛出 [`ModelAuthError`](src/model_service/exceptions.py:15)。该异常未被 [`model_test()`](src/runtime/api/routes.py:92) 捕获，也未转换为结构化错误响应。

## 目标

本次修复目标如下：

1. [`/model-test`](src/runtime/api/routes.py:92) 在模型异常、配置错误或上游失败时，统一返回结构化 JSON 错误体。
2. [`testModel()`](src/static/index.html:276) 不再假设所有错误响应都是 JSON；当后端或中间层返回非 JSON 内容时，页面仍能展示可读错误信息。
3. 对高频配置问题，特别是 [`MODEL_API_KEY`](src/config/model_service.py:6) 未配置，给出明确、可操作的错误提示。
4. 增加测试覆盖接口异常映射与前端容错路径，并通过完整 [`pytest`](AGENTS.md) 验证。

## 非目标

本次不处理以下事项：

1. 不修改模型路由默认值与 [`ModelRouter`](src/model_service/router.py) 现有策略。
2. 不引入新的前端框架、构建流程或静态资源拆分。
3. 不扩展模型服务能力范围，仅修复现有测试入口的错误处理一致性。

## 方案对比

### 方案 A：仅修后端

在 [`model_test()`](src/runtime/api/routes.py:92) 中统一捕获模型异常并返回 JSON。

优点：后端契约统一。

缺点：若未来出现网关、代理或框架级 HTML/纯文本错误，前端仍可能在 [`resp.json()`](src/static/index.html:284) 失败。

### 方案 B：仅修前端

修改 [`testModel()`](src/static/index.html:276) 的响应解析，兼容非 JSON 文本。

优点：页面不再因解析失败报错。

缺点：后端接口仍然返回不一致错误体，其他调用者继续受影响。

### 方案 C：后端统一错误 + 前端兜底兼容

后端将模型异常转换为结构化 JSON，前端增加 JSON/文本双通道解析与友好提示。

优点：同时解决接口一致性与页面健壮性问题；也是最符合当前目标的方案。

结论：采用方案 C。

## 详细设计

### 后端设计

在 [`model_test()`](src/runtime/api/routes.py:92) 中新增异常映射层，职责如下：

1. 捕获 [`ModelAuthError`](src/model_service/exceptions.py:15)
2. 捕获 [`ModelRateLimitError`](src/model_service/exceptions.py:11)
3. 捕获 [`ModelServerError`](src/model_service/exceptions.py:19)
4. 捕获 [`ModelExhaustedError`](src/model_service/exceptions.py:23)

所有异常统一通过 [`error_detail()`](src/shared/schemas/responses.py) 返回结构化错误，字段格式保持与现有 API 一致。

建议的错误映射：

- `MODEL_CONFIG_ERROR`：当检测到 [`ModelServiceConfig.api_key`](src/config/model_service.py:6) 为空或鉴权失败可明确归因为本地未配置时返回，状态码 `503`
- `MODEL_AUTH_ERROR`：上游明确鉴权失败且不能确认是本地漏配时返回，状态码 `502` 或 `401/403` 的网关转义结果，当前接口层统一返回 `502`
- `MODEL_RATE_LIMITED`：上游限流，状态码 `429`
- `MODEL_UPSTREAM_ERROR`：上游 5xx，状态码 `502`
- `MODEL_EXHAUSTED`：回退链全部失败，状态码 `503`

返回消息应以用户可理解为原则。例如当 [`MODEL_API_KEY`](src/config/model_service.py:6) 未配置时，错误消息应明确指出“模型服务未配置 API Key，请先设置环境变量 MODEL_API_KEY”。

### 前端设计

修改 [`testModel()`](src/static/index.html:276) 的响应处理流程：

1. 读取响应头中的 `content-type`
2. 若为 JSON，则尝试解析 JSON
3. 若不是 JSON，则改读文本内容
4. 若 JSON 解析失败，回退为可读文本或默认错误消息

错误提示优先级：

1. `detail.message`
2. 纯文本响应体
3. `resp.statusText`
4. 默认提示“模型调用失败，请稍后重试”

这样即使后端未来仍返回框架默认纯文本，页面也不会再显示 `Unexpected token 'I'`。

### 测试设计

新增或调整以下测试：

1. 后端接口测试：验证 [`/model-test`](src/runtime/api/routes.py:92) 在模型鉴权异常时返回 JSON 错误体
2. 后端接口测试：验证未配置 [`MODEL_API_KEY`](src/config/model_service.py:6) 时返回明确错误消息
3. 前端逻辑测试或最小单元覆盖：验证非 JSON 响应场景不会因强制 JSON 解析而中断

若当前项目没有现成前端测试框架，可优先将解析逻辑抽成小函数，便于以最小成本测试；若不引入新框架，则至少保证后端统一 JSON 后页面主路径可稳定工作，并在静态脚本中实现文本回退逻辑。

## 风险与边界条件

1. 上游厂商返回 401/403 时，无法总是准确区分“本地未配置 API Key”和“Key 错误/失效”；实现中需优先判断本地配置是否为空，再决定错误码。
2. 若存在反向代理插入 HTML 错误页，前端仍应走文本回退并展示摘要文本，而不是再次抛解析异常。
3. 不应泄露完整上游报错或敏感凭据，错误消息需保留可操作性但避免暴露密钥内容。

## 验证计划

实现完成后执行完整验证命令 [`python -m pytest src/tests -v`](AGENTS.md)。

验证重点：

1. [`/model-test`](src/runtime/api/routes.py:92) 的错误响应格式稳定
2. 页面模型测试按钮在失败路径下展示友好提示而非 JSON 解析错误
3. 现有场景测试不受本次修改影响
