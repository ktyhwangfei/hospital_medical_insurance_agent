# Policy Rule Compiler and Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有政策知识变更集与版本化 Release 链路中加入确定性规则编译，并让每条规则可查看原始输入、LLM 提取结果和全部编译步骤；任何不确定结果或缺失轨迹都不得进入活动 Release。

**Architecture:** 编译器只消费已经由 `ModelGateway` 保存的 Extraction，不调用模型。`ChangeSetService` 在聚合候选时批量编译并持久化 run/step；现有 Release 构建只消费 ChangeSet 中的 `CanonicalRule`，健康检查通过后补写 PUBLISH step 和 lineage，激活门禁再次核对完整轨迹。PostgreSQL 保存审计事实，Milvus 仍只保存运行时所需的发布实体。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、PostgreSQL JSONB、现有 Milvus Release builder、Next.js 16、React 19、Vitest、Playwright。

---

## Planned file map

- Create: `src/knowledge_extension/rule_explanation/policy_compiler/__init__.py`
- Create: `src/knowledge_extension/rule_explanation/policy_compiler/models.py`
- Create: `src/knowledge_extension/rule_explanation/policy_compiler/compiler.py`
- Create: `src/knowledge_extension/rule_explanation/policy_compiler/trace_store.py`
- Create: `src/knowledge_extension/rule_explanation/policy_compiler/service.py`
- Create: `src/knowledge_extension/rule_explanation/policy_compiler/backfill.py`
- Modify: `src/knowledge_extension/rule_explanation/change_set_models.py`
- Modify: `src/knowledge_extension/rule_explanation/change_set_service.py`
- Modify: `src/knowledge_extension/rule_explanation/pipeline_store.py`
- Modify: `src/knowledge_extension/rule_explanation/release_index.py`
- Modify: `src/runtime/api/policy_workbench_routes.py`
- Modify: `src/domain/AGENTS.md`
- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Create: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`
- Modify: `src/apps/portal/src/components/policy-knowledge/knowledge-review-detail.tsx`
- Create: `src/tests/unit/knowledge_extension/policy_compiler/__init__.py`
- Create: `src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py`
- Create: `src/tests/unit/knowledge_extension/policy_compiler/test_trace_store.py`
- Modify: `src/tests/unit/knowledge_extension/test_change_set_service.py`
- Modify: `src/tests/unit/knowledge_extension/test_release_index.py`
- Modify: `src/tests/integration/api/test_policy_workbench_api.py`
- Modify: `src/tests/integration/flow/test_policy_release_flow.py`
- Modify: `src/apps/portal/src/tests/policy-knowledge-api.test.ts`
- Create: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`
- Modify: `src/apps/portal/src/tests/policy-knowledge/knowledge-review-page.test.tsx`
- Modify: `src/tests/e2e/flows/portal/policy-knowledge-release.flow.ts`

## Task 1: Define the typed compiler contract

**Files:**

- Create: `src/knowledge_extension/rule_explanation/policy_compiler/__init__.py`
- Create: `src/knowledge_extension/rule_explanation/policy_compiler/models.py`
- Create: `src/tests/unit/knowledge_extension/policy_compiler/__init__.py`
- Create: `src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py`
- Modify: `src/domain/AGENTS.md`

- [ ] **Step 1: Add failing model-boundary tests**

  Cover stable enums and trust-boundary validation: stage names, `MULTIPLY` factor `(0, 1]`, ratio result `[0, 1]`, required evidence, and a derived rule requiring `dependencies` plus `formula`.

  ```python
  def test_multiply_expression_rejects_out_of_range_factor() -> None:
      with pytest.raises(ValidationError):
          PolicyExpression(operator="MULTIPLY", factor=Decimal("1.2"))

  def test_derived_rule_requires_dependency_and_formula() -> None:
      with pytest.raises(ValidationError):
          CanonicalRule(
              rule_id="rule_1",
              subject="personal_payment_ratio",
              source_type="DERIVED",
              result={"ratio": Decimal("0.09")},
              evidence=["evidence_1"],
          )
  ```

