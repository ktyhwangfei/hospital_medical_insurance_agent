# T6 - LangGraph Streaming Wrapper: Learnings

## Implementation Summary

Created `src/runtime/langgraph/streaming.py` — `StreamingLangGraph` wrapper class.

## Key Patterns

- Uses `graph.stream(stream_mode="updates")` API to get per-node incremental updates
- Each stream update is a `dict[str, dict]` with node names as top-level keys
- After stream completes, `graph.get_state(config)` with `snapshot.next` detects interrupts
- When `on_event=None`, falls back to `graph.invoke()` for zero overhead

## Node Labels Covered (9 total)

- Settlement: `validate_claim`, `check_high_risk`, `query_error_knowledge`, `build_recommendation`
- QC: `get_patient_summary`, `run_qc_rules`, `check_qc_issues`, `build_qc_report`
- Shared: `human_confirmation`

## Verified

- [x] AST validation passed
- [x] Module imports without errors
- [x] Smoke test: streaming mode emits correct number of events (2 for A→B graph)
- [x] Smoke test: fallback invoke produces same result as direct graph.invoke()
- [x] LSP diagnostics: clean (no errors/warnings)
- [x] All 9 node labels present in _NODE_LABELS

## Design Decisions

- Wrapper pattern (not subclassing) — leaves LangGraph internals untouched
- `graph_builder_fn` stored but not used internally — needed by caller for resume
- `_emit()` wraps callback in try/except to prevent callback failures from breaking stream
- Uses generic `Any` type for graph object to avoid direct LangGraph type dependency
