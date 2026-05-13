## Why

当前系统已具备知识扩展注册的雏形，但尚未围绕 MCP 形成可治理、可审计、可存储的扩展注册能力。医保智能体后续需要接入院内工具、知识服务、文件资源、向量索引与运行时状态等 MCP 服务，必须先建立统一的 MCP 注册、权限、安全边界和存储抽象，避免业务场景直接耦合具体外部服务。

## What Changes

- 新增 MCP 扩展注册能力，定义 MCP 服务、工具、资源、提示模板、传输方式、健康状态、权限要求和审计元数据。
- 新增 MCP 存储能力，以 PostgreSQL 存储结构化数据，以 Redis/Valkey 承载缓存、连接状态、短期会话和分布式协调，并保留内存实现用于测试。
- 扩展运行时调用契约，允许运行时基于场景、角色、权限、风险等级和能力类型筛选可用 MCP 扩展。
- 扩展安全契约，要求 MCP 注册、查询、启停、调用前评估和调用结果落审计，并对高风险动作执行拦截或人工确认。
- 实现真实远程 MCP Server 连接、初始化握手、能力发现、协议流式通信、工具调用和调用结果归一化。
- 新增 MCP 管理 UI，支持服务注册、连接测试、启停、能力浏览、策略配置、审计查看和存储状态查看。
- 引入 PostgreSQL 与 Redis/Valkey 作为 MCP 存储运行依赖；本变更不默认引入对象存储或配置中心，除非后续出现大文件、二进制资源、跨环境配置治理或密钥托管等明确需求。
- 对真实 MCP 工具调用建立调用前权限校验、风险评估、超时控制、审计追踪和高风险人工确认边界；允许低风险只读 MCP 工具在授权后自动执行。
- 不改变现有 Chat API 的核心响应结构，不替代医保正式结算、病案修改、退费冲正等既有业务系统。

## Capabilities

### New Capabilities
- `mcp-extension-registry`: MCP 服务、工具、资源与提示能力的注册、查询、筛选、状态管理、权限约束和审计元数据契约。
- `mcp-storage`: MCP 注册数据、能力清单、调用策略、资源内容索引、连接状态和运行时状态快照的 PostgreSQL 持久化与 Redis/Valkey 缓存契约。
- `mcp-remote-invocation`: 远程 MCP Server 连接、初始化握手、能力发现、协议流式通信、工具调用、超时重试和错误归一化契约。
- `mcp-management-ui`: MCP 管理界面的服务注册、连接测试、能力浏览、策略配置、启停管理、审计查看和存储状态查看契约。

### Modified Capabilities
- `runtime-execution-loop`: 运行时计划步骤需要能够通过 MCP 扩展注册筛选可用能力，并将 MCP 能力选择、降级、不确定性和审计事件纳入 workflow 状态。
- `security-contracts`: MCP 扩展注册、状态变更、能力调用前评估和调用结果必须满足权限、风控、脱敏、引用或不确定性输出要求。

## Impact

- 受影响代码目录：`src/knowledge_extension/`、`src/runtime/`、`src/security/`、`src/data_platform/storage/`、`src/shared/schemas/`、`src/static/` 或新增前端应用目录、`src/tests/`。
- 受影响契约：新增 MCP 扩展注册、MCP 存储、MCP 远程调用和 MCP 管理 UI OpenSpec 能力，修改运行时执行循环与安全契约的 MCP 调用治理要求。
- 受影响测试：新增 MCP 注册模型、PostgreSQL 持久化、Redis/Valkey 缓存一致性、远程连接握手、流式通信、工具调用、安全边界、管理 UI、运行时集成和审计可追溯测试。
- 受影响基础设施：新增可配置 PostgreSQL 与 Redis/Valkey 运行依赖，并保留内存实现用于测试和本地降级；暂不新增对象存储或配置中心。