- [ ] **Step 2: Run the focused test and confirm RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py -v --tb=short`

  Expected: collection fails because `policy_compiler.models` does not exist.

- [ ] **Step 3: Implement only the required Pydantic models**

  Use `Decimal` for ratios and money. Keep payload snapshots as `dict[str, Any]` fields inside typed Pydantic models; do not add a generic DSL framework.

  ```python
  CompileStage = Literal[
      "INPUT_SNAPSHOT", "LLM_EXTRACTION", "CANONICALIZE", "COMPOSE",
      "RESOLVE", "DERIVE", "VALIDATE", "PUBLISH", "LEGACY_IMPORT",
  ]
  CompileStatus = Literal["RUNNING", "PASS", "WARN", "REVIEW", "FAIL"]

  class ValidationIssue(BaseModel):
      issue_id: str
      severity: Literal["WARN", "REVIEW", "FAIL"]
      code: str
      stage: CompileStage
      fact_id: str | None = None
      rule_id: str | None = None
      message: str
      recommended_action: str

  class PolicyExpression(BaseModel):
      operator: Literal["ABSOLUTE", "MULTIPLY", "COMPLEMENT", "DIRECT_COPY"]
      reference: dict[str, Any] | None = None
      factor: Decimal | None = Field(default=None, gt=0, le=1)
      total: Decimal | None = Field(default=None, gt=0)

  class CanonicalRule(BaseModel):
      rule_id: str
      subject: str
      population: str | None = None
      conditions: dict[str, Any] = Field(default_factory=dict)
      result: dict[str, Any]
      source_type: Literal["DIRECT", "DERIVED"] = "DIRECT"
      evidence: list[str] = Field(min_length=1)
      dependencies: list[str] = Field(default_factory=list)
      formula: PolicyExpression | None = None
      compiler_version: str = "1.0"
      rule_version: int = 1
      status: CompileStatus = "PASS"
  ```

  Add `PolicyFact`, `CompileStep`, `CompileRun`, `CompilationResult`, `RuleCompilationTraceResponse`, and history summary models with the fields approved in the design.

- [ ] **Step 4: Update the domain glossary**

  Add the Chinese/English canonical terms `政策事实 PolicyFact`、`政策表达式 PolicyExpression`、`规范规则 CanonicalRule`、`编译运行 CompileRun`、`编译步骤 CompileStep`、`校验问题 ValidationIssue`. Do not change unrelated entries.

- [ ] **Step 5: Run the model tests and commit**

  Run: `python -m pytest src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py -v --tb=short`

  Expected: PASS.

  Commit: `git add src/knowledge_extension/rule_explanation/policy_compiler src/tests/unit/knowledge_extension/policy_compiler src/domain/AGENTS.md; git commit -m "feat: 定义政策规则编译契约"`

## Task 2: Implement the deterministic compiler

**Files:**

- Create: `src/knowledge_extension/rule_explanation/policy_compiler/compiler.py`
- Modify: `src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py`

- [ ] **Step 1: Add the Golden Case and mutation tests first**

  Keep the fixture inline so the test remains readable and no extra fixture loader is introduced. The case must use arbitrary IDs and a configurable factor, proving the compiler does not depend on a document title, article number, unit ID, hospital level, or `60%`.

  ```python
  def test_relative_ratio_is_resolved_and_derived_without_policy_constants() -> None:
      facts = [
          fact("base_a", population="employee", conditions={"hosp_lv": "tertiary", "amount_band": "0-30000"}, ratio="0.15"),
          fact("base_b", population="employee", conditions={"hosp_lv": "tertiary", "amount_band": "30000-40000"}, ratio="0.10"),
          fact("relative", population="retiree", expression={
              "operator": "MULTIPLY",
              "reference": {"population": "employee", "subject": "personal_payment_ratio"},
              "factor": "0.75",
          }),
      ]
      result = PolicyRuleCompiler().compile(facts)
      assert [rule.result["ratio"] for rule in result.rules if rule.source_type == "DERIVED"] == [Decimal("0.1125"), Decimal("0.075")]
      assert result.status == "PASS"
  ```

  Add mutation cases for `NOT_FOUND`, `AMBIGUOUS`, conflicting duplicate keys, ratio above 1, overlapping amount bands, and missing evidence. Assert stable error codes rather than Chinese messages.

- [ ] **Step 2: Run the compiler tests and confirm RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py -v --tb=short`

  Expected: failures for missing `PolicyRuleCompiler` and stage behavior.

