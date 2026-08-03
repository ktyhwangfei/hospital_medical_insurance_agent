# 政策知识 Unit×Knowledge 对齐与质量发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将政策知识“知识”页重做为审核通过 Unit、结构化 Knowledge、统一标准指标/值域三栏工作台，并新增支持整批统一测试和原子发布的“测试”页。

**Architecture:** 用独立 Pydantic 读模型组合现有政策结构、审核状态、提取结果与已发布 `zcgz` 契约；语义层保存多来源字段/值域绑定与人工草稿，不允许知识页直接发布。候选 Knowledge release 写入独立 Milvus collection 对，质量服务用相同用例集对跑候选与当前活动版本，通过门禁后仅原子切换 PostgreSQL 活动版本指针。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、PostgreSQL、Milvus、Next.js 16、React 19、TypeScript、Vitest、pytest、Playwright/Orca。

---

## 文件职责

- `src/knowledge_extension/rule_explanation/knowledge_workbench_models.py`：Unit、Knowledge、字段映射、可信度与工作台响应模型。
- `src/knowledge_extension/rule_explanation/knowledge_workbench_service.py`：只读组合服务；不得写 SemanticRegistry 私有 store。
- `src/knowledge_extension/rule_explanation/semantic_alignment.py`：多来源指标/值域绑定模型与端口。
- `src/data_platform/storage/postgresql/semantic_alignment_store.py`：来源绑定、草稿标准值的 PostgreSQL adapter。
- `src/knowledge_extension/rule_explanation/quality_models.py`：测试用例、release、run、门禁与逐用例结果模型。
- `src/knowledge_extension/rule_explanation/quality_store.py`：质量存储 Protocol 与内存实现。
- `src/data_platform/storage/postgresql/policy_quality_store.py`：质量与活动版本 PostgreSQL adapter。
- `src/knowledge_extension/rule_explanation/quality_service.py`：候选/基线同集对跑、重复运行一致性、严格提升门禁和 promotion 编排。
- `src/knowledge_extension/rule_explanation/release_index.py`：Milvus release collection 对的构建/搜索 adapter 边界。
- `src/runtime/api/policy_workbench_routes.py`：typed 工作台、语义对齐、测试与发布 API。
- `src/apps/portal/src/lib/policy-knowledge-api.ts`：前端 DTO 与请求函数。
- `src/apps/portal/app/policy-knowledge/knowledge/page.tsx`：三栏工作台，只保留知识治理交互。
- `src/apps/portal/app/policy-knowledge/test/page.tsx`：搜索、经典用例、质量对比与发布门禁。
- `src/apps/portal/src/components/policy-knowledge/`：拆分三栏、指标草稿对话框与质量面板，避免再次形成 800 行单页。

## Task 1：稳定 Unit↔Knowledge 身份与读取模型

**Files:**
- Create: `src/knowledge_extension/rule_explanation/knowledge_workbench_models.py`
- Create: `src/knowledge_extension/rule_explanation/knowledge_workbench_service.py`
- Modify: `src/knowledge_extension/rule_explanation/pipeline_store.py`
- Modify: `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py`
- Modify: `src/runtime/api/policy_pipeline_routes.py`
- Test: `src/tests/unit/knowledge_extension/test_knowledge_workbench.py`

- [x] **Step 1: Write failing identity and approved-unit tests**

  Cover: only `reviewed/published` or approved `unit_audit` units are returned; merged duplicate units are excluded; one Unit returns multiple Knowledge items; reordering rules does not change `knowledge_id`; explicit `unit_id` wins and legacy text matching is marked `legacy_match`.

