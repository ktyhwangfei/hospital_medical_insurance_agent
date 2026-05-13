# Data Platform 缓存机制实现方案

## TL;DR

> **Quick Summary**: 为读多写少的配置类存储（Skill/MCP/Knowledge/Rule/Appeal）引入 Redis 缓存代理层，采用代理模式 + TTL + 写穿透失效 + 熔断降级。同时修复 3 个预埋 Bug：RedisMcpCache 运行时 AttributeError、create_cache_client() 无回退、storage/cache/ports.py 死代码。

> **Deliverables**:
> - 修复 `RedisCacheClient` 缺失的 4 个 Protocol 实现
> - 新建 `cache/config.py`（TTL 配置）、`cache/cached_base.py`（代理基类+序列化+熔断）
> - 6 个域名缓存代理：`CachedSkillStorage`、`CachedMcpStorage`、`CachedKnowledgeStore`、`CachedKnowledgeAssetStorage`、`CachedRuleStorage`、`CachedAppealTemplateStore`
> - 扩展 `CacheClient` Protocol 增加 `delete_pattern`
> - 3 个新工厂函数（Rule / KnowledgeAsset / Appeal）
> - 全量 TDD 单元测试覆盖

> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 4 Waves
> **Critical Path**: Task 4 (Protocol扩展) → Task 5 (Redis实现) → Task 9 (代理基类) → Task 10-15 (6域名代理并行) → Task 16-19 (工厂集成并行)

---

## Context

### Original Request
用户提供 `.qoder/specs/data-platform-cache-mechanism.md` 中的缓存机制方案，要求评估后生成修正版实现计划。系统已部署 Redis 但未被充分利用（架构完整性驱动），Redis 为高可用部署，一致性要求按场景区分。

### Interview Summary
**Key Discussions**:
- **动机**: 架构完整性 — Redis 已部署但 `create_cache_client()` 硬编码且仅 MCP 域局部使用
- **Redis 可靠性**: 生产 Redis 为哨兵/集群模式，高可用
- **一致性要求**: 按场景区分 — 最终一致性可接受，但需提供差异化配置能力
- **测试策略**: TDD — 先写测试再写实现，每个 TODO 含测试用例
- **缓存粒度**: 方案 A — 代理直接包装 Storage Protocol 方法的返回值，统一通过 `_to_cache_value()` 序列化为 JSON-safe 格式

**Research Findings**:
- **Oracle 发现 3 个预埋 Bug**:
  1. 🔴 `RedisMcpCache.reserve_invocation()` / `acquire_invocation_lock()` 调用 `RedisCacheClient` 上不存在的 `reserve()`/`acquire()` 方法 → 运行时 AttributeError
  2. 🔴 `create_cache_client()` 硬编码 Redis，失败时直接抛异常，无回退
  3. 🟡 `storage/cache/ports.py::CachePort` 死代码（0 import）
- **4 个域无工厂函数**: Rule、Knowledge/Asset+Chunk、Appeal、RuleExplanation — 需新建工厂作为缓存注入点
- **PostgreSQL 原始行序列化风险**: `PostgresKnowledgeStorage` / `PostgresRuleStorage` 返回的 dict 含 `date`/`Decimal` 等非 JSON 类型 → 需 `_json_safe_deep()` 转换层
- **两个 PostgreSQL 模式并存**: Pattern A (PostgreSQLClient) 和 Pattern B (executor+dialect) — 本次不改

### Metis Review
**Identified Gaps** (addressed):
- **缓存粒度不清** → 已明确方案 A：存储方法返回值缓存 + `_to_cache_value()` 统一序列化
- **缺少统一 Key 命名规范** → 已纳入 `cached_base.py` 的 `_make_key()` 方法
- **缓存击穿（thundering herd）** → 对 `list_all` 类方法增加 probablistic early expiry（80% TTL 时概率性提前刷新）
- **冷启动** → 接受为已知限制，首次读自动回源
- **Schema 版本漂移** → 缓存值带 `_cached_at` 时间戳，不校验版本（配置数据 Schema 变更同步部署）
- **监控缺口** → 已纳入 `cached_base.py` 的 hits/misses/errors 计数器和 health 暴露

---

## Work Objectives

### Core Objective
为 6 个读多写少配置数据域引入透明 Redis 缓存代理层，降低 PostgreSQL 读负载，同时修复 3 个预埋 Bug 确保代码安全。

### Concrete Deliverables
- `src/data_platform/cache/config.py` — TTL 配置 + 全局开关 + 按域开关
- `src/data_platform/cache/cached_base.py` — 代理基类（安全读写/Key构建/序列化/熔断/指数退避）
- `src/data_platform/storage/skill/cached.py` — `CachedSkillStorage`
- `src/data_platform/storage/mcp/cached.py` — `CachedMcpStorage`（替换 `RedisMcpCache`）
- `src/knowledge_extension/knowledge/cached.py` — `CachedKnowledgeStore`（错误码）
- `src/data_platform/storage/knowledge/cached.py` — `CachedKnowledgeAssetStorage`（资产+切片）
- `src/data_platform/storage/rule/cached.py` — `CachedRuleStorage`
- `src/knowledge_extension/knowledge/cached_appeal.py` — `CachedAppealTemplateStore`
- `src/data_platform/storage/knowledge/factory.py` — 新建 `create_knowledge_asset_storage()`
- `src/data_platform/storage/rule/factory.py` — 新建 `create_rule_storage()`
- `src/knowledge_extension/knowledge/appeal_factory.py` — 新建 `create_appeal_template_store()`
- `src/tests/unit/data_platform/test_cached_base.py` — 代理基类单元测试
- `src/tests/unit/data_platform/test_cached_storages.py` — 6 域名缓存代理集成测试

### Definition of Done
- [ ] `python -m pytest src/tests/unit/data_platform/test_cached_base.py -v` → PASS
- [ ] `python -m pytest src/tests/unit/data_platform/test_cached_storages.py -v` → PASS
- [ ] `CACHE_ENABLED=0 python -m pytest src/tests -v --tb=short` → 全部通过（缓存关闭不破坏现有功能）
- [ ] `python -m pytest src/tests/unit/data_platform/ -v --tb=short` → 全部通过（含现有缓存测试）

### Must Have
- 缓存代理对消费者完全透明（实现相同 Protocol/duck type）
- Redis 故障永不上抛异常到消费者
- 写操作先成功写入 DB，再失效缓存（保证最终一致性）
- Pydantic 域（Skill/MCP）通过 `model_dump(mode="json")` 序列化
- dict 域（Knowledge/Rule/Appeal）通过 `_json_safe_deep()` 递归转换
- 每个域名有独立的 TTL + 缓存开关环境变量
- TDD：每个 TODO 先写测试（RED）→ 实现（GREEN）

### Must NOT Have (Guardrails)
- **不缓存**: Workflow/Task/AuditLog（高写入）、DataStore/Patient（敏感数据）、RuntimeState（临时态）、Adapter 外部调用
- **不修改**: 现有 Storage 实现类的内部逻辑、PostgreSQL 模式（Pattern A/B 保持不变）
- **不新增**: API 端点、路由修改
- **不引入**: 复杂缓存预热策略、后台刷新线程
- **不缓存**: `None` 返回值（防止缓存穿透导致"不存在"被缓存）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, 现有 `src/tests/unit/data_platform/`)
- **Automated tests**: TDD (RED → GREEN → REFACTOR)
- **Framework**: pytest + pytest-asyncio
- **Each task follows**: Write failing test → implement minimal code → verify test passes → refactor

