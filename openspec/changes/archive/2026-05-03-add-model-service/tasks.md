## 1. 基础结构

- [x] 1.1 创建 `src/model_service/` 目录及 `__init__.py`
- [x] 1.2 定义 `ModelType` 枚举（LLM、EMBEDDING、RERANK、OCR）
- [x] 1.3 定义 `Message`、`TokenUsage`、`ModelRequest`、`ModelResponse`、`StreamChunk` 数据结构
- [x] 1.4 定义异常层次 `ModelError`、`ModelTimeoutError`、`ModelRateLimitError`、`ModelAuthError`、`ModelServerError`、`ModelExhaustedError`

## 2. Protocol 接口

- [x] 2.1 定义 `ModelProviderProtocol`（invoke + invoke_stream 双方法）
- [x] 2.2 定义 `ModelGatewayProtocol`（generate + generate_stream 双方法，含 scene 参数）

## 3. 配置模块

- [x] 3.1 创建 `src/config/model_service.py`，使用 pydantic-settings 定义 `ModelServiceConfig`（base_url、api_key、timeout、max_retries，环境变量前缀 MODEL_）
- [x] 3.2 创建 `src/config/model_routing.py`，定义 ROUTING_TABLE、FALLBACK_CHAINS、MODEL_PARAMS 常量

## 4. 模型网关实现

- [x] 4.1 实现 `ModelGateway` 类，封装 provider 调用、路由选择、降级链
- [x] 4.2 实现超时控制（默认 30s）
- [x] 4.3 实现重试逻辑：超时/5xx 立即重试、429 等待 10s 固定延迟、401/403 直接报错
- [x] 4.4 实现 `generate()` 非流式方法
- [x] 4.5 实现 `generate_stream()` 流式方法（同步 Generator）
- [x] 4.6 实现调用日志记录（成功/失败/流式场景）

## 5. OpenAI 兼容 Provider 实现

- [x] 5.1 实现 `OpenAICompatibleProvider`，支持 `invoke()` 调用 `/v1/chat/completions`
- [x] 5.2 实现 `invoke_stream()` 流式调用（SSE 解析）
- [x] 5.3 实现 Embedding 支持（调用 `/v1/embeddings`）
- [x] 5.4 实现 HTTP 状态码映射：401/403→AuthError、429→RateLimitError、5xx→ServerError

## 6. 集成与测试

- [x] 6.1 编写 ModelGateway 单元测试（超时、重试、日志）
- [x] 6.2 编写 ModelGateway 流式测试（正常流式、中断处理）
- [x] 6.3 编写 ModelRouter 单元测试（路由、降级、默认值、AuthError 终止）
- [x] 6.4 编写 OpenAICompatibleProvider 单元测试（请求构造、响应解析、SSE 解析）
- [x] 6.5 运行全部测试确认通过
