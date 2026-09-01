# Semantic Model Workbench UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make semantic model editing understandable and make query validation fully model-driven, including safe random anchor sampling.

**Architecture:** Keep the existing query-model document and bulk PUT contract. The mapping page edits that document through native structured controls; the query page reads a published model and derives every dependent choice from it. Add one review-protected sampling method and endpoint that resolve physical identifiers only from the published registry snapshot.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy Core, React 19, Next.js 16, Vitest, Testing Library, pytest.

---

### Task 1: Published-model anchor sampling

**Files:**
- Modify: `src/semantic_layer/query_planner.py`
- Modify: `src/runtime/api/semantic_routes.py`
- Modify: `src/tests/unit/semantic_layer/test_query_planner.py`
- Modify: `src/tests/integration/api/test_semantic_query_model_api.py`

- [ ] **Step 1: Write failing service tests**

Add tests that construct the seeded published registry and fake DB-API connection, then assert:

```python
value = SemanticQueryService(registry, connect).sample_anchor(
    "inpatient_settlement",
    "inpatient_admission",
    "inpatient_registration.registration_id",
)
assert value == "1671213"
assert "NEWID" in cursor.sql.upper()
```

Also assert an unregistered/non-identifier field raises `SemanticQueryPlanningError` before opening a connection.

- [ ] **Step 2: Verify the service tests fail**

Run:

```powershell
python -m pytest src/tests/unit/semantic_layer/test_query_planner.py -v --tb=short -k "sample_anchor"
```

Expected: FAIL because `SemanticQueryService.sample_anchor` does not exist.

- [ ] **Step 3: Implement the minimum sampling method**

Add `sample_anchor(object_code, entity_code, field_code)` to `SemanticQueryService`. It must:

```python
version = self._planner._published_version(object_code)
field = next((item for item in version.fields if item.field_code == field_code), None)
if field is None or field.field_role != "identifier":
    raise SemanticQueryPlanningError("锚点字段未在已发布模型登记为 identifier")
if not any(
    key.dataset_code == field.dataset_code
    and key.entity_code == entity_code
    and field.column_name in key.columns
    for key in version.keys
):
    raise SemanticQueryPlanningError("锚点字段不能定位目标实体")
```

Resolve the dataset from the version snapshot, build `SELECT DISTINCT TOP 1 <column> ... WHERE <column> IS NOT NULL ORDER BY NEWID()` with SQLAlchemy Core, execute through the injected connection, close the connection, and return `row[0]` or `None`.

- [ ] **Step 4: Verify service tests pass**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Write failing API tests**

Extend the existing API test fixture with a fake runtime and assert:

```python
response = client.post(
    f"{BASE}/query/anchor-sample",
    json={
        "object_code": "inpatient_settlement",
        "entity_code": "inpatient_admission",
        "field_code": "inpatient_registration.registration_id",
    },
    headers=_review_headers(),
)
assert response.status_code == 200
assert response.json() == {"value": "1671213"}
assert client.post(f"{BASE}/query/anchor-sample", json={}).status_code == 401
```

- [ ] **Step 6: Verify API tests fail**

Run:

```powershell
python -m pytest src/tests/integration/api/test_semantic_query_model_api.py -v --tb=short -k "anchor_sample"
```

Expected: FAIL with 404.

- [ ] **Step 7: Implement the endpoint and published model read**

Add typed `AnchorSampleRequest`/`AnchorSampleResponse` models and the review-protected `POST /query/anchor-sample`. Map planning errors to 400, empty samples to 404, and database failures to the existing safe 503 error shape.

Allow `GET /objects/{object_code}/query-model?published=true` to return the latest immutable `BusinessObjectVersion` document; keep the current default behavior unchanged.

- [ ] **Step 8: Verify API tests pass**

Run the command from Step 6. Expected: PASS.

### Task 2: Model-driven query validation page

**Files:**
- Create: `src/apps/portal/src/tests/semantic-query-page.test.tsx`
- Modify: `src/apps/portal/app/semantic-layer/query/page.tsx`

- [ ] **Step 1: Write failing interaction tests**

Mock objects, published query models, metrics, and anchor sampling. Cover:

```typescript
expect(await screen.findByLabelText('业务对象')).toHaveValue('inpatient_settlement')
await user.selectOptions(screen.getByLabelText('业务对象'), 'second_queryable')
expect(screen.getByLabelText('目标实体')).toHaveValue('second_entity')
expect(screen.getByLabelText('锚点值')).toHaveValue('')
expect(screen.queryByText('查询结果')).not.toBeInTheDocument()

await user.click(screen.getByRole('button', { name: '随机取值' }))
expect(await screen.findByLabelText('锚点值')).toHaveValue('1671213')
```