### QA Policy
Every task MUST include agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **API/Backend**: Use Bash (curl/pytest) — Run tests, verify output
- **Library/Module**: Use Bash (pytest) — Import, call, assert results
- **Cache inspection**: Use Bash (redis-cli) — GET/SET/DEL/SCAN

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 0 (P0 Bug Fixes — 3 tasks ALL parallel, no deps):
├── Task 1: fix-redis-cache-client — 补全缺失的4个Protocol [deep]
├── Task 2: fix-cache-client-fallback — create_cache_client 回退 [quick]
└── Task 3: remove-dead-cacheport — 删除死代码 [quick]

Wave 1 (Foundation — 6 tasks ALL parallel, depends Wave 0):
├── Task 4: protocol-delete-pattern — CacheClient 增加 delete_pattern [quick]
├── Task 5: redis-delete-pattern — RedisCacheClient SCAN+UNLINK实现 [quick]
├── Task 6: inmemory-delete-pattern — InMemoryCacheClient 前缀删除 [quick]
├── Task 7: cache-client-optional — create_cache_client_optional() [quick]
├── Task 8: cache-config — config.py TTL+开关 [quick]
└── Task 9: cached-base — 代理基类+序列化+熔断 [deep]

Wave 2 (Domain Proxies — 6 tasks ALL parallel, depends Wave 1):
├── Task 10: cached-skill-storage — CachedSkillStorage [unspecified-high]
├── Task 11: cached-mcp-storage — CachedMcpStorage + 替换RedisMcpCache [depth]
├── Task 12: cached-knowledge-store — CachedKnowledgeStore(错误码) [unspecified-high]
├── Task 13: cached-knowledge-asset — CachedKnowledgeAssetStorage + factory [unspecified-high]
├── Task 14: cached-rule-storage — CachedRuleStorage + factory [unspecified-high]
└── Task 15: cached-appeal-store — CachedAppealTemplateStore + factory [unspecified-high]

