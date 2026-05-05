# mcp-cunchu 模块开发计划设计

## 背景

[`mcp-cunchu`](../../../openspec/changes/mcp-cunchu/) 变更要求围绕 MCP 建设扩展注册、真实远程调用、PostgreSQL + Redis/Valkey 存储、管理 API/UI、运行时集成和安全审计能力。当前项目已具备 [`knowledge_extension`](../../../src/knowledge_extension/) 的扩展注册雏形、[`data_platform/storage`](../../../src/data_platform/storage/) 的存储端口基础、[`runtime`](../../../src/runtime/) 的执行闭环、[`security`](../../../src/security/) 的权限风控审计能力，以及 [`src/static`](../../../src/static/) 静态演示页。

本开发计划采用可交付里程碑组织：先后端契约与真实存储，再远程 MCP 调用，再管理 API/UI，最后运行时集成与验收。第一轮即接入真实 PostgreSQL 与 Redis/Valkey，并提供本地配置、健康检查和集成测试。

## 目标

- 按 [`proposal.md`](../../../openspec/changes/mcp-cunchu/proposal.md) 与 [`design.md`](../../../openspec/changes/mcp-cunchu/design.md) 落地 MCP 模块开发路径。
- 以 PostgreSQL 作为 MCP 事实数据源，保存服务、能力、策略、工具 schema、资源索引、审计索引、连接配置脱敏视图和状态快照。
- 以 Redis/Valkey 作为缓存与短期状态层，保存能力清单缓存、连接健康状态、流式调用短期状态、幂等键、限流计数、分布式锁和热点查询。
- 建立 MCP Client Gateway，统一真实远程 MCP Server 连接、握手、能力发现、流式事件、工具调用和错误归一化。
- 建立 FastAPI 管理 API 与 [`src/static`](../../../src/static/) 静态管理页面。
- 将 MCP 能力选择与低风险工具调用接入运行时，高风险能力必须转人工确认。

## 非目标

- 不引入对象存储或配置中心作为默认运行依赖；大文件、长期归档、跨环境配置发布或密钥托管需求后续另起 OpenSpec 变更。
- 不允许业务场景直接连接 MCP Server 或绕过 MCP 注册服务、MCP Client Gateway、安全权限与风控边界。
- 不建设完整多租户运营后台、复杂审批流或低代码编排平台。
- 不替代医保正式结算、退费冲正、病案修改等既有业务系统操作。

## 推荐方案

采用方案 A：可交付里程碑串行推进。

选择理由：
- 与 [`tasks.md`](../../../openspec/changes/mcp-cunchu/tasks.md) 的任务分组一致，便于逐步验证。
- 先稳定模型、端口、真实存储和健康检查，可降低后续 MCP Client、管理 UI、运行时集成的返工风险。
- 单人或小团队执行更可控，每个阶段都有明确验收产物。
- 第一轮真实接入 PostgreSQL 与 Redis/Valkey，能尽早暴露配置、连接池、事务、缓存一致性和集成测试问题。

备选方案对比：
- 方案 B：存储完成后先做运行时端到端骨架，再补 MCP Client 与 UI。优点是较早验证业务闭环，缺点是容易在 MCP Client 未稳定前形成临时调用抽象。
- 方案 C：按存储、MCP Client、UI、安全运行时并行推进。优点是适合多人团队，缺点是接口未稳定时协调成本高，不适合作为首轮实施策略。

## 里程碑 1：契约、模型与真实存储

### 范围

- 新增 [`src/knowledge_extension/mcp_registry`](../../../src/knowledge_extension/) 模块，定义 MCP 服务、能力、策略、状态、选择结果、审计元数据模型。
- 新增 [`src/data_platform/storage/mcp`](../../../src/data_platform/storage/) 模块，定义 MCP 存储 Protocol。
- 实现内存存储、PostgreSQL 持久化存储、Redis/Valkey 缓存与短期状态实现。
- 增加配置项、连接池、健康检查、启动校验和缓存失效策略。

### 核心产物

- MCP Pydantic 模型。
- MCP 存储端口。
- PostgreSQL 表结构或迁移脚本。
- Redis/Valkey key 命名规则与 TTL 策略。
- MCP 存储健康检查服务。
- 存储单元测试与集成测试。

### 验收标准

- 能注册、读取、更新、禁用 MCP 服务与能力。
- PostgreSQL 保存事实数据，Redis/Valkey 缓存可失效并从 PostgreSQL 恢复。
- 返回对象不泄露可变内部状态。
- 健康检查能区分 PostgreSQL 不可用、Redis/Valkey 不可用和降级状态。

## 里程碑 2：MCP 扩展注册服务

### 范围

- 在 [`src/knowledge_extension/mcp_registry`](../../../src/knowledge_extension/) 实现注册服务。
- 支持服务注册、编辑、启停、删除、详情、列表、能力入库、能力筛选和策略配置。
- 根据场景、角色、权限、能力类型、风险等级和服务状态筛选能力。
- 对高风险 MCP 能力强制标记人工确认。

### 核心产物

- MCP Registry Service。
- MCP 能力筛选器。
- MCP 策略校验器。
- MCP 审计事件生成逻辑。

### 验收标准