Assert the page renders selects/multi-selects instead of entity/field/metric free-text inputs and raw filter/order JSON textareas.

- [ ] **Step 2: Verify interaction tests fail**

Run:

```powershell
npm test -- --run src/tests/semantic-query-page.test.tsx
```

from `src/apps/portal`. Expected: FAIL because fields are not linked and the sampling button is absent.

- [ ] **Step 3: Implement linked model state**

Rewrite the page to:

- fetch objects and each `query-model?published=true`;
- keep only objects with `current_version` and `queryable`;
- fetch metric details for the selected object and keep published query metrics with `fact_field_code` or `expression`;
- derive entity options from keys and anchor options from identifier fields belonging to that entity's keys;
- clear anchor value, advanced conditions, errors, and output whenever object/entity/anchor changes;
- call `/query/anchor-sample` only from the `随机取值` button;
- serialize structured filter/order rows to the unchanged `/query/test` request;
- show `再次点击可重新取样。` below the anchor input.

Use native `<select multiple>`, `<details>`, inputs, and buttons; add no UI dependency.

- [ ] **Step 4: Verify interaction tests pass**

Run the command from Step 2. Expected: PASS.

### Task 3: Structured mapping workbench

**Files:**
- Create: `src/apps/portal/src/tests/semantic-mapping-page.test.tsx`
- Modify: `src/apps/portal/app/semantic-layer/mapping/page.tsx`

- [ ] **Step 1: Write failing interaction tests**

Mock an empty first object and a queryable second object. Assert:

```typescript
expect(await screen.findByLabelText('业务对象')).toHaveValue('inpatient_settlement')
expect(screen.getByText('每行代表')).toBeInTheDocument()
expect(screen.getByText('住院结算')).toBeInTheDocument()
expect(screen.queryByText('参保人登记指标')).not.toBeInTheDocument()
```

Switch to the empty object and assert the `添加数据集` guided action appears. Exercise one structured field edit and assert the existing bulk PUT receives a full query-model document.

- [ ] **Step 2: Verify interaction tests fail**

Run from `src/apps/portal`:

```powershell
npm test -- --run src/tests/semantic-mapping-page.test.tsx
```

Expected: FAIL because the first object is selected, metrics are global, and only JSON editing exists.

- [ ] **Step 3: Implement the workbench**

Keep one `QueryModelDocument` state and render section buttons for overview, datasets, keys, fields, relations, quality rules, and advanced JSON. Each section edits arrays in that document with native controls. Show `DatasetKey.entity_code` and primary key columns as “每行代表”.

On initial load, fetch each query model and select the first queryable published object. Filter metric cards, counts, and rows by `selectedObject`. For an empty model, render the three-step guide and `添加数据集` action. Save every structured edit through the unchanged bulk PUT.

- [ ] **Step 4: Verify interaction tests pass**

Run the command from Step 2. Expected: PASS.

### Task 4: Review and verification

**Files:** All files changed above.

- [ ] **Step 1: Review the diff against the design**

Check object switching, stale-state clearing, published-snapshot usage, physical identifier isolation, empty states, errors, accessibility labels, and absence of new dependencies or metadata fields.

- [ ] **Step 2: Fix confirmed gaps and re-review**

Apply only fixes required by the approved design, then repeat Step 1.

- [ ] **Step 3: Run T1 unit tests**

```powershell
python -m pytest src/tests/unit/semantic_layer/test_query_planner.py -v --tb=short
```

- [ ] **Step 4: Run T2a API tests**

```powershell
python -m pytest src/tests/integration/api/test_semantic_query_model_api.py -v --tb=short
```

- [ ] **Step 5: Run T2b Flow tests**

```powershell
python -m pytest src/tests/integration/flow -v --tb=short -k "settlement"
```

- [ ] **Step 6: Run focused frontend tests and type/build check**

```powershell
npm test -- --run src/tests/semantic-query-page.test.tsx src/tests/semantic-mapping-page.test.tsx
npm run build
```

- [ ] **Step 7: Verify through the managed workspace URL**

Use `..\ws.ps1 restart issue-20`, verify `..\ws.ps1 list`, then open `http://127.0.0.1:3126/semantic-layer/mapping` and `/semantic-layer/query`. Confirm object linkage, empty model guidance, structured editing, random anchor sampling, and validation execution.

No implementation commit is planned because the target files already contain unrelated uncommitted user changes; staging them would mix ownership. Deliver the verified working-tree diff only.

