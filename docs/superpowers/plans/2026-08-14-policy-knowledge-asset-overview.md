# Knowledge Asset Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/policy-knowledge` as an asset-first overview with truthful Unit counts, structured-knowledge compiler status, and compact governance backlog.

**Architecture:** Extend the two existing read-only aggregates instead of adding endpoints. Keep the UI in the existing page module, replace repeated card sections with one asset ledger, one selected knowledge section, and one governance strip.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, PostgreSQL store adapter, Next.js 16, React 19, TypeScript, Tailwind CSS, Vitest/Testing Library, pytest.

---

### Task 1: Add truthful asset aggregation fields

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/pipeline_store.py:814-825`
- Modify: `src/runtime/api/policy_workbench_routes.py:1000-1056`
- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts:1014-1069`
- Create: `src/tests/unit/knowledge_extension/test_policy_pipeline_summary.py`
- Modify: `src/tests/integration/api/test_policy_workbench_api.py:406-412`

- [ ] **Step 1: Write the failing Unit summary test**

```python
def test_pipeline_summary_counts_real_units(monkeypatch):
    store = PipelineStore("postgresql://unused")
    store._client = SummaryClient()
    monkeypatch.setattr(store, "list_documents", lambda **_: {
        "items": [
            {"unit_total": 5, "unit_audited": 3, "pending_count": 2},
            {"unit_total": 4, "unit_audited": 4, "pending_count": 0},
        ],
        "total": 2,
    })
    assert store.get_summary() | {} == {
        "documents_count": 2,
        "documents_raw": 1,
        "extractions_count": 11,
        "extractions_draft": 2,
        "extractions_reviewed": 4,
        "extractions_published": 5,
        "units_count": 9,
        "units_audited": 7,
        "units_pending": 2,
    }
```

- [ ] **Step 2: Run the Unit test and verify it fails**

Run: `python -m pytest -p no:asyncio src/tests/unit/knowledge_extension/test_policy_pipeline_summary.py -q`

Expected: FAIL because the three Unit fields are absent.

- [ ] **Step 3: Extend the existing aggregates minimally**

In `PipelineStore.get_summary()`, reuse `list_documents(page=1, page_size=1000)` and sum its existing `unit_total`, `unit_audited`, and `pending_count` values.

In `GovernanceDashboard`, add:

```python
knowledge_total: int
compilation_by_status: dict[str, int]
```

Compute `knowledge_total` from the already-loaded workbench document summaries and increment `compilation_by_status[item.compilation_status]` during the existing ChangeSet item loop.

Mirror the exact fields in the frontend types:

```ts
export interface GovernanceDashboard {
  knowledge_total: number
  compilation_by_status: Record<string, number>
}

export interface PipelineSummary {
  units_count: number
  units_audited: number
  units_pending: number
}
```

- [ ] **Step 4: Add API assertions and run focused API tests**

Add assertions for `knowledge_total` and `compilation_by_status` to the existing governance dashboard API test.

Run: `python -m pytest -p no:asyncio src/tests/integration/api/test_policy_workbench_api.py -q -k rules_detail_and_dashboard`

Expected: PASS.

- [ ] **Step 5: Commit the aggregation change**

```bash
git add src/knowledge_extension/rule_explanation/pipeline_store.py src/runtime/api/policy_workbench_routes.py src/apps/portal/src/lib/policy-knowledge-api.ts src/tests/unit/knowledge_extension/test_policy_pipeline_summary.py src/tests/integration/api/test_policy_workbench_api.py
git commit -m "feat: 补充知识资产概览聚合"
```

### Task 2: Replace the overview with the accepted asset-first layout

**Files:**
- Modify: `src/apps/portal/src/tests/policy-knowledge/governance-overview-page.test.tsx`
- Modify: `src/apps/portal/app/policy-knowledge/page.tsx`

- [ ] **Step 1: Replace stale overview assertions with asset-first behavior**

