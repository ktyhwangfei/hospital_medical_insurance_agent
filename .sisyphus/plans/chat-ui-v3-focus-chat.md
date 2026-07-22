# 聊天页面 v3 — 专注聊天布局重构

## TL;DR

> **Quick Summary**: 将当前四栏布局（侧边导航 + 快捷提问 + 聊天区 + 执行步骤）重构为"专注聊天"单栏全宽布局：侧边栏改为汉堡菜单，快捷提问改为输入框上方建议词条，执行步骤改为浮动抽屉。
> 
> **Deliverables**:
> - `layout.tsx` — sidebar → 汉堡菜单 Sheet 抽屉
> - `settlement-chat.tsx` — 移除左右面板，聊天区全宽
> - `chat-input.tsx` — 输入框上方添加 suggestion chips
> - `message-list.tsx` — 意图状态栏条件渲染
> - NEW `execution-drawer.tsx` — 浮动执行步骤抽屉
> - `page.tsx` — 移除 max-w-5xl 约束
> - `docs/steering/原型设计文档.md` — 更新 §1.1 §2.1 §3.1 §3.2.1
> 
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 5 waves
> **Critical Path**: layout 改动 → chat 组件改动 → 原型文档更新 → 验证

---

## Context

### 原始需求
用户反馈当前聊天页面（http://127.0.0.1:3000/）四栏布局过重，聊天区被严重挤压，视觉效果不佳。要求按"专注聊天"方案重构：折叠侧边导航为汉堡菜单、移除快捷提问面板、聊天区全宽、执行步骤改为浮动抽屉。

### 用户决策
- 方案：A — 专注聊天
- 原型文档：同步更新 `docs/steering/原型设计文档.md`

### Metis 审查
**识别的缺口** (已处理):
- 状态栏已内联在 message-list.tsx → 只需条件渲染，无需上移
- 连接状态指示器 → 保留在 header 中（汉堡按钮旁）
- 执行步骤抽屉 → 用 shadcn Sheet 包装现有 ExecutionTimeline，不重写
- page.tsx max-w-5xl → 与全宽布局冲突，需移除
- 状态栏 + IntentTraceCard 显示重复数据 → 均为条件渲染，互补不冲突
- Suggestion chips 交互 → 静态，仅作为替代快捷问题的入口方式
- 浮窗打开时聊天输入 → 保持聚焦，不锁滚动

---

## Work Objectives

### Core Objective
将聊天页面从四栏"仪表盘式"布局重构为"专注聊天"单栏全宽布局，提升聊天体验和空间利用率。

### Concrete Deliverables
- `src/apps/portal/app/layout.tsx` — Handler 按钮 + Sheet 抽屉导航（替换固定侧边栏）
- `src/apps/portal/app/page.tsx` — 移除 max-w-5xl → w-full
- `src/apps/portal/src/components/settlement-chat.tsx` — 移除左右面板，聊天全宽
- `src/apps/portal/src/components/chat/message-list.tsx` — 意图状态栏条件渲染
- `src/apps/portal/src/components/chat/chat-input.tsx` — 添加 suggestion chips
- NEW `src/apps/portal/src/components/chat/execution-drawer.tsx` — 浮动执行步骤

### Definition of Done
- [ ] 汉堡按钮可点击展开导航抽屉，含所有 4 个路由链接 + 角色切换 + 版本号
- [ ] 聊天区全宽无 grid 约束，消息列表撑满可用空间
- [ ] 建议词条在输入框上方横向显示，点击发送对应消息
- [ ] 执行步骤仅在右下角浮动按钮，点击展开 Sheet 抽屉
- [ ] 意图状态栏仅在有意图数据时显示
- [ ] 连接状态保留在 header 中
- [ ] `npm run build` 通过
- [ ] `npm run lint` 重构文件 0 errors
- [ ] 原型设计文档已更新

### 必须做
- 用 shadcn `<Sheet>` 组件实现两个抽屉（不是手写）
- 保留所有现有 `data-testid` 属性
- 保留聊天区暗色主题（bg-slate-950/slate-900）
- 执行 FAB 在步骤运行中显示活动指示器
- 预填消息流保持正常工作

