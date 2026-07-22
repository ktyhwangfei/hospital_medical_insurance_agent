"""TDD tests for CachedSkillStorage — test FIRST, then implement.

Covers: cache hit, write-through invalidation, list caching, disabled bypass.
"""
from unittest.mock import patch

import pytest

from src.data_platform.cache.config import CACHE_TTL_SKILL
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.skill.cached import CachedSkillStorage
from src.data_platform.storage.skill.in_memory import InMemorySkillStorage
from src.domain.skill.models import Skill, SkillMetadata, ToolOwner


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cache() -> InMemoryCacheClient:
    return InMemoryCacheClient()


@pytest.fixture
def underlying() -> InMemorySkillStorage:
    return InMemorySkillStorage()


@pytest.fixture
def storage(underlying: InMemorySkillStorage, cache: InMemoryCacheClient) -> CachedSkillStorage:
    return CachedSkillStorage(
        underlying=underlying,
        cache=cache,
        ttl=CACHE_TTL_SKILL,
        enabled=True,
    )


@pytest.fixture
def sample_skill() -> Skill:
    return Skill(
        skill_id="test-skill",
        name="Test Skill",
        description="A test skill for cache testing",
        owner=ToolOwner.CASHIER,
    )


# ── Cache hit: get_skill ─────────────────────────────────────────────────


class TestSkillCacheHit:
    """get_skill called twice → only 1 underlying call (second is cache hit)."""

    def test_get_skill_cached(self, storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        # Arrange: seed underlying store and warm the cache
        underlying.save_skill(sample_skill)
        storage.get_skill("test-skill")  # First call: miss → fetch → cache

        # Act: second call with spy on underlying
        with patch.object(underlying, "get_skill", wraps=underlying.get_skill) as spy:
            result = storage.get_skill("test-skill")

        # Assert: underlying was NOT called (cache hit)
        spy.assert_not_called()
        # Result should be a real Skill object (not dict) after model reconstruction
        assert result is not None
        assert result.skill_id == "test-skill"

    def test_get_skill_miss_calls_underlying(self, storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        """First call with empty cache should call underlying exactly once."""
        underlying.save_skill(sample_skill)

        with patch.object(underlying, "get_skill", wraps=underlying.get_skill) as spy:
            result = storage.get_skill("test-skill")

        spy.assert_called_once_with("test-skill")


# ── Cache hit: list_skills ──────────────────────────────────────────────


class TestListSkillsCacheHit:
    """list_skills called twice → only 1 underlying call."""

    def test_list_skills_cached(self, storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        underlying.save_skill(sample_skill)
        storage.list_skills()  # First call: miss → fetch → cache

        with patch.object(underlying, "list_skills", wraps=underlying.list_skills) as spy:
            result = storage.list_skills()

        spy.assert_not_called()
        assert len(result) == 1
        assert result[0].skill_id == "test-skill"


# ── Write-through: save_skill invalidates cache ──────────────────────────


class TestWriteInvalidate:
    """After save_skill, cache is invalidated so next get_skill fetches fresh."""

    def test_save_skill_invalidates_cache(self, storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        # Arrange: warm cache
        underlying.save_skill(sample_skill)
        storage.get_skill("test-skill")  # Cache the original

        # Act: update via cached storage (invalidates cache)
        updated = sample_skill.model_copy(update={"name": "Updated Skill"})
        storage.save_skill(updated)

        # Assert: next get_skill should call underlying (cache miss after invalidation)
        with patch.object(underlying, "get_skill", wraps=underlying.get_skill) as spy:
            result = storage.get_skill("test-skill")
            spy.assert_called_once_with("test-skill")

    def test_delete_skill_invalidates_cache(self, storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        # Arrange: warm cache
        underlying.save_skill(sample_skill)
        storage.get_skill("test-skill")  # Cache it
        assert underlying.get_skill("test-skill") is not None

        # Act: delete via cached storage (invalidates cache)
        deleted = storage.delete_skill("test-skill")
        assert deleted is True

        # Assert: underlying has no skill, cache was invalidated
        assert underlying.get_skill("test-skill") is None

        # Next get_skill should call underlying and get None
        with patch.object(underlying, "get_skill", wraps=underlying.get_skill) as spy:
            result = storage.get_skill("test-skill")
            spy.assert_called_once_with("test-skill")
            assert result is None


# ── Disabled bypass ──────────────────────────────────────────────────────


class TestDisabledBypass:
    """enabled=False → all methods delegate directly to underlying, no caching."""

    @pytest.fixture
    def disabled_storage(self, underlying: InMemorySkillStorage, cache: InMemoryCacheClient) -> CachedSkillStorage:
        return CachedSkillStorage(
            underlying=underlying,
            cache=cache,
            ttl=CACHE_TTL_SKILL,
            enabled=False,
        )

    def test_get_skill_disabled_calls_underlying(self, disabled_storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        underlying.save_skill(sample_skill)

        with patch.object(underlying, "get_skill", wraps=underlying.get_skill) as spy:
            result = disabled_storage.get_skill("test-skill")

        spy.assert_called_once_with("test-skill")
        assert result is not None

    def test_get_skill_disabled_twice_calls_underlying_twice(self, disabled_storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        """Even calling get_skill twice should call underlying twice (no caching)."""
        underlying.save_skill(sample_skill)

        with patch.object(underlying, "get_skill", wraps=underlying.get_skill) as spy:
            disabled_storage.get_skill("test-skill")
            disabled_storage.get_skill("test-skill")

        spy.assert_called()  # Should be called at least once
        assert spy.call_count == 2

    def test_list_skills_disabled_calls_underlying(self, disabled_storage: CachedSkillStorage, underlying: InMemorySkillStorage, sample_skill: Skill) -> None:
        underlying.save_skill(sample_skill)

        with patch.object(underlying, "list_skills", wraps=underlying.list_skills) as spy:
            result = disabled_storage.list_skills()

        spy.assert_called_once()
        assert len(result) == 1

    def test_save_skilL_disabled_no_cache_write(self, disabled_storage: CachedSkillStorage, underlying: InMemorySkillStorage, cache: InMemoryCacheClient, sample_skill: Skill) -> None:
        """Disabled: save_skill writes to underlying but NOT to cache."""
        disabled_storage.save_skill(sample_skill)

        # Underlying should have the skill
        assert underlying.get_skill("test-skill") is not None

        # Cache should NOT have any skill-related entries
        cache_key = disabled_storage._make_key("get", "test-skill")
        assert cache.get_json(cache_key) is None


# ── health() delegates to underlying ─────────────────────────────────────


class TestHealth:
    def test_health_delegates_to_underlying(self, storage: CachedSkillStorage, underlying: InMemorySkillStorage) -> None:
        health = storage.health()
        assert health.status.value == "healthy"
        assert health.details["backend"] == "in_memory"