The component test must assert:

```tsx
expect(await screen.findByRole('table', { name: '知识资产台账' })).toBeInTheDocument()
expect(screen.getByRole('row', { name: /政策单元 20 13 已审核/ })).toBeInTheDocument()
expect(screen.getByRole('region', { name: '结构化知识详情' })).toHaveTextContent('PASS 20')
expect(screen.getByRole('region', { name: '知识工作域' })).toHaveTextContent('语义发现')
expect(screen.getByRole('region', { name: '治理进度' })).toHaveTextContent('文档')
expect(screen.queryByText('影响分析')).not.toBeInTheDocument()
```

Keep focused degradation coverage for active-release 404 and a failed dashboard request.

- [ ] **Step 2: Run the Portal test and verify it fails**

Run: `npm test -- --run src/tests/policy-knowledge/governance-overview-page.test.tsx`

Working directory: `src/apps/portal`

Expected: FAIL because the old card dashboard is still rendered.

- [ ] **Step 3: Implement the asset ledger**

Replace the current `PipelineFlow`, card strip, lifecycle, quality/impact, and quick-action sections with:

```tsx
<AssetLedger
  summary={summary}
  dashboard={dashboard}
  publishedKnowledge={milvusTotal}
  semantic={semantic}
  release={release}
  buildingCount={buildingCount}
  pendingReleaseCount={pendingReleaseCount}
/>
<KnowledgeAssetDetail
  dashboard={dashboard}
  publishedKnowledge={milvusTotal}
  compilationByStatus={dash?.compilation_by_status ?? {}}
  buildingCount={buildingCount}
  pendingChangeSets={pendingChangeSets}
  pendingReleaseCount={pendingReleaseCount}
  semantic={semantic}
/>
<GovernanceStatus ... />
```

Remove the slow `listEligibleKnowledgeUnits()` request and the low-confidence extraction sample request. Use the new Unit summary fields and the existing dashboard/build/release/semantic responses only.

- [ ] **Step 4: Implement exact visual hierarchy**

Use one bordered page surface, a six-column semantic table, a two-column knowledge detail section, and a compact five-stage governance strip. Preserve existing blue/slate tokens, tabular numerals, keyboard focus, partial loading/error states, desktop-to-mobile overflow behavior, and the four existing work-domain routes.

- [ ] **Step 5: Run the focused Portal test**

Run: `npm test -- --run src/tests/policy-knowledge/governance-overview-page.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit the page change**

```bash
git add src/apps/portal/app/policy-knowledge/page.tsx src/apps/portal/src/tests/policy-knowledge/governance-overview-page.test.tsx
git commit -m "feat: 重构知识资产概览"
```

### Task 3: Focused verification

**Files:**
- Verify only; no new files.

- [ ] **Step 1: Unit**

Run: `python -m pytest -p no:asyncio src/tests/unit/knowledge_extension/test_policy_pipeline_summary.py -q`

Expected: PASS.

- [ ] **Step 2: API**

Run: `python -m pytest -p no:asyncio src/tests/integration/api/test_policy_workbench_api.py -q -k "rules_detail_and_dashboard"`

Expected: PASS.

- [ ] **Step 3: Flow**

Run: `python -m pytest -p no:asyncio src/tests/integration/flow/test_knowledge_build_flow.py -q`

Expected: PASS.

- [ ] **Step 4: Portal**

Run from `src/apps/portal`:

```bash
npm test -- --run src/tests/policy-knowledge/governance-overview-page.test.tsx
npx tsc --noEmit
npm run build
```

Expected: focused Vitest, TypeScript, and production build all pass.

- [ ] **Step 5: UI detector**

Run:

```bash
node C:/Users/于金宝/.agents/skills/impeccable/scripts/detect.mjs --json src/apps/portal/app/policy-knowledge/page.tsx
```

Fix only findings caused by this page change, rerun the focused Portal test, and stop after one confirmation pass.