- [ ] **Step 3: Implement canonicalization and composition**

  Reuse `normalize_ratio` from `policy_retrieval.utils` for numeric input, but reject invalid textual values rather than guessing. Build RuleKey from business dimensions only; keep `unit_id` in evidence metadata, not in identity.

  ```python
  RULE_KEY_FIELDS = (
      "population", "service_type", "hospital_level", "treatment_type",
      "segment", "admission_order", "effective_period", "additional_conditions",
  )

  def rule_key(fact: PolicyFact) -> tuple[object, ...]:
      return (fact.subject, *(freeze(fact.conditions.get(name)) for name in RULE_KEY_FIELDS))
  ```

  `freeze()` should be a small recursive tuple conversion using stdlib only. Do not add a hashing dependency.

- [ ] **Step 4: Implement exact resolution and derivation**

  Match reference selectors against canonical direct rules. Return exactly one of `RESOLVED`, `AMBIGUOUS`, `NOT_FOUND`, `CONFLICT`. Run `MULTIPLY`, `COMPLEMENT`, and `DIRECT_COPY` only after a unique match. Use `Decimal` arithmetic and retain dependency rule IDs plus the original expression.

- [ ] **Step 5: Implement validation and stage snapshots**

  Validate schema, ratio ranges, reference completeness, duplicate/conflicting RuleKeys, and numeric amount-band overlap. Each stage appends a `CompileStep` with typed status, input/output snapshots, issues, and duration. Stop on FAIL; REVIEW results remain inspectable but are not publishable.

- [ ] **Step 6: Run focused tests and commit**

  Run: `python -m pytest src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py -v --tb=short`

  Expected: all compiler Golden and mutation tests PASS.

  Commit: `git add src/knowledge_extension/rule_explanation/policy_compiler/compiler.py src/tests/unit/knowledge_extension/policy_compiler/test_compiler.py; git commit -m "feat: 实现确定性政策规则编译器"`

## Task 3: Persist immutable runs, steps, and lineage

**Files:**

- Create: `src/knowledge_extension/rule_explanation/policy_compiler/trace_store.py`
- Modify: `src/knowledge_extension/rule_explanation/pipeline_store.py`
- Create: `src/tests/unit/knowledge_extension/policy_compiler/test_trace_store.py`

- [ ] **Step 1: Write one shared store-contract test suite**

  Run the same assertions against `InMemoryCompilationTraceStore` and a PostgreSQL adapter backed by the repository's fake client pattern: runs are append-only, steps retain sequence order, recompilation creates history, failed runs remain queryable, and lineage returns canonical snapshots.

