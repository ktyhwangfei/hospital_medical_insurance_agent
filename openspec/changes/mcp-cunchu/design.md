## Context

院端医保智能体当前已完成 MVP 后端核心闭环，并在 `knowledge_extension` 中具备知识扩展服务基础，但 MCP 能力仍缺少面向院内集成的统一注册、存储、安全治理和运行时选择机制。后续如果直接在业务场景中硬编码 MCP Server 或工具调用，会破坏适配器解耦、安全审计和高风险动作拦截约束。

本变更围绕 MCP 形成扩展注册、真实远程调用、持久化存储和管理 UI 能力。MCP 在本设计中被视为外部工具、资源、提示和服务能力的受控集成通道，需要支持真实 MCP Server 连接、初始化握手、能力发现、协议流式通信和低风险授权工具调用，同时对高风险能力保持人工确认边界。

## Goals / Non-Goals

**Goals:**
- 定义 MCP 服务、工具、资源、提示模板和能力策略的 Pydantic 契约。
- 提供 MCP 扩展注册服务，支持注册、查询、状态变更、按场景/角色/权限/风险筛选。
- 提供 MCP 存储端口、PostgreSQL 持久化实现、Redis/Valkey 缓存实现和内存测试实现，保证注册数据、能力清单、调用策略、资源索引和状态快照可存储、可缓存、可替换。
- 实现真实远程 MCP Server 连接、握手、能力发现、协议流式通信、工具调用、超时重试和错误归一化。
- 新增 MCP 管理 UI，支持服务注册、连接测试、能力浏览、策略配置、启停管理、审计查询和存储状态查看。
- 引入 PostgreSQL 与 Redis/Valkey 作为 MCP 存储运行依赖。
- 将 MCP 能力选择纳入运行时执行循环，产生 citations、uncertainties 和审计事件。
- 将 MCP 注册和调用前评估纳入安全契约，保证高风险能力不会自动执行。

**Non-Goals:**
- 不改变现有医保正式结算、退费冲正、病案修改等高风险动作必须由人工在既有系统执行的原则。
- 不在本变更中建设完整多租户运营后台、复杂审批流或低代码编排平台。
- 不允许 MCP 绕过现有适配器、防腐层、权限、风控、脱敏和审计约束直接修改核心业务系统。
- 不默认引入对象存储或配置中心；只有当 MCP 需要保存大体积二进制资源、长期归档文件、跨环境配置发布、密钥托管或配置审计审批时才另行评估。

## Decisions

### Decision 1: MCP 注册归属 `knowledge_extension`，存储端口归属 `data_platform/storage`

MCP 扩展注册是知识与扩展服务域的一部分，服务入口和业务模型放在 `knowledge_extension/mcp_registry`。MCP 注册数据的持久化能力放在 `data_platform/storage/mcp`，通过 Protocol 暴露端口，内存实现用于 MVP 测试。

替代方案是将 MCP 注册直接放到 `runtime`。该方案会让运行时承担扩展资产治理职责，不利于后续与知识资产、规则解释、提示模板形成统一扩展目录，因此不采用。

### Decision 2: 注册模型显式区分服务、能力、策略和状态

MCP Server 描述连接与治理边界，MCP Capability 描述 tool/resource/prompt/service 能力，MCP Policy 描述角色、权限、风险和场景约束，MCP Status 描述 enabled、disabled、degraded、unhealthy 等运行状态。这样可以避免把传输元数据、安全策略和业务能力混在单个裸字典中。

替代方案是使用简单 `dict` 保存 MCP 配置。该方案违反类型安全规范，也难以测试权限、风险和审计边界，因此不采用。

### Decision 3: 远程 MCP 调用采用受控客户端网关

新增 MCP Client Gateway 负责真实远程 MCP Server 连接、初始化握手、能力发现、流式通信和工具调用。运行时不得直接连接 MCP Server，只能通过注册服务和客户端网关完成调用前评估与低风险授权调用。网关统一处理超时、断连、协议错误、鉴权失败、限流和上游错误，并输出结构化错误。

替代方案是在业务场景中直接使用 MCP SDK。该方案会导致安全与审计逻辑分散，也难以统一高风险拦截，因此不采用。

### Decision 4: MCP 存储优先采用 PostgreSQL + Redis/Valkey 双层方案

