# Decisions — CachedStorageBase (Task 9)

## Type signature of `_invalidate_keys`
- Declared as `*key_parts: tuple[str, ...]` (accepts vararg of tuple-of-strings)
- Each arg is a key group; trailing `"*"` signals pattern deletion
- Matches calling pattern: `_invalidate_keys(("get", "id"), ("list", "*"))`

## `_errors` counter incrementation
- `_errors += 1` placed inside `_record_failure()` to tie errors directly to failure events
- This ensures every cache failure is tracked as both a failure metric and an error metric

## None result not cached
- `_cached_read` only caches when `result is not None` — prevents cache penetration for "not found" results
- This matches the plan's design for protection against cache penetration

## Disabled behavior
- When `enabled=False`: `_should_try_cache()` returns False, `_safe_get/set/delete` become no-ops
- In `_cached_read`: skip cache read, always call `fetch_fn()` directly
- Never cache writes or reads when disabled