- [ ] **Step 2: Run the store tests and confirm RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/policy_compiler/test_trace_store.py -v --tb=short`

  Expected: import failure for `trace_store`.

- [ ] **Step 3: Add the minimal store protocol and in-memory adapter**

  ```python
  class CompilationTraceStore(Protocol):
      def create_run(self, run: CompileRun) -> CompileRun: ...
      def append_step(self, run_id: str, step: CompileStep) -> CompileStep: ...
      def finish_run(self, run_id: str, *, status: CompileStatus, metrics: dict[str, Any], error: dict[str, Any] | None = None) -> CompileRun: ...
      def save_lineage(self, *, rule: CanonicalRule, run_id: str, extraction_id: str, document_id: str, release_id: str) -> None: ...
      def get_rule_trace(self, rule_id: str) -> RuleCompilationTraceResponse | None: ...
      def has_release_lineage(self, release_id: str, rule_ids: list[str]) -> bool: ...
  ```

  The in-memory implementation uses dictionaries/lists and copies Pydantic models on read. No repository framework or event bus.

- [ ] **Step 4: Implement PostgreSQL schema and adapter**

  Follow `knowledge_review_store.py`: lazy `PostgreSQLClient`, `_SCHEMA.split(";")`, explicit JSON serialization. Create `policy_compile_runs` and `policy_compile_steps`; add indexes on `(rule_id, rule_version)`, `run_id`, and `(run_id, sequence_no)`.

  Update `LINEAGE_TABLE` and add an idempotent `LINEAGE_MIGRATION` in `pipeline_store.py`:

  ```sql
  ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS compile_run_id VARCHAR(64);
  ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS rule_version INTEGER;
  ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS canonical_rule JSONB;
  ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS release_id VARCHAR(64);
  ```

  Never update a completed run or step. Recompilation always inserts a new `run_id`.

- [ ] **Step 5: Run store tests and commit**

  Run: `python -m pytest src/tests/unit/knowledge_extension/policy_compiler/test_trace_store.py -v --tb=short`

  Expected: PASS for both adapters without a live PostgreSQL dependency.

  Commit: `git add src/knowledge_extension/rule_explanation/policy_compiler/trace_store.py src/knowledge_extension/rule_explanation/pipeline_store.py src/tests/unit/knowledge_extension/policy_compiler/test_trace_store.py; git commit -m "feat: 持久化政策编译运行与步骤"`

## Task 4: Compile ChangeSet candidates and fail closed

**Files:**

- Create: `src/knowledge_extension/rule_explanation/policy_compiler/service.py`
- Modify: `src/knowledge_extension/rule_explanation/change_set_models.py`
- Modify: `src/knowledge_extension/rule_explanation/change_set_service.py`
- Modify: `src/runtime/api/policy_workbench_routes.py`
- Modify: `src/tests/unit/knowledge_extension/test_change_set_service.py`

- [ ] **Step 1: Add failing ChangeSet integration tests**

  Assert that an injected compilation service:

  - snapshots `source_text` and full `policy_extractions.extracted_fields` before compiling;
  - creates a `compile_run_id`, `compilation_status`, and typed `canonical_rule` on each direct or derived item;
  - persists failed/review runs and adds blockers;
  - marks the candidate `NEEDS_DECISION` when any item is REVIEW/FAIL;
  - leaves existing tests that construct `ChangeSetService` without a compiler usable, but such legacy items have no canonical rule and cannot later publish.

- [ ] **Step 2: Run the focused tests and confirm RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_change_set_service.py -v --tb=short`

  Expected: assertions fail because ChangeSet items have no compilation fields.

- [ ] **Step 3: Implement `PolicyCompilationService`**

  The service is the only orchestration layer around the pure compiler. For each source Extraction it writes INPUT_SNAPSHOT and LLM_EXTRACTION, then persists the pure compiler's steps. It must finish a failed run in `finally` before re-raising a persistence error.

  ```python
  class PolicyCompilationService:
      def compile_units(self, units: list[ApprovedUnit]) -> dict[str, CompiledCandidate]:
          items = [knowledge for unit in units for knowledge in unit.knowledge]
          runs = {item.knowledge_id: self._start_run(item) for item in items}
          try:
              result = self._compiler.compile([self._to_fact(item) for item in items])
              return self._persist_result(items=items, runs=runs, result=result)
          except Exception as exc:
              self._finish_failed_runs(runs, exc)
              raise
  ```

  Adapter rules may read generic structured `expression`/`relations`; any missing reference becomes `REVIEW`, never a guessed numeric result. Do not call `ModelGateway` here because the LLM output already exists in `PipelineStore`.

- [ ] **Step 4: Extend ChangeSet items and aggregation**

  Add optional `compile_run_id`, `compilation_status`, and `canonical_rule: CanonicalRule | None`. Derived canonical rules become explicit additional ChangeSet rows so the user can review and trace them individually. Preserve the source KnowledgeItem snapshot in `after` for the existing table UI.

