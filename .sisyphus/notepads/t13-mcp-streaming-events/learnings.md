# T13 - MCP Streaming Event Emission

## Changes Made

### 1. `src/runtime/orchestration/mcp_integration.py`
- Added `on_event: Callable[[str, dict], None] | None = None` parameter to `McpRuntimeIntegration.__init__`
- In `select_for_step()`:
  - Generates `call_id` via `uuid4().hex[:8]` before each operation
  - Emits `stream:tool_call` before calling `_registry.select_capabilities()`
  - Emits `stream:tool_result` after successful selection
  - Emits `stream:error` only on `UNAVAILABLE` status (other non-success statuses like PERMISSION_DENIED, NO_HIT are normal business outcomes, not errors)
  - Measures `duration_ms` using `time.time()` for event timing
- Added imports: `time`, `Callable` from `collections.abc`, `uuid4` from `uuid`

### 2. `src/runtime/scenario_executor.py`
- Replaced deprecated `build_execution_plan` + `execute_plan` path with `McpRuntimeIntegration`
- `_execute_mcp()` now:
  - Imports global `_service` from `src.runtime.api.mcp_routes` as the MCP registry
  - Creates `McpRuntimeIntegration(registry=mcp_registry, on_event=on_event)` - forwarding the callback
  - Calls `select_for_step()` with proper `McpCapabilitySelectionRequest` (scenario, role, capability_type, max_risk_level)
  - Returns selected capabilities or appropriate "no match" response

## Event Flow
```
on_event("stream:tool_call", {call_id, tool_name, params})
  → _registry.select_capabilities(request)
  → on_event("stream:tool_result", {call_id, result, duration_ms})
```

## Patterns Followed
- Same event structure as `SkillExecutionEngine` in `skill_registry/engine.py`
- `call_id` using `uuid4().hex[:8]` per the spec
- `on_event` defaults to `None` for backward compatibility
- Business logic in `select_for_step` is preserved unchanged (audit events, status mapping)

## Gotchas
- `KnowledgeExtensionStatus` has no `FAILED` member - avoid checking for it
- `McpRegistryService.select_capabilities` requires `permissions` set in request or capabilities with `required_permissions` won't match
