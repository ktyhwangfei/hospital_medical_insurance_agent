"""
CachedSkillStorage — 技能存储的缓存代理层

在 SkillStorage Protocol 之上叠加读穿透（read-through）缓存 + 写入失效（write-through invalidate）模式。
继承自 CachedStorageBase，复用熔断器、安全读写、键构建等公共逻辑。

用法::

    store = CachedSkillStorage(
        underlying=PostgresSkillStorage(...),
        cache=RedisCacheClient(...),
        ttl=CACHE_TTL_SKILL,
        enabled=True,
    )
    skill = store.get_skill("sk-001")  # 首次从 PostgreSQL 读取，回写缓存
    skill = store.get_skill("sk-001")  # 命中缓存
"""
import logging

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.ports import CacheClient
from src.data_platform.storage.skill.models import SkillStorageHealth
from src.data_platform.storage.skill.ports import SkillStorage
from src.domain.skill.models import Skill

logger = logging.getLogger(__name__)


class CachedSkillStorage(CachedStorageBase):
    """技能存储的缓存代理。

    读操作优先查缓存（_cached_read），写操作先写入底层再失效相关缓存键。
    """

    def __init__(
        self,
        underlying: SkillStorage,
        cache: CacheClient,
        ttl: int,
        enabled: bool = True,
    ):
        super().__init__(cache, "skill", ttl, enabled)
        self._store = underlying

    # ── Read operations (read-through) ────────────────────────────────

    def get_skill(self, skill_id: str) -> Skill | None:
        cached = self._cached_read(
            self._make_key("get", skill_id),
            lambda: self._store.get_skill(skill_id),
        )
        if cached is None:
            return None
        if isinstance(cached, Skill):
            return cached
        # 缓存命中时反序列化回领域模型（缓存值由 _to_cache_value 转为 JSON dict）
        return Skill.model_validate(cached)

    def list_skills(self) -> list[Skill]:
        return self._list_from_cache("list", "all", fetch_fn=lambda: self._store.list_skills())

    def list_skills_by_owner(self, owner: str) -> list[Skill]:
        return self._list_from_cache("by_owner", owner, fetch_fn=lambda: self._store.list_skills_by_owner(owner))

    def list_skills_by_role(self, role: str) -> list[Skill]:
        return self._list_from_cache("by_role", role, fetch_fn=lambda: self._store.list_skills_by_role(role))

    def _list_from_cache(self, *key_parts: str, fetch_fn) -> list[Skill]:
        """列表读穿透：缓存命中的 JSON 列表反序列化为 Skill 列表。"""
        cached = self._cached_read(self._make_key(*key_parts), fetch_fn)
        if not cached:
            return []
        if cached and isinstance(cached[0], Skill):
            return cached
        return [Skill.model_validate(item) for item in cached]

    # ── Write operations (write-through + invalidate) ─────────────────

    def save_skill(self, skill: Skill) -> None:
        self._store.save_skill(skill)
        self._invalidate_keys(
            ("get", skill.skill_id),
            ("list", "*"),
            ("by_owner", "*"),
            ("by_role", "*"),
        )

    def delete_skill(self, skill_id: str) -> bool:
        result = self._store.delete_skill(skill_id)
        self._invalidate_keys(
            ("get", skill_id),
            ("list", "*"),
            ("by_owner", "*"),
            ("by_role", "*"),
        )
        return result

    # ── Health ────────────────────────────────────────────────────────

    def health(self) -> SkillStorageHealth:
        return self._store.health()
