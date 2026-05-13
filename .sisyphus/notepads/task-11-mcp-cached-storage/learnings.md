# Task 11 - CachedMcpStorage Learnings

## Patterns

1. **CachedStorageBase pattern**: All cached domain storage classes follow the same pattern:
   - Extend `CachedStorageBase` with domain-specific `__init__`
   - Store underlying adapter as `self._store`
   - Read methods use `_cached_read(key, lambda: self._store.method(...))`
   - Write methods delegate to `self._store` then call `_invalidate_keys(...)`
   - Need to handle dict→model reconstruction because `_cached_read` returns dicts on cache hit

2. **Model reconstruction**: `_cached_read` returns:
   - `dict` on cache hit (from JSON deserialization)
   - Original model/list on cache miss (from fetch_fn)
   - Need `_model_or_none()` and `_model_list()` helpers to handle both cases uniformly

3. **Invalidation strategy**:
   - `save_server`: invalidate `("get", id)`, `("list", "servers")`, `("list", "capabilities")`
   - `save_capability`: invalidate `("get", "cap", id)`, `("list", "capabilities")`
   - `delete_capability`: invalidate `("get", "cap", id)`, `("list", "capabilities")`

## Key observations

- `McpStorage` Protocol in `ports.py` does NOT include `list_capabilities_by_server` — the task spec included it but it's not in the actual protocol
- `InMemoryMcpStorage` and `PostgresMcpStorage` also don't have this method
- `CachedMcpStorage` replaces only RedisMcpCache's capability list caching responsibility (1 of 3)
- RedisMcpCache is still used for idempotency (reserve_invocation) and distributed locks
