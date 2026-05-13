import json
from typing import Any

from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus, RateLimitResult


class RedisCacheClient:
    def __init__(self, redis_url: str | None = None, redis_client: Any | None = None, backend: CacheBackend = CacheBackend.REDIS):
        self._backend = backend
        self._redis = redis_client or self._create_client(redis_url)

    # ── CacheClient Protocol ──────────────────────────────────────────

    def get_json(self, key: str) -> dict[str, Any] | None:
        value = self._redis.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._redis.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, sort_keys=True))

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._redis.exists(key))

    def health(self) -> CacheHealth:
        try:
            self._redis.ping()
        except Exception as exc:
            return CacheHealth(status=CacheHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": "connection_failed", "error": exc.__class__.__name__})
        return CacheHealth(status=CacheHealthStatus.HEALTHY, backend=self._backend, available=True, details={"reason": "connected"})

    def delete_pattern(self, prefix: str) -> int:
        """Delete all keys matching `{prefix}*` using SCAN + UNLINK.

        Uses SCAN (non-blocking iteration) instead of KEYS to avoid blocking
        production Redis. Returns count of deleted keys.
        """
        keys = list(self._redis.scan_iter(match=f"{prefix}*", count=100))
        if not keys:
            return 0
        return self._redis.unlink(*keys)

    # ── ShortStateStore Protocol ──────────────────────────────────────

    def save_state(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.set_json(f"state:{namespace}:{key}", value, ttl_seconds)

    def load_state(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self.get_json(f"state:{namespace}:{key}")

    def delete_state(self, namespace: str, key: str) -> None:
        self.delete(f"state:{namespace}:{key}")

    # ── IdempotencyStore Protocol ─────────────────────────────────────

    def reserve(self, key: str, ttl_seconds: int) -> bool:
        cache_key = f"idempotency:{key}"
        payload = json.dumps({"status": "reserved"}, ensure_ascii=False, sort_keys=True)
        # SET NX returns True if key was set, None/False if already exists
        return bool(self._redis.set(cache_key, payload, nx=True, ex=ttl_seconds))

    def complete(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        payload = {"status": "completed", "result": value}
        self.set_json(f"idempotency:{key}", payload, ttl_seconds)

    def get_result(self, key: str) -> dict[str, Any] | None:
        payload = self.get_json(f"idempotency:{key}")
        if payload is None or payload.get("status") != "completed":
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    # ── RateLimiter Protocol ──────────────────────────────────────────

    def increment_and_check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        cache_key = f"rate:{key}"
        count = self._redis.incr(cache_key)
        # Only set expiry on first increment to avoid resetting TTL window
        if count == 1:
            self._redis.expire(cache_key, window_seconds)
        return RateLimitResult(allowed=count <= limit, current_count=count, limit=limit, window_seconds=window_seconds)

    # ── DistributedLock Protocol ─────────────────────────────────────

    def acquire(self, key: str, ttl_seconds: int, owner: str) -> bool:
        cache_key = f"lock:{key}"
        # SET NX EX — atomically set if key does not exist, with TTL
        return bool(self._redis.set(cache_key, owner, nx=True, ex=ttl_seconds))

    def release(self, key: str, owner: str) -> bool:
        cache_key = f"lock:{key}"
        # Get current value and verify ownership before deleting.
        # Note: In production with real Redis, prefer a Lua script for atomicity:
        #   if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end
        current = self._redis.get(cache_key)
        if current is None:
            return False
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current != owner:
            return False
        self._redis.delete(cache_key)
        return True

    def _create_client(self, redis_url: str | None):
        if redis_url is None:
            raise RuntimeError("redis_url_required")
        import redis
        return redis.Redis.from_url(redis_url)