### 必须不做（防护栏）
- **不**修改 `sse-hooks.ts`、`api-client.ts`、`types.ts`
- **不**修改 `ExecutionTimeline` 或 `IntentTraceCard` 组件逻辑
- **不**修改 `ChatMessage`、`IntentTrace`、`ChatRequest` 接口
- **不**添加新动画或过渡效果
- **不**修改 admin 或 embed 应用
- **不**改变聊天颜色主题
- **不**修改字体或基础设计 token

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (vitest + Playwright E2E)
- **Automated tests**: Tests-after
- **Framework**: vitest + Playwright

### QA Policy
Every task includes agent-executed QA scenarios using Playwright.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (布局改造 — 串行，两个文件都影响全局):
├── Task 1: layout.tsx — 汉堡菜单 + Sheet 导航抽屉
└── Task 2: page.tsx — 移除 max-w-5xl

Wave 2 (chat 核心组件 — 并行):
├── Task 3: settlement-chat.tsx — 移除左右面板
├── Task 4: chat-input.tsx — 添加 suggestion chips
└── Task 5: message-list.tsx — 状态栏条件渲染

Wave 3 (新组件 — 依赖 Wave 2):
└── Task 6: execution-drawer.tsx — 浮动执行步骤抽屉

Wave 4 (文档 + 验证 — 并行):
├── Task 7: 更新原型设计文档.md
└── Task 8: Playwright E2E 验证