- [x] **Step 2: Verify RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_knowledge_workbench.py -v --tb=short`

  Expected: import failure for `knowledge_workbench_service`.

- [x] **Step 3: Add typed models and deterministic legacy identity**

  Required public models:

  ```python
  class KnowledgeConfidence(BaseModel):
      completeness: float = Field(ge=0, le=1)
      accuracy: float | None = Field(default=None, ge=0, le=1)
      source_fidelity: float = Field(ge=0, le=1)
      model_confidence: float = Field(ge=0, le=1)
      value_domain_compliance: float = Field(ge=0, le=1)
      overall: float = Field(ge=0, le=1)
      uncertainties: list[str] = Field(default_factory=list)

  class KnowledgeItem(BaseModel):
      knowledge_id: str
      unit_id: str
      extraction_id: str
      business_sentence: str
      source_text: str
      fields: list[KnowledgeField]
      confidence: KnowledgeConfidence
      citations: list[KnowledgeCitation]

  class ApprovedUnit(BaseModel):
      unit_id: str
      doc_id: str
      doc_title: str
      path: list[str]
      source_text: str
      order_no: int
      status: Literal["reviewed", "published"]
      knowledge_count: int
      knowledge: list[KnowledgeItem]
  ```

  Legacy `knowledge_id` must hash `extraction_id + canonical JSON(rule without rule_id/index)`; array position must never enter the hash. Persisted `rule_id`/`knowledge_id` is preferred.

- [x] **Step 4: Persist explicit Unit identity for new extraction writes**

  Add `policy_extractions.unit_id VARCHAR(64)` with an idempotent `ALTER TABLE` and index. Add `unit_id` to create/read/update. Change `extract-leaf` to a Pydantic request containing `unit_id` and `source_text`, validate the node belongs to the requested document, and pass it through `PipelineOrchestrator.extract_single()`.

- [x] **Step 5: Build coherent sentences and explainable confidence**

  Use deterministic templates by `rule_type` (`eligibility`, `payment_ratio`, `deductible`, `cap`, fallback) with subject/condition/result/unit. Completeness uses only fields applicable to that rule type; accuracy is computed only from field values supported by source spans or approved golden cases; source fidelity measures citation coverage. Missing evidence yields `accuracy=None` plus `uncertainties` and must not be converted into a fabricated default score; UI displays “待验证”。

- [x] **Step 6: Verify GREEN and regression**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_knowledge_workbench.py src/tests/unit/knowledge_extension/test_pipeline_coverage.py src/tests/unit/knowledge_extension/test_pipeline_chunking.py -v --tb=short`

- [x] **Step 7: Commit**

  Commit: `feat: 建立稳定的政策单元与知识读取模型`

## Task 2：双来源统一指标与值域治理

**Files:**
- Create: `src/knowledge_extension/rule_explanation/semantic_alignment.py`
- Create: `src/data_platform/storage/postgresql/semantic_alignment_store.py`
- Modify: `src/semantic_layer/registry.py`
- Create: `src/runtime/api/semantic_alignment_routes.py`
- Modify: `src/runtime/api/app.py`
- Modify: `src/data_platform/persistence/semantic_migrations.py`
- Test: `src/tests/unit/knowledge_extension/test_semantic_alignment.py`
- Test: `src/tests/integration/api/test_semantic_alignment_api.py`

- [x] **Step 1: Write failing multi-source and draft-only tests**

  Assert that one published metric accepts multiple bindings from `structured_field` and `policy_knowledge`; duplicate bindings are idempotent; a policy binding carries `doc_id/unit_id/knowledge_id/field_code/evidence/version`; source values map many-to-one to a standard value; new standard values remain draft until object publication.

- [x] **Step 2: Verify RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_semantic_alignment.py -v --tb=short`

- [x] **Step 3: Add source-binding models and storage schema**

  ```python
  class MetricSourceBinding(BaseModel):
      binding_id: str
      metric_code: str
      source_type: Literal["structured_field", "policy_knowledge"]
      source_ref: str
      source_field: str
      source_version: str
      evidence: str

  class SourceValueMapping(BaseModel):
      mapping_id: str
      metric_code: str
      domain_code: str
      binding_id: str
      source_value: str
      standard_value: str
      status: Literal["draft", "published", "rejected"]
  ```

  Add `semantic_metric_source_binding` and `semantic_source_value_mapping` tables with unique constraints on `(metric_code, source_type, source_ref, source_field, source_version)` and `(binding_id, source_value)`.

- [x] **Step 4: Add public semantic APIs**

  Add typed endpoints for binding an existing metric, batch binding, creating a draft metric with source bindings, and proposing a draft standard value. Knowledge routes call these public services only; no access to `registry._store` and no implicit `publish_object()`.

- [x] **Step 5: Verify T1 then T2a**

  Run in order:

  1. `python -m pytest src/tests/unit/knowledge_extension/test_semantic_alignment.py src/tests/unit/semantic_layer -v --tb=short`
  2. `python -m pytest src/tests/integration/api/test_semantic_alignment_api.py src/tests/integration/api/test_semantic_extraction_schema.py -v --tb=short`

- [x] **Step 6: Commit**

  Commit: `feat: 支持双来源指标和值域统一对齐`

## Task 3：知识工作台 API 与标准化投影

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/knowledge_workbench_models.py`
- Modify: `src/knowledge_extension/rule_explanation/knowledge_workbench_service.py`
- Create: `src/runtime/api/policy_workbench_routes.py`
- Modify: `src/runtime/api/app.py`
- Test: `src/tests/unit/knowledge_extension/test_knowledge_workbench.py`
- Test: `src/tests/integration/api/test_policy_workbench_api.py`

