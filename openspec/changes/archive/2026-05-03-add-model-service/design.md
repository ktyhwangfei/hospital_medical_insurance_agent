## Context

当前系统中大模型调用分散在各业务场景（intent、knowledge_extension、business_scenarios）中，没有统一的抽象层。按照架构设计文档，PaaS 层模型服务域应提供模型网关、推理服务、模型路由与降级能力。

模型接入分两阶段：
- **当前版本**: 通过配置远程 API Key（OpenAI 兼容接口）连接外部大模型服务进行测试验证
- **后续版本**: 通过内网部署 vLLM 连接本地大模型，实现自主可控

当前系统特点：全部同步代码（无 async）、无 DI 框架、Protocol 模式已在 data_platform 建立、配置为纯 Python 常量。model_service 将是系统中第一个真正的外部 HTTP 调用模块。

## Goals / Non-Goals

**Goals:**
- 提供统一的模型调用 Protocol 接口，支持 LLM、Embedding、Rerank、OCR 等模型类型
- 实现模型网关，封装请求构造、响应解析、超时重试、调用日志
- 实现模型路由，按业务场景/意图选择合适的模型
- 实现降级策略，主模型不可用时自动 fallback 到备选模型
- 支持流式响应（同步 Generator）
- 当前通过 OpenAI 兼容 API 连接远程服务，后续可替换为 vLLM

**Non-Goals:**
- 不实现模型训练、微调、评估能力
- 不实现模型版本管理/AB 测试
- 不引入 async（保持与现有代码风格一致）

## Decisions

### Decision 1: Protocol 模式定义接口

采用 Python Protocol（typing.Protocol）定义模型调用接口，与 data_platform/ports.py 保持一致风格。

**理由**: 项目已使用 Protocol 模式（如 data_platform/），保持一致性；Protocol 支持结构化子类型，便于后续替换实现。

**替代方案**: 抽象基类（ABC）—— 但 Protocol 更轻量，不需要显式继承。

### Decision 2: 模型类型枚举化

定义 `ModelType` 枚举（LLM、EMBEDDING、RERANK、OCR），路由按类型+场景选择模型。

**理由**: 枚举类型明确、可序列化、便于配置化管理。

### Decision 3: 配置驱动的模型路由

模型路由配置存放在 `src/config/model_routing.py`，按场景映射到模型类型和模型名称。API Key 等敏感配置通过环境变量注入。

**理由**: 配置化便于运维调整，不需要修改代码即可切换模型；环境变量管理敏感信息符合安全规范。

### Decision 4: 降级链（Fallback Chain）

每个模型配置一个降级链列表，主模型失败后按顺序尝试备选模型。

**理由**: 简单可靠，避免复杂的熔断器逻辑；当前 MVP 阶段降级链通常只有一级。

### Decision 5: OpenAI 兼容 API 作为统一接入协议

当前版本通过 OpenAI 兼容 API（`/v1/chat/completions`、`/v1/embeddings`）接入远程大模型服务。后续切换 vLLM 时，vLLM 原生支持 OpenAI 兼容接口，只需修改 base_url 和 api_key 即可无缝迁移。

**理由**: OpenAI API 已成为事实标准；vLLM 原生兼容此协议，降低迁移成本。

**替代方案**: 自定义 HTTP 协议 —— 增加开发量且无额外收益。

### Decision 6: 接口数据结构 — messages 模型

ModelRequest 采用 messages 列表结构（role + content），与 OpenAI API 对齐。

```python
@dataclass
class Message:
    role: str       # "system", "user", "assistant"
    content: str

@dataclass
class ModelRequest:
    messages: list[Message]
    model_type: ModelType
    scene: str
    temperature: float = 0.7
    max_tokens: int = 2048

@dataclass
class ModelResponse:
    content: str
    model_name: str
    usage: TokenUsage       # prompt_tokens, completion_tokens
    finish_reason: str      # "stop", "length", "error"

@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
```

**理由**: messages 结构支持多轮对话和 system prompt；与 OpenAI API 对齐降低 Provider 实现复杂度。使用 dataclass 而非 Pydantic BaseModel，因为这些是 model_service 内部数据结构（非 API schema），与 domain 模型风格一致（`src/domain/` 均使用 dataclass），且无需 Pydantic 的校验/序列化能力。

**替代方案**: 单一 prompt 字符串 —— 无法区分 system/user 角色，限制灵活性。

### Decision 7: 流式响应使用同步 Generator

Protocol 和 Gateway 均提供双方法：`invoke()` 返回完整响应，`invoke_stream()` 返回 `Iterator[StreamChunk]`。

```python
@dataclass
class StreamChunk:
    content: str              # 本次增量 token
    finish_reason: str | None # 仅最后一个 chunk 非 None
    usage: TokenUsage | None  # 仅最后一个 chunk 非 None

class ModelProviderProtocol(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse: ...
    def invoke_stream(self, request: ModelRequest) -> Iterator[StreamChunk]: ...
```

**理由**: 同步 Generator 保持与现有代码风格一致，不引入 async 复杂度；流式支持对用户体验至关重要。

**替代方案**: AsyncGenerator —— 需要整个调用链改为 async，改动范围过大。

### Decision 8: pydantic-settings 管理敏感配置

引入 pydantic-settings 管理环境变量，配置类定义在 `src/config/model_service.py`。

```python
class ModelServiceConfig(BaseSettings):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    default_timeout: int = 30
    max_retries: int = 3

    model_config = SettingsConfigDict(env_prefix="MODEL_")
```

**理由**: pydantic-settings 提供类型校验、默认值、环境变量前缀；当前系统无配置管理方案，需要引入。

**替代方案**: 纯 `os.environ` —— 缺少类型校验，容易出错。

### Decision 9: 异常层次与重试/降级策略

异常层次：

```
ModelError (基类)
├── ModelTimeoutError       # 请求超时，可重试，可降级
├── ModelRateLimitError     # 限流 429，10s 固定延迟重试，可降级
├── ModelAuthError          # 认证失败 401/403，直接报错不降级
├── ModelServerError        # 服务端错误 5xx，可重试，可降级
└── ModelExhaustedError     # 降级链全部失败，终止
```

重试策略：
- 超时、5xx：立即重试，最多 max_retries 次
- 限流 429：等待 10s 固定延迟后重试
- 认证 401/403：直接抛出 ModelAuthError，不重试不降级

降级策略：重试耗尽后自动尝试 fallback 链中的下一个模型；全部失败抛出 ModelExhaustedError。

**理由**: 认证失败说明配置有误，换模型也无法解决；限流用固定延迟简化实现。

## Risks / Trade-offs

- **[风险] 远程 API 依赖外部服务稳定性** → 降级链 + 超时重试机制缓解
- **[风险] 远程 API 与 vLLM 响应格式微小差异** → 统一使用 OpenAI 兼容协议，差异最小化
- **[风险] API Key 泄露风险** → 环境变量注入，不硬编码到代码中
- **[风险] 流式连接中断** → Provider 层捕获异常，Gateway 将已有 chunk 合并返回
- **[权衡] 配置驱动 vs 硬编码** → 选择配置驱动，增加少量复杂度换取灵活性
- **[权衡] 引入 pydantic-settings 依赖** → 值得，解决当前系统无配置管理的问题

## Migration Plan

1. 新增 `src/model_service/` 目录及所有文件
2. 实现 `OpenAICompatibleProvider`，通过环境变量配置 `base_url` 和 `api_key`
3. 各业务模块逐步迁移到使用 ModelGateway（后续迭代）
4. 后续部署 vLLM 时，仅需修改环境变量指向内网 vLLM 地址
