# Skill Management Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Portal `/skills` into a progressive Skill workbench for overview, route explanation, and execution debugging while preserving existing API clients.

**Architecture:** Keep `InfraSkillManagement` as the page-level orchestrator, add typed backend response fields and one overview endpoint, and split presentation into overview, route-test, execution-test, and technical-detail sections only where the existing component becomes difficult to maintain. Existing `/infra-skills`, detail, route-test, `/infra-skills/{skill_id}/test`, refresh, semantic metrics, and query-plan endpoints remain valid.

**Tech Stack:** FastAPI/Pydantic, Python pytest/TestClient, Next.js/React/TypeScript, existing shadcn-style UI components, Playwright.

---

## File map

- Modify `src/runtime/api/schemas.py`: add optional route explanation, execution diagnostics, and overview response models.
- Modify `src/runtime/api/infra_skill_routes.py`: compute ranked route explanations, add `/infra-skills/overview`, and keep old response fields.
- Modify `src/apps/portal/src/lib/types.ts`: mirror the additive response fields.
- Modify `src/apps/portal/src/lib/api-client.ts`: add overview client and typed route/execution parsing without changing existing URLs.
- Modify `src/apps/portal/src/components/infra-skill-management.tsx`: implement the three-layer workbench and resilient local state.
- Modify `src/tests/unit/skill_infra/test_skill_router.py` or add `src/tests/unit/skill_infra/test_route_explanation.py`: lock route explanation behavior.
- Add focused API tests in `src/tests/integration/api/test_infra_skill_routes_api.py`: overview, additive fields, invalid input, and refresh failure.
- Modify `src/tests/e2e/pages/admin/skills.page.ts`: expose stable locators for the workbench.
- Add/modify `src/tests/e2e/flows/admin/skill-management.flow.ts`: cover select → route preview → execute → readable result.

### Task 1: Add response contracts without breaking existing clients

**Files:**
- Modify: `src/runtime/api/schemas.py`
- Modify: `src/apps/portal/src/lib/types.ts`
- Test: `src/tests/integration/api/test_infra_skill_routes_api.py`

- [ ] Add `SkillRouteCandidate`, `SkillRouteTestResponse` optional fields (`confidence`, `match_method`, `matched_keywords`, `excluded_keywords`, `candidates`) with defaults so old JSON consumers remain valid.
- [ ] Add `SkillExecutionDiagnostics` fields to `SkillExecuteTestResponse` (`warnings`, `citations`, `uncertainties`, `trace`, `input_summary`, `latency_ms`) with empty/list-or-null defaults.
- [ ] Add `InfraSkillOverviewItem` and `InfraSkillOverviewResponse` models containing skill identity, load/manifest/field-mapping status, metric count, last-test status, and warning summary.
- [ ] Mirror the exact snake_case fields and nullable/default behavior in the Portal TypeScript interfaces.
- [ ] Write API contract assertions that an existing route response still contains `question` and `matched_skill_id`, and that an existing execution response still contains `skill_id`, `status`, and `result`.
- [ ] Run `pytest src/tests/integration/api/test_infra_skill_routes_api.py -q`; expected existing contract tests pass before route behavior changes.
- [ ] Commit: `feat: add skill workbench response contracts`.

### Task 2: Implement explainable route testing and overview aggregation

