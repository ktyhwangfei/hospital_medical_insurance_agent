# Draft: Bug Fix - Test Failures from 2026-05-13 Full Baseline

## Requirements (confirmed from test report)
- Fix 23 failing tests + 17 broken tests (code-level fractures) across unit/integration layers
- Follow strict verification order: unit → API → flow (per AGENTS.md)
- All fixes must work with `USE_MEMORY_STORAGE=1` environment

## Bug Categories by Priority

### P0 — langgraph Checkpoint Compatibility (12 tests)
- **Root cause**: `JsonPlusSerializer.dumps()` method missing in current langgraph version
- **Affected tests**: 
  - unit: test_orchestration_unified.py (3 settlement + 3 pre-discharge)
  - unit: test_human_confirmation.py (1 assertion + 3 IndexError)
  - flow: test_high_risk_and_permission.py (1 AttributeError)
  - flow: test_runtime_execution_loop.py (1 KeyError + 1 IndexError)
- **Location**: `postgresql_checkpointer.py:184` uses `serde.dumps()`

### P1 — Version Assertion (1 test)
- **Root cause**: Test expects `mode='memory-mvp'` but production config returns `mode='production'`
- **Affected test**: test_openapi_contract.py::test_health_version_and_openapi_contract

### P2 — MCP Transport & Discovery (17 tests)
- **Root cause A**: `McpDiscoverySource` not in `models.py` (ImportError)
- **Root cause B**: MCP SDK transport mocks incomplete (streamable_http/stdio)
- **Affected tests**: test_mcp_discovery.py (1), test_transport.py (16)

### P3 — Memory Mode Behavioral Differences (8+ tests)
- **Root cause**: Degradation/high-risk/knowledge citations don't trigger in memory-only mode
- **Affected tests**: 
  - test_audit_and_degradation.py (degraded → completed)
  - test_high_risk_and_permission.py (not_implemented ≠ waiting_human_confirmation)
  - test_langgraph_e2e_flow.py (high-risk confirmation issues)
  - test_knowledge_extension_runtime.py (empty citations/uncertainty)
  - test_full_mvp_contract.py (empty result list)
  - test_skill_intent_matching.py (unauthorized role not rejected)

## Research Findings (pending)
- [ ] langgraph serde API current version
- [ ] MCP models.py actual enum names
- [ ] Degradation logic in memory mode
- [ ] Version endpoint implementation

## Open Questions
- Scope: Fix P0-P2 only, or also P3?
- P3 tests: Fix code or fix tests to match memory-mode behavior?

## Scope Boundaries
- INCLUDE: All P0-P2 fixes, P3 if feasible
- EXCLUDE: Performance tests, E2E tests, knowledge_routes PostgreSQL dependency
- EXCLUDE: Model gateway timeout issues (environment-dependent)
