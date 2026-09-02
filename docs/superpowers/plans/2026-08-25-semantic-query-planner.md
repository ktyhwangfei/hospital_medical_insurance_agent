# Semantic Query Planner Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Apply superpowers:test-driven-development for every behavior change.

**Goal:** Replace the fixed settlement SQL path with a published semantic model that aggregates every inpatient segment for settlement `1671213`, reports coverage, and exposes the result safely in Policy QA and the semantic editor.

**Architecture:** Extend the existing semantic registry with query-model metadata and publish snapshots. A restricted `SemanticQuery` is planned into pre-aggregated fact branches and compiled with the already-installed SQLAlchemy Core; the existing SQL Server discovery connection executes it. `SettlementDataProvider` remains the runtime boundary, but its real implementation delegates to the semantic query service.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core 2, FastAPI, pyodbc, PostgreSQL, Next.js 16, React, Vitest.

---

### Task 1: Query metadata and published snapshot

**Files:**
- Modify: `src/semantic_layer/models.py`
- Modify: `src/semantic_layer/registry.py`
- Modify: `src/data_platform/storage/postgresql/semantic_registry_store.py`
- Modify: `src/semantic_layer/seed.py`
- Modify: `src/domain/AGENTS.md`
- Test: `src/tests/unit/semantic_layer/test_query_model_registry.py`

1. Write tests for dataset/key/field/relation/quality-rule storage, settlement seed metadata, publish validation, and complete query-model snapshots.
2. Run `uv run pytest src/tests/unit/semantic_layer/test_query_model_registry.py -q` and confirm failures are caused by missing models/store methods.
3. Add the minimal Pydantic models, store methods, PostgreSQL tables/ALTER compatibility, settlement seed, and snapshot fields required by those tests.
4. Re-run the test until green.

### Task 2: Restricted query planner and SQL compiler

**Files:**
- Create: `src/semantic_layer/query_planner.py`
- Test: `src/tests/unit/semantic_layer/test_query_planner.py`

1. Write tests proving `1671213` is an admission anchor, benefit/payment facts are pre-aggregated before joining, the common segment grain is composite, missing/extra/duplicate segments are represented by quality checks, SQL values are bind parameters, and unpublished/ambiguous/unsafe models are rejected.
2. Run `uv run pytest src/tests/unit/semantic_layer/test_query_planner.py -q` and confirm the missing-module failure.
3. Implement `SemanticQuery`, logical-plan/result DTOs, planner, SQLAlchemy Core compiler, and row-result quality evaluation in the smallest module that satisfies the tests.
4. Re-run the test until green.

### Task 3: Semantic execution and Policy QA cutover

**Files:**
- Modify: `src/runtime/policy_qa/settlement_data_provider.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/runtime/policy_qa/public_contract.py`
- Modify: `src/semantic_layer/settlement_bridge.py`
- Test: `src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py`

1. Write a provider test with two benefit/payment segments and assert admission totals, segment counts, coverage status, stay dates, and fail-closed partial/unavailable behavior.
2. Run `uv run pytest src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py -q` and confirm the current fixed-SQL provider fails it.
3. Replace the real provider implementation with the semantic query service, map safe scope fields into `SettlementContext`, and propagate them into the public case context without exposing SQL or physical identifiers.
4. Re-run the test until green.

### Task 4: Semantic API and focused API verification

**Files:**
- Modify: `src/runtime/api/semantic_routes.py`
- Test: `src/tests/integration/api/test_semantic_query_api.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`

1. Write API tests for query-model CRUD, publish diagnostics, `POST /semantic/query/test`, unpublished-model rejection, administrator-only SQL detail, and Policy QA scope fields.
2. Run `uv run pytest src/tests/integration/api/test_semantic_query_api.py src/tests/integration/api/test_policy_qa_routes.py -q` and confirm expected failures.
3. Add typed CRUD/query endpoints and the minimal publish-health response; reuse `SemanticReviewPrincipalDependency` for technical SQL visibility.
4. Re-run the API tests until green.

### Task 5: Portal visibility and query validation

**Files:**
- Modify: `src/apps/portal/app/semantic-layer/layout.tsx`
- Modify: `src/apps/portal/app/semantic-layer/mapping/page.tsx`
- Create: `src/apps/portal/app/semantic-layer/query/page.tsx`
- Modify: `src/apps/portal/src/lib/policy-qa-stream.ts`
- Modify: `src/apps/portal/src/components/policy-qa/calculation-disclosure.tsx`
- Test: `src/apps/portal/src/tests/semantic-query-page.test.tsx`
- Test: `src/apps/portal/src/tests/components/calculation-disclosure.test.tsx`
- Modify: `src/apps/portal/src/tests/lib/use-policy-qa-stream.test.tsx`

1. Write Vitest cases for snake_case conversion, total amount/range/segment display, partial coverage warning, read-only SQL, and query validation output.
2. Run the three focused Vitest files and confirm they fail for missing UI/fields.
3. Rename “映射” to “数据模型”, add the query tab/page, expose compact data-model maintenance, and render scope/coverage safely in Policy QA.
4. Re-run the focused Vitest files until green.

### Task 6: Remove fixed SQL path, review, and scoped flow validation

**Files:**
- Delete: `src/knowledge_extension/rule_explanation/policy_retrieval/config/business_sql.yaml`
- Modify: `src/runtime/discovery/semantic_source.py`
- Modify: `src/runtime/api/semantic_routes.py`
- Modify only direct callers that still import the deleted file
- Test: `src/tests/integration/flow/test_semantic_settlement_flow.py`

1. Write the two-segment Flow test plus partial, duplicate-key, missing-anchor, and connection-failure cases.
2. Run `uv run pytest src/tests/integration/flow/test_semantic_settlement_flow.py -q` and confirm the current runtime cannot satisfy it.
3. Delete the YAML and remove `TOP 1`, joined-YAML, and semantic-vs-business-SQL fallback paths; update consistency validation to inspect the logical plan.
4. Self-review the requirement checklist and diff, fix confirmed gaps, then re-review.
5. Verify in order:
   - Unit: `uv run pytest src/tests/unit/semantic_layer/test_query_model_registry.py src/tests/unit/semantic_layer/test_query_planner.py src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py -q`
   - API: `uv run pytest src/tests/integration/api/test_semantic_query_api.py src/tests/integration/api/test_policy_qa_routes.py -q`
   - Flow: `uv run pytest src/tests/integration/flow/test_semantic_settlement_flow.py -q`
   - Portal: focused Vitest files, `npm run typecheck`, and `npm run build` from `src/apps/portal`
   - Search: confirm no runtime reference to `business_sql.yaml`, `_query_joined`, or settlement `TOP 1` remains.