- [ ] **Step 5: Wire only the production getter**

  In `_get_change_set_service()`, inject `PolicyCompilationService(PipelineStore(), PolicyRuleCompiler(), _get_compilation_trace_store())`. Select memory/PostgreSQL trace storage with the existing `USE_MEMORY_STORAGE` switch. Keep constructor injection available for tests; do not introduce a factory module.

- [ ] **Step 6: Run tests and commit**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_change_set_service.py src/tests/unit/knowledge_extension/policy_compiler -v --tb=short`

  Expected: PASS.

  Commit: `git add src/knowledge_extension/rule_explanation/policy_compiler/service.py src/knowledge_extension/rule_explanation/change_set_models.py src/knowledge_extension/rule_explanation/change_set_service.py src/runtime/api/policy_workbench_routes.py src/tests/unit/knowledge_extension/test_change_set_service.py; git commit -m "feat: 在知识变更集中执行规则编译"`

## Task 5: Publish only canonical rules and require trace lineage

**Files:**

- Modify: `src/knowledge_extension/rule_explanation/release_index.py`
- Modify: `src/runtime/api/policy_workbench_routes.py`
- Modify: `src/tests/unit/knowledge_extension/test_release_index.py`

- [ ] **Step 1: Add failing release tests**

  Cover: release reads exactly its `source_change_set_id`; rejects items without PASS/WARN canonical rules; uses stable canonical rule IDs; writes PUBLISH PASS plus lineage only after both collections are healthy; a trace-store failure keeps release `building`; and promote gate rejects missing lineage.

- [ ] **Step 2: Run focused release tests and confirm RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_release_index.py -v --tb=short`

  Expected: failures because the current source reads the live workbench and the builder does not write traces.

- [ ] **Step 3: Make the existing release source consume one ChangeSet**

  Change `KnowledgeWorkbenchReleaseSource.records()` to `records(change_set: KnowledgeChangeSet)`. Iterate `change_set.items`, reject missing or non-publishable compilation results, and adapt `CanonicalRule` to the existing `build_ingest_records()` input. Keep the class name to avoid an unrelated rename.

  Return `facts`, `rules`, and a small list of publication records `(run_id, extraction_id, document_id, canonical_rule)`; do not create a new release repository abstraction.

- [ ] **Step 4: Make `ReleaseIndexBuilder` record PUBLISH before ready**

  Inject `CompilationTraceStore`. After create/insert/load/health succeeds, append PUBLISH PASS and `save_lineage()` for every canonical rule. Only then save release status `ready`. Any trace exception propagates and leaves the active release untouched.

- [ ] **Step 5: Tighten build and promote routes**

  In `build_candidate_release`, load the release, require its source ChangeSet, and pass that ChangeSet to `records()`. In the governed promote validator, call `has_release_lineage(release_id, expected_rule_ids)` and return existing `POLICY_RELEASE_LINEAGE_INVALID` on failure.

