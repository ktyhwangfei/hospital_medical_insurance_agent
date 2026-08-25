# interaction/ — 多模态交互层契约

## OVERVIEW

Interaction layer contract defining 6 multi-modal interaction domains, all currently stub implementations. The only active business interaction is Policy QA in `runtime/api/policy_qa_routes.py` (`POST /policy-qa/stream`).

## STRUCTURE

- **chat/** — Inactive Chat contract stub. It is not an API entry point; do not restore retired `/chat` or the old orchestrator/LangGraph flow.

- **file/** — File upload handling contract.
  Stub only. Upload parsing, validation, temp storage to be implemented.
  Leverages shared file utilities, no business logic here.

- **voice/** — Voice interaction contract.
  Stub only. ASR/TTS integration, audio format handling to be implemented.
  Future: connect to model_service for voice I/O.

- **page_context/** — Page context awareness contract.
  Stub only. Captures current page state (route, selections, patient context)
  from frontend for enriched AI reasoning. Channel-specific context protocol.

- **notification/** — Message notification/push contract.
  Stub only. Push notifications, in-app alerts, WebSocket event dispatch.
  Future: connect to runtime event system for proactive alerts.

- **knowledge_upload/** — Knowledge file upload contract.
  Stub only. Knowledge document ingestion, differs from file/ in that it
  triggers vectorization pipeline (tasks → knowledge_extension/assets).
  Calls knowledge_extension post-CRUD storage.

## STATUS

- All 6 subdirs: `__init__.py` with module-level stub code only.
- Actual interaction logic is in `runtime/api/` and downstream.
- No dedicated unit tests — coverage via integration flow tests only.
- Pattern: define protocol/interface here → implement in runtime layer.
  Do NOT put orchestration logic in this directory.
