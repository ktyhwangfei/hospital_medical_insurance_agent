"""
缓存规则解释存储 — CachedRuleStorage

包装 PostgresRuleStorage（或任意底层存储），通过 CachedStorageBase
提供读穿透（read-through）缓存和写后失效（write-through invalidation）。
"""

import logging
from typing import Any

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.config import CACHE_TTL_RULE
from src.data_platform.cache.ports import CacheClient
from src.data_platform.storage.rule.postgres import PostgresRuleStorage

logger = logging.getLogger(__name__)


class CachedRuleStorage(CachedStorageBase):
    """规则解释缓存代理

    继承 CachedStorageBase，包装底层存储提供读穿透缓存。
    读操作优先走缓存，写操作同步写透后主动失效相关缓存键。
    """

    def __init__(
        self,
        cache: CacheClient,
        underlying: PostgresRuleStorage,
        ttl: int = CACHE_TTL_RULE,
        enabled: bool = True,
    ):
        super().__init__(cache=cache, domain="rule", default_ttl=ttl, enabled=enabled)
        self._underlying = underlying

    # ── Read methods (read-through) ───────────────────────────────────────

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        """获取单条规则（读穿透缓存）"""
        key = self._make_key("get", rule_id)

        def fetch() -> dict[str, Any] | None:
            return self._underlying.get_rule(rule_id)

        return self._cached_read(key, fetch)

    def list_rules(self, scenario: str | None = None) -> list[dict[str, Any]]:
        """按场景列出规则（读穿透缓存）

        缓存键: ``rule:list/{scenario}``（scenario 为 None 时使用 "all"）。
        """
        scenario_key = scenario or "all"
        key = self._make_key("list", scenario_key)

        def fetch() -> list[dict[str, Any]]:
            return self._underlying.list_rules(scenario)

        return self._cached_read(key, fetch)

    # ── Write methods (write-through + invalidate) ────────────────────────

    def save_rule(self, rule: dict[str, Any]) -> None:
        """保存规则后失效相关缓存"""
        rule_id = rule.get("rule_id", "")
        self._underlying.save_rule(rule)
        self._invalidate_keys(("get", rule_id), ("list", "*"))

    def update_rule(self, rule: dict[str, Any]) -> None:
        """更新规则后失效相关缓存"""
        rule_id = rule.get("rule_id", "")
        self._underlying.save_rule(rule)  # upsert
        self._invalidate_keys(("get", rule_id), ("list", "*"))

    def delete_rule(self, rule_id: str) -> None:
        """删除规则后失效相关缓存"""
        self._underlying.delete_rule(rule_id)
        self._invalidate_keys(("get", rule_id), ("list", "*"))

    # ── Delegated passthrough methods ─────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """合并缓存层与底层存储的健康状态"""
        base_health = super().health()
        underlying_health = self._underlying.health()
        base_health["underlying"] = underlying_health
        return base_health
