# Learnings — CachedStorageBase (Task 9)

## Patterns
- `CachedStorageBase` follows a clean abstract base pattern: all cache operations go through `self._cache` (CacheClient Protocol), never directly to Redis
- Circuit breaker auto-recovers based on `_last_failure_time + CIRCUIT_BREAKER_WINDOW` — when `_last_failure_time` is `0.0` (default), the check `time.time() - 0.0 > window` immediately passes, causing auto-recovery. Tests must set `_last_failure_time = time.time()` to test "within window" behavior.
- `_invalidate_keys` uses tuple expansion: trailing `"*"` means pattern deletion, others mean single key deletion
- `_cached_read` returns `Any` because fetch_fn return type is unknown (domain-specific)
- `_errors` is incremented inside `_record_failure()`, tying error counting directly to failure recording

## Gotchas
- `InMemoryCacheClient.get_json` returns deep copies, so cache hits return new objects each time
- `CIRCUIT_BREAKER_THRESHOLD` and `CIRCUIT_BREAKER_WINDOW` default to 5 and 60 respectively (from config.py)
- `_safe_get` returns `None` both for cache miss and when circuit is open — callers can't distinguish but don't need to
- `_to_cache_value` uses `hasattr(value, "model_dump")` to detect Pydantic models — avoid importing Pydantic directly

# QA Verification — 2026-05-13

## Full Scope: 13 scenarios, 469 tests

| Scenario | Tests | Result |
|----------|-------|--------|
| Full data_platform suite | 267 | ✅ |
| CACHE_ENABLED=0 regression | 75 | ✅ |
| Cached Skill Storage | 10 | ✅ |
| Cached MCP Storage | 11 | ✅ |
| Cached Knowledge Store | 9 | ✅ |
| Cached Knowledge Asset | 13 | ✅ |
| Cached Rule Storage | 20 | ✅ |
| Cached Appeal Store | 21 | ✅ |
| Redis Cache Full Protocols | 24 | ✅ |
| Cache Delete Pattern | 9 | ✅ |
| Cache Client Fallback | 3 | ✅ |
| Cache Client Optional | 5 | ✅ |
| MCP Redis Cache regression | 2 | ✅ |

**Verdict: APPROVE** — 469/469 pass, 0 failures, 0 regressions.