MCP 存储定义统一 Protocol。PostgreSQL 作为事实存储，保存 MCP 服务、能力、工具 schema、资源索引、策略、审计索引、连接配置脱敏视图、状态快照和管理 UI 配置。Redis/Valkey 作为派生缓存与短期状态层，保存能力清单缓存、连接健康状态、流式调用短期状态、幂等键、限流计数、分布式锁和热点查询结果。内存实现仅用于测试、本地开发和降级验证。读写返回 Pydantic 对象副本，并提供按 server_id、capability_id、capability_type、scenario、role、permission、risk_level 的查询能力。

替代方案一是只使用 PostgreSQL。该方案可以满足正确性，但连接健康、流式短期状态、限流、幂等和热点能力清单会频繁读写数据库，增加延迟与锁竞争，因此不作为运行态唯一方案。

替代方案二是额外引入对象存储或配置中心。当前 MCP 注册数据、工具 schema、资源索引和管理配置均属于结构化或半结构化数据，可用 PostgreSQL 的 JSON 字段、普通表和版本字段承载；Redis/Valkey 可覆盖缓存和短期状态。对象存储只有在需要保存大体积文件、二进制资源、原始附件或长期归档时才有必要。配置中心只有在需要跨环境动态配置发布、复杂审批、灰度配置和集中密钥治理时才有必要。因此本阶段不默认引入，避免过早增加部署复杂度。

### Decision 5: MCP 管理 UI 先采用轻量管理页并复用现有 API 前缀

新增 MCP 管理 API 和静态管理页面或前端模块，提供注册、连接测试、启停、能力浏览、策略配置和审计查看。UI 必须调用后端 API，不直接接触密钥明文；敏感连接配置仅展示脱敏值。

替代方案是仅通过配置文件维护 MCP 服务。该方案无法满足运行期治理、连接测试和审计查看需求，因此不采用。

## Risks / Trade-offs

- [Risk] 真实 MCP Server 连接不稳定或协议实现差异导致调用失败 → Mitigation：客户端网关统一握手、超时、重试、错误归一化和降级输出。
- [Risk] MCP 能力可能声明高风险工具 → Mitigation：注册和筛选阶段强制记录 risk_level、required_permissions、human_confirmation_required，并复用安全风控检查。
- [Risk] PostgreSQL 承载过多半结构化资源内容导致表膨胀 → Mitigation：仅保存资源索引、文本型 schema 和必要元数据；一旦出现大体积二进制或长期归档需求，再以独立变更引入对象存储。
- [Risk] Redis/Valkey 缓存与 PostgreSQL 事实数据不一致 → Mitigation：以 PostgreSQL 为准，缓存设置 TTL、版本号和失效策略，关键写操作先落库后失效缓存。
- [Risk] 管理 UI 可能泄露 MCP 连接密钥 → Mitigation：后端只返回脱敏配置，密钥写入走专用接口并审计。
- [Risk] 运行时耦合具体 MCP 存储实现 → Mitigation：运行时仅依赖注册服务或 Protocol，不直接访问内存仓储。

## Migration Plan

1. 新增 MCP 注册、远程调用、存储和管理 API 的模型与 Protocol。
2. 实现 PostgreSQL 持久化、Redis/Valkey 缓存与短期状态适配，并保留内存测试实现。
3. 实现 MCP Client Gateway，覆盖连接、握手、能力发现、流式通信、工具调用和错误归一化。
4. 新增 MCP 管理 API 与 UI，支持注册、连接测试、启停、能力浏览、策略配置和审计查看。
5. 在运行时计划或编排中接入 MCP 注册服务与客户端网关；低风险只读工具可授权调用，高风险工具转人工确认。
6. 增加单元、集成、端到端、安全边界和 UI 测试。
7. 回滚时关闭 MCP 运行时调用开关，保留原有业务场景执行路径不变。

## Open Questions

- 真实 MCP Client 优先采用官方 Python SDK、轻量 HTTP/SSE 客户端，还是院内集成平台代理？
- 管理 UI 采用现有 `src/static` 轻量页面，还是新增独立前端应用目录？
- MCP 资源内容是否会在近期出现大体积二进制或长期归档需求；如果会，应另起对象存储专项变更。
- MCP 密钥管理是否由现有环境变量/院内密钥系统承载；如果需要跨环境动态发布和审批，应另起配置中心专项变更。
