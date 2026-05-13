# Task 7 - create_cache_client_optional - Learnings

## 2026-05-13

- Added `create_cache_client_optional() -> CacheClient | None` to `src/data_platform/cache/__init__.py`
- Logic: reads `CACHE_ENABLED` env var (default "1"), returns `None` when disabled, else delegates to `create_cache_client()` with exception catch
- `CACHE_FAIL_OPEN` control still lives in `create_cache_client()` — this function just catches any exception and returns `None`
- Tests cover: disabled (CACHE_ENABLED=0), create failure, success, default-enabled, and true-value variants ("1"/"true"/"yes")
- No changes to `create_cache_client()` signature or existing behavior