- [x] **Step 1: Write failing mapping tests**

  Assert field states `mapped/unmapped/not_applicable/invalid`; raw and standard values are both preserved; mapping is bound to the published `zcgz` contract version; unavailable semantic registry returns a typed 503 and never an empty successful contract.

- [x] **Step 2: Verify RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_knowledge_workbench.py -v --tb=short -k mapping`

- [x] **Step 3: Implement read-only projection**

  Expose `GET /policy-workbench/documents` and `GET /policy-workbench/documents/{doc_id}` with response models. The document response contains approved Unit list, selected contract version, Knowledge confidence, field mapping and citations. Reuse `build_extraction_schema(registry, "zcgz")` plus public alignment queries.

- [x] **Step 4: Verify T1 then T2a**

  Run in order:

  1. `python -m pytest src/tests/unit/knowledge_extension/test_knowledge_workbench.py -v --tb=short`
  2. `python -m pytest src/tests/integration/api/test_policy_workbench_api.py src/tests/integration/api/test_openapi_contract.py -v --tb=short`

- [ ] **Step 5: Commit**

  Commit: `feat: 提供政策知识三栏工作台接口`

## Task 4：候选 Knowledge release 与质量存储

**Files:**
- Create: `src/knowledge_extension/rule_explanation/quality_models.py`
- Create: `src/knowledge_extension/rule_explanation/quality_store.py`
- Create: `src/data_platform/storage/postgresql/policy_quality_store.py`
- Modify: `src/data_platform/persistence/migrations.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_quality_store.py`
- Test: `src/tests/unit/data_platform/test_policy_quality_migration.py`

- [ ] **Step 1: Write failing lifecycle and atomic-pointer tests**

  Cover case-set versioning, candidate release immutability, run configuration hashing, candidate/baseline result separation, exactly one active release, failed promotion preserving the old active pointer, and rollback to a retained release.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_quality_store.py src/tests/unit/data_platform/test_policy_quality_migration.py -v --tb=short`

- [ ] **Step 3: Implement Pydantic domain and store port**

  Required states: release `building/ready/testing/passed/failed/active/retired`; run `queued/running/passed/failed`; case `active/disabled`. Store all collection names, `contract_version`, `case_set_version`, `config_hash`, quality summary and audit actor.

- [ ] **Step 4: Implement PostgreSQL adapter and transaction**

  Create `policy_qa_test_cases`, `policy_knowledge_releases`, `policy_quality_runs`, `policy_quality_case_results`, and singleton `policy_active_release`. `promote_release()` must lock the singleton row, verify release status `passed`, update old/new statuses and pointer in one transaction.

- [ ] **Step 5: Verify GREEN**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_quality_store.py src/tests/unit/data_platform/test_policy_quality_migration.py -v --tb=short`

- [ ] **Step 6: Commit**

  Commit: `feat: 增加政策知识版本与质量存储`

## Task 5：独立 collection 对、批量测试与严格发布门禁

**Files:**
- Create: `src/knowledge_extension/rule_explanation/release_index.py`
- Create: `src/knowledge_extension/rule_explanation/quality_service.py`
- Modify: `src/knowledge_extension/rule_explanation/rules_search_service.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_quality_service.py`
- Test: `src/tests/integration/flow/test_policy_release_flow.py`

- [ ] **Step 1: Write failing gate tests**

  Cover: candidate and baseline use identical case/config versions; each candidate repeats at least three times; consistency compares repeated result IDs/ranking under the same mode; candidate score must be strictly greater than baseline; required-case failure blocks; no baseline requires an absolute threshold; promotion failure leaves active release unchanged.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_quality_service.py -v --tb=short`

- [ ] **Step 3: Implement versioned index adapter**

  Build `policy_facts_{release_id}` and `policy_rules_{release_id}` using existing parameterized schema helpers. Load and health-check both before marking the release ready. Search services receive the two names from one `KnowledgeRelease` and never resolve them independently.

