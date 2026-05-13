"""
申诉模板存储工厂 — create_appeal_template_store

遵循与 rule/skill 工厂相同的模式：
- USE_MEMORY_STORAGE=1 → InMemoryAppealTemplateStore
- 默认 → PostgresAppealTemplateStore，若 cache 可用且 CACHE_ENABLED_APPEAL=1 → CachedAppealTemplateStore
"""

import logging
import os
from typing import Any

from src.data_platform.cache.ports import CacheClient

logger = logging.getLogger(__name__)


class InMemoryAppealTemplateStore:
    """内存申诉模板存储（降级/测试用）"""

    def __init__(self):
        self._templates: list[dict[str, Any]] = []

    def list_templates(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        if enabled_only:
            return [t for t in self._templates if t.get("enabled", True)]
        return list(self._templates)

    def save_template(self, template: dict[str, Any]) -> None:
        template_id = template.get("template_id", "")
        for i, t in enumerate(self._templates):
            if t.get("template_id") == template_id:
                self._templates[i] = template
                break
        else:
            self._templates.append(template)

    def update_template(self, template: dict[str, Any]) -> None:
        self.save_template(template)

    def delete_template(self, template_id: str) -> None:
        self._templates = [t for t in self._templates if t.get("template_id") != template_id]

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "backend": "in_memory"}


def create_appeal_template_store(cache: CacheClient | None = None):
    """创建申诉模板存储实例

    优先级：
    1. ``USE_MEMORY_STORAGE=1`` → InMemoryAppealTemplateStore（降级/测试）
    2. cache 存在且 ``CACHE_ENABLED_APPEAL=1`` → CachedAppealTemplateStore（PostgreSQL + 缓存）
    3. 兜底 → PostgresAppealTemplateStore（直接数据库）

    Args:
        cache: 可选 CacheClient 实例，提供时若启用缓存则包装为 CachedAppealTemplateStore
    """
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")

    if use_memory:
        logger.info("Using InMemoryAppealTemplateStore")
        return InMemoryAppealTemplateStore()

    # ── PostgreSQL 存储 ────────────────────────────────────────────
    from src.config.production import DATABASE_URL
    from src.knowledge_extension.knowledge.appeal_postgres import PostgresAppealTemplateStore

    underlying = PostgresAppealTemplateStore(database_url=DATABASE_URL)
    logger.info("Created PostgresAppealTemplateStore")

    cache_enabled = os.getenv("CACHE_ENABLED_APPEAL", "1")
    if cache is not None and cache_enabled == "1":
        from src.knowledge_extension.knowledge.cached_appeal import CachedAppealTemplateStore

        logger.info("Wrapping with CachedAppealTemplateStore (cache enabled)")
        return CachedAppealTemplateStore(cache=cache, underlying=underlying)

    logger.info("Using PostgresAppealTemplateStore directly (no cache)")
    return underlying