- 同一输入下能力筛选结果稳定排序。
- disabled、unhealthy 或权限不匹配能力不会被自动选择。
- 高风险能力不会进入自动执行列表。
- 能输出 selected_capabilities、excluded_capabilities、reasons、citations 或 uncertainties。

## 里程碑 3：远程 MCP Client Gateway

### 范围

- 新增 MCP Client Gateway，统一远程 MCP Server 连接、初始化握手、协议版本校验和能力发现。
- 支持流式协议事件归一化，覆盖增量事件、完成事件和错误事件。
- 支持低风险只读工具真实调用，调用前必须完成权限、风险、参数和超时校验。
- 归一化鉴权失败、限流、超时、断连、畸形消息和上游错误。

### 核心产物

- MCP Client Gateway Protocol 与实现。
- MCP 连接测试服务。
- MCP 流式事件模型。
- MCP 工具调用结果模型。
- MCP 错误归一化模型。

### 验收标准

- 能连接测试用 MCP Server 并完成握手。
- 能发现工具、资源、提示和服务能力并写入注册服务。
- 能执行一个低风险只读工具并返回结构化结果。
- 高风险工具调用请求在 Gateway 前被阻断。
- 错误不会泄露密钥、Token、Authorization 头或敏感参数。

## 里程碑 4：管理 API 与静态 UI

### 范围

- 在 [`src/runtime/api`](../../../src/runtime/api/) 增加 MCP 管理 API 路由。
- 在 [`src/static`](../../../src/static/) 增加 MCP 管理页面。
- UI 支持服务注册、编辑、启停、连接测试、能力浏览、策略配置、审计查看和存储状态查看。
- 所有敏感连接配置只展示脱敏值。

### 核心 API

- `GET /api/v1/medical-insurance-ai-agent/mcp/servers`
- `POST /api/v1/medical-insurance-ai-agent/mcp/servers`
- `GET /api/v1/medical-insurance-ai-agent/mcp/servers/{server_id}`
- `PATCH /api/v1/medical-insurance-ai-agent/mcp/servers/{server_id}`
- `POST /api/v1/medical-insurance-ai-agent/mcp/servers/{server_id}/test-connection`
- `GET /api/v1/medical-insurance-ai-agent/mcp/capabilities`
- `PATCH /api/v1/medical-insurance-ai-agent/mcp/capabilities/{capability_id}/policy`
- `GET /api/v1/medical-insurance-ai-agent/mcp/audit-events`
- `GET /api/v1/medical-insurance-ai-agent/mcp/storage/health`

### 验收标准

- API 响应使用 Pydantic 模型和统一错误结构。
- UI 能完成注册、连接测试、能力查看和策略修改主路径。
- UI 不展示密钥明文。
- OpenAPI 契约测试通过。

## 里程碑 5：运行时、安全与验收

### 范围

- 将 MCP 能力筛选接入 [`runtime/planning`](../../../src/runtime/planning/) 或 [`runtime/orchestration`](../../../src/runtime/orchestration/)。
- 将低风险 MCP 工具调用写入 workflow 状态。
- 将高风险 MCP 能力接入 [`security/risk_control`](../../../src/security/risk_control/) 与人工确认任务闭环。
- 对 MCP 调用结果执行脱敏、引用追踪、不确定性补齐和审计记录。
- 验证 MCP 不可用时既有医保导办主流程可降级返回。

### 验收标准

- workflow 记录 request_id、server_id、capability_id、stream summary、latency、audit_event。
- 低风险 MCP 工具可在授权后自动调用。
- 高风险 MCP 工具只创建人工确认任务，不执行真实调用。
- 所有最终响应包含 citations 或 uncertainties。
- `npx openspec validate "mcp-cunchu" --strict` 与 `python -m pytest src/tests -v` 通过。

## 测试策略

- 单元测试：模型校验、策略筛选、错误归一化、缓存 key 构造、脱敏逻辑。
- 存储测试：PostgreSQL CRUD、事务一致性、Redis/Valkey TTL、缓存失效、健康检查。
- 集成测试：注册服务 + 存储、Client Gateway + 测试 MCP Server、管理 API + 服务层。
- 安全测试：权限拒绝、高风险拦截、密钥脱敏、审计记录、响应可追溯。
- 端到端测试：注册 MCP Server、连接测试、能力发现、低风险调用、workflow 记录、UI 主路径。

## 风险与缓解

- PostgreSQL 与 Redis/Valkey 本地依赖增加测试复杂度：提供明确环境变量、健康检查和可跳过的集成测试标记。
- MCP 协议实现差异导致 Client Gateway 不稳定：先使用测试 MCP Server 固化握手、能力发现和流式事件契约。
- UI 与后端 API 同步成本：以 OpenAPI/Pydantic 模型为事实源，UI 只消费后端结构化响应。
- 高风险工具误执行：调用前统一经过风险控制，默认 deny，高风险能力只允许创建人工确认任务。

## 实施顺序摘要

1. 模型与端口。
2. PostgreSQL 与 Redis/Valkey 真实存储。
3. MCP 注册服务与能力筛选。
4. MCP Client Gateway。
5. 管理 API。
6. 静态管理 UI。
7. 运行时、安全、审计集成。
8. 验收测试与文档收尾。
