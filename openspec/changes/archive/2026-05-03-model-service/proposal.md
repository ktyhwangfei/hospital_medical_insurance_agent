## Why

当前项目已在[`docs/steering/架构设计.md`](docs/steering/架构设计.md)中将[`model_service/`](src/model_service)定义为PaaS核心服务域之一，但MVP代码基线尚未落地统一模型服务抽象，导致运行时未来接入LLM、Embedding、Rerank、OCR与语音能力时只能直接耦合具体实现。现在补齐该能力，可以在保持MVP内存化与低依赖前提下，为后续知识增强、意图识别、编排调度和降级治理提供稳定的模型访问边界。

## What Changes

- 新增统一的[`model-service`](openspec/changes/model-service/specs/model-service/spec.md)能力规格，定义模型网关、模型注册、路由、降级、追溯与安全输出约束。
- 为MVP增加内存化模型服务实现边界，覆盖LLM、Embedding与Rerank三类基础能力的统一请求/响应契约。
- 约束运行时只能通过模型服务访问模型能力，不允许业务场景或编排层直接耦合具体模型实现。
- 明确模型失败时的降级策略、引用与不确定性输出要求，以及审计事件记录要求。

## Capabilities

### New Capabilities
- `model-service`: 统一封装模型调用入口、模型选择、降级策略、可追溯输出以及面向运行时的标准化服务契约。

### Modified Capabilities
- 无

## Impact

- 受影响目录主要包括[`src/model_service/`](src/model_service)、[`src/runtime/scheduling/`](src/runtime/scheduling/service.py)、[`src/runtime/intent/`](src/runtime/intent/service.py)、[`src/knowledge_extension/`](src/knowledge_extension)以及相关测试目录。
- 将新增模型服务相关领域契约、内存实现与测试样例，但不引入PostgreSQL、Redis/Valkey、Milvus等运行依赖。
- 未来API与场景服务在需要模型能力时，将通过统一模型服务边界间接访问具体模型。
