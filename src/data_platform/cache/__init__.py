import logging
import os

from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus, RateLimitResult
from src.data_platform.cache.ports import CacheClient, DistributedLock, IdempotencyStore, RateLimiter, ShortStateStore

logger = logging.getLogger(__name__)


def create_cache_client() -> CacheClient:
    """创建缓存客户端（默认使用Redis，故障时回退到InMemory）"""
    from src.config.production import REDIS_URL
    from src.data_platform.cache.redis_cache import RedisCacheClient
    try:
        client = RedisCacheClient(redis_url=REDIS_URL)
        logger.info(f"Using Redis cache: {REDIS_URL.split('@')[-1] if '@' in REDIS_URL else REDIS_URL}")
        return client
    except Exception as e:
        fail_open = os.getenv("CACHE_FAIL_OPEN", "1").lower() in ("1", "true", "yes")
        if not fail_open:
            logger.error(f"Failed to create Redis cache client: {e}")
            raise
        logger.warning(f"Redis unavailable, falling back to InMemoryCacheClient: {e}")
        from src.data_platform.cache.in_memory import InMemoryCacheClient
        return InMemoryCacheClient()


def create_cache_client_optional() -> CacheClient | None:
    """安全工厂：缓存禁用或不可用时返回 None，消费者据此跳过缓存包装"""
    cache_enabled = os.getenv("CACHE_ENABLED", "1").lower() in ("1", "true", "yes")
    if not cache_enabled:
        logger.info("Cache disabled via CACHE_ENABLED=0")
        return None
    try:
        return create_cache_client()
    except Exception as e:
        logger.warning(f"Failed to create cache client, returning None: {e}")
        return None


__all__ = [
    "CacheBackend",
    "CacheClient",
    "CacheHealth",
    "CacheHealthStatus",
    "DistributedLock",
    "IdempotencyStore",
    "RateLimitResult",
    "RateLimiter",
    "ShortStateStore",
    "create_cache_client",
    "create_cache_client_optional",
]
