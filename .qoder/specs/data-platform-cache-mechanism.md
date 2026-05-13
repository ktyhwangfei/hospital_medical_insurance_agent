# Data Platform 缓存机制实现方案

## Context

当前系统的数据访问只有两种模式：PostgreSQL（生产）或纯内存（测试/回退）。生产环境下，每次读操作都直连数据库，对于 Skill、MCP、Knowledge 等读多写少的配置类数据，这造成了不必要的数据库负载和延迟。Redis 基础设施已就绪（`src/data_platform/cache/`），但仅被 MCP 的 `RedisMcpCache` 局部使用，未系统化集成到存储层。

**目标**：为读多写少的配置类存储域引入 Redis 缓存代理层，采用装饰器/代理模式 + TTL + 写穿透策略，对上层消费者完全透明。

---

## 实现方案

### 架构设计

```
消费者 (routes / orchestrator / services)
    │  调用 SkillStorage / McpStorage / etc. Protocol
    ▼
CachedXxxStorage (代理)
    ├─ CacheClient (Redis / InMemory)  ← 读时先查缓存
    └─ Underlying Storage (PostgreSQL)  ← 缓存未命中时回源
```

**数据流**：
- **读（命中）**：CachedStorage → Redis → 返回反序列化结果
- **读（未命中）**：CachedStorage → Redis miss → PostgreSQL → 写入 Redis（带TTL）→ 返回
- **写**：CachedStorage → PostgreSQL 写成功 → 删除/更新相关缓存键
- **Redis 故障**：catch exception → log warning → 直接走 PostgreSQL → 返回（不抛异常）

---

### 文件清单

#### 新建文件

| 文件 | 职责 |
|------|------|
| `src/data_platform/cache/config.py` | 缓存 TTL 配置、key 前缀常量、全局开关 |
| `src/data_platform/cache/cached_base.py` | 缓存代理基类：封装安全读写/删除/熔断逻辑 |
| `src/data_platform/storage/skill/cached.py` | `CachedSkillStorage` 代理 |
| `src/data_platform/storage/mcp/cached.py` | `CachedMcpStorage` 代理 |
| `src/knowledge_extension/knowledge/cached.py` | `CachedKnowledgeStore`（错误码）代理 |
| `src/data_platform/storage/rule/cached.py` | `CachedRuleStorage` 代理 |
| `src/data_platform/storage/knowledge/cached.py` | `CachedKnowledgeStorage`（资产+切片）代理 |
| `src/knowledge_extension/knowledge/cached_appeal.py` | `CachedAppealTemplateStore` 代理 |
| `src/tests/data_platform/test_cached_storages.py` | 缓存代理单元测试 |

#### 修改文件

| 文件 | 变更 |
|------|------|
| `src/data_platform/cache/ports.py` | `CacheClient` Protocol 增加 `delete_pattern(prefix: str) -> int` |
| `src/data_platform/cache/redis_cache.py` | 实现 `delete_pattern()` — SCAN + DELETE |
| `src/data_platform/cache/in_memory.py` | 实现 `delete_pattern()` — 前缀匹配删除 |
| `src/data_platform/cache/__init__.py` | 新增 `create_cache_client_optional() -> CacheClient | None` |
| `src/data_platform/storage/skill/factory.py` | 条件包装 `CachedSkillStorage` |
| `src/data_platform/storage/mcp/factory.py` | 条件包装 `CachedMcpStorage` |
| `src/knowledge_extension/knowledge/factory.py` | 条件包装 `CachedKnowledgeStore` |
| `src/config/production.py` | 增加 `CACHE_ENABLED`、各域 TTL 环境变量 |

---

### 详细设计

#### 1. 缓存配置 — `src/data_platform/cache/config.py`

```python
import os

# 全局开关
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1").lower() in ("1", "true", "yes")
CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", "")  # 多租户隔离用

# 各域 TTL（秒）
CACHE_TTL_SKILL = int(os.getenv("CACHE_TTL_SKILL", "3600"))          # 1h
CACHE_TTL_MCP = int(os.getenv("CACHE_TTL_MCP", "3600"))              # 1h
CACHE_TTL_KNOWLEDGE = int(os.getenv("CACHE_TTL_KNOWLEDGE", "7200"))  # 2h
CACHE_TTL_RULE = int(os.getenv("CACHE_TTL_RULE", "7200"))            # 2h
CACHE_TTL_ASSET = int(os.getenv("CACHE_TTL_ASSET", "1800"))          # 30m
CACHE_TTL_APPEAL = int(os.getenv("CACHE_TTL_APPEAL", "7200"))        # 2h
```