Critical Path: Task 1 → Task 3 → Task 6 → Task 8
Max Concurrent: 3 (Wave 2)
```

### Dependency Matrix

- **1**: - - 3-6, 1
- **2**: - - 3-6, 1
- **3**: 1, 2 - 6, 2
- **4**: 1, 2 - - , 2
- **5**: 1, 2 - - , 2
- **6**: 3 - 8, 3
- **7**: 3 - - , 4
- **8**: 6 - - , 4

### Agent Dispatch Summary

- **Wave 1**: 2 — T1→deep, T2→quick
- **Wave 2**: 3 — T3→visual-engineering, T4→quick, T5→quick
- **Wave 3**: 1 — T6→visual-engineering
- **Wave 4**: 2 — T7→writing, T8→visual-engineering (+ playwright-cli)

## TODOs

- [ ] 1. Wave 1 — layout.tsx：汉堡菜单 + Sheet 导航抽屉

  **What to do**:
  1. 阅读 `src/apps/portal/app/layout.tsx` 当前 sidebar 实现（当前为固定 232px/56px 的 flex 侧栏）
  2. 移除现有 `<aside>` 侧边栏，替换为：
     - Header 左上角：`<SheetTrigger>` 汉堡按钮 `<Button variant="ghost" size="icon"><Menu /></Button>`，`data-testid="hamburger-button"`
     - `<SheetContent side="left">` 内包含：导航链接（4 个路由）+ `<RoleSwitcher>` + 版本号 "医保AI导办平台 v0.1"
     - 导航链接用当前 `NAV_SECTIONS` 或等效列表，每个 item 用 `<Link>` 或 router.push
  3. Header 布局调整：`[汉堡按钮] [品牌标识] [spacer] [ConnectionBadge]`
  4. 保留 `ConnectionBadge` 在 header 中（不放进抽屉）
  5. 保留 `RoleSwitcher` 但从 header 移到 Sheet 抽屉内
  6. 保留现有的 `transition-all duration-300` 但只作用于汉堡按钮/header
  7. 确保 `main` 区域的 `<main className="flex-1 overflow-auto p-6">` 不变（不影响其他页面）

  **Must NOT do**:
  - 不修改 admin 或 embed 应用的 layout
  - 不改变 `main p-6` 样式（影响所有路由的共享布局）
  - 不删除现有的 NAV_SECTIONS 数据定义

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 涉及根布局组件，影响所有路由，需要仔细处理导航和角色切换的交互
  - **Skills**: [`frontend-design`]
    - `frontend-design`: 需要汉堡菜单的视觉实现和动画过渡

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (Task 1 → Task 2)
  - **Blocks**: Tasks 3-6
  - **Blocked By**: None

  **References**:
  - `src/apps/portal/app/layout.tsx` — 当前 sidebar + header 实现
  - `src/apps/portal/src/components/role-switcher.tsx` — RoleSwitcher 组件
  - `src/apps/portal/src/components/ui/sheet.tsx` — shadcn Sheet 组件（确认存在）
  - `lucide-react` 中 `Menu` 图标用于汉堡按钮

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: 汉堡按钮可见且可点击
    Tool: Playwright
    Steps:
      1. 导航到 http://localhost:3000
      2. 断言: page.getByTestId('hamburger-button').isVisible()
      3. 点击汉堡按钮
      4. 断言: 抽屉可见，含导航链接
    Expected Result: 汉堡按钮可点击，抽屉展开
    Evidence: .sisyphus/evidence/task-1-hamburger-open.png

  Scenario: 导航抽屉内容完整
    Tool: Playwright
    Steps:
      1. 点击汉堡按钮
      2. 断言: 抽屉中含 "对话导办", "结算异常", "出院前质控", "运营看板"
      3. 断言: 抽屉中含角色切换器
      4. 断言: 抽屉中含 "医保AI导办平台 v0.1"
    Expected Result: 所有导航项和版本号存在
    Evidence: .sisyphus/evidence/task-1-drawer-content.png
  ```

  **Commit**: YES
  - Message: `refactor(portal): sidebar改为汉堡菜单Sheet抽屉导航`
  - Files: `src/apps/portal/app/layout.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 2. Wave 1 — page.tsx：移除 max-w-5xl 约束

  **What to do**:
  1. 阅读 `src/apps/portal/app/page.tsx`，找到 `max-w-5xl` 约束
  2. 将 `className="mx-auto max-w-5xl"` 改为 `className="w-full"` 或移除容器 div
  3. 确保 SettlementChat 可以全宽渲染
  4. 验证其他路由页面（/settlement, /qc, /dashboard）不受影响（它们有自己的 page.tsx）

  **Must NOT do**:
  - 不修改 settlement/、qc/、dashboard/ 的 page.tsx
  - 不修改 layout.tsx 的 main 标签

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 一行 CSS 类名修改，无逻辑变化

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (Task 1 → Task 2)
  - **Blocks**: Tasks 3-6
  - **Blocked By**: Task 1

  **References**:
  - `src/apps/portal/app/page.tsx` — 聊天页面的路由组件

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: 聊天区全宽无约束
    Tool: Playwright
    Steps:
      1. 导航到 http://localhost:3000
      2. 执行: page.evaluate(() => { const main = document.querySelector('main'); return getComputedStyle(main).maxWidth; })
    Expected Result: maxWidth 为 'none' 或 >= 视口宽度，不限制在 1024px
    Evidence: .sisyphus/evidence/task-2-full-width.png
  ```

  **Commit**: YES
  - Message: `fix(portal): 移除page.tsx的max-w-5xl约束支持全宽聊天`
  - Files: `src/apps/portal/app/page.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 3. Wave 2 — settlement-chat.tsx：聊天区全宽

  **What to do**:
  1. 移除整个左侧快捷提问面板（当前 `lg:col-span-1` 的 Card，含快捷提问按钮和角色视图）
  2. 将外层 grid 从 `grid grid-cols-1 lg:grid-cols-4` 改为单列全宽 `flex flex-col`
  3. 移除右侧执行步骤 `aside` 面板（当前 `hidden xl:flex min-h-0 flex-col bg-slate-900/60`）
  4. 移除 CardContent 内部的 `grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]`，改为 `flex flex-col`
  5. ChatMessageList 和 ChatInput 保持上下排列
  6. 执行步骤区域替换为 `<ExecutionDrawer steps={steps} isStreaming={isStreaming} />`
  7. 保留高风险确认 Dialog
  8. 确保 `data-testid="chat-grid"` 改为 `data-testid="chat-container"`

  **Must NOT do**:
  - 不修改 ChatMessageList、ChatInput、IntentTraceCard 组件
  - 不删除 `quickQuestions` 或 `intentIdToLabel` 等数据/函数（Task 4 会用到 quickQuestions）

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 大幅调整组件布局结构，需要视觉验证
  - **Skills**: [`frontend-design`]
    - `frontend-design`: 布局重构需要审美判断

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (与 Tasks 4-5 并行)
  - **Blocks**: Task 6
  - **Blocked By**: Tasks 1, 2

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx` — 完整当前布局
  - `src/apps/portal/src/components/chat/execution-drawer.tsx` — 待创建（Task 6），先留导入位

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: 聊天区全宽无左右面板
    Tool: Playwright
    Steps:
      1. 导航到 http://localhost:3000
      2. 断言: 无左侧快捷提问面板（page.getByText('快捷提问').not.toBeVisible()）
      3. 断言: 无右侧执行步骤侧栏（page.getByText('执行步骤').文本不在 aside 中）
      4. 断言: chat-container 全宽
    Expected Result: 仅聊天消息区 + 输入框可见
    Evidence: .sisyphus/evidence/task-3-full-chat.png
  ```

  **Commit**: YES
  - Message: `refactor(portal): 聊天区全宽—移除快捷提问面板和执行步骤侧栏`
  - Files: `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 4. Wave 2 — chat-input.tsx：添加 suggestion chips

  **What to do**:
  1. 在 `chat-input.tsx` 中，在 textarea 上方添加横向排列的 suggestion chips：
     ```tsx
     <div className="flex gap-2 mb-2 overflow-x-auto" data-testid="suggestion-chips">
       {suggestions.map((q, i) => (
         <button key={i} onClick={() => onSend(q)} className="shrink-0 px-3 py-1.5 text-xs rounded-full border ...">
           {q}
         </button>
       ))}
     </div>
     ```
  2. 添加 `suggestions: string[]` prop（从 settlement-chat 传入 `quickQuestions`）
  3. 当 `disabled`（isLoading）时，chips 也 disabled 并降低透明度
  4. 流式传输期间 chips 仍可见但不可点击
  5. 使用紧凑样式（border-slate-200, hover:bg-blue-50, text-slate-600）

  **Must NOT do**:
  - 不删除 settlement-chat.tsx 中 quickQuestions 的定义
  - 不修改 textarea 的发送逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 添加简单的 chips UI，约 15 行代码

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (与 Tasks 3, 5 并行)
  - **Blocks**: None
  - **Blocked By**: Tasks 1, 2

  **References**:
  - `src/apps/portal/src/components/chat/chat-input.tsx` — 当前 ChatInput 组件
  - `src/apps/portal/src/components/settlement-chat.tsx:260-263` — quickQuestions 数组

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: Suggestion chips 可见且可点击
    Tool: Playwright
    Steps:
      1. 导航到 http://localhost:3000
      2. 断言: page.getByTestId('suggestion-chips').isVisible()
      3. 点击第一个 chip
      4. 断言: 消息已发送（用户消息出现在聊天中）
    Expected Result: 点击 chip 发送对应问题
    Evidence: .sisyphus/evidence/task-4-chips-click.png
  ```

  **Commit**: YES
  - Message: `feat(portal): chat-input上方添加suggestion chips替代快捷提问`
  - Files: `src/apps/portal/src/components/chat/chat-input.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 5. Wave 2 — message-list.tsx：状态栏条件渲染

  **What to do**:
  1. 将意图状态栏（当前 `grid-cols-3` 的 div，行 69-87）包装为条件渲染：
     ```tsx
     {intentTrace && (
       <div className="mb-3 grid grid-cols-3 gap-3" data-testid="intent-stats-bar">
         {/* 当前意图/置信度/路由状态 */}
       </div>
     )}
     ```
  2. 当 `intentTrace === null` 时，状态栏不渲染（页面初始状态更干净）
  3. 注意：第 89-93 行的 `IntentTraceCard` 已有 `intentTrace &&` 条件，保持不变

  **Must NOT do**:
  - 不删除状态栏内容（grid-cols-3 的三列）
  - 不修改 IntentTraceCard 渲染逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 仅添加一个 `{intentTrace && (` 条件包裹

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (与 Tasks 3-4 并行)
  - **Blocks**: None
  - **Blocked By**: Tasks 1, 2

  **References**:
  - `src/apps/portal/src/components/chat/message-list.tsx:69-87` — 意图状态栏

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: 初始无意图时状态栏不显示
    Tool: Playwright
    Steps:
      1. 导航到 http://localhost:3000 (刷新)
      2. 断言: page.getByTestId('intent-stats-bar').toBeNull()
    Expected Result: 初始页面干净，无状态栏
    Evidence: .sisyphus/evidence/task-5-no-stats-initial.png

  Scenario: 有意图数据后状态栏显示
    Tool: Playwright
    Steps:
      1. 发送一条消息
      2. 等待意图识别完成
      3. 断言: page.getByTestId('intent-stats-bar').isVisible()
    Expected Result: 状态栏在有意图数据后出现
    Evidence: .sisyphus/evidence/task-5-stats-visible.png
  ```

  **Commit**: YES
  - Message: `refactor(portal): 意图状态栏条件渲染—仅在有意图数据时显示`
  - Files: `src/apps/portal/src/components/chat/message-list.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 6. Wave 3 — execution-drawer.tsx：浮动执行步骤抽屉

  **What to do**:
  1. 创建 `src/apps/portal/src/components/chat/execution-drawer.tsx`
  2. 组件结构：
     ```tsx
     <Sheet>
       <SheetTrigger asChild>
         <Button className="fixed bottom-6 right-6 z-50 rounded-full shadow-lg" data-testid="execution-fab">
           <Activity className="w-5 h-5" />
           {isStreaming && steps.length > 0 && (
             <span className="absolute -top-1 -right-1 flex h-4 w-4" data-testid="execution-fab-badge">
               <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
               <span className="relative inline-flex rounded-full h-4 w-4 bg-cyan-500 text-[10px] text-white items-center justify-center">
                 {steps.length}
               </span>
             </span>
           )}
         </Button>
       </SheetTrigger>
       <SheetContent side="right" className="w-[380px]" data-testid="execution-drawer">
         <SheetHeader>
           <SheetTitle>执行步骤</SheetTitle>
         </SheetHeader>
         <ExecutionTimeline steps={steps} />
       </SheetContent>
     </Sheet>
     ```
  3. Props: `steps: StreamStepDisplay[]`, `isStreaming: boolean`
  4. FAB 固定在右下角 (`fixed bottom-6 right-6 z-50`)
  5. 使用 `lucide-react` 的 `Activity` 图标
  6. Sheet 使用 `side="right"`，宽度 380px
  7. FAB 徽章在 `isStreaming && steps.length > 0` 时显示动画脉冲点 + 步骤数
  8. 在 `settlement-chat.tsx` 中替换 `aside` 为 `<ExecutionDrawer>`

  **Must NOT do**:
  - 不修改 ExecutionTimeline 组件内部逻辑
  - 不改变 ExecutionTimeline 的 props 接口

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 浮动按钮 + 抽屉是视觉新组件，需要 FAB 样式和动画
  - **Skills**: [`frontend-design`]
    - `frontend-design`: FAB 按钮样式和徽章动画

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 8
  - **Blocked By**: Task 3

  **References**:
  - `src/apps/portal/src/components/chat/execution-timeline.tsx` — 被包装的组件
  - `src/apps/portal/src/components/ui/sheet.tsx` — shadcn Sheet
  - `lucide-react` 中 `Activity` 图标

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: FAB 可见且固定在右下角
    Tool: Playwright
    Steps:
      1. 导航到 http://localhost:3000
      2. 断言: page.getByTestId('execution-fab').isVisible()
      3. 验证: FAB 位置在视口右下角
    Expected Result: FAB 按钮可见
    Evidence: .sisyphus/evidence/task-6-fab-visible.png

  Scenario: 流式传输中 FAB 显示活动徽章
    Tool: Playwright
    Steps:
      1. 发送一条消息触发流式响应
      2. 在流式进行中，断言: page.getByTestId('execution-fab-badge').isVisible()
    Expected Result: FAB 徽章显示步骤数
    Evidence: .sisyphus/evidence/task-6-fab-badge.png

  Scenario: 点击 FAB 打开执行步骤抽屉
    Tool: Playwright
    Steps:
      1. 点击 FAB 按钮
      2. 断言: page.getByTestId('execution-drawer').isVisible()
      3. 断言: 抽屉中含执行步骤列表
    Expected Result: 抽屉展开显示 ExecutionTimeline
    Evidence: .sisyphus/evidence/task-6-drawer-open.png
  ```

  **Commit**: YES
  - Message: `feat(portal): 新增浮动执行步骤抽屉组件`
  - Files: `src/apps/portal/src/components/chat/execution-drawer.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 7. Wave 4 — 更新原型设计文档

  **What to do**:
  1. 更新 `docs/steering/原型设计文档.md` 以下章节：
     - **§1.1 系统概览**：Sidebar 描述改为"可折叠汉堡菜单（Sheet 抽屉）"，Header 包含汉堡按钮 + ConnectionBadge + 品牌标识
     - **§2.1 布局规范**：更新侧边栏约束为"汉堡菜单按钮 40×40px，抽屉 280px 宽"；内容区改为"全宽，无 max-w 约束"
     - **§3.1 组件树**：在 SettlementChat 下移除 QuickQuestions，添加 ExecutionDrawer；Sidebar 改为 HamburgerDrawer
     - **§3.2.1 SettlementChat**：更新描述为"单栏全宽布局，聊天区 + 输入框 + 浮动执行步骤抽屉"
     - 版本号：2.0 → 3.0
  2. 添加变更说明到附录 B

  **Must NOT do**:
  - 不修改其他章节（CRUD 规范、验收标准、数据库映射等）
  - 不删除现有内容，只做增量更新

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 文档更新，纯文字工作

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (与 Task 8 并行)
  - **Blocks**: None
  - **Blocked By**: Task 3

  **References**:
  - `docs/steering/原型设计文档.md` — 当前版本 v2.0

  **Commit**: YES
  - Message: `docs: 更新原型设计文档—聊天页面v3专注聊天布局`
  - Files: `docs/steering/原型设计文档.md`

