"""TDD tests for CachedRuleStorage — cache isolation, write-through, factory.

Covers:
- Scenario-based cache isolation: list_rules("settlement") hit vs list_rules("qc") miss
- Write-through after save: invalidation forces fresh read
- Key format convention
- Factory with memory fallback and cache wrapping
"""

from unittest.mock import MagicMock, patch

import pytest

from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.rule.cached import CachedRuleStorage


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cache():
    return InMemoryCacheClient()


@pytest.fixture
def underlying():
    storage = MagicMock()
    storage.get_rule.return_value = {
        "rule_id": "R001",
        "rule_name": "医保结算规则",
        "scenario": "settlement",
        "explanation": "门诊结算后24小时内可发起医保上传",
    }
    storage.list_rules.return_value = [
        {
            "rule_id": "R001",
            "rule_name": "医保结算规则",
            "scenario": "settlement",
            "explanation": "门诊结算后24小时内可发起医保上传",
        },
        {
            "rule_id": "R002",
            "rule_name": "DRG分组规则",
            "scenario": "settlement",
            "explanation": "根据主要诊断和手术编码确定DRG组",
        },
    ]
    return storage


@pytest.fixture
def cached(cache, underlying):
    return CachedRuleStorage(cache=cache, underlying=underlying, ttl=3600, enabled=True)


# ── Key format ────────────────────────────────────────────────────────────


class TestKeyFormat:
    def test_get_rule_key(self, cached: CachedRuleStorage):
        assert cached._make_key("get", "R001") == "rule:get/R001"

    def test_list_rule_key(self, cached: CachedRuleStorage):
        assert cached._make_key("list", "settlement") == "rule:list/settlement"

    def test_list_all_key(self, cached: CachedRuleStorage):
        assert cached._make_key("list", "all") == "rule:list/all"


# ── Scenario-based cache isolation ───────────────────────────────────────


class TestScenarioIsolation:
    """Cache keys are scoped by scenario; different scenarios are isolated."""

    def test_list_rules_cache_hit_for_same_scenario(self, cached, underlying):
        """First call is a miss (fetches from underlying + caches);
        second call with same scenario is a hit (no underlying call)."""
        # Act — first call: miss
        result1 = cached.list_rules("settlement")
        assert len(result1) == 2
        assert underlying.list_rules.call_count == 1

        # Act — second call with same scenario: hit
        result2 = cached.list_rules("settlement")
        assert len(result2) == 2
        # underlying NOT called again — cache hit
        assert underlying.list_rules.call_count == 1

        # Verify counters
        assert cached._misses == 1
        assert cached._hits == 1

    def test_list_rules_cache_miss_for_different_scenario(self, cached, underlying):
        """Different scenario → different cache key → cache miss."""
        # Arrange — prime cache with settlement rules
        cached.list_rules("settlement")

        # Different scenario should produce a different key
        underlying.list_rules.return_value = [
            {
                "rule_id": "R003",
                "rule_name": "出院质控规则",
                "scenario": "qc",
                "explanation": "出院前需完成病历质控检查",
            },
        ]

        # Act — query different scenario
        result = cached.list_rules("qc")

        # Assert — new scenario causes cache miss, underlying called again
        assert len(result) == 1
        assert result[0]["scenario"] == "qc"
        assert underlying.list_rules.call_count == 2
        assert cached._misses == 2  # first settlement + second qc = 2 misses
        assert cached._hits == 0

    def test_list_rules_none_scenario_uses_all_key(self, cached, underlying):
        """list_rules(None) and list_rules(None) → same key → second is hit."""
        cached.list_rules(None)
        assert underlying.list_rules.call_count == 1

        cached.list_rules(None)
        # second call should be a cache hit
        assert underlying.list_rules.call_count == 1

    def test_get_rule_cache_hit(self, cached, underlying):
        """get_rule caches per rule_id; repeated call is a hit."""
        # First call: miss
        cached.get_rule("R001")
        assert underlying.get_rule.call_count == 1

        # Second call: hit
        cached.get_rule("R001")
        assert underlying.get_rule.call_count == 1

    def test_get_rule_different_ids_different_keys(self, cached, underlying):
        """Different rule_ids produce different cache keys (isolated)."""
        underlying.get_rule.side_effect = [
            {"rule_id": "R001", "rule_name": "Rule 1"},
            {"rule_id": "R002", "rule_name": "Rule 2"},
        ]

        r1 = cached.get_rule("R001")
        assert r1["rule_id"] == "R001"
        assert underlying.get_rule.call_count == 1

        r2 = cached.get_rule("R002")
        assert r2["rule_id"] == "R002"
        assert underlying.get_rule.call_count == 2  # different key → miss


# ── Write-through invalidation ───────────────────────────────────────────


