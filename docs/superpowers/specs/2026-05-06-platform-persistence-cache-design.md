# 平台级 Persistence / Cache 基础设施设计

## 背景

`mcp-cunchu` 当前已完成内存存储、PostgreSQL/Redis health stub、MCP 注册、管理 API、运行时接入和安全边界。`openspec/changes/mcp-cunchu/tasks.md` 中仍有真实 PostgreSQL 事实存储、Redis/Valkey 缓存、流式短期状态、幂等、限流、分布式锁等任务未完成。

这些能力不应只服务 MCP。后续 Tools、Skills、A2A、外部 Agent 接入、任务闭环和审计查询也会复用持久化存储与缓存。因此本轮不在 `src/data_platform/storage/mcp/` 中直接写死数据库驱动，而是建设平台级通用 Persistence / Cache 基础设施，再由 MCP 仓储复用。

## 目标

1. 提供数据库无关的关系型持久化基础设施，当前落地 PostgreSQL，预留金仓等国产数据库切换点。
2. 提供缓存无关的短期状态与协同能力，当前落地 Redis/Valkey，预留替换点。
3. 保持业务模块只依赖领域仓储接口，不直接依赖 PostgreSQL、金仓、Redis 或具体驱动。
4. 在默认本地开发和测试环境中保持内存实现可用，不因外部数据库缺失阻断主流程。
5. 为 MCP 先实现真实持久化和缓存复用示例，形成 Tools、Skills、A2A 后续接入模板。

## 非目标

1. 本轮不实现完整数据库迁移平台，只提供可重复执行的 schema bootstrap 能力。
2. 本轮不强制所有运行时状态切到数据库，既有内存 workflow/task 状态保持不变。
3. 本轮不实现生产级连接池治理、读写分离、多租户分库分表或跨库事务。
4. 本轮不要求金仓真实环境可连接，只预留方言与执行器扩展点，并用测试验证可替换边界。

## 目录设计

```text
src/data_platform/persistence/
  __init__.py
  models.py
  ports.py
  dialects.py
  executors.py
  migrations.py

src/data_platform/cache/
  __init__.py
  models.py
  ports.py
  redis_cache.py
  in_memory.py

src/data_platform/storage/mcp/
  postgres.py
  redis_cache.py
```

## Persistence 抽象

### 核心模型

- `DatabaseBackend`：`postgresql`、`kingbase`、`unknown`。
- `DatabaseHealth`：`status`、`backend`、`available`、`details`。
- `SqlStatement`：封装 SQL 文本与参数，避免业务层直接拼接字符串。
- `QueryResult`：封装 `rows`、`rowcount`。

### 核心接口

`SqlDialect` 负责数据库差异：

- 参数占位符格式。
- JSON 编码和 JSON 字段表达。
- upsert 语句生成。
- 分页语法。
- 时间函数。
- schema bootstrap DDL。

`DatabaseExecutor` 负责执行：

- `execute(statement)`。
- `fetch_one(statement)`。
- `fetch_all(statement)`。
- `transaction()`。
- `health()`。

`SchemaMigrator` 负责最小化 schema bootstrap：

- 幂等建表。
- 幂等索引创建。
- 记录当前 schema version。

### PostgreSQL 与金仓兼容策略

当前实现 `PostgresDialect` 与 `PsycopgDatabaseExecutor`。`PostgresDialect` 使用 PostgreSQL 兼容 SQL，尽量避免非必要专有语法。金仓后续通过两种方式接入：

1. 如果金仓驱动兼容 PostgreSQL 协议，则复用 `PsycopgDatabaseExecutor`，只替换 `KingbaseDialect`。
2. 如果驱动 API 不兼容，则新增 `KingbaseDatabaseExecutor`，保持上层仓储不变。

MCP、Tools、Skills、A2A 领域仓储只接收 `DatabaseExecutor` 和 `SqlDialect`，不得直接 import `psycopg`、`kingbase` 或其他具体驱动。

## Cache 抽象

### 核心模型

- `CacheBackend`：`redis`、`valkey`、`in_memory`、`unknown`。
- `CacheHealth`：`status`、`backend`、`available`、`details`。
- `CacheEntry`：`key`、`value`、`ttl_seconds`。

### 核心接口

`CacheClient` 提供通用操作：

- `get_json(key)`。
- `set_json(key, value, ttl_seconds)`。
- `delete(key)`。
- `exists(key)`。
- `health()`。

`ShortStateStore` 提供短期状态：

- `save_state(namespace, key, value, ttl_seconds)`。
- `load_state(namespace, key)`。
- `delete_state(namespace, key)`。

`IdempotencyStore` 提供幂等：

- `reserve(key, ttl_seconds)`。
- `complete(key, value, ttl_seconds)`。
- `get_result(key)`。

`RateLimiter` 提供限流计数：

- `increment_and_check(key, limit, window_seconds)`。

`DistributedLock` 提供分布式锁：

- `acquire(key, ttl_seconds, owner)`。
- `release(key, owner)`。

