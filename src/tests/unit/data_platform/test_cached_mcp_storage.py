"""CachedMcpStorage 单元测试

测试读穿透缓存、写入失效、缓存禁用、及与底层存储集成。
"""
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)


def _server(server_id: str = "srv-1") -> McpServer:
    return McpServer(
        server_id=server_id,
        name=f"测试服务器 {server_id}",
        endpoint="https://example.com/mcp",
        transport=McpTransportType.SSE,
        status=McpServerStatus.ENABLED,
    )


def _capability(cap_id: str = "cap-1", server_id: str = "srv-1") -> McpCapability:
    return McpCapability(
        capability_id=cap_id,
        server_id=server_id,
        name=f"能力 {cap_id}",
        capability_type=McpCapabilityType.TOOL,
        description="测试能力",
        risk_level=McpRiskLevel.LOW,
    )


# ── Cache hit tests ─────────────────────────────────────────────────


def test_list_servers_cache_hit_reduces_underlying_calls():
    """list_servers 两次调用 > 第二次命中缓存 > 底层仅调用一次"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    underlying.save_server(_server("srv-1"))
    underlying.save_server(_server("srv-2"))

    # 第一次调用：缓存未命中，走底层
    result1 = cached_storage.list_servers()
    assert len(result1) == 2

    # 缓存应已写入
    cache_key = cached_storage._make_key("list", "servers")
    assert cache.get_json(cache_key) is not None

    # 第二次调用：命中缓存，不再调用底层
    result2 = cached_storage.list_servers()
    assert len(result2) == 2

    # 两次结果一致
    assert [s.server_id for s in result1] == [s.server_id for s in result2]


def test_get_server_cache_hit():
    """get_server 两次调用 > 第二次命中缓存"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    underlying.save_server(_server("srv-1"))

    # 第一次：缓存未命中
    srv = cached_storage.get_server("srv-1")
    assert srv is not None
    assert srv.server_id == "srv-1"

    # 缓存应已写入
    cache_key = cached_storage._make_key("get", "srv-1")
    assert cache.get_json(cache_key) is not None

    # 第二次：命中缓存
    srv2 = cached_storage.get_server("srv-1")
    assert srv2 is not None
    assert srv2.server_id == "srv-1"


def test_list_capabilities_cache_hit():
    """list_capabilities 两次调用 > 第二次命中缓存"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    underlying.save_capability(_capability("cap-a", "srv-1"))
    underlying.save_capability(_capability("cap-b", "srv-1"))

    result1 = cached_storage.list_capabilities()
    assert len(result1) == 2

    # 直接往底层加数据（不改缓存）
    underlying.save_capability(_capability("cap-c", "srv-1"))

    # 命中缓存，仍返回 2 条（旧数据）
    result2 = cached_storage.list_capabilities()
    assert len(result2) == 2


def test_get_capability_cache_hit():
    """get_capability 两次调用 > 第二次命中缓存"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    underlying.save_capability(_capability("cap-1", "srv-1"))

    cap = cached_storage.get_capability("cap-1")
    assert cap is not None
    assert cap.capability_id == "cap-1"

    cache_key = cached_storage._make_key("get", "cap", "cap-1")
    assert cache.get_json(cache_key) is not None

    cap2 = cached_storage.get_capability("cap-1")
    assert cap2 is not None
    assert cap2.capability_id == "cap-1"


# ── Write-through invalidation tests ────────────────────────────────


def test_save_server_invalidates_cache():
    """save_server 后缓存失效 > get_server 获取新数据"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    server = _server("srv-1")
    cached_storage.save_server(server)

    # 修改底层数据（模拟外部变更）
    updated = _server("srv-1").model_copy(update={"name": "已更新名称"})
    underlying.save_server(updated)

    # 缓存已失效，get 应获取最新数据
    loaded = cached_storage.get_server("srv-1")
    assert loaded is not None
    assert loaded.name == "已更新名称"


def test_save_capability_invalidates_cache():
    """save_capability 后缓存失效 > get_capability 获取新数据"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    capability = _capability("cap-1", "srv-1")
    cached_storage.save_capability(capability)

    updated = _capability("cap-1", "srv-1").model_copy(update={"name": "已更新"})
    underlying.save_capability(updated)

    loaded = cached_storage.get_capability("cap-1")
    assert loaded is not None
    assert loaded.name == "已更新"


def test_save_server_populates_list_cache_after_invalidation():
    """save_server 后 list_servers 缓存被清除 > 重新从底层获取"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    underlying.save_server(_server("srv-1"))

    # 首次填充缓存
    result1 = cached_storage.list_servers()
    assert len(result1) == 1

    # save_server 应该失效 list 缓存
    cached_storage.save_server(_server("srv-2"))

    # 现在底层有 2 个服务器
    result2 = cached_storage.list_servers()
    assert len(result2) == 2


def test_delete_capability_invalidates_cache():
    """delete_capability 后缓存失效 > list 不再包含已删项目"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    underlying.save_capability(_capability("cap-1", "srv-1"))
    underlying.save_capability(_capability("cap-2", "srv-1"))

    # 首次填充缓存
    before = cached_storage.list_capabilities()
    assert len(before) == 2

    # 删除其中一个 > 缓存失效
    deleted = cached_storage.delete_capability("cap-1")
    assert deleted is True

    # 重新获取 > 走底层
    after = cached_storage.list_capabilities()
    assert len(after) == 1
    assert after[0].capability_id == "cap-2"


# ── Cache disabled tests ────────────────────────────────────────────


def test_disabled_cache_bypasses():
    """enabled=False > 每次都走底层"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache, enabled=False)
    underlying.save_server(_server("srv-1"))

    result1 = cached_storage.list_servers()
    assert len(result1) == 1

    # 底层新增数据
    underlying.save_server(_server("srv-2"))

    # cache 禁用 > 应看到新数据
    result2 = cached_storage.list_servers()
    assert len(result2) == 2


# ── Health tests ────────────────────────────────────────────────────


def test_health_delegates_to_underlying():
    """health() 委托到底层存储"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)
    health = cached_storage.health()

    assert isinstance(health, McpStorageHealth)
    assert health.status == McpStorageHealthStatus.HEALTHY


# ── None handling ───────────────────────────────────────────────────


def test_get_server_none_not_cached():
    """get_server 返回 None 时不应缓存（防止缓存穿透）"""
    underlying = InMemoryMcpStorage()
    cache = InMemoryCacheClient()
    from src.data_platform.storage.mcp.cached import CachedMcpStorage

    cached_storage = CachedMcpStorage(underlying=underlying, cache=cache)

    # 不存在的服务器
    result = cached_storage.get_server("non-existent")
    assert result is None

    # 缓存中不应有键
    cache_key = cached_storage._make_key("get", "non-existent")
    assert cache.get_json(cache_key) is None