class TestWriteThrough:
    """Write operations invalidate related cache keys."""

    def test_save_rule_invalidates_get_cache(self, cached, underlying):
        """After save, a subsequent get_rule should re-fetch from underlying."""
        # Arrange — prime cache
        cached.get_rule("R001")
        assert underlying.get_rule.call_count == 1

        # Act — save triggers invalidate
        cached.save_rule({"rule_id": "R001", "rule_name": "Updated"})

        # Assert — next read goes to underlying (not cache)
        cached.get_rule("R001")
        assert underlying.get_rule.call_count == 2  # fresh fetch

    def test_save_rule_invalidates_list_cache(self, cached, underlying):
        """After save, list cache for the domain is also invalidated."""
        # Arrange — prime both caches
        cached.list_rules("settlement")
        cached.get_rule("R001")

        # Act — save (invalidates "get" and "list/*")
        cached.save_rule({"rule_id": "R001", "rule_name": "Updated"})

        # Assert — both get and list re-fetch from underlying
        cached.get_rule("R001")
        cached.list_rules("settlement")
        assert underlying.get_rule.call_count == 2  # fresh
        assert underlying.list_rules.call_count == 2  # fresh

    def test_update_rule_invalidates_cache(self, cached, underlying):
        """update_rule (alias for upsert) also invalidates related keys."""
        cached.get_rule("R001")
        cached.list_rules("settlement")
        assert underlying.get_rule.call_count == 1
        assert underlying.list_rules.call_count == 1

        cached.update_rule({"rule_id": "R001", "rule_name": "Updated"})

        # After invalidation, reads go to underlying
        cached.get_rule("R001")
        cached.list_rules("settlement")
        assert underlying.get_rule.call_count == 2
        assert underlying.list_rules.call_count == 2

    def test_delete_rule_invalidates_cache(self, cached, underlying):
        """delete_rule invalidates get and list cache keys."""
        cached.get_rule("R001")
        cached.list_rules("settlement")
        assert underlying.get_rule.call_count == 1

        cached.delete_rule("R001")

        # After invalidation, reads go to underlying
        cached.get_rule("R001")
        assert underlying.get_rule.call_count == 2  # re-fetched

    def test_save_rule_no_cache_hit_after_write(self, cached, underlying):
        """Verifies that after save + immediate get_rule, the data is fresh."""
        # Arrange — first fetch caches the value
        cached.get_rule("R001")
        first_value = underlying.get_rule.return_value

        # Act — update underlying data to simulate a change
        updated_value = {
            "rule_id": "R001",
            "rule_name": "医保结算规则（已更新）",
            "scenario": "settlement",
        }
        underlying.get_rule.return_value = updated_value

        # Save triggers invalidation
        cached.save_rule({"rule_id": "R001", "rule_name": "医保结算规则（已更新）"})

        # Read should get the fresh value
        result = cached.get_rule("R001")
        assert result["rule_name"] == "医保结算规则（已更新）"


# ── Disabled cache behavior ──────────────────────────────────────────────


class TestDisabledCache:
    def test_disabled_cache_always_calls_underlying(self, cache, underlying):
        """When cache is disabled, reads always fall through to underlying."""
        cached = CachedRuleStorage(cache=cache, underlying=underlying, ttl=3600, enabled=False)

        cached.get_rule("R001")
        cached.get_rule("R001")
        assert underlying.get_rule.call_count == 2  # no caching

    def test_disabled_cache_no_invalidation(self, cache, underlying):
        """When cache is disabled, save does not invalidate (nothing to invalidate)."""
        cached = CachedRuleStorage(cache=cache, underlying=underlying, ttl=3600, enabled=False)

        # save should still call underlying
        cached.save_rule({"rule_id": "R001"})
        assert underlying.save_rule.call_count == 1


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
        """USE_MEMORY_STORAGE=1 returns InMemoryRuleStorage."""
        with patch.dict("os.environ", {"USE_MEMORY_STORAGE": "1"}):
            from src.data_platform.storage.rule.factory import create_rule_storage

            storage = create_rule_storage()
            assert "InMemory" in type(storage).__name__

    def test_postgres_without_cache_when_no_cache_provided(self):
        """Without cache arg, returns bare PostgresRuleStorage."""
        with patch.dict("os.environ", {"USE_MEMORY_STORAGE": ""}):
            from src.data_platform.storage.rule.factory import create_rule_storage

            storage = create_rule_storage(cache=None)
            assert "PostgresRuleStorage" in type(storage).__name__

    def test_postgres_without_cache_when_cache_disabled(self):
        """When CACHE_ENABLED_RULE=0 but cache provided, returns PostgresRuleStorage."""
        with patch.dict("os.environ", {"CACHE_ENABLED_RULE": "0"}):
            from src.data_platform.storage.rule.factory import create_rule_storage

            storage = create_rule_storage(cache=InMemoryCacheClient())
            assert "PostgresRuleStorage" in type(storage).__name__

    def test_cached_rule_storage_when_cache_enabled(self):
        """With cache provided and CACHE_ENABLED_RULE=1, returns CachedRuleStorage."""
        with patch.dict("os.environ", {"CACHE_ENABLED_RULE": "1"}):
            from src.data_platform.storage.rule.factory import create_rule_storage

            storage = create_rule_storage(cache=InMemoryCacheClient())
            assert "CachedRuleStorage" in type(storage).__name__