#### 2. 缓存代理基类 — `src/data_platform/cache/cached_base.py`

提供安全的缓存操作封装 + 熔断机制：

```python
class CachedStorageBase:
    def __init__(self, cache: CacheClient, domain: str, default_ttl: int):
        self._cache = cache
        self._domain = domain
        self._default_ttl = default_ttl
        self._failure_count = 0
        self._last_failure_time = 0.0
        # 连续 5 次失败后 60 秒内跳过缓存
        self._circuit_threshold = 5
        self._circuit_window = 60.0

    def _make_key(self, *parts: str) -> str:
        """生成缓存键，带可选全局前缀"""
        ...

    def _should_try_cache(self) -> bool:
        """熔断判断：连续失败过多则短路"""
        ...

    def _safe_get(self, key: str) -> dict | None:
        """安全读取，异常时返回 None 并记录"""
        ...

    def _safe_set(self, key: str, value: dict, ttl: int | None = None) -> None:
        """安全写入，异常时仅记录 warning"""
        ...

    def _safe_delete(self, key: str) -> None:
        """安全删除单个键"""
        ...

    def _safe_delete_pattern(self, prefix: str) -> None:
        """安全删除匹配前缀的所有键"""
        ...
```

#### 3. CacheClient Protocol 扩展

在 `ports.py` 中增加：
```python
def delete_pattern(self, prefix: str) -> int: ...
```

Redis 实现使用 `SCAN 0 MATCH {prefix}* COUNT 100` 迭代 + 批量 `DELETE`，避免 `KEYS` 阻塞。

InMemory 实现使用 `[k for k in self._values if k.startswith(prefix)]` 前缀过滤。

#### 4. `create_cache_client_optional()` — 安全工厂

```python
def create_cache_client_optional() -> CacheClient | None:
    """创建缓存客户端，失败时返回 None（不抛异常）"""
    from src.data_platform.cache.config import CACHE_ENABLED
    if not CACHE_ENABLED:
        return None
    try:
        return create_cache_client()
    except Exception as e:
        logger.warning(f"Redis unavailable, caching disabled: {e}")
        return None
```

#### 5. 缓存代理实现（以 Skill 为例）

```python
class CachedSkillStorage(CachedStorageBase):
    def __init__(self, underlying: SkillStorage, cache: CacheClient, ttl: int):
        super().__init__(cache, "skill", ttl)
        self._store = underlying

    def get_skill(self, skill_id: str) -> Skill | None:
        key = self._make_key("get", skill_id)
        cached = self._safe_get(key)
        if cached is not None:
            return Skill(**cached)
        result = self._store.get_skill(skill_id)
        if result is not None:
            self._safe_set(key, result.model_dump(mode="json"))
        return result

    def list_skills(self) -> list[Skill]:
        key = self._make_key("list", "all")
        cached = self._safe_get(key)
        if cached is not None:
            return [Skill(**item) for item in cached["items"]]
        result = self._store.list_skills()
        self._safe_set(key, {"items": [s.model_dump(mode="json") for s in result]})
        return result

    def save_skill(self, skill: Skill) -> None:
        self._store.save_skill(skill)  # 先写 DB
        # 写穿透：删除相关缓存
        self._safe_delete(self._make_key("get", skill.skill_id))
        self._safe_delete_pattern(self._make_key("list"))
        self._safe_delete_pattern(self._make_key("by_owner"))
        self._safe_delete_pattern(self._make_key("by_role"))

    def delete_skill(self, skill_id: str) -> bool:
        result = self._store.delete_skill(skill_id)
        if result:
            self._safe_delete(self._make_key("get", skill_id))
            self._safe_delete_pattern(self._make_key("list"))
            self._safe_delete_pattern(self._make_key("by_owner"))
            self._safe_delete_pattern(self._make_key("by_role"))
        return result

    def health(self) -> SkillStorageHealth:
        return self._store.health()  # 透传底层健康状态
```

#### 6. 非 Pydantic 存储的代理（Knowledge/Rule/Appeal）

