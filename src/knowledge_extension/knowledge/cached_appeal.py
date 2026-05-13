"""
缓存申诉模板存储 — CachedAppealTemplateStore

包装 PostgresAppealTemplateStore（或任意底层存储），通过 CachedStorageBase
提供读穿透（read-through）缓存和写后失效（write-through invalidation）。
"""

import logging
from typing import Any

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.config import CACHE_TTL_APPEAL
from src.data_platform.cache.ports import CacheClient

logger = logging.getLogger(__name__)


class CachedAppealTemplateStore(CachedStorageBase):
    """申诉模板缓存代理

    继承 CachedStorageBase，包装底层存储提供读穿透缓存。
    读操作优先走缓存，写操作同步写透后主动失效相关缓存键。
    """

    def __init__(
        self,
        cache: CacheClient,
        underlying: Any,
        ttl: int = CACHE_TTL_APPEAL,
        enabled: bool = True,
    ):
        super().__init__(cache=cache, domain="appeal", default_ttl=ttl, enabled=enabled)
        self._underlying = underlying

    # ── Read methods (read-through) ───────────────────────────────────────

    def list_templates(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        """列出申诉模板（读穿透缓存）

        缓存键: ``appeal:list/{enabled_only}``
        """
        key = self._make_key("list", str(enabled_only).lower())

        def fetch() -> list[dict[str, Any]]:
            return self._underlying.list_templates(enabled_only)

        return self._cached_read(key, fetch)

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        """获取单个申诉模板（读穿透缓存）

        缓存键: ``appeal:get/{template_id}``
        通过底层 list_templates 过滤实现。
        """
        key = self._make_key("get", template_id)

        def fetch() -> dict[str, Any] | None:
            templates = self._underlying.list_templates(enabled_only=False)
            for t in templates:
                if t.get("template_id") == template_id:
                    return t
            return None

        return self._cached_read(key, fetch)

    # ── Write methods (write-through + invalidate) ────────────────────────

    def save_template(self, template: dict[str, Any]) -> None:
        """保存申诉模板后失效相关缓存"""
        template_id = template.get("template_id", "")
        self._underlying.save_template(template)
        self._invalidate_keys(("get", template_id), ("list", "*"))

    def update_template(self, template: dict[str, Any]) -> None:
        """更新申诉模板后失效相关缓存"""
        template_id = template.get("template_id", "")
        self._underlying.update_template(template)
        self._invalidate_keys(("get", template_id), ("list", "*"))

    def delete_template(self, template_id: str) -> None:
        """删除申诉模板后失效相关缓存"""
        self._underlying.delete_template(template_id)
        self._invalidate_keys(("get", template_id), ("list", "*"))

    # ── Delegated passthrough methods ─────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """合并缓存层与底层存储的健康状态"""
        base_health = super().health()
        underlying_health = self._underlying.health()
        base_health["underlying"] = underlying_health
        return base_health