Wave 3 (Factory Integration — 4 tasks ALL parallel, depends Wave 2):
├── Task 16: integrate-skill-factory — 改 create_skill_storage() [quick]
├── Task 17: integrate-mcp-factory — 改 create_mcp_storage() + 清理 RedisMcpCache [unspecified-high]
├── Task 18: integrate-knowledge-factory — 改 create_knowledge_store() [quick]
└── Task 19: production-config — production.py 增加 TTL + 开关 env vars [quick]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
```

**Critical Path**: Task 4 → Task 5 → Task 9 → Task 10/11 → Task 16/17 → F1-F4
**Parallel Speedup**: ~65% faster than sequential (Wave 2 = 6 parallel)
**Max Concurrent**: 6 (Wave 2)

---

## TODOs

- [x] 1. Fix RedisCacheClient — 补全缺失的 4 个 Protocol 实现

  **What to do**:
  - 在 `src/data_platform/cache/redis_cache.py` 的 `RedisCacheClient` 类中增加以下方法实现：
    - `ShortStateStore`: `save_state(namespace, key, value, ttl)` → `SET {ns}:{key} {json_dumps(value)} EX {ttl}`, `load_state(ns, key)` → `GET {ns}:{key}` + `json_loads`, `delete_state(ns, key)` → `DEL {ns}:{key}`
    - `IdempotencyStore`: `reserve(key, ttl)` → `SETNX idempotency:{key} 1 EX {ttl}`, `complete(key, value, ttl)` → `SET idempotency:{key} {json_dumps(value)} EX {ttl}`, `get_result(key)` → `GET idempotency:{key}` + `json_loads`
    - `RateLimiter`: `increment_and_check(key, limit, window)` → `INCR rate:{key}` + 首次调用 `EXPIRE rate:{key} {window}`，返回 `RateLimitResult(allowed=count<=limit, current_count=count, limit=limit, window=window)`
    - `DistributedLock`: `acquire(key, ttl, owner)` → `SET lock:{key} {owner} NX EX {ttl}` 返回 `bool`, `release(key, owner)` → Lua 脚本 `GET + DEL if owner matches`
  - 更新类声明为 `class RedisCacheClient(CacheClient, ShortStateStore, IdempotencyStore, RateLimiter, DistributedLock)` 或保持 duck typing
  - **注意**: `RedisMcpCache` 通过 `InMemoryCacheClient` 测试一直通过，但生产切换到真实 Redis 会 `AttributeError`。这是本次修复的主要动机
  - **测试**: 先写测试 `test_redis_cache_client_full_protocols.py`，用 FakeRedis 验证所有新增方法的输入输出契约
    - 测试 `reserve()` 幂等：第二次 reserve 相同 key 返回 False
    - 测试 `acquire()` 锁：同一 owner 可重入，不同 owner 被拒绝
    - 测试 `increment_and_check()` 速率限制窗口语义

  **Must NOT do**:
  - 不修改 `InMemoryCacheClient`（它已完整实现，作为参考实现）
  - 不修改 `RedisMcpCache` 类本身（Task 11 统一处理替换）

  **Recommended Agent Profile**:
  > Python 后端，需要理解 Redis 原语和 Lua 脚本
  - **Category**: `deep`
    - Reason: 涉及分布式锁 Lua 脚本、速率限制窗口语义，需深入理解
  - **Skills**: [`systematic-debugging`, `test-driven-development`]
    - `systematic-debugging`: Bug 根源是 Protocol 实现缺失，需系统分析
    - `test-driven-development`: 先写测试验证契约，再补实现

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0 (with Tasks 2, 3)
  - **Blocks**: Tasks 5, 7, 9, 11
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/data_platform/cache/ports.py:1-80` — ShortStateStore, IdempotencyStore, RateLimiter, DistributedLock Protocol 契约（方法签名和返回值类型）
  - `src/data_platform/cache/in_memory.py:1-89` — InMemoryCacheClient 完整参考实现（所有方法的正确语义）
  - `src/data_platform/cache/redis_cache.py:1-40` — RedisCacheClient 现有实现（5 个方法，需扩展到此文件）
  - `src/data_platform/cache/models.py:1-30` — CacheHealth, RateLimitResult 模型定义
  - `src/data_platform/storage/mcp/redis_cache.py:40-80` — RedisMcpCache 调用 reserve()/acquire()/release() 的位置（验证修复必要性的依据）

  **Acceptance Criteria**:

  **TDD (tests first)**:
  - [ ] 新建测试文件 `src/tests/unit/data_platform/test_redis_cache_full_protocols.py`
  - [ ] `python -m pytest src/tests/unit/data_platform/test_redis_cache_full_protocols.py -v` → 全部 FAIL（红，协议尚未实现）
  - [ ] 实现完成后 → 全部 PASS（绿）

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: IdempotencyStore reserve — first call succeeds, second fails
    Tool: Bash (pytest)
    Preconditions: FakeRedis 已初始化
    Steps:
      1. client = RedisCacheClient(redis_client=fake_redis)
      2. assert client.reserve("req-001", ttl=60) is True
      3. assert client.reserve("req-001", ttl=60) is False (重复保留)
    Expected Result: 第一次 reserve=True, 第二次 reserve=False
    Failure Indicators: 第二次 reserve 返回 True（未正确实现 SETNX）
    Evidence: .sisyphus/evidence/task-1-idempotency-reserve.txt

  Scenario: DistributedLock acquire — owner exclusivity
    Tool: Bash (pytest)
    Preconditions: FakeRedis 已初始化
    Steps:
      1. assert client.acquire("lock-a", ttl=10, owner="proc-1") is True
      2. assert client.acquire("lock-a", ttl=10, owner="proc-2") is False
      3. assert client.release("lock-a", owner="proc-2") is False
      4. assert client.release("lock-a", owner="proc-1") is True
    Expected Result: 仅 owner 能释放锁，不同 owner 被拒绝
    Evidence: .sisyphus/evidence/task-1-distributed-lock.txt

  Scenario: RateLimiter — 窗口内计数
    Tool: Bash (pytest)
    Preconditions: FakeRedis 已初始化
    Steps:
      1. r1 = client.increment_and_check("api-x", limit=3, window=60)
      2. r2 = client.increment_and_check("api-x", limit=3, window=60)
      3. r3 = client.increment_and_check("api-x", limit=3, window=60)
      4. r4 = client.increment_and_check("api-x", limit=3, window=60)
    Expected Result: r1-r3 allowed=True, r4 allowed=False, r4.current_count=4
    Evidence: .sisyphus/evidence/task-1-rate-limiter.txt
  ```

  **Evidence to Capture**:
  - [ ] Pytest output showing all new tests PASS
  - [ ] Before/after comparison of `redis_cache.py` method count (5→17+)

  **Commit**: YES (independent)
  - Message: `fix(cache): implement missing Protocols on RedisCacheClient (IdempotencyStore, DistributedLock, RateLimiter, ShortStateStore)`
  - Files: `src/data_platform/cache/redis_cache.py`, `src/tests/unit/data_platform/test_redis_cache_full_protocols.py`
  - Pre-commit: `python -m pytest src/tests/unit/data_platform/test_redis_cache_full_protocols.py -v`

- [x] 2. Fix create_cache_client() — 增加 Redis 不可用时的回退机制

  **What to do**:
  - 修改 `src/data_platform/cache/__init__.py` 中的 `create_cache_client()` 函数
  - 增加 `try/except`：Redis 连接失败时 catch `redis.ConnectionError` + `redis.TimeoutError`
  - 回退到 `InMemoryCacheClient()` 并 log warning（含失败原因）
  - 回退行为通过 `CACHE_FAIL_OPEN` 环境变量控制（默认 `"1"` — Redis 故障时回退到内存缓存而非抛异常）
  - 同时重命名现有函数为 `create_cache_client_strict()` 保留原始行为（向后兼容）
  - **测试**: 新建 `test_cache_client_fallback.py`，模拟 Redis 不可用，验证回退到 InMemory 且不抛异常
    - 测试 `CACHE_FAIL_OPEN=1` → Redis 不可用 → 返回 InMemoryCacheClient 实例
    - 测试 `CACHE_FAIL_OPEN=0` → Redis 不可用 → 抛异常

  **Must NOT do**:
  - 不改 `RedisCacheClient` 类的初始化逻辑
  - 不修改任何现有调用方对 `create_cache_client()` 的使用（返回值类型保持 `CacheClient`）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 范围小，单一函数 + 测试
  - **Skills**: [`test-driven-development`]
    - `test-driven-development`: 先写失败场景测试

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0 (with Tasks 1, 3)
  - **Blocks**: Task 7 (create_cache_client_optional 依赖此修复)
  - **Blocked By**: None

  **References**:
  - `src/data_platform/cache/__init__.py:1-20` — 现有 `create_cache_client()` 实现
  - `src/config/production.py:1-30` — REDIS_URL 配置来源
  - `src/data_platform/cache/in_memory.py:1-30` — InMemoryCacheClient 构造函数

  **Acceptance Criteria**:

  **TDD**:
  - [ ] 新建 `src/tests/unit/data_platform/test_cache_client_fallback.py`
  - [ ] `python -m pytest src/tests/unit/data_platform/test_cache_client_fallback.py -v` → RED → GREEN

  **QA Scenarios**:
  ```
  Scenario: Redis 不可用时回退到 InMemory (fail-open)
    Tool: Bash (pytest)
    Preconditions: CACHE_FAIL_OPEN=1, REDIS_URL 指向不可达地址
    Steps:
      1. client = create_cache_client()  # Redis 连接失败
      2. assert isinstance(client, InMemoryCacheClient)
      3. client.set_json("test", {"ok": True}, 60)
      4. assert client.get_json("test") == {"ok": True}
    Expected Result: 返回 InMemoryCacheClient 实例，功能正常
    Evidence: .sisyphus/evidence/task-2-fallback-inmemory.txt

  Scenario: CACHE_FAIL_OPEN=0 时 Redis 不可用抛异常
    Tool: Bash (pytest)
    Preconditions: CACHE_FAIL_OPEN=0, REDIS_URL 指向不可达地址
    Steps:
      1. with pytest.raises(Exception): create_cache_client()
    Expected Result: 抛出 ConnectionError 或 TimeoutError
    Evidence: .sisyphus/evidence/task-2-fail-closed.txt
  ```

  **Commit**: YES
  - Message: `fix(cache): add graceful fallback to InMemoryCacheClient when Redis unavailable`
  - Files: `src/data_platform/cache/__init__.py`, `src/tests/unit/data_platform/test_cache_client_fallback.py`

- [x] 3. Remove dead CachePort Protocol

  **What to do**:
  - 删除 `src/data_platform/storage/cache/ports.py` 文件（`CachePort` Protocol，2 个方法，0 个 import，无实现者）
  - 删除 `src/data_platform/storage/cache/__init__.py` 中对该文件的 re-export（如有）
  - 全项目搜索确认无引用：`grep -r "CachePort" src/` → 预期 0 结果
  - 全项目搜索确认无引用：`grep -r "storage.cache.ports" src/` → 预期 0 结果
  - **如发现任何引用**：先评估是否需要迁移到 `data_platform/cache/ports.py::CacheClient`

  **Must NOT do**:
  - 不删除 `data_platform/cache/ports.py`（这是正式的 5-Protocol 定义）
  - 不修改 `data_platform/cache/` 下的任何文件

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯删除操作 + 引用搜索
  - **Skills**: []
    - 不需要特殊 skill

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 0 (with Tasks 1, 2)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `src/data_platform/storage/cache/ports.py` — 待删除文件
  - `src/data_platform/cache/ports.py` — 正式的 CacheClient Protocol（保留）

  **Acceptance Criteria**:
  - [ ] `src/data_platform/storage/cache/ports.py` 文件不存在
  - [ ] `grep -r "CachePort" src/` 返回空
  - [ ] `grep -r "storage\.cache\.ports" src/` 返回空
  - [ ] `python -m pytest src/tests/unit/data_platform/ -v` → 全部通过（无 import 错误）

  **QA Scenarios**:
  ```
  Scenario: 删除后全项目无引用
    Tool: Bash (grep)
    Steps:
      1. grep -r "CachePort" src/  # 应无输出
      2. grep -r "storage\.cache\.ports" src/  # 应无输出
      3. python -m pytest src/tests/unit/data_platform/ -v  # 全部通过
    Expected Result: grep 无匹配，pytest 全部通过
    Evidence: .sisyphus/evidence/task-3-cacheport-removed.txt
  ```

  **Commit**: YES
  - Message: `chore(cache): remove dead CachePort Protocol (storage/cache/ports.py)`
  - Files: `src/data_platform/storage/cache/ports.py` (deleted)

- [x] 4. Extend CacheClient Protocol with delete_pattern

- [x] 5. Implement delete_pattern on RedisCacheClient (SCAN + UNLINK)

- [x] 6. Implement delete_pattern on InMemoryCacheClient

- [x] 7. Create create_cache_client_optional() safe factory

- [x] 8. Create cache/config.py — TTL 配置与全局开关

  **What to do**:
  - 新建 `src/data_platform/cache/config.py`
  - 包含以下配置常量（均通过环境变量可覆盖）：
    ```python
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1")  # 全局缓存开关
    CACHE_FAIL_OPEN = os.getenv("CACHE_FAIL_OPEN", "1")  # Redis故障时回退到InMemory
    CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", "")  # 多租户隔离前缀
    # 各域 TTL（秒）
    CACHE_TTL_SKILL = int(os.getenv("CACHE_TTL_SKILL", "3600"))        # 1h
    CACHE_TTL_MCP = int(os.getenv("CACHE_TTL_MCP", "3600"))            # 1h
    CACHE_TTL_KNOWLEDGE = int(os.getenv("CACHE_TTL_KNOWLEDGE", "7200")) # 2h
    CACHE_TTL_RULE = int(os.getenv("CACHE_TTL_RULE", "7200"))           # 2h
    CACHE_TTL_ASSET = int(os.getenv("CACHE_TTL_ASSET", "1800"))         # 30m
    CACHE_TTL_APPEAL = int(os.getenv("CACHE_TTL_APPEAL", "7200"))       # 2h
    # 按域缓存开关（精细控制）
    CACHE_ENABLED_SKILL = os.getenv("CACHE_ENABLED_SKILL", "1")
    CACHE_ENABLED_MCP = os.getenv("CACHE_ENABLED_MCP", "1")
    CACHE_ENABLED_KNOWLEDGE = os.getenv("CACHE_ENABLED_KNOWLEDGE", "1")
    CACHE_ENABLED_RULE = os.getenv("CACHE_ENABLED_RULE", "1")
    CACHE_ENABLED_ASSET = os.getenv("CACHE_ENABLED_ASSET", "1")
    CACHE_ENABLED_APPEAL = os.getenv("CACHE_ENABLED_APPEAL", "1")
    # 熔断参数
    CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CACHE_CIRCUIT_THRESHOLD", "5"))   # 连续失败阈值
    CIRCUIT_BREAKER_WINDOW = int(os.getenv("CACHE_CIRCUIT_WINDOW", "60"))         # 熔断恢复窗口（秒）
    ```
  - **测试**: 新建 `test_cache_config.py`，验证各环境变量默认值

  **Must NOT do**:
  - 不在 config.py 中引入 Redis 连接逻辑（连接逻辑在 cache/__init__.py）
  - 不写业务逻辑，纯配置常量

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯配置文件，逻辑简单
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 9 (cached_base.py 需要 TTL 配置)
  - **Blocked By**: None

  **References**:
  - `src/config/production.py:1-30` — 参考现有环境变量配置风格

  **QA Scenarios**:
  ```
  Scenario: 默认 TTL 值正确
    Tool: Bash (python)
    Steps:
      1. python -c "from src.data_platform.cache.config import CACHE_TTL_SKILL; assert CACHE_TTL_SKILL == 3600"
      2. python -c "from src.data_platform.cache.config import CACHE_TTL_KNOWLEDGE; assert CACHE_TTL_KNOWLEDGE == 7200"
    Expected Result: 无 AssertionError
    Evidence: .sisyphus/evidence/task-8-config-defaults.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add cache config with per-domain TTLs and feature flags`
  - Files: `src/data_platform/cache/config.py`

- [x] 9. Create cached_base.py — 缓存代理基类（序列化 + 熔断 + 安全操作）

  **What to do**:
  - 新建 `src/data_platform/cache/cached_base.py`
  - 实现 `CachedStorageBase` 类，提供所有域名代理的公共逻辑：
    1. **构造函数**: `__init__(self, cache: CacheClient, domain: str, default_ttl: int, per_domain_enabled: bool)`
    2. **Key 构建**: `_make_key(*parts: str) -> str` — 格式 `{CACHE_KEY_PREFIX}{domain}:{'/'.join(parts)}`，例如 `skill:get/sk-001`
    3. **熔断器**: 
       - `_should_try_cache() -> bool` — 连续失败达阈值且在窗口内 → 返回 False
       - `_record_failure()` / `_record_success()` — 更新计数器
       - `_failure_count` + `_last_failure_time` + `_circuit_open: bool`
    4. **安全操作**（永不抛异常）:
       - `_safe_get(key) -> dict | None` — 异常时 `_record_failure()` + return None
       - `_safe_set(key, value, ttl) -> None` — 异常时 `_record_failure()` + log warning
       - `_safe_delete(key) -> None` — 异常时 log warning
       - `_safe_delete_pattern(prefix) -> None` — 异常时 log warning
    5. **序列化辅助**:
       - `_to_cache_value(value) -> dict` — 统一入口：Pydantic 模型调用 `model_dump(mode="json")`，dict 递归 `_json_safe_deep()`，list 逐元素转换
       - `_json_safe_deep(obj) -> Any` — 递归处理 `date`→isoformat, `datetime`→isoformat, `Decimal`→float, `bytes`→base64, `set`→list
    6. **缓存读模式**:
       - `_cached_read(key, fetch_fn, ttl=None) -> Any` — 标准 read-through：查缓存 → miss 则调 fetch_fn → 写缓存 → 返回
       - 对 `fetch_fn` 返回 `None` 时不缓存（防穿透）
    7. **缓存失效模式**:
       - `_invalidate_keys(*keys)` — 批量删除缓存键，先写 DB 成功后调用
    8. **监控**: `hits`, `misses`, `errors` 计数器 + `health() -> dict` 方法
  - **测试**: 先写 `test_cached_base.py`（本计划中最关键的测试文件之一）
    - 测试 `_make_key` 键命名规范
    - 测试 `_json_safe_deep` 处理 date/Decimal/datetime
    - 测试 `_to_cache_value` 处理 Pydantic 模型和 dict
    - 测试熔断器：连续失败 N 次后熔断，窗口结束后恢复
    - 测试 `_cached_read`：命中/未命中/None 不缓存
    - 测试 `_safe_get` Redis 故障时返回 None（不抛异常）

  **Must NOT do**:
  - 不在此类中定义域名特定的缓存逻辑（在子类中实现）
  - 不直接 import 任何具体的存储类（保持抽象）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心抽象层，设计影响所有域名代理，需谨慎设计接口
  - **Skills**: [`test-driven-development`, `brainstorming`]
    - `test-driven-development`: 先写全面测试
    - `brainstorming`: 设计 `_cached_read` / `_invalidate_keys` 公共接口

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 10-15 (所有域名代理继承此类)
  - **Blocked By**: Task 8 (config.py TTL 配置)

  **References**:
  - `src/data_platform/cache/config.py` — TTL 配置常量
  - `src/data_platform/cache/ports.py:CacheClient` — 依赖的缓存接口
  - `src/data_platform/storage/skill/ports.py:SkillStorage` — 参考 Protocol 模式
  - `src/data_platform/storage/mcp/redis_cache.py:1-80` — 参考 RedisMcpCache 的安全操作模式

  **Acceptance Criteria**:

  **TDD**:
  - [ ] 新建 `src/tests/unit/data_platform/test_cached_base.py`
  - [ ] `python -m pytest src/tests/unit/data_platform/test_cached_base.py -v` → RED → GREEN
  - [ ] 覆盖所有公共方法 + 熔断器状态转换

  **QA Scenarios**:
  ```
  Scenario: _json_safe_deep — date/Decimal/datetime 转换
    Tool: Bash (pytest)
    Steps:
      1. import datetime, decimal
      2. obj = {"created": datetime.date(2026, 5, 13), "amount": decimal.Decimal("99.99")}
      3. result = CachedStorageBase._json_safe_deep(obj)
      4. assert result["created"] == "2026-05-13"
      5. assert result["amount"] == 99.99
    Expected Result: date→isoformat, Decimal→float
    Evidence: .sisyphus/evidence/task-9-json-safe-deep.txt

  Scenario: _cached_read — 命中返回缓存，未命中调 fetch_fn
    Tool: Bash (pytest with InMemoryCacheClient)
    Steps:
      1. call_count = 0
      2. def fetch(): nonlocal call_count; call_count += 1; return {"data": "fresh"}
      3. r1 = base._cached_read("test:key", fetch)  # miss → 调 fetch
      4. r2 = base._cached_read("test:key", fetch)  # hit → 不调 fetch
      5. assert call_count == 1
      6. assert r1 == r2 == {"data": "fresh"}
    Expected Result: 第一次 miss 调 fetch，第二次 hit 不调
    Evidence: .sisyphus/evidence/task-9-cached-read.txt

  Scenario: 熔断器 — 连续失败后跳过缓存
    Tool: Bash (pytest)
    Steps:
      1. 模拟 Redis 连续 5 次 _safe_get 抛异常
      2. assert base._circuit_open is True
      3. 第 6 次 _should_try_cache() 返回 False
      4. 等待 60s 后 assert base._circuit_open is False
    Expected Result: 5 次失败→熔断，60s 后恢复
    Evidence: .sisyphus/evidence/task-9-circuit-breaker.txt

  Scenario: fetch_fn 返回 None 时不缓存
    Tool: Bash (pytest)
    Steps:
      1. def fetch_none(): return None
      2. base._cached_read("test:none", fetch_none)
      3. assert base._safe_get("test:none") is None  # 未写入缓存
    Expected Result: None 不被缓存
    Evidence: .sisyphus/evidence/task-9-none-not-cached.txt
  ```

  **Evidence to Capture**:
  - [ ] Pytest output showing all test_cached_base tests PASS
  - [ ] Coverage report for cached_base.py (≥90%)

  **Commit**: YES
  - Message: `feat(cache): add CachedStorageBase with serialization, circuit breaker, and safe operations`
  - Files: `src/data_platform/cache/cached_base.py`, `src/tests/unit/data_platform/test_cached_base.py`

- [x] 10. Create CachedSkillStorage + TDD tests

  **What to do**:
  - 新建 `src/data_platform/storage/skill/cached.py`
  - 实现 `CachedSkillStorage` 类：
    1. 实现 `SkillStorage` Protocol（或 duck typing）
    2. 构造函数 `__init__(self, underlying: SkillStorage, cache: CacheClient, ttl: int, enabled: bool)`
    3. 若 `enabled=False` → 所有方法直接转发到 `underlying`（零开销旁路）
    4. 读方法使用 `_cached_read()`：
       - `get_skill(skill_id)` → key=`skill:get/{skill_id}`
       - `list_skills()` → key=`skill:list/all`
       - `list_skills_by_owner(owner)` → key=`skill:by_owner/{owner}`
       - `list_skills_by_role(role)` → key=`skill:by_role/{role}`
    5. 写方法使用 write-through invalidation：
       - `save_skill(skill)` → 先 `underlying.save_skill(skill)` → 删除 `skill:get/{id}` + `skill:list/*` + `skill:by_owner/*` + `skill:by_role/*`
       - `delete_skill(skill_id)` → 先 `underlying.delete_skill(skill_id)` → 同上删除
    6. `health()` → 透传 `underlying.health()`
  - **测试**: 先写 `test_cached_skill_storage.py`（TDD）
    - 用 InMemorySkillStorage + InMemoryCacheClient 测试
    - 测试缓存命中：两次 `get_skill` 只触发一次底层 `get_skill`（用 spy）
    - 测试写穿透：`save_skill` 后缓存被删除，下次读回源
    - 测试 `list_skills` 缓存
    - 测试 `enabled=False` 旁路

  **Must NOT do**:
  - 不修改 `InMemorySkillStorage` 或 `PostgresSkillStorage`
  - 不在代理中实现业务逻辑（纯缓存代理）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 中等复杂度，需要理解 SkillStorage Protocol + 缓存代理模式
  - **Skills**: [`test-driven-development`]
    - `test-driven-development`: TDD 流程

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 11, 12, 13, 14, 15)
  - **Blocks**: Task 16 (工厂集成)
  - **Blocked By**: Task 9 (cached_base.py)

  **References**:
  - `src/data_platform/cache/cached_base.py` — 继承的基类
  - `src/data_platform/storage/skill/ports.py:SkillStorage` — 需实现的 Protocol
  - `src/data_platform/storage/skill/in_memory.py` — 测试用的底层存储
  - `src/data_platform/cache/config.py:CACHE_TTL_SKILL` — TTL 配置
  - `src/data_platform/storage/skill/factory.py` — 后续集成的工厂

  **Acceptance Criteria**:
  - [ ] 新建 `src/tests/unit/data_platform/test_cached_skill_storage.py`
  - [ ] `python -m pytest src/tests/unit/data_platform/test_cached_skill_storage.py -v` → GREEN

  **QA Scenarios**:
  ```
  Scenario: get_skill 缓存命中
    Tool: Bash (pytest)
    Steps:
      1. storage = InMemorySkillStorage(); storage.save_skill(Skill(skill_id="s1", name="test"))
      2. cached = CachedSkillStorage(storage, InMemoryCacheClient(), ttl=3600, enabled=True)
      3. with patch.object(storage, 'get_skill', wraps=storage.get_skill) as spy:
      4.   r1 = cached.get_skill("s1"); r2 = cached.get_skill("s1")
      5.   assert spy.call_count == 1  # 底层只调用一次
    Expected Result: 首次 miss→底层, 第二次 hit→缓存
    Evidence: .sisyphus/evidence/task-10-cache-hit.txt

  Scenario: save_skill 写入后缓存失效
    Tool: Bash (pytest)
    Steps:
      1. cached.save_skill(Skill(skill_id="s1", name="v1"))
      2. cached.get_skill("s1")  # 预热缓存
      3. cached.save_skill(Skill(skill_id="s1", name="v2"))  # 写穿透
      4. result = cached.get_skill("s1")
      5. assert result.name == "v2"  # 读到新值（回源）
    Expected Result: 写后读到最新数据
    Evidence: .sisyphus/evidence/task-10-write-invalidate.txt

  Scenario: enabled=False 旁路缓存
    Tool: Bash (pytest)
    Steps:
      1. cached = CachedSkillStorage(storage, cache, enabled=False)
      2. with patch.object(storage, 'get_skill', wraps=storage.get_skill) as spy:
      3.   cached.get_skill("s1"); cached.get_skill("s1")
      4.   assert spy.call_count == 2  # 每次都调底层
    Expected Result: 直接透传，不经过缓存
    Evidence: .sisyphus/evidence/task-10-disabled-bypass.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add CachedSkillStorage proxy with TDD tests`
  - Files: `src/data_platform/storage/skill/cached.py`, `src/tests/unit/data_platform/test_cached_skill_storage.py`

- [x] 11. Create CachedMcpStorage + 替换 RedisMcpCache + TDD tests

  **What to do**:
  - 新建 `src/data_platform/storage/mcp/cached.py`
  - 实现 `CachedMcpStorage` 类，结构同 Task 10
  - **关键差异**: MCP 域有两层缓存需合并：
    1. 原 `RedisMcpCache` 的能力列表缓存 (`mcp:capabilities:{scenario}`) → 合并到 `list_capabilities()` 的 `_cached_read` 中
    2. 原 `RedisMcpCache` 的幂等保留 (`mcp:{request_id}`) + 分布式锁 (`mcp:capability:{id}`) → 保留在 `RedisMcpCache` 中（或迁移到直接使用 `IdempotencyStore`/`DistributedLock` Protocol）
  - **替换策略**: 修改 `create_mcp_storage()` 和 `McpSettings` 消费者，用 `CachedMcpStorage` 包裹存储，`RedisMcpCache` 降级为仅幂等/锁工具
  - **测试**: 先写 `test_cached_mcp_storage.py`
    - 测试 server/capability 的缓存读/写穿透
    - 测试 RedisMcpCache 的幂等锁功能不受影响

  **Must NOT do**:
  - 不删除 `RedisMcpCache` 的幂等/锁逻辑（除非确认无其他消费者）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需理解 MCP 域的双层缓存架构，涉及 RedisMcpCache 迁移
  - **Skills**: [`test-driven-development`, `systematic-debugging`]
    - `systematic-debugging`: 迁移过程中可能出现缓存键冲突

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 17 (工厂集成)
  - **Blocked By**: Task 9

  **References**:
  - `src/data_platform/storage/mcp/ports.py:McpStorage` — Protocol
  - `src/data_platform/storage/mcp/redis_cache.py:1-120` — 现有缓存层（需整合）
  - `src/data_platform/storage/mcp/in_memory.py` — 测试用底层存储
  - `src/data_platform/cache/config.py:CACHE_TTL_MCP` — TTL 配置

  **Acceptance Criteria**:
  - [ ] 新建 `src/tests/unit/data_platform/test_cached_mcp_storage.py`
  - [ ] `python -m pytest src/tests/unit/data_platform/test_cached_mcp_storage.py -v` → GREEN
  - [ ] 现有 `test_mcp_redis_cache.py` 全部通过（幂等/锁功能不受影响）

  **QA Scenarios**:
  ```
  Scenario: list_servers 缓存命中
    Tool: Bash (pytest)
    Steps:
      1. cached.save_server(McpServer(server_id="srv-1", ...))
      2. with spy on underlying.list_servers:
      3.   cached.list_servers(); cached.list_servers()
      4.   assert spy.call_count == 1
    Expected Result: 第二次调用命中缓存
    Evidence: .sisyphus/evidence/task-11-mcp-cache-hit.txt

  Scenario: MCP 写穿透后缓存失效
    Tool: Bash (pytest)
    Steps:
      1. cached.save_server(server_v1); cached.get_server("srv-1")
      2. cached.save_server(server_v2)
      3. result = cached.get_server("srv-1")
      4. assert result.name == server_v2.name
    Expected Result: 写后读到最新数据
    Evidence: .sisyphus/evidence/task-11-mcp-write-invalidate.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add CachedMcpStorage proxy, integrate with existing RedisMcpCache`
  - Files: `src/data_platform/storage/mcp/cached.py`, `src/tests/unit/data_platform/test_cached_mcp_storage.py`

- [x] 12. Create CachedKnowledgeStore (ErrorCode) + TDD tests

  **What to do**:
  - 新建 `src/knowledge_extension/knowledge/cached.py`
  - 实现 `CachedKnowledgeStore`（错误码域），duck typing 匹配 `InMemoryKnowledgeWrapper` 接口：
    - `get_error_code(error_code: str) -> dict | None` → key=`knowledge:ec/{error_code}`
    - `list_error_codes() -> list[dict]` → key=`knowledge:ec/all`
  - **序列化注意**: 错误码数据是 `dict[str, Any]`，来自 psycopg 可能有 `date` 类型 → 使用 `_json_safe_deep()`
  - **测试**: 先写 `test_cached_knowledge_store.py`
    - 测试错误码缓存的读命中/写穿透
    - 测试 `date` 字段的序列化（如有）

  **Must NOT do**:
  - 不修改 `ERROR_CODE_KNOWLEDGE` 硬编码字典

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 18 (工厂集成)
  - **Blocked By**: Task 9

  **References**:
  - `src/knowledge_extension/knowledge/factory.py:1-30` — 现有 InMemoryKnowledgeWrapper 接口
  - `src/knowledge_extension/knowledge/postgres.py` — PostgreSQL 实现
  - `src/knowledge_extension/knowledge/in_memory.py` — 硬编码错误码数据
  - `src/data_platform/cache/config.py:CACHE_TTL_KNOWLEDGE`

  **Acceptance Criteria**:
  - [ ] 新建 `src/tests/unit/data_platform/test_cached_knowledge_store.py`
  - [ ] `python -m pytest src/tests/unit/data_platform/test_cached_knowledge_store.py -v` → GREEN

  **QA Scenarios**:
  ```
  Scenario: 错误码查询缓存命中
    Tool: Bash (pytest)
    Steps:
      1. cached = CachedKnowledgeStore(underlying, InMemoryCacheClient(), ttl=7200, enabled=True)
      2. with spy on underlying.get_error_code:
      3.   cached.get_error_code("E-UPLOAD-001"); cached.get_error_code("E-UPLOAD-001")
      4.   assert spy.call_count == 1
    Expected Result: 第二次命中缓存
    Evidence: .sisyphus/evidence/task-12-ec-cache-hit.txt

  Scenario: list_error_codes 全量缓存
    Tool: Bash (pytest)
    Steps:
      1. cached.list_error_codes(); cached.list_error_codes()
      2. spy call_count == 1
    Expected Result: 第二次命中缓存
    Evidence: .sisyphus/evidence/task-12-ec-list-cache.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add CachedKnowledgeStore proxy for error code domain`
  - Files: `src/knowledge_extension/knowledge/cached.py`, `src/tests/unit/data_platform/test_cached_knowledge_store.py`

- [x] 13. Create CachedKnowledgeAssetStorage + factory + TDD tests

  **What to do**:
  - 新建 `src/data_platform/storage/knowledge/cached.py`
  - 新建 `src/data_platform/storage/knowledge/factory.py`（该域此前**无工厂**）
  - 实现 `CachedKnowledgeAssetStorage`（知识资产+切片域）：
    - 包装 `PostgresKnowledgeStorage`（或 `InMemoryKnowledgeStorage`）
    - 缓存 `list_assets(type)` → key=`knowledge_asset:list/{type}`
    - 缓存 `get_asset_chunks(asset_id)` → key=`knowledge_asset:chunks/{asset_id}`
    - 写操作后删除相关缓存键
  - 工厂函数 `create_knowledge_asset_storage() -> KnowledgeAssetStorage`:
    - `USE_MEMORY_STORAGE=1` → 返回 InMemory 实现（需新建简易 InMemory 类或复用）
    - 否则 → 创建 `PostgresKnowledgeStorage` → 条件包装 `CachedKnowledgeAssetStorage`
  - **序列化注意**: 资产数据含 `effective_date` (DATE), `metadata` (JSONB) → 使用 `_json_safe_deep()`
  - **测试**: 新建 `test_cached_knowledge_asset.py`

  **Must NOT do**:
  - 不修改 `PostgresKnowledgeStorage` 内部逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需同时建代理+工厂+InMemory实现
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None（该域无工厂集成步骤，工厂在本次自建）
  - **Blocked By**: Task 9

  **References**:
  - `src/data_platform/storage/knowledge/postgres.py` — 现有 PostgreSQL 实现
  - `src/data_platform/storage/skill/factory.py` — 参考工厂模式
  - `src/data_platform/cache/config.py:CACHE_TTL_ASSET`

  **QA Scenarios**:
  ```
  Scenario: list_assets 缓存命中 + 写穿透
    Tool: Bash (pytest)
    Steps:
      1. cached.list_assets("policy"); cached.list_assets("policy")
      2. 底层 spy.call_count == 1
      3. cached.save_asset(new_asset)
      4. cached.list_assets("policy")  # 失效后回源
    Expected Result: 命中后 write 失效再回源
    Evidence: .sisyphus/evidence/task-13-asset-cache.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add CachedKnowledgeAssetStorage with factory`
  - Files: `src/data_platform/storage/knowledge/cached.py`, `src/data_platform/storage/knowledge/factory.py`, `src/tests/unit/data_platform/test_cached_knowledge_asset.py`

- [x] 14. Create CachedRuleStorage + factory + TDD tests

  **What to do**:
  - 新建 `src/data_platform/storage/rule/cached.py`
  - 新建 `src/data_platform/storage/rule/factory.py`（该域此前**无工厂**）
  - 实现 `CachedRuleStorage`：
    - 包装 `PostgresRuleStorage`（或简易 InMemory 实现）
    - 缓存 `list_rules(scenario)` → key=`rule:list/{scenario}`
    - 缓存 `get_rule(rule_id)` → key=`rule:get/{rule_id}`
    - 写操作后删除相关缓存键
  - 工厂函数 `create_rule_storage() -> RuleStorage`:
    - `USE_MEMORY_STORAGE=1` → InMemory dict（简易实现）
    - 否则 → Postgres → 条件包装 Cached
  - **序列化注意**: 规则数据含 `effective_date` (DATE), `conditions` (JSON) → 使用 `_json_safe_deep()`
  - **测试**: 新建 `test_cached_rule_storage.py`

  **Must NOT do**:
  - 不修改 `PostgresRuleStorage` 内部逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: Task 9

  **References**:
  - `src/data_platform/storage/rule/postgres.py` — 现有 PostgreSQL 实现
  - `src/data_platform/storage/skill/factory.py` — 参考工厂模式
  - `src/data_platform/cache/config.py:CACHE_TTL_RULE`

  **QA Scenarios**:
  ```
  Scenario: list_rules 按 scenario 缓存隔离
    Tool: Bash (pytest)
    Steps:
      1. cached.list_rules("settlement"); cached.list_rules("settlement")
      2. spy call_count == 1 (settlement)
      3. cached.list_rules("qc")  # 不同 scenario 应 miss
      4. spy call_count == 2
    Expected Result: 不同 scenario 有独立缓存键
    Evidence: .sisyphus/evidence/task-14-rule-scenario-isolation.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add CachedRuleStorage with factory`
  - Files: `src/data_platform/storage/rule/cached.py`, `src/data_platform/storage/rule/factory.py`, `src/tests/unit/data_platform/test_cached_rule_storage.py`

- [x] 15. Create CachedAppealTemplateStore + factory + TDD tests

  **What to do**:
  - 新建 `src/knowledge_extension/knowledge/cached_appeal.py`
  - 新建 `src/knowledge_extension/knowledge/appeal_factory.py`（该域此前**无工厂**）
  - 实现 `CachedAppealTemplateStore`：
    - 包装 `PostgresAppealTemplateStore`（或简易 InMemory 实现）
    - 缓存 `list_templates(enabled_only=True)` → key=`appeal:list/true`
    - 写操作后删除相关缓存键
  - 工厂函数 `create_appeal_template_store() -> AppealTemplateStore`
  - **测试**: 新建 `test_cached_appeal_store.py`

  **Must NOT do**:
  - 不修改 `PostgresAppealTemplateStore` 内部逻辑

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: [`test-driven-development`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: None
  - **Blocked By**: Task 9

  **References**:
  - `src/knowledge_extension/knowledge/appeal_postgres.py` — 现有 PostgreSQL 实现
  - `src/data_platform/storage/skill/factory.py` — 参考工厂模式
  - `src/data_platform/cache/config.py:CACHE_TTL_APPEAL`

  **QA Scenarios**:
  ```
  Scenario: list_templates 缓存命中
    Tool: Bash (pytest)
    Steps:
      1. cached.list_templates(True); cached.list_templates(True)
      2. spy call_count == 1
    Expected Result: 第二次命中缓存
    Evidence: .sisyphus/evidence/task-15-appeal-cache.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): add CachedAppealTemplateStore with factory`
  - Files: `src/knowledge_extension/knowledge/cached_appeal.py`, `src/knowledge_extension/knowledge/appeal_factory.py`, `src/tests/unit/data_platform/test_cached_appeal_store.py`

- [x] 16. Integrate CachedSkillStorage into create_skill_storage()

  **What to do**:
  - 修改 `src/data_platform/storage/skill/factory.py` 的 `create_skill_storage()` 函数
  - 在 PostgreSQL 路径中，`PostgresSkillStorage` 创建成功后：
    1. 调用 `create_cache_client_optional()` 获取 `cache_client`
    2. 若 `cache_client is not None` + `CACHE_ENABLED_SKILL == "1"` → 用 `CachedSkillStorage` 包装
    3. 否则返回原始 `PostgresSkillStorage`
  - InMemory 路径不包装缓存（`USE_MEMORY_STORAGE=1` 时）

  **Must NOT do**:
  - 不修改 factory 的 try/except 结构
  - 不修改 `InMemorySkillStorage` 路径

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 工厂函数局部修改，逻辑简单
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 17, 18, 19)
  - **Blocks**: None
  - **Blocked By**: Task 10 (CachedSkillStorage 已存在)

  **References**:
  - `src/data_platform/storage/skill/factory.py:1-30` — 待修改工厂
  - `src/data_platform/storage/skill/cached.py` — 缓存代理类
  - `src/data_platform/cache/__init__.py:create_cache_client_optional`

  **QA Scenarios**:
  ```
  Scenario: CACHE_ENABLED=1 + CACHE_ENABLED_SKILL=1 → 返回 CachedSkillStorage
    Tool: Bash (pytest)
    Steps:
      1. os.environ["CACHE_ENABLED"] = "1"; os.environ["CACHE_ENABLED_SKILL"] = "1"
      2. storage = create_skill_storage()
      3. assert isinstance(storage, CachedSkillStorage)
    Expected Result: CachedSkillStorage 实例
    Evidence: .sisyphus/evidence/task-16-skill-cached.txt

  Scenario: CACHE_ENABLED_SKILL=0 → 返回原始 PostgresSkillStorage
    Tool: Bash (pytest)
    Steps:
      1. os.environ["CACHE_ENABLED_SKILL"] = "0"
      2. storage = create_skill_storage()
      3. assert isinstance(storage, PostgresSkillStorage)
    Expected Result: PostgresSkillStorage 实例（未包装）
    Evidence: .sisyphus/evidence/task-16-skill-uncached.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): integrate CachedSkillStorage into create_skill_storage() factory`
  - Files: `src/data_platform/storage/skill/factory.py`

- [x] 17. Integrate CachedMcpStorage into create_mcp_storage() + 清理 RedisMcpCache

  **What to do**:
  - 修改 `src/data_platform/storage/mcp/factory.py` 的 `create_mcp_storage()` 函数
  - PostgreSQL 路径（postgresql/kingbase）:
    1. 创建 `PostgresMcpStorage` 后
    2. 读取 `settings.cache_backend` 或 `CACHE_ENABLED_MCP` 环境变量
    3. 若启用缓存 → 获取 `cache_client` → 用 `CachedMcpStorage` 包装
  - MCP 域特殊处理：
    - `RedisMcpCache` 的能力列表缓存逻辑合并到 `CachedMcpStorage` 中
    - `RedisMcpCache` 的幂等/锁功能保留但降级为独立工具（不由存储代理管理）
  - **测试**: 确保现有 MCP 路由测试全部通过

  **Must NOT do**:
  - 不删除 `RedisMcpCache` 文件（保留供后续评估）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: MCP 域最复杂，涉及 settings 对象和已有缓存层整合
  - **Skills**: [`test-driven-development`, `systematic-debugging`]

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: Task 11 (CachedMcpStorage 已存在)

  **References**:
  - `src/data_platform/storage/mcp/factory.py:1-60` — 待修改工厂
  - `src/data_platform/storage/mcp/cached.py` — 缓存代理类
  - `src/config/mcp.py:McpSettings` — cache_backend 字段

  **QA Scenarios**:
  ```
  Scenario: settings.cache_backend="redis" → 返回 CachedMcpStorage
    Tool: Bash (pytest)
    Steps:
      1. settings = McpSettings(cache_backend="redis", persistence_backend="postgresql")
      2. storage = create_mcp_storage(settings)
      3. assert isinstance(storage, CachedMcpStorage)
    Expected Result: CachedMcpStorage 实例
    Evidence: .sisyphus/evidence/task-17-mcp-cached.txt
  ```

  **Commit**: YES
  - Message: `feat(cache): integrate CachedMcpStorage into create_mcp_storage() factory`
  - Files: `src/data_platform/storage/mcp/factory.py`

- [x] 18. Integrate CachedKnowledgeStore into create_knowledge_store()

  **What to do**:
  - 修改 `src/knowledge_extension/knowledge/factory.py` 的 `create_knowledge_store()` 函数
  - PostgreSQL 路径中，`PostgresKnowledgeStore` 创建后：
    1. 调用 `create_cache_client_optional()` + 检查 `CACHE_ENABLED_KNOWLEDGE`
    2. 若启用 → 用 `CachedKnowledgeStore` 包装
  - InMemory 路径不改（`USE_MEMORY_STORAGE=1`）

  **Must NOT do**:
  - 不修改内联的 `InMemoryKnowledgeWrapper`

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单工厂局部修改

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: Task 12

  **References**:
  - `src/knowledge_extension/knowledge/factory.py:1-30`
  - `src/knowledge_extension/knowledge/cached.py`

  **Commit**: YES
  - Message: `feat(cache): integrate CachedKnowledgeStore into create_knowledge_store() factory`
  - Files: `src/knowledge_extension/knowledge/factory.py`

- [x] 19. Add cache TTL + toggle env vars to production.py

  **What to do**:
  - 修改 `src/config/production.py`，增加缓存相关环境变量：
    - `CACHE_ENABLED`（默认 `"1"`）
    - `CACHE_FAIL_OPEN`（默认 `"1"`）
    - `CACHE_KEY_PREFIX`（默认 `""`）
    - 各域 TTL 变量（`CACHE_TTL_SKILL` 等，与 config.py 默认值一致）
    - 各域启用开关（`CACHE_ENABLED_SKILL` 等，默认 `"1"`）
  - 确保与 `src/data_platform/cache/config.py` 的默认值同步

  **Must NOT do**:
  - 不修改现有 PostgreSQL/Redis/Milvus 配置

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯配置追加

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: None (可与 Wave 2 并行)

  **References**:
  - `src/config/production.py:1-50` — 现有配置风格
  - `src/data_platform/cache/config.py` — 默认值需同步

  **QA Scenarios**:
  ```
  Scenario: 新增 env vars 可被读取
    Tool: Bash (python)
    Steps:
      1. python -c "from src.config.production import CACHE_ENABLED; assert CACHE_ENABLED == '1'"
    Expected Result: 无 AssertionError
    Evidence: .sisyphus/evidence/task-19-config-vars.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add cache TTL and toggle environment variables to production.py`
  - Files: `src/config/production.py`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run test). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest src/tests/unit/data_platform/ -v`. Review all changed files for: bare `except:`, `as any`/`# type: ignore`, console.log equivalent, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp). Verify `import` paths use `src.` prefix.
  Output: `Build [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration: cache hit after write-through invalidation, circuit breaker fallback, TTL expiry. Test edge cases: empty state, None returns, TTL=0. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 0**: 3 commits — one per bug fix
- **Wave 1**: 6 commits — one per foundation task
- **Wave 2**: 6 commits — one per cached storage proxy
- **Wave 3**: 4 commits — one per factory + config

---

## Success Criteria

### Verification Commands
```bash
# 核心：缓存单元测试全部通过
python -m pytest src/tests/unit/data_platform/test_cached_base.py src/tests/unit/data_platform/test_cached_storages.py -v

# 缓存关闭不破坏现有功能
CACHE_ENABLED=0 python -m pytest src/tests -v --tb=short

# 现有缓存测试不受影响
python -m pytest src/tests/unit/data_platform/ -v --tb=short

# 端到端启动验证
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
# curl http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/skills  → 第二次调用命中缓存
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] 3 pre-existing bugs fixed
- [ ] 6 domain proxies built and tested
- [ ] TTL enforcement verified
- [ ] Circuit breaker fallback verified
- [ ] Write-through invalidation verified
- [ ] CACHE_ENABLED=0 regression-free