Redis 与 Valkey 统一由 `RedisCacheClient` 实现。Valkey 使用 Redis 兼容协议时只通过配置标识 backend，不改变上层接口。

## MCP 仓储落地

`PostgresMcpStorage` 从 health stub 升级为真实仓储实现：

- `save_server()` 写入 `mcp_servers`。
- `get_server()` 读取并还原 `McpServer`。
- `list_servers()` 稳定排序返回。
- `save_capability()` 写入 `mcp_capabilities`。
- `get_capability()` 读取并还原 `McpCapability`。
- `list_capabilities()` 稳定排序返回。
- `health()` 调用 `DatabaseExecutor.health()` 并补充 MCP schema 状态。

`RedisMcpCache` 从 health stub 升级为 MCP 专用缓存封装，但内部依赖通用 `CacheClient`：

- 缓存能力列表。
- 缓存连接健康状态。
- 保存流式调用短期状态。
- 提供幂等键、限流计数和分布式锁包装。

## 数据表

### `mcp_servers`

- `server_id`：主键。
- `payload_json`：完整 `McpServer` JSON，不存明文敏感响应视图。
- `status`：冗余状态字段，用于索引和查询。
- `transport`：冗余传输类型。
- `updated_at`：更新时间。

### `mcp_capabilities`

- `capability_id`：主键。
- `server_id`：服务 ID。
- `payload_json`：完整 `McpCapability` JSON。
- `capability_type`：冗余能力类型。
- `risk_level`：冗余风险等级。
- `enabled`：冗余启用状态。
- `updated_at`：更新时间。

### `mcp_audit_index`

- `audit_id`：主键。
- `event_type`。
- `server_id`。
- `capability_id`。
- `workflow_id`。
- `summary_json`。
- `created_at`。

本轮 MCP 仓储优先实现 `mcp_servers` 和 `mcp_capabilities`，`mcp_audit_index` 可先建表并预留写入接口。

## 配置

扩展 `McpSettings` 或新增平台级设置：

- `persistence_backend`：默认 `in_memory`，可选 `postgresql`、`kingbase`。
- `postgres_dsn`：当前 PostgreSQL 连接串。
- `database_schema_auto_init`：默认 `false`，测试或本地可开启。
- `cache_backend`：默认 `in_memory`，可选 `redis`、`valkey`。
- `redis_url`：Redis/Valkey 连接串。
- `connection_timeout_seconds`。

默认仍使用内存实现，避免没有外部服务时影响当前演示和测试。

## 错误处理与降级

- 数据库驱动未安装：health 返回 `unhealthy`，details 说明 `driver_not_installed`。
- 数据库不可连接：health 返回 `unhealthy`，不抛出到 API 顶层。
- schema 未初始化：health 返回 `degraded` 或 `unhealthy`，取决于是否可自动初始化。
- Redis 不可用：缓存 health 返回 `unhealthy`，MCP 选择流程可直接走数据库或内存，不因缓存失败阻断。
- 写入失败：仓储方法抛出领域明确异常，API 层再转换为标准错误结构。

## 测试策略

1. 使用 FakeExecutor 测试方言和仓储 SQL 生成，不依赖真实 PostgreSQL。
2. 使用 SQLite 仅作为 executor 行为测试替身时，不声明其代表 PostgreSQL 或金仓。
3. Redis/Valkey 通过 FakeCacheClient 覆盖缓存语义，真实 Redis 用环境变量启用可选集成测试。
4. 若 `MCP_POSTGRES_DSN` 存在且 `psycopg` 可用，运行真实 PostgreSQL 集成测试。
5. 全量测试必须在无 PostgreSQL/Redis 的默认环境中通过。

## 实施顺序

1. 新增 persistence/cache 通用接口与模型。
2. 实现 `PostgresDialect` 和 `KingbaseDialect` 骨架。
3. 实现 `PsycopgDatabaseExecutor`，在驱动缺失时返回明确 health。
4. 将 `PostgresMcpStorage` 改造为依赖 executor/dialect 的真实仓储。
5. 实现 Redis/Valkey 通用缓存客户端与 `RedisMcpCache` 包装。
6. 扩展配置与工厂函数，在 API 层可选择内存、PostgreSQL、Redis/Valkey。
7. 补充默认无外部依赖测试、FakeExecutor 测试和可选真实集成测试。

## 验收标准

1. MCP 业务层不直接依赖具体数据库驱动。
2. PostgreSQL 真实存储可保存和读取 MCP server/capability。
3. Redis/Valkey 缓存可保存短期状态、幂等键、限流计数和锁状态。
4. 切换到金仓时只需新增或替换 dialect/executor，不修改 MCP Registry Service。
5. 默认无外部服务环境下，全部现有测试继续通过。
6. 有 PostgreSQL/Redis 环境变量时，可运行真实集成测试验证连接和 CRUD。

## 自检

- 无 TBD/TODO 占位。
- 设计范围聚焦在平台级 persistence/cache 与 MCP 首个落地实现。
- 默认运行不依赖外部数据库，与当前 MVP 约束兼容。
- PostgreSQL 当前落地与金仓后续切换点已明确分离。
