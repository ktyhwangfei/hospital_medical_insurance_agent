"""TDD tests for CachedKnowledgeStore — test FIRST, then implement.

Covers: cache hit for get_error_code, list_error_codes caching, disabled bypass.
"""
from unittest.mock import patch

import pytest

from src.data_platform.cache.config import CACHE_TTL_KNOWLEDGE
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.knowledge_extension.knowledge.cached import CachedKnowledgeStore


# ── Mock underlying store ──────────────────────────────────────────────


class MockErrorCodeStore:
    """内存模拟底层知识库存储，记录每次方法调用"""

    def __init__(self):
        self._data = {
            "E-UPLOAD-001": {
                "description": "费用明细未全部上传",
                "exception_type": "费用上传异常",
                "responsible_role": "收费员",
                "recommendation": "请核对费用上传状态，补传失败明细后重新预结算。",
            },
        }
        self.get_calls = 0
        self.list_calls = 0

    def get_error_code(self, code: str) -> dict | None:
        self.get_calls += 1
        return self._data.get(code)

    def list_error_codes(self) -> list[dict]:
        self.list_calls += 1
        return [{"error_code": k, **v} for k, v in self._data.items()]


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def cache() -> InMemoryCacheClient:
    return InMemoryCacheClient()


@pytest.fixture
def underlying() -> MockErrorCodeStore:
    return MockErrorCodeStore()


@pytest.fixture
def storage(
    underlying: MockErrorCodeStore,
    cache: InMemoryCacheClient,
) -> CachedKnowledgeStore:
    return CachedKnowledgeStore(
        underlying=underlying,
        cache=cache,
        ttl=CACHE_TTL_KNOWLEDGE,
        enabled=True,
    )


# ── Cache hit: get_error_code ─────────────────────────────────────────


class TestGetErrorCodeCacheHit:
    """get_error_code 调用两次 → 底层只调用一次（第二次命中缓存）"""

    def test_get_error_code_cached(
        self,
        storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """第一次调用后缓存预热，第二次命中缓存不调用底层"""
        # Arrange: warm the cache with first call
        storage.get_error_code("E-UPLOAD-001")

        # Act: second call with spy on underlying
        with patch.object(underlying, "get_error_code", wraps=underlying.get_error_code) as spy:
            result = storage.get_error_code("E-UPLOAD-001")

        # Assert: underlying was NOT called (cache hit)
        spy.assert_not_called()
        assert result is not None
        assert result["description"] == "费用明细未全部上传"

    def test_get_error_code_miss_calls_underlying(
        self,
        storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """第一次调用（空缓存）应调用底层"""
        with patch.object(underlying, "get_error_code", wraps=underlying.get_error_code) as spy:
            result = storage.get_error_code("E-UPLOAD-001")

        spy.assert_called_once_with("E-UPLOAD-001")
        assert result is not None
        assert result["description"] == "费用明细未全部上传"


# ── Cache hit: list_error_codes ───────────────────────────────────────


class TestListErrorCodesCacheHit:
    """list_error_codes 调用两次 → 底层只调用一次"""

    def test_list_error_codes_cached(
        self,
        storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """第一次调用后缓存预热，第二次命中"""
        storage.list_error_codes()  # First call: miss → fetch → cache

        with patch.object(underlying, "list_error_codes", wraps=underlying.list_error_codes) as spy:
            result = storage.list_error_codes()

        spy.assert_not_called()
        assert len(result) == 1
        assert result[0]["error_code"] == "E-UPLOAD-001"

    def test_list_error_codes_miss_calls_underlying(
        self,
        storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """第一次调用（空缓存）应调用底层"""
        with patch.object(underlying, "list_error_codes", wraps=underlying.list_error_codes) as spy:
            result = storage.list_error_codes()

        spy.assert_called_once()
        assert len(result) == 1


# ── Cache miss: non-existent error code ───────────────────────────────


class TestCacheMissNonExistent:
    """不存在的错误码不会缓存 None，避免缓存穿透"""

    def test_missing_code_not_cached(
        self,
        storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """不存在的错误码每次调用都走底层（_cached_read 不缓存 None）"""
        result1 = storage.get_error_code("NOT_EXIST")
        assert result1 is None
        assert underlying.get_calls == 1

        result2 = storage.get_error_code("NOT_EXIST")
        assert result2 is None
        assert underlying.get_calls == 2  # 第二次仍然调用了底层


# ── Disabled bypass ──────────────────────────────────────────────────


class TestDisabledBypass:
    """enabled=False 时所有方法直接委托底层，不读写缓存"""

    @pytest.fixture
    def disabled_storage(
        self,
        underlying: MockErrorCodeStore,
        cache: InMemoryCacheClient,
    ) -> CachedKnowledgeStore:
        return CachedKnowledgeStore(
            underlying=underlying,
            cache=cache,
            ttl=CACHE_TTL_KNOWLEDGE,
            enabled=False,
        )

    def test_get_error_code_disabled_calls_underlying(
        self,
        disabled_storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """禁用时 get_error_code 调用底层"""
        with patch.object(underlying, "get_error_code", wraps=underlying.get_error_code) as spy:
            result = disabled_storage.get_error_code("E-UPLOAD-001")

        spy.assert_called_once_with("E-UPLOAD-001")
        assert result is not None

    def test_get_error_code_disabled_twice_calls_underlying_twice(
        self,
        disabled_storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """禁用时两次调用都走底层"""
        with patch.object(underlying, "get_error_code", wraps=underlying.get_error_code) as spy:
            disabled_storage.get_error_code("E-UPLOAD-001")
            disabled_storage.get_error_code("E-UPLOAD-001")

        assert spy.call_count == 2

    def test_list_error_codes_disabled_calls_underlying(
        self,
        disabled_storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
    ) -> None:
        """禁用时 list_error_codes 调用底层"""
        with patch.object(underlying, "list_error_codes", wraps=underlying.list_error_codes) as spy:
            result = disabled_storage.list_error_codes()

        spy.assert_called_once()
        assert len(result) == 1

    def test_disabled_no_cache_write(
        self,
        disabled_storage: CachedKnowledgeStore,
        underlying: MockErrorCodeStore,
        cache: InMemoryCacheClient,
    ) -> None:
        """禁用时缓存不应有任何知识库条目"""
        disabled_storage.get_error_code("E-UPLOAD-001")

        cache_key = disabled_storage._make_key("ec", "E-UPLOAD-001")
        assert cache.get_json(cache_key) is None