- [ ] 8. Wave 4 — Playwright E2E 验证

  **What to do**:
  1. 启动 portal dev server (`cd src/apps/portal && npm run dev`)
  2. 使用 Playwright 执行全功能验证：
     - 汉堡菜单打开 → 导航链接可见 → 角色切换器在工作
     - Suggestion chips 点击发送消息
     - 聊天全流程：发送 → 意图识别 → 消息返回 → 微调器停止
     - 执行 FAB 可见 → 流式传输时徽章显示 → 点击展开抽屉
     - 预填消息流：从 /settlement 跳转携带消息
     - 高风险确认 Dialog 仍正常工作
  3. 截图保存到 `.sisyphus/evidence/final-v3/`
  4. 验证所有 data-testid 保留

  **Must NOT do**:
  - 不修改 E2E 测试代码（仅执行验证）

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 需要 Playwright 进行端到端 UI 验证
  - **Skills**: [`playwright-cli`]
    - `playwright-cli`: 浏览器自动化和截图

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (与 Task 7 并行)
  - **Blocks**: None
  - **Blocked By**: Task 6

  **Acceptance Criteria**:

  **QA Scenarios**:
  ```
  Scenario: 全功能端到端验证
    Tool: Bash + Playwright
    Steps:
      1. 确保 dev server 运行
      2. npm run build 通过
      3. Playwright 手动测试全部场景
    Expected Result: 所有 UI 功能正常
    Evidence: .sisyphus/evidence/final-v3/*.png
  ```

  **Commit**: NO（验证任务，不产生代码提交）