**Files:**
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/runtime/api/schemas.py`
- Test: `src/tests/unit/skill_infra/test_route_explanation.py`
- Test: `src/tests/integration/api/test_infra_skill_routes_api.py`

- [ ] Add a route-test helper that calls `route_question_ranked(request.question, min_confidence=0.0)` and maps `SkillMatch` values to the new response fields; set `matched_skill_id` to the top result or `None`.
- [ ] Preserve the existing `POST /infra-skills/route-test` URL and return shape; only add fields.
- [ ] Ensure candidates are sorted by descending confidence and that empty input returns a normal validation error rather than invoking a Skill.
- [ ] Add `GET /infra-skills/overview` using the loader registry. For each loaded Skill, check manifest presence, check `field_mapping.yaml` through the existing parser, count semantic metrics with the existing metric helper, and use explicit `last_test_status=None` when no persisted test history exists.
- [ ] Add additive execution diagnostics: measure elapsed time with `time.perf_counter()`, copy only known `warnings`, `citations`, `uncertainties`, and trace fields from the result, and build `input_summary` from safe keys only (`patient_id`, `encounter_id`, `target_fee_item`, `context_keys`). Never serialize the raw context into the diagnostics.
- [ ] Write unit tests for ranked candidates, no-match behavior, and safe input summary; write API tests for overview status and execution compatibility.
- [ ] Run `pytest src/tests/unit/skill_infra/test_route_explanation.py src/tests/integration/api/test_infra_skill_routes_api.py -q`; expected all pass.
- [ ] Commit: `feat: expose explainable skill diagnostics`.

### Task 3: Add typed Portal API functions and resilient request state

**Files:**
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Modify: `src/apps/portal/src/lib/types.ts`
- Test: `src/apps/portal/src/lib/__tests__/skill-api-client.test.ts` (create if the existing frontend test convention has no equivalent)

- [ ] Add `getInfraSkillsOverview()` calling `GET /infra-skills/overview`.
- [ ] Keep `testInfraSkillExecution()` on the existing `/infra-skills/{skill_id}/test` URL and return the additive diagnostics type.
- [ ] Add a small pure formatter for route results that distinguishes `no_match`, `keyword`, and LLM/hybrid methods without embedding UI markup.
- [ ] Ensure request failures reject with the existing `requestJson` error shape; do not replace already loaded list/detail data with an empty array on overview failure.
- [ ] Test URL encoding for skill IDs, route result parsing, and failure propagation.
- [ ] Run the Portal unit command from `src/apps/portal/package.json`; expected TypeScript and focused tests pass.
- [ ] Commit: `feat: add typed skill workbench client`.

### Task 4: Refactor `/skills` into the three-layer workbench

**Files:**
- Modify: `src/apps/portal/src/components/infra-skill-management.tsx`
- Modify: `src/apps/portal/app/skills/page.tsx` only if the page header needs accessible labels
- Test: `src/tests/e2e/pages/admin/skills.page.ts`

- [ ] Replace the current table-first layout with a responsive overview list/cards while retaining the existing action/object filters and adding text search and status filtering.
- [ ] Load list and overview independently; show list data even if overview metrics fail, and show a local retry control for the failed region.
- [ ] Add explicit selected Skill state. Selecting a card opens the work area without requiring a second detail modal for normal inspection.
- [ ] Create four visible sections/tabs: `概览`, `路由试验`, `执行试验`, `技术详情`; keep Manifest, field mapping, query plan, files, and SKILL.md under technical details.
- [ ] Route test UI must show top match, confidence, method, matched keywords, excluded keywords, and candidate list; show a no-match empty state instead of a string-only result.
- [ ] Execution test UI must validate JSON locally, show field-level input errors, render `result` as readable sections when possible, and put raw JSON/trace behind an expandable disclosure.
- [ ] Display `warnings`, `citations`, and `uncertainties` as distinct panels; keep default context limited to the existing P001/E001 sample and do not echo raw sensitive context.
- [ ] Preserve detail loading, refresh, filter reset, and existing semantic metric/query-plan subcomponents.
- [ ] Add accessible labels/test IDs for Skill cards, route input, route preview, execution input, execute button, result summary, and technical details.
- [ ] Run `npm run lint` and `npm run build` in `src/apps/portal`; expected both pass.
- [ ] Commit: `feat: redesign skill management workbench`.

### Task 5: Cover the complete admin interaction flow

**Files:**
- Modify: `src/tests/e2e/pages/admin/skills.page.ts`
- Modify: `src/tests/e2e/flows/admin/skill-management.flow.ts`
- Test: existing Portal API mocks/fixtures used by the flow

- [ ] Add page-object methods for `selectSkill`, `submitRouteQuestion`, `readRouteExplanation`, `submitExecutionTest`, and `readResultSummary` using the new accessible labels/test IDs.
- [ ] Add a flow that navigates to `/skills`, selects a real loaded Skill, submits a route question such as `统筹自付怎么算？`, verifies a candidate explanation, executes with P001/E001 context, and verifies the structured result summary.
- [ ] Add a flow assertion that a route-test failure leaves the selected Skill and list visible and exposes a retry action.
- [ ] Run the focused Playwright flow with the project’s documented frontend/backend startup scripts; expected the complete flow passes.
- [ ] Commit: `test: cover skill workbench interaction flow`.

### Task 6: Run required verification and update documentation

**Files:**
- Modify: `docs/steering/` only if the existing Portal component/API documentation needs the new `/skills` interaction contract
- Modify: `PROGRESS.md` with the completed focus/result if required by project convention

- [ ] Run unit tests first: `pytest src/tests/unit/skill_infra -q`.
- [ ] Run API tests second: `pytest src/tests/integration/api/test_infra_skill_routes_api.py -q`.
- [ ] Run Flow tests third using the documented Playwright flow command.
- [ ] Run `git diff --check` and inspect `git status --short` for unrelated changes.
- [ ] Verify no new direct model HTTP calls, no high-risk action path, and no raw sensitive context in responses.
- [ ] Commit documentation/verification updates with `docs: document skill workbench interaction` if documentation changed.

## Self-review checklist

- Spec coverage: the overview, progressive disclosure, route explanation, execution diagnostics, error handling, security constraints, compatibility, and unit/API/Flow verification each map to Tasks 1–6.
- Placeholder scan: no TBD/TODO steps are used; every code change names an exact file and test command.
- Type consistency: Python and TypeScript field names remain snake_case and match the additive Pydantic contracts; the execution URL remains `/infra-skills/{skill_id}/test`.
