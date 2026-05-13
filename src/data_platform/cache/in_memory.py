import copy
import time
from typing import Any

from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus, RateLimitResult


class InMemoryCacheClient:
    def __init__(self):
        self._values: dict[str, tuple[dict[str, Any], float]] = {}
        self._locks: dict[str, tuple[str, float]] = {}

    def get_json(self, key: str) -> dict[str, Any] | None:
        self._purge_expired_key(key)
        entry = self._values.get(key)
        if entry is None:
            return None
        return copy.deepcopy(entry[0])

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._values[key] = (copy.deepcopy(value), time.time() + ttl_seconds)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def exists(self, key: str) -> bool:
        self._purge_expired_key(key)
        return key in self._values

    def delete_pattern(self, prefix: str) -> int:
        """Delete all keys starting with the given prefix.

        Performs expired key purge on each candidate before deleting.
        Returns count of deleted keys.
        """
        keys_to_delete = [k for k in self._values if k.startswith(prefix)]
        for key in keys_to_delete:
            self._purge_expired_key(key)
        # Re-check which keys still exist after purge
        keys_to_delete = [k for k in keys_to_delete if k in self._values]
        for key in keys_to_delete:
            del self._values[key]
        return len(keys_to_delete)

    def health(self) -> CacheHealth:
        return CacheHealth(status=CacheHealthStatus.HEALTHY, backend=CacheBackend.IN_MEMORY, available=True, details={"backend": "in_memory"})

    def save_state(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.set_json(f"state:{namespace}:{key}", value, ttl_seconds)

    def load_state(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self.get_json(f"state:{namespace}:{key}")

    def delete_state(self, namespace: str, key: str) -> None:
        self.delete(f"state:{namespace}:{key}")

    def reserve(self, key: str, ttl_seconds: int) -> bool:
        cache_key = f"idempotency:{key}"
        if self.exists(cache_key):
            return False
        self.set_json(cache_key, {"status": "reserved"}, ttl_seconds)
        return True

    def complete(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.set_json(f"idempotency:{key}", {"status": "completed", "result": value}, ttl_seconds)

    def get_result(self, key: str) -> dict[str, Any] | None:
        payload = self.get_json(f"idempotency:{key}")
        if payload is None or payload.get("status") != "completed":
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    def increment_and_check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        cache_key = f"rate:{key}"
        payload = self.get_json(cache_key) or {"count": 0}
        count = int(payload["count"]) + 1
        self.set_json(cache_key, {"count": count}, window_seconds)
        return RateLimitResult(allowed=count <= limit, current_count=count, limit=limit)

    def acquire(self, key: str, ttl_seconds: int, owner: str) -> bool:
        self._purge_expired_lock(key)
        if key in self._locks:
            return False
        self._locks[key] = (owner, time.time() + ttl_seconds)
        return True

    def release(self, key: str, owner: str) -> bool:
        self._purge_expired_lock(key)
        current = self._locks.get(key)
        if current is None or current[0] != owner:
            return False
        self._locks.pop(key, None)
        return True

    def _purge_expired_key(self, key: str) -> None:
        entry = self._values.get(key)
        if entry is not None and entry[1] < time.time():
            self._values.pop(key, None)

    def _purge_expired_lock(self, key: str) -> None:
        entry = self._locks.get(key)
        if entry is not None and entry[1] < time.time():
            self._locks.pop(key, None)
