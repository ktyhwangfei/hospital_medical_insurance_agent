from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.mcp.redis_cache import RedisMcpCache
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilityType, McpRiskLevel


def test_mcp_cache_stores_capability_list():
    cache = RedisMcpCache(cache_client=InMemoryCacheClient())
    capabilities = [McpCapability(capability_id="cap-1", server_id="srv-1", name="政策检索", capability_type=McpCapabilityType.TOOL, description="检索政策", risk_level=McpRiskLevel.LOW)]

    cache.save_capability_list("settlement_exception", capabilities, ttl_seconds=60)
    loaded = cache.load_capability_list("settlement_exception")

    assert loaded == capabilities


def test_mcp_cache_supports_idempotency_and_locks():
    cache = RedisMcpCache(cache_client=InMemoryCacheClient())

    assert cache.reserve_invocation("req-1", ttl_seconds=60) is True
    assert cache.reserve_invocation("req-1", ttl_seconds=60) is False
    assert cache.acquire_invocation_lock("cap-1", "worker-1", ttl_seconds=60) is True
    assert cache.acquire_invocation_lock("cap-1", "worker-2", ttl_seconds=60) is False
    assert cache.release_invocation_lock("cap-1", "worker-1") is True
