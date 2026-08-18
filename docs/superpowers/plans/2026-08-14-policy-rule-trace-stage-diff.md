# Policy Rule Trace Stage Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有纵向 JSON 编译溯源抽屉改成横向阶段轨道，并逐阶段展示真实输入、输出、问题和高亮变化。

**Architecture:** 保持现有 Trace API 和 Dialog 懒加载不变。在 `rule-trace-drawer.tsx` 内增加固定阶段注册表、最小 payload 展平/对齐/Diff 函数和阶段语义模式；相同结构做字段 Diff，不同结构把输入视为来源、输出视为产物，避免误报删除。组件只消费 API 响应，不执行任何领域计算。

**Tech Stack:** Next.js 16、React 19、TypeScript、Tailwind CSS、现有 Dialog/Lucide、Vitest/Testing Library。

---

## Planned file map

- Modify: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx` — 阶段轨道、阶段选择、变化模型、输入输出面板和降级视图。
- Modify: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx` — 在现有测试中覆盖横向阶段、默认异常聚焦、变化高亮、未执行和 legacy 行为。
- Already updated: `docs/steering/政策知识治理-需求迭代记录.md` — 需求追踪。
- Already created: `docs/superpowers/specs/2026-08-14-policy-rule-trace-stage-diff-design.md` — 已确认设计。

## Task 1: Define the visible trace behavior with failing tests

**Files:**

- Modify: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

- [ ] **Step 1: Extend the existing trace fixture with real stage payloads**

Use the existing `trace` fixture and add these ordered steps before `VALIDATE`:

```tsx
{
  step_id: 'step_snapshot', run_id: 'run_1', sequence_no: 1,
  stage: 'INPUT_SNAPSHOT', status: 'PASS',
  input_payload: { source_text: '退休人员个人支付比例为在职人员的60%' },
  output_payload: { source_text: '退休人员个人支付比例为在职人员的60%' },
  issues: [], error: null, duration_ms: 0,
  started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:00Z',
},
{
  step_id: 'step_derive', run_id: 'run_1', sequence_no: 6,
  stage: 'DERIVE', status: 'PASS',
  input_payload: {
    resolutions: {
      fact_relative: {
        relation: { population: 'retiree', expression: { operator: 'MULTIPLY', factor: '0.60' } },
        rules: [{ rule_id: 'rule_base', population: 'employee', result: { ratio: '0.15' } }],
      },
    },
  },
  output_payload: {
    result: [{
      rule_id: 'rule_derived', population: 'retiree', result: { ratio: '0.09' },
      source_type: 'DERIVED', dependencies: ['rule_base'],
      formula: { operator: 'MULTIPLY', factor: '0.60' },
    }],
  },
  issues: [], error: null, duration_ms: 1,
  started_at: '2026-08-11T00:00:00Z', finished_at: '2026-08-11T00:00:01Z',
},
```

- [ ] **Step 2: Replace the first broad rendering assertion with the required user behavior**

```tsx
it('renders the horizontal pipeline and focuses the first review stage', async () => {
  const user = userEvent.setup()
  render(<RuleTraceDrawer open ruleId="rule_1" runId="run_1" onOpenChange={vi.fn()} />)

  expect(await screen.findByRole('heading', { name: '规则编译溯源' })).toBeInTheDocument()
  const tabs = screen.getAllByRole('tab')
  expect(tabs.map((tab) => tab.textContent)).toEqual(expect.arrayContaining([
    expect.stringContaining('输入快照'),
    expect.stringContaining('规则推导'),
    expect.stringContaining('确定性校验'),
    expect.stringContaining('发布'),
  ]))
  expect(screen.getByRole('tab', { name: /确定性校验/ })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByText('OVERLAPPING_RANGE')).toBeInTheDocument()

  await user.click(screen.getByRole('tab', { name: /规则推导/ }))
  expect(screen.getByText('阶段输入')).toBeInTheDocument()
  expect(screen.getByText('阶段输出')).toBeInTheDocument()
  expect(screen.getByText('0.09')).toHaveAttribute('data-change', 'derived')
  expect(screen.getByText(/dependencies/)).toBeInTheDocument()
})
```

- [ ] **Step 3: Add one focused non-fabrication case**

```tsx
it('marks downstream stages as not executed and keeps legacy import single-stage', async () => {
  vi.mocked(getRuleCompilationTrace).mockResolvedValue({
    ...trace,
    rule_id: 'legacy_rule',
    steps: [{
      ...trace.steps[0],
      step_id: 'legacy_step',
      sequence_no: 1,
      stage: 'LEGACY_IMPORT',
      status: 'REVIEW',
    }],
    issues: [],
  })

  render(<RuleTraceDrawer open ruleId="legacy_rule" onOpenChange={vi.fn()} />)

  expect(await screen.findByRole('tab', { name: /历史导入/ })).toBeInTheDocument()
  expect(screen.getAllByRole('tab')).toHaveLength(1)
  expect(screen.getByText(/中间编译历史缺失/)).toBeInTheDocument()
})
```

- [ ] **Step 4: Run the focused component test and verify RED**

Run from `src/apps/portal`:

```powershell
npm test -- src/tests/policy-knowledge/rule-trace-drawer.test.tsx
```

Expected: FAIL because the current component has no stage tabs, default stage selection, change markup or legacy single-stage view.

## Task 2: Implement the minimum stage and change model

**Files:**

