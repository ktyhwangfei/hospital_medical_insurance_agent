"""TDD tests for CachedAppealTemplateStore — cache isolation, write-through, factory.

Covers:
- Cache isolation: list_templates(True) vs list_templates(False) different keys
- get_template: caches per template_id
- Write-through after save: invalidation forces fresh read
- Key format convention
- Factory with memory fallback and cache wrapping
"""

from unittest.mock import MagicMock, patch

import pytest

from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.knowledge_extension.knowledge.cached_appeal import CachedAppealTemplateStore


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cache():
    return InMemoryCacheClient()


@pytest.fixture
def underlying():
    storage = MagicMock()
    storage.list_templates.return_value = [
        {
            "template_id": "at-001",
            "template_name": "费用上传异常申诉模板",
            "template_type": "appeal",
            "denial_reason_pattern": "费用上传",
            "enabled": True,
        },
        {
            "template_id": "at-002",
            "template_name": "DRG分组申诉模板",
            "template_type": "appeal",
            "denial_reason_pattern": "DRG分组",
            "enabled": True,
        },
        {
            "template_id": "at-003",
            "template_name": "已废弃模板",
            "template_type": "appeal",
            "denial_reason_pattern": "废弃",
            "enabled": False,
        },
    ]
    return storage


@pytest.fixture
def cached(cache, underlying):
    return CachedAppealTemplateStore(cache=cache, underlying=underlying, ttl=3600, enabled=True)


# ── Key format ────────────────────────────────────────────────────────────


class TestKeyFormat:
    def test_list_templates_true_key(self, cached: CachedAppealTemplateStore):
        assert cached._make_key("list", "true") == "appeal:list/true"

    def test_list_templates_false_key(self, cached: CachedAppealTemplateStore):
        assert cached._make_key("list", "false") == "appeal:list/false"

    def test_get_template_key(self, cached: CachedAppealTemplateStore):
        assert cached._make_key("get", "at-001") == "appeal:get/at-001"


# ── Cache isolation ───────────────────────────────────────────────────────


class TestCacheIsolation:
    """Cache keys are scoped by enabled_only and template_id."""

    def test_list_templates_cache_hit_for_same_enabled(self, cached, underlying):
        """list_templates(True) followed by list_templates(True) → second is hit."""
        # Act — first call: miss
        result1 = cached.list_templates(True)
        assert len(result1) == 3  # mock returns all templates regardless of enabled_only
        assert underlying.list_templates.call_count == 1

        # Act — second call with same enabled_only: hit
        result2 = cached.list_templates(True)
        assert len(result2) == 3
        assert underlying.list_templates.call_count == 1  # NOT called again

        # Verify counters
        assert cached._misses == 1
        assert cached._hits == 1

    def test_list_templates_default_is_true(self, cached, underlying):
        """list_templates() defaults to enabled_only=True; same key as list_templates(True)."""
        cached.list_templates()
        assert underlying.list_templates.call_count == 1

        cached.list_templates(True)
        assert underlying.list_templates.call_count == 1  # hit

    def test_list_templates_cache_miss_for_different_enabled(self, cached, underlying):
        """enabled_only=True vs False → different cache keys → cache miss."""
        # Arrange — prime cache with enabled_only=True
        cached.list_templates(True)
        assert cached._misses == 1

        # Different enabled_only should produce a different key
        underlying.list_templates.return_value = [
            {"template_id": "at-003", "template_name": "已废弃模板", "enabled": False},
        ]

        # Act — query with different enabled_only
        result = cached.list_templates(False)

        # Assert — new param causes cache miss, underlying called again
        assert len(result) == 1
        underlying.list_templates.assert_called_with(False)
        assert underlying.list_templates.call_count == 2
        assert cached._misses == 2

    def test_get_template_cache_hit(self, cached, underlying):
        """get_template caches per template_id; repeated call is hit."""
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板", "enabled": True},
        ]

        # First call: miss
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 1

        # Second call: hit
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 1  # NOT called again

    def test_get_template_different_ids_different_keys(self, cached, underlying):
        """Different template_ids produce different cache keys (isolated)."""
        underlying.list_templates.side_effect = [
            [{"template_id": "at-001", "template_name": "T1"}],
            [{"template_id": "at-002", "template_name": "T2"}],
        ]

        r1 = cached.get_template("at-001")
        assert r1["template_id"] == "at-001"
        assert underlying.list_templates.call_count == 1

        r2 = cached.get_template("at-002")
        assert r2["template_id"] == "at-002"
        assert underlying.list_templates.call_count == 2  # different key → miss

    def test_get_template_returns_none_for_missing(self, cached, underlying):
        """get_template returns None when no matching template found."""
        underlying.list_templates.return_value = []

        result = cached.get_template("at-999")
        assert result is None


# ── Write-through invalidation ───────────────────────────────────────────


