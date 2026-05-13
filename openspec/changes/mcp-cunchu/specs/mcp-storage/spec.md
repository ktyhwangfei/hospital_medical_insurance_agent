## ADDED Requirements

### Requirement: MCP storage must persist registry data through PostgreSQL and Redis/Valkey
系统 MUST 定义 MCP 存储端口，以 PostgreSQL 保存事实数据，以 Redis/Valkey 保存缓存、连接状态和短期运行状态，且运行时和业务场景 MUST NOT 直接依赖具体存储实现。

#### Scenario: Save and load MCP registry snapshot
- **WHEN** MCP 注册服务保存一个包含服务、能力、策略和状态的快照
- **THEN** MCP 存储端口 MUST 能够按 server_id 和 capability_id 读取对应数据
- **AND** 读取结果 MUST 与保存时的类型化模型一致

#### Scenario: Use PostgreSQL for structured MCP data
- **WHEN** MCP 服务、能力、工具 schema、资源索引、策略、审计索引或状态快照被注册或更新
- **THEN** 系统 MUST 将结构化与半结构化事实数据持久化到 PostgreSQL
- **AND** 上层 MCP 注册服务 MUST 只依赖同一 Protocol 契约

#### Scenario: Use Redis or Valkey for cache and short-lived state
- **WHEN** MCP 能力清单、连接健康状态、流式调用短期状态、幂等键、限流计数或分布式锁发生变化
- **THEN** 系统 MUST 能将热点数据和短期状态写入 Redis/Valkey
- **AND** 缓存失效后系统 MUST 能从持久化存储恢复必要元数据

#### Scenario: Avoid additional storage by default
- **WHEN** MCP 资源内容可表示为结构化元数据、文本 schema、资源 URI 或资源索引
- **THEN** 系统 MUST 使用 PostgreSQL 保存事实数据并使用 Redis/Valkey 加速访问
- **AND** 系统 MUST NOT 默认引入对象存储或配置中心运行依赖

#### Scenario: Defer object storage or config center to explicit future need
- **WHEN** MCP 后续需要保存大体积二进制资源、长期归档文件、跨环境配置发布、集中密钥托管或复杂配置审批
- **THEN** 系统 MUST 通过新的 OpenSpec 变更评估对象存储或配置中心
- **AND** 当前 MCP 存储端口 MUST 保持可扩展以便后续接入

### Requirement: MCP in-memory storage must remain available for tests
系统 MUST 保留 MCP 内存存储实现用于测试、本地开发和降级验证，且 MUST 返回数据副本，避免调用方修改内部状态。

#### Scenario: Caller mutates returned MCP object
- **WHEN** 调用方读取 MCP 服务或能力后修改返回对象
- **THEN** 内存存储中的原始注册数据 MUST NOT 被隐式修改

#### Scenario: Query order remains deterministic
- **WHEN** 调用方按场景、角色或能力类型多次查询 MCP 能力
- **THEN** 内存存储 MUST 返回稳定排序结果
- **AND** 测试 MUST 能够进行确定性断言

### Requirement: MCP storage must track status and audit metadata
系统 MUST 在 MCP 存储中保存服务状态、能力状态、最近更新时间、更新来源和审计事件引用。

#### Scenario: Disable MCP server
- **WHEN** 管理逻辑将 MCP 服务状态更新为 disabled
- **THEN** MCP 存储 MUST 保存状态变更时间、变更原因和 audit_event
- **AND** 后续能力查询 MUST 反映禁用状态

#### Scenario: Record capability selection snapshot
- **WHEN** 运行时选择或排除 MCP 能力
- **THEN** MCP 存储或运行时状态 MUST 能记录选择快照
- **AND** 快照 MUST 包含 selected_capabilities、excluded_capabilities、reasons 和 citations 或 uncertainties