- [ ] **Step 6: Run tests and commit**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_release_index.py -v --tb=short`

  Expected: PASS.

  Commit: `git add src/knowledge_extension/rule_explanation/release_index.py src/runtime/api/policy_workbench_routes.py src/tests/unit/knowledge_extension/test_release_index.py; git commit -m "feat: 发布规范规则并强制校验编译血缘"`

## Task 6: Expose typed rule trace API and legacy backfill

**Files:**

- Create: `src/knowledge_extension/rule_explanation/policy_compiler/backfill.py`
- Modify: `src/runtime/api/policy_workbench_routes.py`
- Modify: `src/tests/integration/api/test_policy_workbench_api.py`

- [ ] **Step 1: Add failing API tests**

  Test `GET /policy-workbench/rules/{rule_id}/trace` for direct, derived, failed/review, multi-version history, LEGACY_IMPORT, and missing rule. Assert the response model includes `raw_input`, `llm_output`, ordered steps, issues, publication, and history; assert missing returns `RULE_TRACE_NOT_FOUND`.

- [ ] **Step 2: Run the API tests and confirm RED**

  Run: `python -m pytest src/tests/integration/api/test_policy_workbench_api.py -v --tb=short -k trace`

  Expected: 404 route-not-found or missing response model.

- [ ] **Step 3: Implement the typed endpoint**

  ```python
  @router.get("/rules/{rule_id}/trace", response_model=RuleCompilationTraceResponse)
  def get_rule_compilation_trace(rule_id: str) -> RuleCompilationTraceResponse:
      trace = _get_compilation_trace_store().get_rule_trace(rule_id)
      if trace is None:
          raise HTTPException(
              status_code=404,
              detail=error_detail("RULE_TRACE_NOT_FOUND", "规则编译轨迹不存在", {"rule_id": rule_id}),
          )
      return trace
  ```

  The endpoint inherits the existing policy-workbench access boundary and performs no writes.

- [ ] **Step 4: Add the idempotent backfill command**

  `python -m src.knowledge_extension.rule_explanation.policy_compiler.backfill` enumerates reviewed/published workbench rules, reuses `PolicyCompilationService`, and skips rules already traced. If the original Extraction cannot be reconstructed, persist one `LEGACY_IMPORT` run/step with the available rule snapshot and an explicit missing-history issue; never fabricate CANONICALIZE through VALIDATE output.

- [ ] **Step 5: Run API tests and commit**

  Run: `python -m pytest src/tests/integration/api/test_policy_workbench_api.py -v --tb=short -k 'trace or rule_detail'`

  Expected: PASS.

  Commit: `git add src/knowledge_extension/rule_explanation/policy_compiler/backfill.py src/runtime/api/policy_workbench_routes.py src/tests/integration/api/test_policy_workbench_api.py; git commit -m "feat: 提供逐规则编译溯源接口"`

## Task 7: Add the per-row trace drawer

**Files:**

- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Create: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`
- Modify: `src/apps/portal/src/components/policy-knowledge/knowledge-review-detail.tsx`
- Modify: `src/apps/portal/src/tests/policy-knowledge-api.test.ts`
- Create: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`
- Modify: `src/apps/portal/src/tests/policy-knowledge/knowledge-review-page.test.tsx`

- [ ] **Step 1: Add failing API-client and component tests**

  Assert URL encoding, one `查看溯源` button per rule row, no trace request before click, lazy fetch after click, right-side drawer content, ordered stages, expandable input/output, error-code highlighting, retry, close, and full JSON view.

- [ ] **Step 2: Run Portal tests and confirm RED**

  Run from `src/apps/portal`: `npm test -- src/tests/policy-knowledge-api.test.ts src/tests/policy-knowledge/rule-trace-drawer.test.tsx src/tests/policy-knowledge/knowledge-review-page.test.tsx`

  Expected: missing API function/component/button failures.

- [ ] **Step 3: Add typed client contracts**

  Mirror the Pydantic response with `CompileStage`, `CompileStatus`, `ValidationIssue`, `CompileStep`, and `RuleCompilationTrace`. Add:

  ```typescript
  export const getRuleCompilationTrace = (ruleId: string) =>
    request<RuleCompilationTrace>(
      `${WORKBENCH_API}/rules/${encodeURIComponent(ruleId)}/trace`,
    )
  ```

- [ ] **Step 4: Build the drawer by reusing the existing Dialog pattern**

  Copy the right-positioned `DialogContent` class pattern from `skill-execution-test-drawer.tsx`; do not add a UI dependency. Fetch only when `open && ruleId`. Render summary badges, raw input, LLM output, and ordered stage `<details>` blocks. A local `fullPayload` state opens one full-screen Dialog for long JSON.

- [ ] **Step 5: Add the row action**

  Put `查看溯源` outside the approve/reject conditional so reviewed, invalid, direct, and derived rows all receive it. Parent state owns `traceRuleId`; row receives a single `onViewTrace` callback.

- [ ] **Step 6: Run Portal tests and type checking, then commit**

  Run from `src/apps/portal`:

  - `npm test -- src/tests/policy-knowledge-api.test.ts src/tests/policy-knowledge/rule-trace-drawer.test.tsx src/tests/policy-knowledge/knowledge-review-page.test.tsx`
  - `npx tsc --noEmit`

  Expected: PASS and zero TypeScript errors.

  Commit: `git add src/apps/portal/src/lib/policy-knowledge-api.ts src/apps/portal/src/components/policy-knowledge src/apps/portal/src/tests/policy-knowledge-api.test.ts src/apps/portal/src/tests/policy-knowledge; git commit -m "feat: 增加规则编译溯源抽屉"`

## Task 8: Verify the complete governed flow

**Files:**

- Modify: `src/tests/integration/flow/test_policy_release_flow.py`
- Modify: `src/tests/e2e/flows/portal/policy-knowledge-release.flow.ts`

- [ ] **Step 1: Add the failing backend Flow cases**

  Add one happy path covering Extraction snapshot → compile runs/steps → ChangeSet review → Release build → lineage → active release → trace read. Add one fail-closed path where RESOLVE is ambiguous or trace persistence fails; assert active release remains unchanged and the failed run is queryable.

- [ ] **Step 2: Run the focused Flow test and confirm RED**

  Run: `python -m pytest src/tests/integration/flow/test_policy_release_flow.py -v --tb=short -k compile_trace`

  Expected: failure until the flow fixture wires compiler and trace store.

- [ ] **Step 3: Complete only missing wiring revealed by the Flow test**

  Keep fixes in the files already listed above. Do not add fallback publishing or special-case the Golden policy. If the test exposes a missing trace, fix the shared coordinator/store path.

- [ ] **Step 4: Add the Playwright trace-drawer assertion**

  Extend the existing policy knowledge release flow: navigate to a candidate review, click the first row's `查看溯源`, assert the drawer contains `原始输入`, `LLM 提取`, `CANONICALIZE`, `VALIDATE`, and `PUBLISH`, then close it. Reuse the current page/server setup.

- [ ] **Step 5: Execute mandatory verification in strict order**

  1. T1 unit:

     `python -m pytest src/tests/unit/knowledge_extension -v --tb=short`

  2. T2a API, only after T1 passes:

     `python -m pytest src/tests/integration/api/test_policy_workbench_api.py -v --tb=short`

  3. T2b Flow, only after T2a passes:

     `python -m pytest src/tests/integration/flow/test_policy_release_flow.py -v --tb=short`

  4. Portal, only after T2b passes:

     `Set-Location src/apps/portal; npm test; npx tsc --noEmit; npm run build`

  5. E2E after the workspace servers are started with the repository scripts:

     `Set-Location src/tests/e2e; npm test -- flows/portal/policy-knowledge-release.flow.ts`

  Expected: every stage PASS; stop at the first failure and fix it before continuing.

- [ ] **Step 6: Inspect the final diff and commit**

  Run:

  - `git status --short`
  - `git diff --check`
  - `git diff --stat origin/main...HEAD`

  Confirm there are no unrelated edits, no direct LLM HTTP calls, no hardcoded policy IDs/article numbers/factors, and no publish path that bypasses trace lineage.

  Commit: `git add src/tests/integration/flow/test_policy_release_flow.py src/tests/e2e/flows/portal/policy-knowledge-release.flow.ts; git commit -m "test: 验证政策编译溯源发布闭环"`

---

## Deliberate V1 limits

- Keep the old one-off derivation/migration utilities untouched but remove them from the governed Release path; delete them only in a separately reviewed cleanup.
- Support only exact structured references plus `MULTIPLY`, `COMPLEMENT`, and `DIRECT_COPY`; fuzzy cross-document reference and nested exception reasoning remain REVIEW.
- Reuse current policy-workbench access control and Dialog implementation; add no new auth layer, UI package, rule repository, event bus, or DSL engine.
