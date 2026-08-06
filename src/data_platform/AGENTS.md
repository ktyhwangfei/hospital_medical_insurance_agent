# data_platform/ — DaaS 数据底座

## 概述

数据访问、存储端口、缓存（Redis）、持久化（PostgreSQL）、Skill/Tool/MCP/向量存储。

## 结构

```
data_platform/
├── data_access/          # 数据访问端口 + PostgreSQL 实现（患者 & 交易数据）
├── cache/                # 缓存端口 + 内存/Redis 实现（redis_cache.py）
├── persistence/          # PostgreSQL 持久化层（dialects, executors, migrations）
└── storage/              # 存储实现
    ├── skill/            # 技能存储（ports + in_memory + postgres + factory + seed）
    ├── mcp/              # MCP 存储（ports + in_memory + postgres + redis_cache + factory）
    ├── postgresql/       # 共享 PostgreSQL 存储（client, models, audit/task/workflow store）
    ├── knowledge/        # 知识资产存储（postgres.py → knowledge_assets + knowledge_chunks）
    ├── rule/             # 规则解释存储（postgres.py → rule_explanations）
    ├── cache/            # 缓存存储端口（CachePort Protocol）
    ├── vector/           # 向量存储端口（VectorSearchPort Protocol）
    └── tool/             # ⚠️ 空目录（无 __init__.py），不要 import
```

## 关键约定

- 存储遵循 ports/adapter 模式：`ports.py` → `in_memory.py` → `postgres.py`
- 默认 PostgreSQL，`USE_MEMORY_STORAGE=1` 回退内存实现
- `PostgreSQLClient` 延迟连接，首次操作建立
- 配置在 `src/config/production.py`，环境变量可覆盖
- 详细表结构见 `docs/steering/数据库设计文档.md`

## 数据库表一览（18 张）

| 表名 | 用途 | 定义位置 |
|------|------|---------|
| `patients` | 患者基本信息 | `data_access/postgres.py` |
| `insurance_transactions` | 医保交易记录（结算/上传状态） | `data_access/postgres.py` |
| `workflows` | 工作流实例（编排引擎状态机） | `postgresql/models.py` |
| `tasks` | 人工确认任务（待办/确认/拒绝） | `postgresql/models.py` |
| `audit_logs` | 审计日志（全操作留痕） | `postgresql/models.py` |
| `sessions` | 用户会话管理 | `postgresql/models.py` |
| `skills` | AI 技能注册表（步骤+关键词+角色） | `storage/skill/postgres.py` |
| `mcp_servers` | MCP 服务器注册（JSON 序列化存储） | `storage/mcp/postgres.py` |
| `mcp_capabilities` | MCP 能力注册（关联 server_id） | `storage/mcp/postgres.py` |
| `error_code_knowledge` | 医保错误码知识库 | `knowledge/postgres.py` |
| `rule_explanations` | 规则解释库 | `storage/rule/postgres.py` |
| `knowledge_assets` | 知识资产 | `storage/knowledge/postgres.py` |
| `knowledge_chunks` | 知识切片 | `storage/knowledge/postgres.py` |
| `risk_control_rules` | 风控规则 | `security/risk_control/storage/postgres.py` |
| `risk_control_events` | 风控事件记录 | `security/risk_control/storage/postgres.py` |
| `appeal_templates` | 申诉模板 | `knowledge_extension/knowledge/appeal_postgres.py` |
| `prompt_templates` | 提示词模板 | `knowledge_extension/prompt_templates/postgres.py` |
| `checkpoints` | LangGraph 检查点 | `runtime/langgraph/postgresql_checkpointer.py` |

## 注意事项

- 所有表通过 `CREATE TABLE IF NOT EXISTS` 自动建表
- `PostgreSQLClient` 通过可重入锁串行化共享连接操作；事务锁覆盖 `BEGIN` 到 `COMMIT/ROLLBACK`，禁止其他线程的 SQL 穿插
- `UnavailableDatabaseExecutor` 用于驱动未安装时的优雅降级
- 建表 SQL 定义有重复：`models.py`（SQLAlchemy）和 `*_store.py`（原始 SQL）需同步维护