这些存储使用 `dict[str, Any]` 作为数据格式，缓存代理直接存取 dict 无需序列化转换：

```python
class CachedKnowledgeStore(CachedStorageBase):
    def get_error_code(self, error_code: str) -> dict | None:
        key = self._make_key("error_code", error_code)
        cached = self._safe_get(key)
        if cached is not None:
            return cached
        result = self._store.get_error_code(error_code)
        if result is not None:
            self._safe_set(key, result)
        return result
```

#### 7. 缓存键命名规范

| 域 | 键模式 | 示例 |
|----|--------|------|
| skill | `skill:get:{id}`, `skill:list:all`, `skill:by_owner:{owner}`, `skill:by_role:{role}` | `skill:get:sk-001` |
| mcp | `mcp:server:{id}`, `mcp:servers:all`, `mcp:cap:{id}`, `mcp:caps:all` | `mcp:server:srv-001` |
| knowledge | `knowledge:ec:{code}`, `knowledge:ec:all` | `knowledge:ec:E-UPLOAD-001` |
| rule | `rule:get:{id}`, `rule:list:{scenario}` | `rule:list:settlement` |
| asset | `asset:list:{type}`, `asset:chunks:{id}` | `asset:list:policy` |
| appeal | `appeal:list:{enabled}` | `appeal:list:true` |

若设置了 `CACHE_KEY_PREFIX=tenant1`，则所有键前置 `tenant1:` 前缀。

#### 8. 工厂集成（以 Skill 为例）

```python
def create_skill_storage() -> SkillStorage:
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")

    if not use_memory:
        try:
            storage = PostgresSkillStorage(DATABASE_URL)
            # 尝试包装缓存代理
            from src.data_platform.cache import create_cache_client_optional
            from src.data_platform.cache.config import CACHE_TTL_SKILL
            cache = create_cache_client_optional()
            if cache is not None:
                from src.data_platform.storage.skill.cached import CachedSkillStorage
                return CachedSkillStorage(storage, cache, CACHE_TTL_SKILL)
            return storage
        except Exception as e:
            logger.warning(f"... falling back to in-memory: {e}")

    return InMemorySkillStorage()  # 内存模式不加缓存
```

其他工厂（MCP、Knowledge、Rule、Appeal、Asset）同理。

#### 9. 熔断机制

- 连续 5 次缓存操作异常 → 标记熔断开启
- 熔断期间（60秒）所有缓存操作直接跳过 → 直连 DB
- 60秒后自动尝试恢复 → 成功则重置计数器

---

### 实现顺序

1. **基础设施**：`cache/config.py` → `cache/cached_base.py` → 扩展 `ports.py` → 实现 `delete_pattern` → 增加 `create_cache_client_optional`
2. **缓存代理**：`skill/cached.py` → `mcp/cached.py` → `knowledge/cached.py` → `rule/cached.py` → `knowledge/cached.py`(资产) → `cached_appeal.py`
3. **工厂集成**：修改各 `factory.py` 条件包装
4. **配置补充**：`production.py` 增加 TTL 常量
5. **测试**：编写单元测试验证缓存命中/失效/熔断

---

### 验证方式

```bash
# 1. 运行全部测试（确保不破坏现有功能）
python -m pytest src/tests -v

# 2. 内存模式仍正常（不触发缓存）
USE_MEMORY_STORAGE=1 python -m pytest src/tests -v

# 3. 带缓存模式测试（新增测试文件）
python -m pytest src/tests/data_platform/test_cached_storages.py -v

# 4. 禁用缓存开关验证
CACHE_ENABLED=0 python -m pytest src/tests -v

# 5. 启动服务验证端到端
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
# 调用 /api/v1/medical-insurance-ai-agent/skills → 第二次调用应从缓存返回
# 调用 POST /skills 创建技能 → 再 GET /skills 应看到最新数据（缓存已失效）
```

---

### 关键约束

- `USE_MEMORY_STORAGE=1` 时不包装缓存代理（测试环境无需 Redis）
- Redis 故障永不上抛异常到消费者
- 写操作先成功写入 DB，再失效缓存（保证最终一致性）
- 不缓存纯计算操作（如 `render_template`）
- 不缓存高频写入的数据（Workflow、Task、AuditLog）
