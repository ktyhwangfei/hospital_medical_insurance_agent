# Task 11 - Issues

## Resolved Issues

1. **`list_capabilities_by_server` not in McpStorage Protocol**
   - The task specification listed it as part of McpStorage Protocol
   - But `ports.py` (actual Protocol), `InMemoryMcpStorage`, and `PostgresMcpStorage` all lack it
   - Resolution: Removed from `CachedMcpStorage` and corresponding test
   - Note: When the Protocol is updated to include this method, `CachedMcpStorage` should be updated to cache it too

## Unresolved Gaps

- `list_capabilities_by_server` missing from `McpStorage` Protocol — potential future addition needed