- Modify: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`

- [ ] **Step 1: Add the fixed stage registry and view types**

```tsx
const STAGES: Array<{ stage: CompileStage; label: string; mode: StageMode }> = [
  { stage: 'INPUT_SNAPSHOT', label: '输入快照', mode: 'baseline' },
  { stage: 'LLM_EXTRACTION', label: 'LLM 提取', mode: 'transform' },
  { stage: 'CANONICALIZE', label: '规范化', mode: 'diff' },
  { stage: 'COMPOSE', label: '规则组合', mode: 'transform' },
  { stage: 'RESOLVE', label: '引用消解', mode: 'transform' },
  { stage: 'DERIVE', label: '规则推导', mode: 'derive' },
  { stage: 'VALIDATE', label: '确定性校验', mode: 'validate' },
  { stage: 'PUBLISH', label: '发布', mode: 'publish' },
]

type StageMode = 'baseline' | 'diff' | 'transform' | 'derive' | 'validate' | 'publish' | 'legacy'
type ChangeKind = 'added' | 'changed' | 'removed' | 'derived' | 'unchanged'

interface FlatField {
  path: string
  value: unknown
}

interface FieldChange extends FlatField {
  kind: ChangeKind
  before?: unknown
}
```

- [ ] **Step 2: Add small pure payload helpers**

Implement:

```tsx
function isRecord(value: unknown): value is Record<string, unknown>
function unwrapResult(value: Record<string, unknown>): unknown
function stableItemKey(value: unknown, index: number): string
function flattenPayload(value: unknown, path?: string): FlatField[]
function diffFields(input: unknown, output: unknown): FieldChange[]
function normalizedPayload(step: CompileStep, side: 'input' | 'output'): unknown
function stageChangeKind(stage: CompileStage, change: FieldChange): ChangeKind
```

Rules:

- `unwrapResult()` returns `payload.result` when present, otherwise the payload.
- `flattenPayload()` recursively emits leaf fields; arrays use `fact_id`, `rule_id`, `issue_id`, then index.
- CANONICALIZE compares `input_payload.facts` with unwrapped output.
- DERIVE marks produced output fields as `derived`.
- Transform/publish stages treat output fields as produced artifacts, not as proof that input fields were deleted.
- VALIDATE uses `step.issues` as output and never fabricates field paths.
- Empty or malformed values return an empty field list rather than throwing.

- [ ] **Step 3: Build the visible stage list and default selection**

```tsx
function traceStages(trace: RuleCompilationTrace): TraceStageView[]
function defaultStageKey(stages: TraceStageView[]): string
```

Normal runs render the eight fixed stages, mapping actual steps by stage and marking missing stages `notRun: true`. `LEGACY_IMPORT` returns only one legacy stage. Default selection is first REVIEW/FAIL, else last actual stage with changes, else last actual stage.

- [ ] **Step 4: Render the horizontal rail and semantic workspace**

Replace the vertical `<details data-testid="trace-stage">` list with:

```tsx
<div role="tablist" aria-label="编译阶段" className="flex min-w-max gap-2">
  {stages.map((item) => (
    <button
      key={item.key}
      role="tab"
      aria-selected={item.key === selectedStageKey}
      onClick={() => setSelectedStageKey(item.key)}
    >
      <span>{item.label}</span>
      <span>{item.notRun ? '未执行' : `${item.status} · ${item.durationMs}ms`}</span>
      <span>{item.summary}</span>
    </button>
  ))}
</div>
```

The selected stage renders:

- `阶段输入` and `阶段输出` field panels;
- a center change summary on desktop;
- `只看变化 / 全部字段 / JSON Diff` controls;
- issues with code, message and recommended action;
- `data-change="added|changed|removed|derived"` on highlighted value elements;
- the existing full JSON button and modal.

Use `w-[96vw] max-w-none` for the drawer. On narrow screens stack input/output with `grid-cols-1 lg:grid-cols-[minmax(0,1fr)_10rem_minmax(0,1fr)]` and keep the rail horizontally scrollable.

- [ ] **Step 5: Preserve load, retry, close and stale-run behavior**

Reset `selectedStageKey` whenever the committed trace target changes. Keep the existing `loadedTrace` identity check, retry counter, `fullPayload` modal and close behavior unchanged.

- [ ] **Step 6: Run the focused test and verify GREEN**

Run from `src/apps/portal`:

```powershell
npm test -- src/tests/policy-knowledge/rule-trace-drawer.test.tsx
```

Expected: all tests in the file PASS with no warnings.

## Task 3: Focused verification

**Files:** No production changes unless a relevant failure is found.

- [ ] **Step 1: Run compiler unit tests**

```powershell
python -m pytest -p no:asyncio src/tests/unit/knowledge_extension/policy_compiler -q --tb=short
```

Expected: PASS.

- [ ] **Step 2: Run Trace API tests**

```powershell
python -m pytest -p no:asyncio src/tests/integration/api/test_policy_workbench_api.py -q --tb=short -k trace
```

Expected: PASS.

- [ ] **Step 3: Run compilation Flow tests**

```powershell
python -m pytest -p no:asyncio src/tests/integration/flow/test_policy_release_flow.py -q --tb=short -k compile_trace
```

Expected: PASS.

- [ ] **Step 4: Run Portal checks**

From `src/apps/portal`:

```powershell
npm test -- src/tests/policy-knowledge/rule-trace-drawer.test.tsx
npx tsc --noEmit
npm run build
```

Expected: focused Vitest PASS, zero TypeScript errors, production build succeeds.

- [ ] **Step 5: Inspect the scoped diff**

```powershell
git diff --check -- src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx docs/steering/政策知识治理-需求迭代记录.md docs/superpowers/specs/2026-08-14-policy-rule-trace-stage-diff-design.md docs/superpowers/plans/2026-08-14-policy-rule-trace-stage-diff.md
```

Expected: no whitespace errors. Leave changes uncommitted because the shared worktree already contains unrelated user changes.

