# Model Service 设计文档

日期: 2026-05-02
状态: 已批准
OpenSpec 变更: `openspec/changes/add-model-service/`

## 1. 概述

为院端医保智能体系统新增统一模型服务层（model_service），将分散在各业务场景中的大模型调用抽象为独立服务。支持 LLM、Embedding、Rerank、OCR 等多模型统一管理，提供模型网关、路由、降级、流式响应能力。

当前版本通过 OpenAI 兼容 API 连接远程大模型测试；后续切换为内网 vLLM 部署。

## 2. 文件结构

```
src/model_service/
├── __init__.py
├── models.py           # Message, TokenUsage, ModelRequest, ModelResponse, StreamChunk
├── exceptions.py       # ModelError 层次（Timeout, RateLimit, Auth, Server, Exhausted）
├── ports.py            # ModelProviderProtocol, ModelGatewayProtocol
├── router.py           # ModelRouter（路由 + 降级链）
├── gateway.py          # ModelGateway（对外入口，含重试、日志）
└── providers/
    ├── __init__.py
    └── openai_compatible.py  # OpenAICompatibleProvider

src/config/
├── model_service.py    # ModelServiceConfig（pydantic-settings，环境变量 MODEL_ 前缀）
└── model_routing.py    # ModelType 枚举, ROUTING_TABLE, FALLBACK_CHAINS, MODEL_PARAMS

src/tests/model_service/
├── test_gateway.py
├── test_router.py
└── test_openai_provider.py
```

## 3. 数据结构

全部使用 dataclass（与 domain 模型风格一致）：

- `Message`: role + content
- `ModelRequest`: messages + model_type + scene + temperature + max_tokens
- `ModelResponse`: content + model_name + usage + finish_reason
- `StreamChunk`: content + finish_reason + usage（增量 token）
- `TokenUsage`: prompt_tokens + completion_tokens

## 4. 异常层次

```
ModelError (基类, 含 model_name)
├── ModelTimeoutError       # 超时，可重试，可降级
├── ModelRateLimitError     # 429，10s 固定延迟重试，可降级
├── ModelAuthError          # 401/403，直接报错不降级
├── ModelServerError        # 5xx，可重试，可降级
└── ModelExhaustedError     # 降级链全部失败，含 failures 列表
```

## 5. Protocol 接口

### ModelProviderProtocol
- `invoke(request: ModelRequest) -> ModelResponse`
- `invoke_stream(request: ModelRequest) -> Iterator[StreamChunk]`

### ModelGatewayProtocol
- `generate(messages: list[Message], model_type: str, scene: str) -> ModelResponse`
- `generate_stream(messages: list[Message], model_type: str, scene: str) -> Iterator[StreamChunk]`

Gateway 内部负责将 Message 转换为 Provider 所需格式。

## 6. 配置

### ModelServiceConfig（pydantic-settings）
- `MODEL_BASE_URL`: 默认 `https://api.openai.com/v1`
- `MODEL_API_KEY`: 默认空
- `MODEL_DEFAULT_TIMEOUT`: 默认 30
- `MODEL_MAX_RETRIES`: 默认 3

### 路由配置（Python 常量）
- `ROUTING_TABLE`: `(scene, model_type) → model_name`
- `FALLBACK_CHAINS`: `model_name → [fallback_names]`
- `MODEL_PARAMS`: `model_name → {temperature, max_tokens}`

## 7. 核心行为

### 7.1 重试策略
- 超时/5xx：立即重试，最多 max_retries 次
- 429：等待 10s 固定延迟后重试
- 401/403：直接抛出 ModelAuthError

### 7.2 降级策略
- 重试耗尽 → 尝试 fallback 链下一个模型
- 全部失败 → ModelExhaustedError

### 7.3 流式响应
- 同步 Generator（Iterator[StreamChunk]）
- 中断处理：Generator 内部捕获连接异常，yield 已收到的 chunks 后正常终止（不抛异常），同时记录部分失败日志

### 7.4 日志记录
- 成功：model_name, scene, latency_ms, token_usage
- 失败：model_name, scene, error_type, error_message
- 流式：model_name, scene, total_chunks, latency_ms, token_usage

## 8. 实现顺序（Wave）

```
Wave 1: 目录 + ModelType + models.py + exceptions.py
Wave 2: ports.py + config (model_service.py + model_routing.py)
Wave 3: OpenAICompatibleProvider + ModelRouter
Wave 4: ModelGateway (generate + generate_stream + 日志)
Wave 5: 测试
```

## 9. 依赖

- 新增依赖：pydantic-settings、httpx（HTTP 客户端）
- 被依赖：后续 runtime/intent、business_scenarios、knowledge_extension 迁移使用