- [ ] **Step 4: Implement scoring and gate**

  Per case store expected citations/knowledge IDs, precision/recall/rank score and diagnostics. Gate requires all required cases, configured minimum quality, configured minimum repeat consistency, and strict `candidate_overall > baseline_overall`; cross-mode Jaccard remains diagnostic only.

- [ ] **Step 5: Verify T1 then T2b**

  Run in order:

  1. `python -m pytest src/tests/unit/knowledge_extension/test_policy_quality_service.py -v --tb=short`
  2. `python -m pytest src/tests/integration/flow/test_policy_release_flow.py -v --tb=short`

- [ ] **Step 6: Commit**

  Commit: `feat: 实现政策知识批量测试与原子发布`

## Task 6：测试与发布 API

**Files:**
- Modify: `src/runtime/api/policy_workbench_routes.py`
- Test: `src/tests/integration/api/test_policy_quality_api.py`
- Test: `src/tests/integration/flow/test_policy_release_flow.py`

- [ ] **Step 1: Write failing API tests**

  Cover test-case CRUD, candidate creation, run start/detail, gate block reason, promotion, rollback and active release query. Assert response models and 409 on blocked promotion.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest src/tests/integration/api/test_policy_quality_api.py -v --tb=short`

- [ ] **Step 3: Add typed endpoints**

  Use `/policy-workbench/test-cases`, `/releases`, `/quality-runs`, `/releases/{release_id}/promote`, `/releases/{release_id}/rollback`, and `/releases/active`. Routes perform validation and delegate to services; they do not instantiate Milvus directly inside endpoint functions.

- [ ] **Step 4: Verify T2a then T2b**

  Run in order:

  1. `python -m pytest src/tests/integration/api/test_policy_workbench_api.py src/tests/integration/api/test_policy_quality_api.py src/tests/integration/api/test_openapi_contract.py -v --tb=short`
  2. `python -m pytest src/tests/integration/flow/test_policy_release_flow.py -v --tb=short`

- [ ] **Step 5: Commit**

  Commit: `feat: 提供政策知识质量测试与发布接口`

## Task 7：知识页三栏交互

**Files:**
- Create: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Create: `src/apps/portal/src/components/policy-knowledge/unit-column.tsx`
- Create: `src/apps/portal/src/components/policy-knowledge/knowledge-column.tsx`
- Create: `src/apps/portal/src/components/policy-knowledge/alignment-column.tsx`
- Create: `src/apps/portal/src/components/policy-knowledge/metric-draft-dialog.tsx`
- Modify: `src/apps/portal/app/policy-knowledge/knowledge/page.tsx`
- Test: `src/apps/portal/src/tests/policy-knowledge/knowledge-workbench.test.tsx`

- [ ] **Step 1: Write failing component tests**

  Assert only approved Units render; Unit click filters Knowledge; Knowledge click highlights its Unit and updates right column; one Unit can render multiple Knowledge cards; confidence dimensions are visible; unmapped fields support single/batch selection; binding existing metric is primary and creating draft never displays “已发布”.

- [ ] **Step 2: Verify RED**

  Run: `npm test -- src/tests/policy-knowledge/knowledge-workbench.test.tsx` in `src/apps/portal`.

- [ ] **Step 3: Implement responsive three-column workbench**

  Keep document selector and internal candidate/release badge. Remove search/library tabs from Knowledge. On wide screens use three columns with independent scroll; on narrow screens use Unit→Knowledge→标准化 staged panels. Use `aria-selected`, keyboard focus and stable IDs.

- [ ] **Step 4: Implement human-only semantic actions**

  Right column supports bind-existing, single create and batch create. Batch rows individually confirm name/code/semantic type/unit/value domain; object is fixed `zcgz`; do not hardcode all entries as `Atomic + Amount`. Successful creation shows `draft/待语义层发布` and a link to semantic-layer review.

- [ ] **Step 5: Verify GREEN, lint and build**

  Run in `src/apps/portal`:

  1. `npm test -- src/tests/policy-knowledge/knowledge-workbench.test.tsx`
  2. `npm run lint`
  3. `npm run build`

- [ ] **Step 6: Commit**

  Commit: `feat: 重做政策知识三栏知识工作台`

## Task 8：独立测试页与导航

**Files:**
- Create: `src/apps/portal/app/policy-knowledge/test/page.tsx`
- Create: `src/apps/portal/src/components/policy-knowledge/quality-dashboard.tsx`
- Create: `src/apps/portal/src/components/policy-knowledge/test-case-editor.tsx`
- Modify: `src/apps/portal/app/policy-knowledge/layout.tsx`
- Test: `src/apps/portal/src/tests/policy-knowledge/policy-test-page.test.tsx`
- Create: `src/tests/e2e/pages/portal/policy-knowledge.page.ts`
- Create: `src/tests/e2e/flows/portal/policy-knowledge-release.flow.ts`

- [ ] **Step 1: Write failing page tests**

  Assert navigation order `概览→文档→单元→知识→测试`; all precise/semantic/hybrid search controls exist only on Test; candidate/baseline chart, repeated consistency, failure details and disabled publish button render from API state.

- [ ] **Step 2: Verify RED**

  Run: `npm test -- src/tests/policy-knowledge/policy-test-page.test.tsx` in `src/apps/portal`.

- [ ] **Step 3: Implement Test page**

  Include search diagnostics, classic-case CRUD, candidate creation/run, per-case diff, quality/consistency visualization, blocked reasons, atomic publish and rollback history. Never offer per-Unit or per-Knowledge publish.

- [ ] **Step 4: Verify frontend and T4**

  Run unit test and build, then use `start-servers.ps1`. Validate `/policy-knowledge/knowledge` and `/policy-knowledge/test` with Orca, capture screenshots, and run `npx playwright test flows/portal/policy-knowledge-release.flow.ts` from `src/tests/e2e`.

- [ ] **Step 5: Commit**

  Commit: `feat: 增加政策知识统一测试与发布页面`

## Task 9：完整串行验证与文档收口

**Files:**
- Modify: `docs/steering/政策知识治理平台设计-V2.1.md`
- Modify: `docs/steering/语义层设计文档.md`
- Modify: `docs/steering/接口设计文档.md`
- Modify: `docs/steering/政策知识治理-需求迭代记录.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: Update source-of-truth docs**

  Document five-page IA, dual authoritative sources, multi-source metric/value bindings, human draft review, contract versioning, release collection pair, quality gate and rollback. Mark `9b3c503` compare route/service as rejected design, not the implementation baseline.

