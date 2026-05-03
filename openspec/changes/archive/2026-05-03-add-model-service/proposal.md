## Why

当前系统中大模型调用分散在各业务场景中，缺乏统一的模型服务层。按架构设计，PaaS 层应包含模型服务域（模型网关、推理服务、模型路由与降级），需要将模型调用能力抽象为独立服务，支持 LLM、Embedding、Rerank、OCR 等多模型统一管理。

## What Changes

- 新增 `src/model_service/` 模块，提供统一的模型调用接口
- 实现模型网关（ModelGateway），统一封装模型请求/响应、超时重试、调用日志
- 实现模型路由（ModelRouter），按意图/场景选择模型，支持降级链自动切换
- 定义 Protocol 接口，当前通过 OpenAI 兼容 API 连接远程大模型测试，后续切换为内网 vLLM 部署

## Capabilities

### New Capabilities

- `model-gateway`: 统一模型调用网关，封装请求/响应、超时、重试、日志
- `model-routing`: 模型路由与降级，按场景/意图选择模型并支持 fallback

### Modified Capabilities

（无）

## Impact

- 新增目录: `src/model_service/`
- 依赖: `src/config/`（模型配置）、pydantic-settings（新增依赖，环境变量管理）
- 被依赖: `runtime/intent/`、`business_scenarios/`、`knowledge_extension/` 等需要调用模型的模块
- 架构文档: 与 `docs/steering/架构设计.md` 中模型服务域描述对齐
