# 规则溯源决策视图实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将规则溯源抽屉从八个内部步骤改为三个有业务结论的审核阶段，并消除当前候选中的批次重复展示。

**Architecture:** 在现有 React 组件内把 CompileStep 投影为三个 StageView，不改变 trace API。模型阶段优先选取当前 rule_id 对应的候选；治理阶段聚合规范化、组合及有效关系变化；判定阶段根据规范规则、校验问题和 publication 生成真实结论。

**Tech Stack:** Next.js 16、React、TypeScript、Tailwind CSS、Vitest、Testing Library。

---

### Task 1: 固化三段决策语义

**Files:**
- Modify: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

- [x] **Step 1: 写失败测试**

将主场景断言改为三个 tab：`模型识别`、`规范化与冲突`、`发布判定`；断言不再存在 `原始输入` tab，并新增无规范规则时显示“当前不可发布”的场景。

- [x] **Step 2: 验证测试失败**

Run: `npm test -- --run src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

Expected: FAIL，当前实现仍渲染八个 tab，且没有发布判定说明。

### Task 2: 实现候选级三段视图

**Files:**
- Modify: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`
- Test: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

- [x] **Step 1: 实现最小投影**

保留现有 `StageView`、字段 Diff、JSON 详情和错误处理；将 `buildStages` 改为：

```ts
return [
  buildRecognitionStage(trace),
  buildGovernanceStage(trace),
  buildReleaseDecisionStage(trace),
]
```

候选裁剪使用现有 `rule_id`、`fact_id` 稳定标识；只有找到匹配项时才裁剪，保证历史数据兼容。

- [x] **Step 2: 展示真实结论**

无规范规则时显示“当前不可发布”；存在校验问题时显示“需要人工处理”；已发布时显示 release；未发布但可发布时说明需在发布管理完成整批审核、构建和生效。

- [x] **Step 3: 验证聚焦测试通过**

Run: `npm test -- --run src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

Expected: PASS。

### Task 3: 完成项目验证与浏览器复验

**Files:**
- Verify: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`

- [x] **Step 1: 按项目顺序运行后端验证**

Run: `python -m pytest -p no:asyncio src/tests/unit/knowledge_extension/test_policy_compiler.py -q`

Run: `python -m pytest -p no:asyncio src/tests/integration/api/test_policy_workbench_api.py -q`

Run: `python -m pytest -p no:asyncio src/tests/flow/test_policy_knowledge_build_flow.py -q`

- [x] **Step 2: 运行 Portal 验证**

Run: `npm test -- --run src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

Run: `npm run type-check`

Run: `npm run build`

- [x] **Step 3: 复验真实页面**

打开用户提供的审核 URL，确认三个阶段、当前候选级模型输出、不可发布原因和发布说明均符合设计。

### Task 4: 固化原文高亮与规范化双侧展示

**Files:**
- Modify: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`
- Test: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

- [x] **Step 1: 写失败测试**

增加两个断言场景：

```tsx
expect(screen.getByRole('heading', { name: '单元原文' })).toBeInTheDocument()
expect(screen.getByText('10万元').closest('mark')).toBeInTheDocument()
expect(screen.getByText('100000').closest('[data-source-match="true"]')).toBeInTheDocument()

await user.click(screen.getByRole('tab', { name: /规范化与冲突/ }))
expect(screen.getByRole('heading', { name: '规范化输入' })).toBeInTheDocument()
expect(screen.getByRole('heading', { name: /规范化输出.*未变化/ })).toBeInTheDocument()
```

- [x] **Step 2: 运行测试并确认失败**

Run: `npm test -- --run src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

Expected: FAIL，当前模型输入只有 `candidate_id`，规范化无变化时隐藏双侧字段。

### Task 5: 实现对照高亮与固定规范化输出

**Files:**
- Modify: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`
- Test: `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

- [x] **Step 1: 保留模型原文输入并生成安全匹配词**

模型阶段不再覆盖 `input_payload`，仅把输出裁成当前候选；从候选叶子值生成精确匹配词，并为整数金额补充万元别名：

```ts
const focused = source && candidate
  ? { ...source, output_payload: { candidate } }
  : source

function sourceAliases(value: unknown): string[] {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 10000 && value % 10000 === 0) {
    return [String(value), `${value / 10000}万元`]
  }
  return typeof value === 'string' || typeof value === 'number' ? [String(value)] : []
}
```

- [x] **Step 2: 渲染模型专用双栏与固定规范化双栏**

`StageComparison` 在模型阶段渲染“单元原文 / 模型提取结果”，命中片段使用 `<mark>`；规范化阶段强制 `showAll=true` 并使用“规范化输入 / 规范化输出”标题。

- [x] **Step 3: 运行聚焦测试**

Run: `npm test -- --run src/tests/policy-knowledge/rule-trace-drawer.test.tsx`

Expected: PASS。

### Task 6: 收纳审核操作并完成验证

**Files:**
- Modify: `src/apps/portal/src/components/policy-knowledge/knowledge-review-detail.tsx`
- Modify: `src/apps/portal/src/tests/policy-knowledge/knowledge-review-page.test.tsx`
- Delete after browser acceptance: `src/apps/portal/public/policy-review-prototype.html`

- [x] **Step 1: 写失败测试**

```tsx
expect(screen.getAllByRole('button', { name: '通过' })).not.toHaveLength(0)
expect(screen.getAllByRole('button', { name: '查看对照' })).toHaveLength(pendingChangeSet.items.length)
expect(screen.getAllByText('更多操作')).toHaveLength(pendingChangeSet.items.length)
expect(screen.getByText('其他处理')).toBeInTheDocument()
```

打开对应 `<summary>` 后，再按原有断言触发拒绝、退回、重提取及整批处理。

- [x] **Step 2: 实现原生渐进披露菜单**

使用 `<details className="relative">` 与 `<summary>` 收纳现有按钮；不改变任何 handler、disabled 条件或确认对话框。

- [x] **Step 3: 按顺序验证**

Run: `npm test -- --run src/tests/policy-knowledge/rule-trace-drawer.test.tsx src/tests/policy-knowledge/knowledge-review-page.test.tsx`

Run: `npx tsc --noEmit`

Run: `npx eslint src/components/policy-knowledge/rule-trace-drawer.tsx src/components/policy-knowledge/knowledge-review-detail.tsx`

Run: `npm run build`

最后打开用户提供的真实审核 URL，核对高亮、规范化双栏、行级菜单和页脚菜单。
