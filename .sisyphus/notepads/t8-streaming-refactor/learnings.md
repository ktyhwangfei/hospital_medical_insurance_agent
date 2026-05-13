# T8 Streaming Refactor - Learnings

## Implementation Notes

### Problem
The `/chat/stream` endpoint in `routes.py` used fake streaming: it processed synchronously via `process_chat_request()` and emitted pre-defined staged SSE events (`step`, `intent_trace`, `final`, `done`) without any real per-step events from execution.

### Solution
Rewrote `chat_stream()` to produce real streaming events:

1. **StreamingEmitter**: Created with `buffer.append` as yield_fn. All `stream:*` events (`stream:start`, `stream:intent_trace`, `stream:step`, `stream:tool_call`, `stream:tool_result`, `stream:final`, `stream:done`) are appended to a buffer list.

2. **Buffer Flush Pattern**: After each logical milestone (start, intent_done, execution, response), `yield from buffer; buffer.clear()` flushes events to the SSE client. This is required because Python sync generators cannot `yield` from inside nested closures (the `on_event` callback).

3. **on_event Callback**: The `UnifiedScenarioExecutor.execute(context, on_event=on_event)` call receives events from `SkillExecutionEngine` (tool_call/tool_result during skill steps) and `StreamingLangGraph` (step events during LangGraph node execution). The callback maps these to emitter calls.

4. **Backward Compatibility**: All old-style events (`step`, `intent_trace`, `final`, `done`) are emitted alongside their `stream:*` counterparts.

### Key Architecture
```
chat_stream() in routes.py:
  emitter.emit_start()                → stream:start
  detect_intent_smart() + emit        → stream:intent_trace + old intent_trace
  emitter.emit_step()                 → stream:step (intent done)
  old-style step events               → step (risk_control, authorization, scenario_processing)
  executor.execute(on_event=on_event) → stream:tool_call / stream:tool_result / stream:step
  emitter.emit_step()                 → stream:step (response_rendering)
  emitter.emit_final()                → stream:final + old final
  emitter.emit_done()                 → stream:done + old done
```

### Events Emitted (in order)
1. `stream:start` — immediately, with intent='detecting'
2. `stream:intent_trace` + `intent_trace` — after intent detection
3. `stream:step` (intent_detection) + `step` — intent done status
4. `step` (risk_control, authorization, scenario_processing) — old-style backward compat
5. `stream:tool_call` / `stream:tool_result` — during executor execution (via on_event)
6. `stream:step` (LangGraph nodes) — during LangGraph execution (via on_event from StreamingLangGraph)
7. `stream:step` (response_rendering) + `step` — post-processing
8. `stream:final` + `final` — complete response
9. `stream:done` + `done` — stream end

### Files Changed
- `src/runtime/api/routes.py`: Added imports (`StreamingEmitter`, `build_runtime_context`), rewrote `chat_stream()` (lines 137-264)

### Design Decisions
- Buffer pattern chosen over async/await to keep the existing sync SSE generator paradigm
- `StreamingEmitter` NOT directly used for yielding; instead its `_yield` function points to `buffer.append`, allowing emitter to write SSE strings to the buffer while we control when to yield to the client
- `build_runtime_context()` used instead of `orchestrator._build_context()` to avoid double-parsing intent
- New `UnifiedScenarioExecutor` created (not reused from orchestrator) to keep lifecycles clean