- [ ] **Step 2: Run strict T1 → T2a → T2b**

  Run in order and stop on first failure:

  1. `python -m pytest src/tests/unit/knowledge_extension src/tests/unit/semantic_layer src/tests/unit/data_platform -v --tb=short`
  2. `python -m pytest src/tests/integration/api/test_policy_workbench_api.py src/tests/integration/api/test_policy_quality_api.py src/tests/integration/api/test_semantic_alignment_api.py src/tests/integration/api/test_openapi_contract.py -v --tb=short`
  3. `python -m pytest src/tests/integration/flow/test_policy_release_flow.py src/tests/integration/flow/test_knowledge_extension_runtime.py -v --tb=short`

- [ ] **Step 3: Run frontend verification**

  Run `npm test`, `npm run lint`, and `npm run build` in `src/apps/portal`; then complete Orca screenshots and the policy release Playwright flow.

- [ ] **Step 4: Verify working tree and evidence**

  Run `git diff --check`, inspect `git status --short`, and record exact test counts, screenshots, rollback behavior and any environment-dependent tests not run.

- [ ] **Step 5: Commit**

  Commit: `docs: 更新政策知识统一对齐与发布设计`

---

## 需求覆盖自检

1. 三栏：Task 3、7。
2. Unit 切换、一单元多知识、反向高亮：Task 1、7。
3. 字段连读成完整意思：Task 1。
4. 完整性、准确性等可信度：Task 1、5；无证据时显示不确定性，不伪造。
5. 右栏来自语义层发布契约：Task 2、3。
6. 未映射字段人工单条/批量生成 draft 指标：Task 2、7。
7. 来源值对齐统一标准值域，新增标准值走人工草稿：Task 2、7。
8. 搜索迁移到独立测试页，经典用例量化/可视化，严格提升与一致性门禁，整批原子发布：Task 4、5、6、8。

## 回滚说明

- UI 可按提交回退到旧 Knowledge 页面，但新表为向后兼容增量，不在回滚时删除。
- Semantic draft/binding 不自动进入 published contract，回退 UI/API 不影响当前发布版本。
- Knowledge release promotion 只切活动指针；业务回滚切回上一保留版本，不删除当前或历史 collection。
- 发布过程中任一构建、测试、事务失败均保持旧活动指针不变。
