# 全过程流式问答改造设计

## 背景

当前演示页面 [`src/static/index.html`](src/static/index.html) 的业务导办请求通过 [`callChat()`](src/static/index.html:239) 调用 [`POST /api/v1/medical-insurance-ai-agent/chat`](src/runtime/api/routes.py:28)，模型测试通过 [`testModel()`](src/static/index.html:276) 调用 [`POST /api/v1/medical-insurance-ai-agent/model-test`](src/runtime/api/routes.py:94)。两者都使用普通 [`fetch()`](src/static/index.html:248) 并在响应完成后执行 [`resp.json()`](src/static/index.html:249)，因此页面表现为一次性返回。

底层模型服务已经存在 [`ModelGateway.generate_stream()`](src/model_service/gateway.py:76) 与 [`OpenAICompatibleProvider.invoke_stream()`](src/model_service/providers/openai_compatible.py:33)，但 API 层未暴露流式路由，前端也未使用 `ReadableStream` 或 SSE 事件协议消费分片。

用户目标是：

1. LLM 基础调用逐字或分片流式显示。
2. 业务导办按步骤事件流式展示全过程。
3. 必须保留现有非流式接口，兼容旧页面和既有测试。
4. 前端需要保留开关，可切换流式/非流式模式。

## 目标

本次改造目标如下：

1. 保留 [`/chat`](src/runtime/api/routes.py:28) 与 [`/model-test`](src/runtime/api/routes.py:94) 的现有非流式接口契约不变。
2. 新增 [`/chat/stream`](src/runtime/api/routes.py:28) 作为业务导办全过程事件流接口。
3. 新增 [`/model-test/stream`](src/runtime/api/routes.py:94) 作为 LLM 基础调用文本分片流接口。
4. 前端新增“流式模式”开关，开启时使用流式接口，关闭时继续使用现有非流式接口。
5. 流式失败时，前端展示结构化错误或可读错误信息；不破坏现有非流式降级能力。
6. 增加后端流式接口测试与前端关键逻辑验证，最终执行完整 [`python -m pytest src/tests -v`](AGENTS.md)。

## 非目标

1. 不替换现有业务导办场景服务。
2. 不改变 [`AgentResponse`](src/runtime/api/schemas.py:14) 的非流式响应结构。
3. 不引入前端构建工具或框架。
4. 不把业务导办最终结果改为纯文本；业务最终结果仍以现有结构化卡片展示。

## 方案对比

### 方案 A：只做 LLM 基础调用流式

新增 [`/model-test/stream`](src/runtime/api/routes.py:94)，页面只对模型测试按钮使用流式文本展示。

优点：改动小，最容易落地。

缺点：业务导办按钮仍然一次性返回，不满足“全过程流式”。

### 方案 B：统一 SSE 事件流

新增 [`/chat/stream`](src/runtime/api/routes.py:28) 与 [`/model-test/stream`](src/runtime/api/routes.py:94)，统一采用 `text/event-stream` 风格的事件格式，前端用 [`fetch()`](src/static/index.html:248) + `ReadableStream` 读取并解析事件。

优点：兼容 `POST` 请求体，适合当前 [`ChatRequest`](src/runtime/api/schemas.py:6) 与 [`ModelTestRequest`](src/runtime/api/schemas.py:60)；不受 `EventSource` 只能 `GET` 的限制；可承载步骤事件、文本分片、最终结构化结果与错误事件。

缺点：前端需要实现轻量 SSE parser。

### 方案 C：WebSocket 双向通道

新增 WebSocket 端点承载业务导办和模型流式消息。

优点：实时能力强，适合复杂交互。

缺点：超出当前 MVP 必要范围，测试和错误处理复杂度更高。

结论：采用方案 B。

## 流式协议设计

采用 `text/event-stream` 格式，每个事件包含 `event` 与 `data`：

```text
event: step
data: {"step":"intent_detection","message":"正在识别意图"}

event: final
data: {"status":"completed","scenario":"settlement_exception_guidance",...}

event: done
data: {}
```

### 业务导办事件类型

[`/chat/stream`](src/runtime/api/routes.py:28) 输出以下事件：

1. `step`：流程步骤提示。
   - `intent_detection`：正在识别意图
   - `risk_control`：正在检查高风险动作
   - `authorization`：正在校验角色权限
   - `scenario_processing`：正在执行场景导办
   - `response_rendering`：正在生成结构化结果
2. `final`：最终 [`AgentResponse`](src/runtime/api/schemas.py:14) 的 JSON 序列化结果。
3. `error`：结构化错误，包含 `error_code` 与 `message`。
4. `done`：流结束。

业务导办流式接口不改变现有业务结果，只是在执行关键阶段前后发出步骤事件，最终仍返回完整结构化结果，前端用现有 [`renderResult()`](src/static/index.html:141) 渲染卡片。

### 模型测试事件类型

[`/model-test/stream`](src/runtime/api/routes.py:94) 输出以下事件：

1. `start`：返回模型名或场景信息。
2. `delta`：返回一段文本分片。
3. `final`：返回完成信息，例如模型名、token 用量、结束原因。
4. `error`：结构化错误。
5. `done`：流结束。

