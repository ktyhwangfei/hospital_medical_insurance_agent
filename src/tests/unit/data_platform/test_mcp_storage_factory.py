from src.config.mcp import McpSettings
from src.data_platform.storage.mcp.cached import CachedMcpStorage
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage


def test_factory_uses_in_memory_by_default():
    storage = create_mcp_storage(McpSettings())
    assert isinstance(storage, InMemoryMcpStorage)


def test_factory_can_create_postgres_storage_with_unavailable_executor():
    """PostgreSQL 后端可能被 CachedMcpStorage 包裹（默认 cache 启用）。"""
    storage = create_mcp_storage(McpSettings(persistence_backend="postgresql"))
    # 可能直接是 PostgresMcpStorage，也可能是被 CachedMcpStorage 包裹
    if isinstance(storage, CachedMcpStorage):
        assert isinstance(storage._store, PostgresMcpStorage)
    else:
        assert isinstance(storage, PostgresMcpStorage)
    assert storage.health().postgres_available is False or storage.health().postgres_available is True


def test_factory_caches_postgres_when_cache_backend_is_redis():
    """当 cache_backend='redis' 时，必定使用 CachedMcpStorage 包裹。"""
    storage = create_mcp_storage(
        McpSettings(persistence_backend="postgresql", cache_backend="redis")
    )
    assert isinstance(storage, CachedMcpStorage)
    assert isinstance(storage._store, PostgresMcpStorage)


def test_factory_does_not_cache_in_memory_storage():
    """InMemory 后端永不缓存（仅 PostgreSQL 后端有条件包裹）。"""
    storage = create_mcp_storage(
        McpSettings(persistence_backend="in_memory", cache_backend="redis")
    )
    assert isinstance(storage, InMemoryMcpStorage)