---

## Final Verification Wave

- [ ] F1. **npm run build** — 编译零错误
- [ ] F2. **npm run lint** — 重构文件 0 errors
- [ ] F3. **Playwright 全功能验证** — 汉堡菜单、suggestion chips、执行抽屉、聊天全流程
- [ ] F4. **原型文档一致性** — 代码改动与文档描述一致

---

## Commit Strategy

- **1**: `refactor(portal): sidebar改为汉堡菜单Sheet抽屉导航` — layout.tsx
- **2**: `fix(portal): 移除page.tsx的max-w-5xl约束支持全宽聊天` — page.tsx
- **3**: `refactor(portal): 聊天区全宽—移除快捷提问面板和执行步骤侧栏` — settlement-chat.tsx
- **4**: `feat(portal): chat-input上方添加suggestion chips替代快捷提问` — chat-input.tsx
- **5**: `refactor(portal): 意图状态栏条件渲染—仅在有意图数据时显示` — message-list.tsx
- **6**: `feat(portal): 新增浮动执行步骤抽屉组件` — execution-drawer.tsx
- **7**: `docs: 更新原型设计文档—聊天页面v3专注聊天布局` — 原型设计文档.md

---

## Success Criteria

### Verification Commands
```bash
cd src/apps/portal && npm run build   # Expected: exit 0
cd src/apps/portal && npm run lint     # Expected: 0 errors in refactored files
```

### Final Checklist
- [ ] 汉堡菜单打开/关闭流畅
- [ ] 聊天区全宽无空白
- [ ] Suggestion chips 点击发送正常
- [ ] 执行步骤浮动按钮 + 抽屉正常
- [ ] 意图状态栏条件渲染正确
- [ ] 预填消息流正常
- [ ] 所有 data-testid 保留
- [ ] 构建无错误