前端收到 `delta` 时持续追加到同一个消息气泡中，实现逐字或分片显示。

## 后端设计

### 新增工具函数

在 [`src/runtime/api/routes.py`](src/runtime/api/routes.py) 或新文件 [`src/runtime/api/streaming.py`](src/runtime/api/streaming.py) 中提供事件格式化函数：

```python
def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

若实现中发现 [`routes.py`](src/runtime/api/routes.py) 继续膨胀，应优先创建 [`src/runtime/api/streaming.py`](src/runtime/api/streaming.py)，保持职责边界清晰。

### [`/chat/stream`](src/runtime/api/routes.py:28)

新增 `POST /chat/stream`，接收与 [`chat()`](src/runtime/api/routes.py:28) 相同的 [`ChatRequest`](src/runtime/api/schemas.py:6)。内部复用现有业务逻辑，但在关键阶段 yield 事件。

为了避免复制太多逻辑，可抽取共享函数，例如：

- [`process_chat_request()`](src/runtime/api/routes.py:28)：返回 [`AgentResponse`](src/runtime/api/schemas.py:14)
- [`chat()`](src/runtime/api/routes.py:28)：直接返回该结果
- [`chat_stream()`](src/runtime/api/routes.py:28)：在步骤事件之间调用相同处理逻辑并 yield `final`

### [`/model-test/stream`](src/runtime/api/routes.py:94)

新增 `POST /model-test/stream`，接收 [`ModelTestRequest`](src/runtime/api/schemas.py:60)，调用 [`ModelGateway.generate_stream()`](src/model_service/gateway.py:76)，将每个 [`StreamChunk`](src/model_service/models.py) 映射为 `delta` 事件。

若 [`generate_stream()`](src/model_service/gateway.py:76) 中断，应输出 `error` 事件，并最终输出 `done`。

## 前端设计

### 流式模式开关

在 [`src/static/index.html`](src/static/index.html) 侧边栏增加一个开关：

- 标签：`流式模式`
- 默认：开启
- 行为：
  - 开启：业务请求调用 [`/chat/stream`](src/runtime/api/routes.py:28)，模型测试调用 [`/model-test/stream`](src/runtime/api/routes.py:94)
  - 关闭：继续使用 [`/chat`](src/runtime/api/routes.py:28) 与 [`/model-test`](src/runtime/api/routes.py:94)

### 事件流解析

前端使用 `fetch()` 发起 `POST`，再使用：

- `resp.body.getReader()`
- `TextDecoder`
- 按 `\n\n` 切分事件块

解析 `event:` 与 `data:` 后分发到不同渲染函数。

### 业务导办渲染

流式业务导办分两层展示：

1. 步骤事件：追加或更新“正在识别意图 → 正在检查风控 → 正在执行场景导办”等过程提示。
2. 最终结果：收到 `final` 后调用现有 [`renderResult()`](src/static/index.html:141) 生成完整结构化结果卡片。

### 模型测试渲染

模型测试收到 `delta` 时持续更新同一个气泡中的文本区域，收到 `final` 后补充模型名、token 和结束信息。

## 错误处理

1. 后端流式接口必须捕获业务异常并输出 `error` 事件。
2. 模型超时、网络异常与回退链耗尽应复用现有结构化错误映射。
3. 前端流式读取失败时，显示“流式请求失败”，并提示用户可关闭流式模式重试。
4. 非流式接口保持现有错误处理逻辑。

## 测试设计

1. API 契约测试：验证 [`/chat/stream`](src/runtime/api/routes.py:28) 返回 `text/event-stream`，包含 `step`、`final`、`done`。
2. API 契约测试：验证 [`/model-test/stream`](src/runtime/api/routes.py:94) 返回 `delta` 或 `error` 与 `done`。
3. 回归测试：现有 [`/chat`](src/runtime/api/routes.py:28) 与 [`/model-test`](src/runtime/api/routes.py:94) 测试不变且继续通过。
4. 前端手工验证：开关开启时逐步显示，关闭时一次性返回。

## 验证计划

1. 运行流式接口定向测试。
2. 运行完整 [`python -m pytest src/tests -v`](AGENTS.md)。
3. 启动服务：`uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 18080 --factory`。
4. 页面验证：
   - 流式模式开启：点击 [`LLM 基础调用`](src/static/index.html:94)，文本逐步追加。
   - 流式模式开启：点击 [`结算异常导办`](src/static/index.html:87)，步骤事件逐步出现，最终渲染结构化卡片。
   - 流式模式关闭：两类按钮继续走现有一次性返回。

## 风险与边界条件

1. 当前业务导办并不依赖 LLM 生成最终文本，因此“业务全过程流式”表现为步骤事件流，不是逐字生成业务结果。
2. [`ModelGateway.generate_stream()`](src/model_service/gateway.py:76) 当前错误处理较弱，实施时需要补充流式异常归一化和测试。
3. 浏览器端 `fetch()` 流读取需要处理半包事件，必须维护 buffer，不能假设每次 read 都是一条完整事件。
4. 必须保留非流式接口，避免破坏现有测试和旧调用方。
