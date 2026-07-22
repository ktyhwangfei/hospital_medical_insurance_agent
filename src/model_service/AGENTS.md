# model_service/ — 模型服务网关

## 概述

统一 LLM 调用入口。路由 → Provider → 非流式/流式响应。禁止绕过直接调 HTTP。

## 结构

```
model_service/
├── gateway.py              # ModelGateway，唯一对外入口，重试 + fallback 链
├── router.py               # ModelRouter，scene + model_type → provider 路由
├── models.py               # Message, ModelRequest, ModelResponse, StreamChunk, TokenUsage
├── exceptions.py           # 异常层次：ModelTimeoutError / ModelRateLimitError / ModelAuthError / ModelServerError / ModelExhaustedError
├── ports.py                # ModelProviderProtocol + ModelGatewayProtocol（Protocol 接口）
└── providers/
    └── openai_compatible.py # 当前唯一 Provider，适配 OpenAI 兼容接口（DeepSeek / Qwen 等）
```

## 关键约定

- **所有 LLM 调用必须通过 ModelGateway**。违反者视为架构违规。
- **异常必须使用 exceptions.py 中的类型**。禁止裸 Exception 上浮。
- **重试策略**：rate limit → 等 10s 重试；timeout/server error → 立即重试；auth error → 不重试直接抛。最多重试 `max_retries` 次（默认 3）。
- **Fallback 链**：主模型失败 → 依次尝试 fallback 模型 → 全部失败抛 `ModelExhaustedError`，携带所有失败记录。
- **流式约定**：`generate_stream()` 返回 `Iterator[StreamChunk]`，外部 SSE 端点逐块转发，`[DONE]` 标记结束。
- **路由解析顺序**：精确匹配 (scene, model_type) → 默认匹配 (default, model_type) → fallback 链。
- **当前 Provider**：仅 `OpenAICompatibleProvider`，通过 `base_url + api_key` 配置。新增 provider 需实现 `ModelProviderProtocol`。
- **配置来源**：模型参数、路由表、fallback 链在 `src/config/model_routing.py`，服务配置在 `src/config/model_service.py`。
- **管理 API**：模型路由/配置 CRUD 路由在 `src/runtime/api/model_routes.py`。

## 注意事项

- dummy 模式（`base_url="dummy"`）用于调试，根据 prompt 关键词返回固定 JSON。
- 当前无单元测试覆盖 `ModelGateway._call_provider` 的 retry 分支。
- `providers/` 目录当前仅一个实现，扩展时注意 Provider 层不要硬编码路由逻辑。
