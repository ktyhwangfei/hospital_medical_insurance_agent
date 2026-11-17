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

- `ops_screening/`：运营问数对筛查结果的只读查询（Issue #86）。读 bjyb 里已有的结算/费用/诊断，并关联规则执行结果；不建表、不改规则。核实结论只写疑点的 `verify_status`。
- 其余 6 个子目录仍是契约桩。
- 业务入口仍是 `runtime/api/policy_qa_routes.py` 的 `data_query` 模式，不另做管理台。
