# Semantic Metric Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the eight governance fields to semantic metrics, enforce complete published metadata, expose them through the existing API and Portal, and seed five queryable outpatient metrics plus one draft encounter-count metric.

**Architecture:** Extend the existing `Metric` model, PostgreSQL registry store, semantic routes, and `/semantic-layer/metrics` page. Keep drafts permissive, enforce the 15-field completeness check in `Registry.publish_object`, and let query consumers continue reading published snapshots only.

**Tech Stack:** Python, Pydantic, PostgreSQL/JSONB, FastAPI, Next.js/React, Vitest, pytest.

---

### Task 1: Model and publish-gate tests

**Files:**
- Modify: `src/tests/unit/semantic_layer/test_models.py`
- Create: `src/tests/unit/semantic_layer/test_metric_governance.py`

- [ ] **Step 1: Write failing tests** for eight defaults, completeness failure, and completeness success using `Metric` and `SemanticRegistry`.
- [ ] **Step 2: Run** `uv run python -m pytest src/tests/unit/semantic_layer/test_metric_governance.py -q`; expect failures because fields and validator do not exist.
- [ ] **Step 3: Implement the smallest model/registry changes** in Tasks 2 and 3.
- [ ] **Step 4: Re-run** the focused tests and require green.
- [ ] **Step 5: Commit** `test: define semantic metric governance contract`.

### Task 2: Extend Metric and PostgreSQL schema

**Files:**
- Modify: `src/semantic_layer/models.py`
- Modify: `src/data_platform/storage/postgresql/semantic_registry_store.py`
- Modify: `src/tests/unit/data_platform/test_semantic_registry_stale_metric_write.py`

- [ ] **Step 1:** Add `synonyms`, `compatible_dimensions`, `default_time_role`, `refresh_frequency`, `permission_level`, `owner`, `reviewer`, and `precision` to `Metric` with backward-compatible defaults.
- [ ] **Step 2:** Add matching JSONB/VARCHAR/INTEGER columns to `CREATE TABLE`, `ALTER TABLE`, and `INSERT ... ON CONFLICT` SQL, preserving existing schema-version logic.
- [ ] **Step 3:** Extend row-to-model mapping and snapshot conversion where required.
- [ ] **Step 4:** Add a regression assertion that every INSERT column is covered by CREATE/ALTER DDL.
- [ ] **Step 5:** Run `uv run python -m pytest src/tests/unit/data_platform/test_semantic_registry_stale_metric_write.py src/tests/unit/semantic_layer/test_models.py -q`.
- [ ] **Step 6:** Commit `feat: persist semantic metric governance fields`.

### Task 3: Enforce publish completeness and expose API fields

**Files:**
- Modify: `src/semantic_layer/registry.py`
- Modify: `src/runtime/api/semantic_routes.py`
- Create: `src/tests/integration/api/test_semantic_metric_governance_api.py`
- Modify: `src/tests/integration/flow/test_semantic_query_workbench_flow.py`

- [ ] **Step 1:** Add failing API tests for updating governance fields, rejecting incomplete publish, and accepting complete publish.
- [ ] **Step 2:** Run the focused API tests and confirm expected failures.
- [ ] **Step 3:** Add one registry completeness helper and call it from `publish_object`; return a stable 400/409 error with missing field names.
- [ ] **Step 4:** Extend request/detail/summary DTOs and update mapping for all eight fields.
- [ ] **Step 5:** Add a Flow assertion that a published complete metric is queryable while the draft encounter-count metric is absent.
- [ ] **Step 6:** Run API then Flow tests in order.
- [ ] **Step 7:** Commit `feat: gate semantic metric publication on governance`.

### Task 4: Seed first outpatient metrics

**Files:**
- Modify: `src/semantic_layer/seed.py`
- Modify: `src/tests/unit/semantic_layer/test_seed.py`

- [ ] **Step 1:** Add failing seed assertions for five published metrics with all 15 fields and one draft encounter-count metric.
- [ ] **Step 2:** Run the focused seed test and confirm failure.
- [ ] **Step 3:** Add only the six metric definitions, using existing object/source/aggregation conventions and leaving encounter count draft.
- [ ] **Step 4:** Run `uv run python -m pytest src/tests/unit/semantic_layer/test_seed.py -q`.
- [ ] **Step 5:** Commit `feat: seed governed outpatient metrics`.

### Task 5: Portal governance form and display

**Files:**
- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Modify: `src/apps/portal/app/semantic-layer/metrics/page.tsx`
- Create or modify: `src/apps/portal/src/tests/semantic-metric-governance.test.tsx`

- [ ] **Step 1:** Add failing Vitest coverage for rendering governance fields and submitting them through the existing update client.
- [ ] **Step 2:** Run the focused Vitest test and confirm failure.
- [ ] **Step 3:** Extend TypeScript contracts and the existing editor/list with the eight fields and completeness status.
- [ ] **Step 4:** Run focused Vitest, `npm run typecheck`, scoped ESLint, and `npm run build` from `src/apps/portal`.
- [ ] **Step 5:** Commit `feat: edit semantic metric governance in portal`.

### Task 6: Review and verification

- [ ] **Step 1:** Review `git diff` against the spec; fix omissions only.
- [ ] **Step 2:** Run Unit suite for semantic layer/data platform.
- [ ] **Step 3:** Run API suite for semantic routes.
- [ ] **Step 4:** Run Flow suite for semantic query workbench.
- [ ] **Step 5:** Run Portal Vitest, TypeScript, scoped ESLint, and build.
- [ ] **Step 6:** Update `PROGRESS.md` with evidence and limitations.
