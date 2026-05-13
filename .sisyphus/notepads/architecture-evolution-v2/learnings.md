# Learnings - Architecture Evolution V2

## Task 1: Adapter Port/Protocol Contracts

### Patterns observed
- All 7 existing InMemory adapters follow a uniform pattern: single method `(patient_id: str, encounter_id: str) -> AdapterCallResult`
- All use `successful_result()` helper from `src.adapters.base`
- None currently inherit from any base class — they are plain classes (makes `runtime_checkable` Protocol a natural fit)

### Port design decisions
- Used `typing.Protocol` with `@runtime_checkable` decorator so `isinstance()` checks work on plain classes
- Named each Port `{Capability}Port` (e.g., `InsuranceInterfacePort`)
- Method signatures derived directly from in_memory implementations
- All return `AdapterCallResult` (existing model from `src.adapters.base.models`)
- No `AdapterCallContext` parameter in port methods — contexts are constructed internally by adapters

### Test strategy
- `test_ports.py` verifies structural conformance via `isinstance(adapter, Port)` which checks method presence at runtime
- Also verifies basic execution path: call method with test IDs, assert `result.status.value == "success"`
- Import test ensures all 7 ports are exported from `src.adapters.ports.__init__`

### Files created
- `src/adapters/ports/__init__.py`
- `src/adapters/ports/insurance_interface.py`
- `src/adapters/ports/billing.py`
- `src/adapters/ports/his.py`
- `src/adapters/ports/emr.py`
- `src/adapters/ports/pre_audit.py`
- `src/adapters/ports/drg_dip.py`
- `src/adapters/ports/medical_record.py`
- `src/tests/unit/adapters/__init__.py`
- `src/tests/unit/adapters/test_ports.py`

### Verification
- LSP diagnostics: 0 errors across 26 files in src/adapters
- All 14 adapter tests pass (8 new port tests + 6 existing adapter contract tests)
- Pre-existing test failures in `knowledge_extension/` (McpAuthType import) are unrelated

### Gotchas
- `src/tests/unit/adapters/` did not exist previously — needed `__init__.py` created
- Each method in a Protocol must have `...` (Ellipsis) as the body — not `pass`

## Task 2: RuntimeOrchestrator Abstraction

### Patterns observed
- Current orchestration in `process_chat_request()` (routes.py, lines 347-443) is a monolithic procedural function with three paths: high-risk LangGraph -> skill/langgraph dispatch -> legacy fallback
- `build_runtime_context()` requires `IntentResult` (from `parse_intent`) — context assembly depends on intent parsing
- `build_human_confirmation_response()` in `risk_control/service.py` already encapsulates blocked-action response construction — reusable from orchestrator
- Skill resolution logic (parse_message, match_skill_by_intent) stays in routes.py until Task 7
- `SkillExecutionEngine.execute_skill()` takes `(skill, context, tool_storage)` — aligns directly with `SkillExecutor` Protocol signature

### Design decisions
- Used plain `typing.Protocol` (not `@runtime_checkable`) for ScenarioExecutor and SkillExecutor — these are injection contracts, not structural subtype checks. Runtime checkability is unnecessary for constructor-injected dependencies.
- `_resolve_scenario` is a `@staticmethod` — takes context not self, making it easy to override or extract
- `ScenarioExecutor.can_handle(scenario)` enables strategy selection without isinstance checks or dict-based routing
- Added optional `authorization_checker` and `tool_storage` parameters beyond the 4 required by spec — pragmatic completeness without breaking the core contract
- Return type of `_check_security` is `AgentResponse | None` — `None` means safe, `AgentResponse` means blocked (waiting_human_confirmation)

### Files created
- `src/runtime/orchestrator.py`

### Verification
- LSP diagnostics: 0 errors on new file
- `python -c "from src.runtime.orchestrator import RuntimeOrchestrator, ScenarioExecutor, SkillExecutor"` — all three symbols importable
- `inspect.signature` confirms all method signatures match spec
- All existing integration/intent tests pass (no regression on routes.py since orchestrator is not yet wired in)
- Pre-existing test failures (knowledge_extension McpAuthType, LangGraph state tests) are unrelated

### Gotchas
- `ScenarioExecutor.execute()` and `SkillExecutor.execute_skill()` return `AgentResponse` (not async) — matches current codebase where all execution is synchronous
- `ToolStorage` is imported from `src.data_platform.storage.tool.ports` (Protocol), not from the concrete in_memory module
- `Skill` is from `src.domain.skill.models` — keep import clean, don't import from storage ports