class TestWriteThrough:
    """Write operations invalidate related cache keys."""

    def test_save_template_invalidates_get_cache(self, cached, underlying):
        """After save, a subsequent get_template should re-fetch from underlying."""
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板", "enabled": True},
        ]

        # Arrange — prime cache
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 1

        # Act — save triggers invalidate
        cached.save_template({"template_id": "at-001", "template_name": "Updated"})

        # Assert — next read goes to underlying (not cache)
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 2  # fresh fetch

    def test_save_template_invalidates_list_cache(self, cached, underlying):
        """After save, list cache for the domain is also invalidated."""
        # Arrange — prime both caches
        cached.list_templates(True)
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板", "enabled": True},
        ]
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 2  # 1 for list + 1 for get

        # Act — save (invalidates "get" and "list/*")
        cached.save_template({"template_id": "at-001", "template_name": "Updated"})

        # Assert — both get and list re-fetch from underlying
        cached.get_template("at-001")
        cached.list_templates(True)
        assert underlying.list_templates.call_count == 4  # 2 fresh reads

    def test_update_template_invalidates_cache(self, cached, underlying):
        """update_template also invalidates related keys."""
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板", "enabled": True},
        ]

        cached.get_template("at-001")
        cached.list_templates(True)
        assert underlying.list_templates.call_count == 2

        cached.update_template({"template_id": "at-001", "template_name": "Updated"})

        # After invalidation, reads go to underlying
        cached.get_template("at-001")
        cached.list_templates(True)
        assert underlying.list_templates.call_count == 4

    def test_delete_template_invalidates_cache(self, cached, underlying):
        """delete_template invalidates get and list cache keys."""
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板", "enabled": True},
        ]

        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 1

        cached.delete_template("at-001")

        # After invalidation, read goes to underlying
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 2  # re-fetched

    def test_save_template_no_cache_hit_after_write(self, cached, underlying):
        """After save + immediate get_template, data is fresh."""
        # Arrange — first fetch caches the value
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板", "enabled": True},
        ]
        cached.get_template("at-001")
        assert underlying.list_templates.call_count == 1

        # Act — update underlying data to simulate a change
        underlying.list_templates.return_value = [
            {"template_id": "at-001", "template_name": "费用上传异常申诉模板（已更新）", "enabled": True},
        ]

        # Save triggers invalidation
        cached.save_template({"template_id": "at-001", "template_name": "费用上传异常申诉模板（已更新）"})

        # Read should get the fresh value
        result = cached.get_template("at-001")
        assert result["template_name"] == "费用上传异常申诉模板（已更新）"


# ── Disabled cache behavior ──────────────────────────────────────────────


class TestDisabledCache:
    def test_disabled_cache_always_calls_underlying(self, cache, underlying):
        """When cache is disabled, reads always fall through to underlying."""
        cached = CachedAppealTemplateStore(cache=cache, underlying=underlying, ttl=3600, enabled=False)

        cached.list_templates(True)
        cached.list_templates(True)
        assert underlying.list_templates.call_count == 2  # no caching

    def test_disabled_cache_no_invalidation(self, cache, underlying):
        """When cache is disabled, save does not invalidate (nothing to invalidate)."""
        cached = CachedAppealTemplateStore(cache=cache, underlying=underlying, ttl=3600, enabled=False)

        cached.save_template({"template_id": "at-001"})
        assert underlying.save_template.call_count == 1


# ── Health ────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_merges_underlying(self, cached, underlying):
        """health() returns both cache stats and underlying health."""
        underlying.health.return_value = {"status": "healthy", "backend": "postgresql"}
        h = cached.health()
        assert "hits" in h
        assert "misses" in h
        assert "underlying" in h
        assert h["underlying"]["status"] == "healthy"


# ── Factory ──────────────────────────────────────────────────────────────


class TestFactory:
    def test_memory_fallback(self):
        """USE_MEMORY_STORAGE=1 returns InMemoryAppealTemplateStore."""
        with patch.dict("os.environ", {"USE_MEMORY_STORAGE": "1"}):
            from src.knowledge_extension.knowledge.appeal_factory import create_appeal_template_store

            storage = create_appeal_template_store()
            assert "InMemory" in type(storage).__name__

    def test_postgres_without_cache_when_no_cache_provided(self):
        """Without cache arg, returns PostgresAppealTemplateStore."""
        with patch.dict("os.environ", {"USE_MEMORY_STORAGE": ""}):
            from src.knowledge_extension.knowledge.appeal_factory import create_appeal_template_store

            storage = create_appeal_template_store(cache=None)
            assert "PostgresAppealTemplateStore" in type(storage).__name__

    def test_postgres_without_cache_when_cache_disabled(self):
        """When CACHE_ENABLED_APPEAL=0 but cache provided, returns PostgresAppealTemplateStore."""
        with patch.dict("os.environ", {"CACHE_ENABLED_APPEAL": "0"}):
            from src.knowledge_extension.knowledge.appeal_factory import create_appeal_template_store

            storage = create_appeal_template_store(cache=InMemoryCacheClient())
            assert "PostgresAppealTemplateStore" in type(storage).__name__

    def test_cached_appeal_store_when_cache_enabled(self):
        """With cache provided and CACHE_ENABLED_APPEAL=1, returns CachedAppealTemplateStore."""
        with patch.dict("os.environ", {"CACHE_ENABLED_APPEAL": "1"}):
            from src.knowledge_extension.knowledge.appeal_factory import create_appeal_template_store

            storage = create_appeal_template_store(cache=InMemoryCacheClient())
            assert "CachedAppealTemplateStore" in type(storage).__name__
