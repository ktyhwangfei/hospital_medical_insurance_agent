"""
规则解释存储工厂 — create_rule_storage

遵循与 skill/mcp 工厂相同的模式：
- USE_MEMORY_STORAGE=1 → InMemoryRuleStorage
- 默认 → PostgresRuleStorage，若 cache 可用且 CACHE_ENABLED_RULE=1 → CachedRuleStorage
"""

import logging
import os

from src.data_platform.cache.ports import CacheClient

logger = logging.getLogger(__name__)


def create_rule_storage(cache: CacheClient | None = None):
    """创建规则解释存储实例

    优先级：
    1. ``USE_MEMORY_STORAGE=1`` → InMemoryRuleStorage（降级/测试）
    2. cache 存在且 ``CACHE_ENABLED_RULE=1`` → CachedRuleStorage（PostgreSQL + 缓存）
    3. 兜底 → PostgresRuleStorage（直接数据库）

    Args:
        cache: 可选 CacheClient 实例，提供时若启用缓存则包装为 CachedRuleStorage
    """
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")

    if use_memory:
        from src.data_platform.storage.rule.in_memory import InMemoryRuleStorage

        logger.info("Using InMemoryRuleStorage")
        return InMemoryRuleStorage()

    # ── PostgreSQL 存储 ────────────────────────────────────────────
    from src.config.production import DATABASE_URL
    from src.data_platform.storage.rule.postgres import PostgresRuleStorage

    underlying = PostgresRuleStorage(database_url=DATABASE_URL)
    logger.info("Created PostgresRuleStorage")

    cache_enabled = os.getenv("CACHE_ENABLED_RULE", "1")
    if cache is not None and cache_enabled == "1":
        from src.data_platform.storage.rule.cached import CachedRuleStorage

        logger.info("Wrapping with CachedRuleStorage (cache enabled)")
        return CachedRuleStorage(cache=cache, underlying=underlying)

    logger.info("Using PostgresRuleStorage directly (no cache)")
    return underlying
