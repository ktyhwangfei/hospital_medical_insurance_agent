## Context

当前代码仓库仅实现了[`runtime`](src/runtime)、[`business_scenarios`](src/business_scenarios)、[`adapters`](src/adapters)与[`knowledge_extension/knowledge`](src/knowledge_extension/knowledge)等MVP核心子集，尚未建立[`model_service/`](src/model_service)目录与统一模型调用契约，但在架构设计中该服务域已被明确定位为PaaS核心能力。后续意图识别、RAG、规则解释、编排调度以及多模态入口都会依赖模型能力，如果没有统一网关与端口，运行时将直接耦合具体供应商SDK或推理实现，破坏当前以Protocol和内存实现为主的解耦纪律。

本次设计需要兼顾三个约束：一是维持MVP阶段“以内存实现为主、不引入外部基础设施运行依赖”的项目现状；二是遵守高风险动作需人工确认、模型输出需可追溯且可声明不确定性的安全要求；三是与现有[`runtime/scheduling`](src/runtime/scheduling/service.py)、[`runtime/intent`](src/runtime/intent/service.py)以及[`knowledge_extension`](src/knowledge_extension)形成可扩展而非侵入式集成边界。

## Goals / Non-Goals

**Goals：**
- 建立[`model_service`](src/model_service)服务域的最小可行架构边界，包括模型网关、模型注册表、能力端口与内存实现。
- 定义LLM、Embedding、Rerank三类能力的统一请求响应契约，使运行时通过标准接口访问模型。
- 规定模型路由、失败降级、审计事件和可追溯输出的行为约束，为后续OCR、语音、意图模型扩展预留一致机制。
- 保证模型服务与业务场景、知识服务、编排调度之间的依赖方向清晰，避免跨层直接调用。

**Non-Goals：**
- 不在本次变更中引入真实vLLM、第三方LLM SDK、GPU调度或分布式推理。
- 不实现OCR、Speech、Intent专用模型的完整能力，只在契约层预留扩展位。
- 不修改现有业务场景的全部执行流程，只定义后续接入模型服务所需边界与替换路径。
- 不建设模型评测平台、成本计费或运营报表。

## Decisions

### 决策一：采用“网关服务 + 能力端口 + 内存适配器”分层
- 方案：在[`src/model_service/`](src/model_service)下拆分[`model_gateway`](src/model_service/model_gateway)、[`llm`](src/model_service/llm)、[`embedding`](src/model_service/embedding)、[`rerank`](src/model_service/rerank)等子模块，使用Protocol定义端口，再提供内存实现。
- 原因：与现有[`adapters`](src/adapters)和[`data_platform/storage`](src/data_platform/storage)的解耦风格保持一致，便于未来将内存实现替换为真实模型供应商接入。
- 备选方案A：在[`runtime/scheduling/service.py`](src/runtime/scheduling/service.py)中直接编写模型调用逻辑。未采用，因为会把调度层与具体模型强耦合。
- 备选方案B：仅定义一个通用`invoke_model()`函数。未采用，因为不同模型能力在输入输出结构、审计字段与降级策略上差异明显，后续扩展成本高。

### 决策二：先收敛到三类基础能力契约
- 方案：MVP规格只要求LLM文本生成、Embedding向量化与Rerank重排序三类统一能力。
- 原因：这三类能力直接支撑聊天生成、知识检索与引用增强，是当前运行时最接近落地的模型能力集合。
- 备选方案：一次性覆盖OCR、Speech、Intent模型。未采用，因为当前代码基线尚无对应调用方，会扩大实现面且降低提案聚焦度。

### 决策三：模型输出必须带来源声明或不确定性声明
- 方案：模型网关对上游返回统一结构，至少包含`content`、`citations`、`uncertainties`、`model_id`、`audit_event`等字段；若无可验证来源，则必须显式返回不确定性说明。
- 原因：符合项目在[`AGENTS.md`](AGENTS.md)中定义的安全约束，避免模型生成无来源确定性结论。
- 备选方案：仅对知识问答场景要求引用。未采用，因为模型服务作为平台层能力，应统一执行最小治理底线。

### 决策四：降级策略在模型服务内部统一处理，对运行时暴露稳定错误语义
- 方案：当主模型不可用、超时或命中风控规则时，模型网关优先选择同能力备用模型；若无备用模型，则返回结构化失败结果与降级原因，而不是抛出供应商特定异常。
- 原因：运行时和场景层更关注“能力可用性”而非底层异常细节，统一错误语义便于测试与后续审计。
- 备选方案：由调用方自行决定降级。未采用，因为会让路由、知识服务、编排层重复实现一套模型容错逻辑。

## Risks / Trade-offs

- [风险] 先定义抽象可能与未来真实模型SDK能力不完全匹配 → 缓解：契约聚焦最小公共字段，并通过能力子模块而非单一万能接口保留扩展空间。
- [风险] 统一要求引用或不确定性声明会增加调用方组装成本 → 缓解：在模型网关统一补齐默认字段，调用方仅消费规范化结果。
- [风险] 仅提供内存实现可能掩盖真实网络超时、鉴权与并发问题 → 缓解：在任务清单中预留后续适配真实供应商与故障注入测试工作。
- [权衡] 当前不实现独立模型评测与成本治理，短期能控制范围，但后续上线前仍需补充观测与运营能力。

## Migration Plan

1. 先创建[`openspec/changes/model-service/specs/model-service/spec.md`](openspec/changes/model-service/specs/model-service/spec.md)明确行为契约。
2. 实现[`src/model_service/`](src/model_service)目录结构、Pydantic模型与Protocol端口。
3. 在[`runtime/scheduling`](src/runtime/scheduling/service.py)或后续规划模块中改为依赖模型服务网关，而不是直接调用具体模型。
4. 增加单元测试与集成测试，覆盖模型路由、降级、追溯字段与安全输出。
5. 后续如接入真实模型供应商，可在不改变上游契约的前提下增加新适配器并逐步替换内存实现。

## Open Questions

- 模型服务统一响应结构是否直接复用[`src/shared/schemas/responses.py`](src/shared/schemas/responses.py)中的错误细节模型，还是在模型域定义独立错误对象后再映射。
- [`runtime/intent`](src/runtime/intent/service.py)后续是继续保留规则优先识别，还是允许在置信度不足时回退到模型服务。
- Embedding与Rerank结果是否需要在MVP阶段纳入审计事件细粒度记录，还是仅记录上层知识检索调用轨迹。
