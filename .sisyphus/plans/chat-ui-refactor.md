# 聊天界面UI修复与组件重构

## TL;DR

> **快速总结**: 修复门户聊天页面3个UI Bug（留白过多、不自动滚动、微调器卡死），紧凑化UI布局，从920行单体组件拆分为标准模块，并搭建前端单元测试基础设施。
>
> **交付成果**:
> - 3个Bug修复（安全超时、viewport滚动、高度计算修正）
> - 4个新组件（ChatMessageList、ChatInput、StreamingBubble、chat/helpers.ts）
> - 紧凑极简UI风格（减少多余padding/间距）
> - vitest + React Testing Library测试基础设施
> - 增强的Playwright E2E测试（data-testid选择器 + 新增场景）
>
> **预估工作量**: Large
> **并行执行**: YES — 5个并行波次
> **关键路径**: Bug修复 → UI紧凑化 → 测试基础 → 组件提取 → 测试编写 → 最终验证

---

## Context

### 原始需求
用户反馈门户聊天页面存在三个UI问题：
1. **留白太多** — 聊天区域底部有大量空白
2. **对话框不自动滚动** — 新消息到来时未自动滚动到底部
3. **医保结算异常导办旁边的圈一直转** — 微调器在流式传输结束后不停止

用户选择：**标准拆分重构 + vitest+RTL单元测试 + Playwright E2E增强 + 紧凑极简风格**

### 访谈总结
**关键讨论**:
- 组件拆分粒度: 标准拆分（ChatMessageList、ChatInput、StreamingBubble + 已有IntentTraceCard/ExecutionTimeline）
- 测试策略: 两者都做（从零搭建vitest + 增强已有Playwright E2E套件）
- UI方向: 紧凑极简，减少不必要的padding和空白
- 重构范围: 不改变IntentTraceCard和ExecutionTimeline

**研究发现**:
- `settlement-chat.tsx` (920行) — 核心单体聊天组件，包含消息渲染、输入区域、SSE流处理
- `h-[calc(100vh-200px)]` 行569 — 实际可用高度~112px，减去200px导致~96px多余空白
- `scrollIntoView` + `@base-ui/react` ScrollArea — scrollIntoView无法正确滚动ScrollArea内部视口
- `isStreaming` 重置仅依赖 `sseStatus === 'closed'` — 但后端可能不发送`done`事件
- 门户 `package.json` — 零测试依赖，无vitest/jest/testing-library
- Playwright E2E套件 — 存在于 `src/tests/e2e/`，但使用脆弱CSS选择器（`[class*="streaming"]`）

### Metis审查
**识别的缺口** (已处理):
- 重构与Bug修复的顺序: **先修Bug，再紧凑化，再重构，最后测试** — 原子提交保证可追溯
- Bug 3严重性被低估: 后端不发`done`时微调器永久旋转 — **添加30秒安全超时**
- E2E选择器脆弱性: CSS类名在重构后会变化 — **添加data-testid属性，更新页面对象**
- UI紧凑化主观性: 需要具体CSS值 — **明确定义padding/间距/高度变化**
- `@base-ui/react` ScrollArea API未确认: 需查阅文档 — **作为任务前置研究步骤**
- 辅助函数提取范围: `extractContent`等200行辅助代码 — **包含进chat/helpers.ts提取**
- 测试基础设施兼容性: vitest + Next.js 16 + React 19 — **安装前验证兼容性**
- 布局变更影响范围: `main p-6`被所有路由共享 — **仅针对聊天页面修改变量，其他页面保持不动**

---

## Work Objectives

### 核心目标
修复门户聊天页面的3个UI Bug，紧凑化UI布局，从920行单体组件拆分为可维护的标准模块，并建立前端测试体系。

### 具体交付成果
- `src/apps/portal/src/components/settlement-chat.tsx` — 瘦身后的主聊天组件（<300行）
- `src/apps/portal/src/components/chat/message-list.tsx` — 消息列表 + 自动滚动
- `src/apps/portal/src/components/chat/chat-input.tsx` — 输入区域 + 发送按钮
- `src/apps/portal/src/components/chat/streaming-bubble.tsx` — 流式传输气泡
- `src/apps/portal/src/components/chat/helpers.ts` — 提取的辅助函数
- `src/apps/portal/vitest.config.ts` — vitest配置
- `src/apps/portal/src/tests/setup.ts` — 测试环境设置
- `src/apps/portal/src/tests/components/` — 3个组件测试文件
- `src/tests/e2e/pages/portal/chat.page.ts` — 更新后的页面对象（data-testid选择器）
- `src/tests/e2e/flows/portal/chat-ux.flow.ts` — 新增UX验证流程

### 完成标准
- [ ] 3个Bug全部修复且可验证
- [ ] UI紧凑化完成，无明显多余空白
- [ ] 4个新组件成功提取，功能完全等价
- [ ] `npm run build` 无错误通过
- [ ] `npm run lint` 无错误通过
- [ ] vitest组件测试: 3个测试文件全部PASS
- [ ] Playwright E2E: 所有portal流程测试PASS
- [ ] 构建后的页面在浏览器中功能正常

### 必须做
- 修复Bug时保持原子提交（一个Bug一个commit）
- 重构期间保持功能完全等价
- 添加data-testid属性替换脆弱的CSS选择器
- Bug 3添加30秒安全超时
- 辅助函数提取到chat/helpers.ts

### 必须不做（防护栏）
- **不**改变IntentTraceCard或ExecutionTimeline组件
- **不**在一次commit中混合Bug修复和重构
- **不**添加新状态管理库（zustand/redux等）
- **不**改变CSS类名（除非是紧凑化有意为之）
- **不**修改共享布局影响其他页面（/settlement、/qc、/dashboard）
- **不**为辅助函数添加JSDoc注释（这不是文档项目）
- **不**在vitest设置未验证兼容性前直接安装

---

## Verification Strategy

> **零人工干预** — 所有验证均由代理执行。无例外。

### 测试决策
- **基础设施存在**: 后端pytest YES，前端单元 NO，前端E2E YES
- **自动化测试**: 两者都做（vitest组件测试 + Playwright E2E）
- **框架**: vitest + @testing-library/react（组件），Playwright（E2E）
- **TDD**: NO — 先修Bug和重构，再补测试（确保现有功能不退化）

### QA策略
每个任务包含代理执行的QA场景。
证据保存至 `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`。

- **前端/UI**: 使用Playwright — 导航、交互、断言DOM、截图
- **构建/测试**: 使用Bash — 运行npm命令，验证退出码和输出

---

## Execution Strategy

### 并行执行波次

> 每组内任务最大化并行，组间串行保障依赖。

```
Wave 1 (Bug修复 — 同文件串行):
├── Task 1: Bug 3 修复 — 微调器永不停止 [deep]
├── Task 2: Bug 2 修复 — 自动滚动失效 [deep]
└── Task 3: Bug 1 修复 — 留白过多 [quick]

Wave 2 (UI紧凑化 + 测试基础 — 并行):
├── Task 4: UI紧凑化 — 减少padding/间距 [visual-engineering]
└── Task 5: vitest + React Testing Library安装配置 [quick]

Wave 3 (E2E增强 — 并行):
├── Task 6: 添加data-testid + 修复E2E页面对象 [quick]
├── Task 7: 新增Playwright E2E — 自动滚动验证 [visual-engineering]
└── Task 8: 新增Playwright E2E — 微调器完成验证 [visual-engineering]

Wave 4 (组件提取 — 最大并行):
├── Task 9: 提取 ChatMessageList 组件 [deep]
├── Task 10: 提取 ChatInput 组件 [quick]
├── Task 11: 提取 StreamingBubble 组件 [quick]
└── Task 12: 提取 chat/helpers.ts 辅助函数 [quick]

Wave 5 (组件测试 — 并行):
├── Task 13: vitest — ChatMessageList 测试 [deep]
├── Task 14: vitest — ChatInput 测试 [quick]
└── Task 15: vitest — StreamingBubble 测试 [quick]

Wave FINAL (全部完成后 — 4个并行审查):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
→ 呈现结果 → 等待用户明确确认

关键路径: Task 1 → Task 3 → Task 9 → Task 13 → Task F1-F4 → 用户确认
并行加速: 相比串行~65%更快
最大并发: 4 (Wave 4)
```

### 依赖矩阵

- **1-3**: - - 4-12, 1 (串行)
- **4**: 3 - 9-12, 2
- **5**: - - 13-15, 2
- **6-8**: 3 - - , 3
- **9**: 3, 4 - 13, 4
- **10**: 3, 4 - 14, 4
- **11**: 3, 4 - 15, 4
- **12**: 3 - 9-11, 4
- **13**: 5, 9 - F1-F4, 5
- **14**: 5, 10 - F1-F4, 5
- **15**: 5, 11 - F1-F4, 5
- **F1-F4**: 6-8, 13-15 - - , FINAL

### 代理调度摘要

- **Wave 1**: 3 — T1→deep, T2→deep, T3→quick
- **Wave 2**: 2 — T4→visual-engineering, T5→quick
- **Wave 3**: 3 — T6→quick, T7→visual-engineering, T8→visual-engineering
- **Wave 4**: 4 — T9→deep, T10→quick, T11→quick, T12→quick
- **Wave 5**: 3 — T13→deep, T14→quick, T15→quick
- **Wave FINAL**: 4 — F1→oracle, F2→unspecified-high, F3→unspecified-high, F4→deep

---

## TODOs

- [x] 1. Wave 1 — Bug 3修复：微调器永不停止（安全超时 + 缺失done事件处理）

  **What to do**:
  1. 阅读 `settlement-chat.tsx` 第502-509行的 `useEffect` — 理解isStreaming重置逻辑仅依赖 `sseStatus === 'closed'` 的缺陷
  2. 阅读 `sse-hooks.ts` 第461-463行 — 确认 `done` 事件处理调用 `updateStatus('closed')`
  3. 在第502行 `useEffect` 中增加**30秒安全超时**：如 `streamEnabled` 为true超过30秒且 `sseStatus` 未变为 `closed` 或 `error`，强制执行 `setIsLoading(false); setIsStreaming(false); setStreamEnabled(false)`
  4. 在 `handleSseEvent` 回调（`useChatStream` 中）的 `done` case 增加日志确认 `updateStatus('closed')` 被调用
  5. 在 `useChatStream` 的异步流处理 finally 块中增加兜底：如果流结束但状态不是 `closed` 或 `error`，强制调用 `updateStatus('closed')`
  6. 运行 `cd src/apps/portal && npm run build` 确认无编译错误

  **Must NOT do**:
  - 不改变IntentTraceCard中的Loader2渲染逻辑（该组件不在修改范围内）
  - 不修改 `useSSEConnection` hook（`useChatStream` 不使用它）
  - 不使用 `setTimeout` 在渲染期间（使用 `useRef` + `useEffect` 的定时器模式）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要深入理解SSE流的状态机、React hooks闭包陷阱和异步状态管理
  - **Skills**: [`systematic-debugging`]
    - `systematic-debugging`: 需要追踪SSE事件流 → React状态更新 → useEffect依赖的完整链路

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (串行，Tasks 1→2→3 修改同一文件)
  - **Blocks**: Tasks 4-12（后续所有任务依赖Bug修复完成）
  - **Blocked By**: None（可立即开始）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:337` — `isStreaming` 状态定义
  - `src/apps/portal/src/components/settlement-chat.tsx:502-509` — 当前仅依赖sseStatus的重置逻辑
  - `src/apps/portal/src/lib/sse-hooks.ts:282-540` — `useChatStream` hook完整实现
  - `src/apps/portal/src/lib/sse-hooks.ts:461-463` — `done` 事件处理：`updateStatus('closed')`
  - `src/apps/portal/src/lib/sse-hooks.ts:343-348` — `cancel()` 函数也调用 `updateStatus('closed')`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 正常流结束 — done事件到达，微调器应停止
    Tool: Playwright
    Preconditions: 后端可正常响应，发送完整SSE事件流含done
    Steps:
      1. 导航到 http://localhost:3000
      2. 在输入框 `.chat-input` 输入 "测试消息"
      3. 点击发送按钮 `[data-testid="send-button"]`
      4. 等待流式传输完成（最多60秒）: page.waitForSelector('[data-testid="streaming-indicator"]', { state: 'hidden', timeout: 60000 })
      5. 断言微调器不可见: expect(page.locator('[data-testid="loader-icon"]')).not.toBeVisible()
    Expected Result: 微调器在正常done事件后消失
    Failure Indicators: 60秒后微调器仍可见
    Evidence: .sisyphus/evidence/task-1-spinner-normal.png

  Scenario: 异常流结束 — 后端不发done直接关闭连接，微调器应在30秒内停止
    Tool: Playwright
    Preconditions: Mock模式或后端不发done事件直接关闭SSE连接
    Steps:
      1. 导航到 http://localhost:3000
      2. 发送一条消息触发SSE流
      3. 等待最多35秒: page.waitForSelector('[data-testid="streaming-indicator"]', { state: 'hidden', timeout: 35000 })
      4. 断言微调器不可见
      5. 检查输入框是否恢复可用: expect(page.locator('[data-testid="chat-input"]')).toBeEnabled()
    Expected Result: 微调器在最迟30秒内因安全超时而停止
    Failure Indicators: 35秒后微调器仍可见或输入框仍禁用
    Evidence: .sisyphus/evidence/task-1-spinner-timeout.png
  ```

  **Evidence to Capture**:
  - [ ] task-1-spinner-normal.png — 正常done事件后微调器消失的截图
  - [ ] task-1-spinner-timeout.png — 安全超时触发后微调器消失的截图

  **Commit**: YES
  - Message: `fix(portal): 微调器永久旋转 — 添加30s安全超时和缺失done事件兜底处理`
  - Files: `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 2. Wave 1 — Bug 2修复：自动滚动失效（使用ScrollArea视口ref替代scrollIntoView）

  **What to do**:
  1. 阅读 `@base-ui/react` ScrollArea 文档（需先 `npx context7` 或查看 `node_modules/@base-ui/react/scroll-area/`）— 确认是否暴露 `viewportRef` prop 或需用 `ref` 获取内部视口DOM
  2. 在 `settlement-chat.tsx` 中创建 `const viewportRef = useRef<HTMLDivElement>(null)`
  3. 找到ScrollArea内部的视口元素（当前封装在 `scroll-area.tsx` 中渲染 `<ScrollAreaPrimitive.Viewport>`），给该Viewport添加ref转发
  4. 修改滚动逻辑（当前第427-429行）：将 `scrollBottomRef.current?.scrollIntoView(...)` 替换为 `viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: 'smooth' })`
  5. 保持滚动哨兵div（`scrollBottomRef`）作为布局辅助但不用于滚动
  6. 如果ScrollArea不支持ref转发，考虑用 `document.querySelector` 直接查询视口元素，或移除ScrollArea改用简单 `overflow-y-auto` div
  7. 运行构建验证

  **Must NOT do**:
  - 不移除ScrollArea组件（如果其API支持滚动）
  - 不使用 `window.scrollTo` 或滚动外层容器
  - 不改变消息列表的渲染结构

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要查阅第三方库API文档，理解DOM结构，选择最合适的滚动方案
  - **Skills**: [`systematic-debugging`]
    - `systematic-debugging`: 需要排查为什么scrollIntoView不工作，测试多种替代方案

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (串行，Task 1 → Task 2)
  - **Blocks**: Tasks 6-8（E2E测试依赖滚动修复）, Task 9（ChatMessageList提取依赖滚动逻辑）
  - **Blocked By**: Task 1（同一文件，需串行）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:344` — `scrollBottomRef` 定义
  - `src/apps/portal/src/components/settlement-chat.tsx:427-429` — 当前滚动逻辑：`scrollIntoView`
  - `src/apps/portal/src/components/settlement-chat.tsx:664` — ScrollArea包裹消息列表
  - `src/apps/portal/src/components/settlement-chat.tsx:801` — 滚动哨兵div
  - `src/apps/portal/src/components/ui/scroll-area.tsx` — ScrollArea封装组件
  - `@base-ui/react/scroll-area` 文档 — 查看视口ref API：https://base-ui.com/react/components/scroll-area

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 新消息到来时自动滚动到底部
    Tool: Playwright
    Preconditions: 消息列表足够长，超过视口高度
    Steps:
      1. 导航到 http://localhost:3000
      2. 发送多条消息使列表超过视口
      3. 手动滚动到顶部
      4. 发送一条新消息触发自动滚动
      5. 等待流式完成: page.waitForSelector('[data-testid="streaming-indicator"]', { state: 'hidden' })
      6. 执行滚动位置检查: page.evaluate(() => { const vp = document.querySelector('[data-testid="chat-viewport"]'); return vp.scrollTop + vp.clientHeight >= vp.scrollHeight - 50; })
    Expected Result: 返回值 true，视口已滚动到底部50px以内
    Failure Indicators: 返回 false，视口不在底部
    Evidence: .sisyphus/evidence/task-2-scroll-bottom.png

  Scenario: 流式传输过程中持续跟随滚动
    Tool: Playwright
    Preconditions: SSE流正在输出内容
    Steps:
      1. 导航到 http://localhost:3000
      2. 发送消息触发长流式响应
      3. 在流式传输进行中等待3秒
      4. 检查滚动位置: page.evaluate(() => { const vp = document.querySelector('[data-testid="chat-viewport"]'); return vp.scrollTop + vp.clientHeight >= vp.scrollHeight - 100; })
    Expected Result: 流式传输中视口保持在底部
    Failure Indicators: 内容增长但视口未跟随
    Evidence: .sisyphus/evidence/task-2-scroll-streaming.png
  ```

  **Evidence to Capture**:
  - [ ] task-2-scroll-bottom.png — 新消息后的底部滚动截图
  - [ ] task-2-scroll-streaming.png — 流式传输中持续跟随的截图

  **Commit**: YES
  - Message: `fix(portal): 自动滚动失效 — 使用ScrollArea视口ref的scrollTo替代scrollIntoView`
  - Files: `src/apps/portal/src/components/settlement-chat.tsx`, `src/apps/portal/src/components/ui/scroll-area.tsx`（如需修改）
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 3. Wave 1 — Bug 1修复：留白过多（修正高度计算，减少多余空白）

  **What to do**:
  1. 测量实际可用高度：header `h-14`=56px, main `p-6`=48px(上下), 内部card padding约20px, 总计约~124px
  2. 将 `settlement-chat.tsx` 第569行 `h-[calc(100vh-200px)]` 改为 `h-[calc(100vh-7.75rem)]`（7.75rem=124px）或使用更精确的计算
  3. 推荐使用 `min-h-0 flex-1` 让flexbox自动填充可用空间，替代固定calc
  4. 检查并减小消息列表内部的多余padding：ScrollArea的 `px-6 pt-5 pb-3` 可改为 `px-4 pt-3 pb-2`
  5. 检查Card组件的padding：CardHeader的 `py-4 px-5` 可改为 `py-3 px-4`
  6. 确保修改不影响其他使用相同组件的页面
  7. 运行 `npm run build` 确认无编译错误

  **Must NOT do**:
  - 不修改 `src/apps/portal/app/layout.tsx` 中的 `main p-6`（影响所有路由）
  - 不改变字体大小或颜色
  - 不修改grid布局结构

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 精确的CSS值修改，逻辑简单，主要是调整数值

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (串行，Task 2 → Task 3)
  - **Blocks**: Task 4（UI紧凑化在此基础上进一步调整）
  - **Blocked By**: Task 2（同一文件，需串行）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:569` — `h-[calc(100vh-200px)]` 需要修改
  - `src/apps/portal/src/components/settlement-chat.tsx:664` — ScrollArea内padding
  - `src/apps/portal/src/components/settlement-chat.tsx:611` — Card组件使用
  - `src/apps/portal/app/layout.tsx:160` — header `h-14`
  - `src/apps/portal/app/layout.tsx:176` — main `p-6`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 聊天区域高度使用可用空间，无明显底部空白
    Tool: Playwright
    Preconditions: 视口高度 ~900px
    Steps:
      1. 导航到 http://localhost:3000
      2. 等待页面加载完成: page.waitForSelector('[data-testid="chat-grid"]')
      3. 执行高度测量: page.evaluate(() => { const grid = document.querySelector('[data-testid="chat-grid"]'); const main = document.querySelector('main'); return { gridBottom: grid.getBoundingClientRect().bottom, mainBottom: main.getBoundingClientRect().bottom }; })
    Expected Result: gridBottom 与 mainBottom 差距 ≤ 24px（即网格底部接近主区域底部）
    Failure Indicators: 差距 > 50px（仍有明显空白）
    Evidence: .sisyphus/evidence/task-3-whitespace-fixed.png
  ```

  **Evidence to Capture**:
  - [ ] task-3-whitespace-fixed.png — 修复后布局的全屏截图

  **Commit**: YES
  - Message: `fix(portal): 聊天区域留白过多 — 修正高度计算，使用flex-1自适应填充`
  - Files: `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 4. Wave 2 — UI紧凑化：减少全局padding和间距，实现紧凑极简风格

  **What to do**:
  1. 系统性地遍历 `settlement-chat.tsx` 中所有padding/margin值，按以下规则紧凑化：
     - CardHeader: `py-4 px-5` → `py-3 px-4`
     - ScrollArea内部: `px-6 pt-5 pb-3` → `px-4 pt-3 pb-2`
     - 消息间距: `space-y-5` → `space-y-3`
     - 输入区域: `p-4` → `p-3`
     - 统计栏（如有）: 减小 `p-4` → `p-3`, `gap-4` → `gap-3`
  2. 将消息气泡 `max-w-[80%]` 适当收紧为 `max-w-[75%]`
  3. 检查快捷问题区域的间距，减小 `gap-2` → `gap-1.5`
  4. 确保缩小后文本不截断、按钮可点击
  5. 运行 `npm run build` 确认无编译错误

  **Must NOT do**:
  - 不改变字体大小（保持 `text-sm`、`text-xs` 等不变）
  - 不改变颜色或设计系统
  - 不修改头像大小或形状
  - 不影响移动端响应式布局

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: CSS间距系统性调整，需要视觉判断力确保紧凑但不拥挤
  - **Skills**: [`frontend-design`]
    - `frontend-design`: 需要审美判断来平衡紧凑和可读性

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (与Task 5并行)
  - **Blocks**: Tasks 9-12（组件提取基于紧凑化后的代码）
  - **Blocked By**: Task 3

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx` — 全部padding/margin值
  - `src/apps/portal/src/components/ui/card.tsx` — Card组件padding默认值
  - `src/apps/portal/app/layout.tsx` — 全局布局（不做修改）

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 紧凑化后聊天界面功能正常，无截断或重叠
    Tool: Playwright
    Preconditions: 紧凑化CSS已应用
    Steps:
      1. 导航到 http://localhost:3000
      2. 截图全页面: page.screenshot({ fullPage: false })
      3. 检查输入框可见: expect(page.locator('[data-testid="chat-input"]')).toBeVisible()
      4. 检查发送按钮可点击: expect(page.locator('[data-testid="send-button"]')).toBeEnabled()
      5. 发送一条消息验证对话气泡正常显示
    Expected Result: 界面紧凑但不拥挤，所有交互元素正常
    Failure Indicators: 文本截断、按钮重叠、内容超出边界
    Evidence: .sisyphus/evidence/task-4-compact-ui.png
  ```

  **Evidence to Capture**:
  - [ ] task-4-compact-ui.png — 紧凑化后的页面截图

  **Commit**: YES
  - Message: `style(portal): 紧凑极简UI — 系统性减少全局padding和间距`
  - Files: `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 5. Wave 2 — 搭建vitest + React Testing Library测试基础设施

  **What to do**:
  1. 查阅 vitest + Next.js 16 + React 19 兼容性：使用 Context7 或查看 vitest 官方文档确认最新版本支持
  2. 在 `src/apps/portal/` 安装测试依赖：
     ```bash
     npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom @vitejs/plugin-react
     ```
  3. 创建 `src/apps/portal/vitest.config.ts`，配置：
     - `environment: 'jsdom'`
     - `include: ['src/tests/**/*.test.{ts,tsx}']`
     - `resolve.alias` 映射 `@/` → `src/`（与tsconfig一致）
     - `setupFiles: ['./src/tests/setup.ts']`
  4. 创建 `src/apps/portal/src/tests/setup.ts`，导入 `@testing-library/jest-dom` 的匹配器
  5. 在 `package.json` 添加 `"test": "vitest run"` 和 `"test:watch": "vitest"` 脚本
  6. 创建简单示例测试 `src/apps/portal/src/tests/example.test.tsx` 验证vitest能渲染React组件
  7. 运行 `npx vitest run` 确认示例测试通过
  8. 如遇Next.js模块解析问题（server components、image等），创建 `__mocks__` 目录mock这些模块

  **Must NOT do**:
  - 不安装jest或其他测试框架（只用vitest）
  - 不修改 `tsconfig.json` 中的编译目标或模块设置（除非必要）
  - 不创建复杂的mock系统（保持最小可行）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 标准化工具安装和配置，主要是npm install + 写配置文件

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (与Task 4并行)
  - **Blocks**: Tasks 13-15（vitest测试需要测试基础设施）
  - **Blocked By**: None（独立于Bug修复）

  **References**:
  - `src/apps/portal/package.json` — 当前依赖和脚本
  - `src/apps/portal/tsconfig.json` — path alias配置
  - vitest官方文档: https://vitest.dev/guide/
  - Next.js + vitest集成: Context7查询 `/vercel/next.js` 或 vitest文档

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: vitest能成功运行示例测试
    Tool: Bash
    Preconditions: 依赖已安装，config已创建
    Steps:
      1. cd src/apps/portal
      2. npx vitest run
    Expected Result: exit code 0，至少1个测试PASS
    Failure Indicators: 配置错误、模块未找到、兼容性错误
    Evidence: .sisyphus/evidence/task-5-vitest-running.txt
  ```

  **Evidence to Capture**:
  - [ ] task-5-vitest-running.txt — vitest运行输出

  **Commit**: YES
  - Message: `chore(portal): 搭建vitest + React Testing Library测试基础设施`
  - Files: `vitest.config.ts`, `src/tests/setup.ts`, `src/tests/example.test.tsx`, `package.json`
  - Pre-commit: `cd src/apps/portal && npx vitest run`

- [ ] 6. Wave 3 — 添加data-testid + 修复E2E页面对象选择器

  **What to do**:
  1. 在 `settlement-chat.tsx` 关键元素上添加 `data-testid` 属性：
     - 聊天网格容器: `data-testid="chat-grid"`
     - 消息列表视口: `data-testid="chat-viewport"`
     - 输入框: `data-testid="chat-input"`
     - 发送按钮: `data-testid="send-button"`
     - 流式指示器: `data-testid="streaming-indicator"`
     - 微调器图标: `data-testid="loader-icon"`
     - 消息气泡: `data-testid="message-bubble-{idx}"`
  2. 更新 `src/tests/e2e/pages/portal/chat.page.ts` 页面对象：
     - 将 `streamingIndicator: '[class*="streaming"], [class*="loading"]'` 替换为 `streamingIndicator: '[data-testid="streaming-indicator"]'`
     - 将 `responseArea: '[class*="response"], [class*="message"]'` 替换为 `responseArea: '[data-testid="chat-viewport"]'`
     - 添加新的定位器：`inputBox`, `sendButton`, `loaderIcon`
  3. 运行已有E2E测试确认未破坏: `cd src/tests/e2e && npx playwright test smoke/portal-smoke.spec.ts flows/portal/`
  4. 如有失败，调整data-testid位置或页面对象选择器

  **Must NOT do**:
  - 不在IntentTraceCard或ExecutionTimeline中添加data-testid（不在修改范围内）
  - 不删除任何现有CSS类（data-testid是增量的）
  - 不修改E2E测试的断言逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 添加HTML属性 + 更新定位器字符串，机械操作但需细心

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (与Tasks 7-8并行)
  - **Blocks**: None（独立任务）
  - **Blocked By**: Tasks 1-3（依赖Bug修复后的代码形态）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx` — 需要添加data-testid的元素
  - `src/tests/e2e/pages/portal/chat.page.ts` — 当前页面对象（含脆弱选择器）
  - `src/tests/e2e/smoke/portal-smoke.spec.ts` — 冒烟测试
  - `src/tests/e2e/flows/portal/` — 流程测试

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 更新后的E2E测试全部通过
    Tool: Bash
    Preconditions: data-testid已添加，页面对象已更新
    Steps:
      1. cd src/tests/e2e
      2. npx playwright test smoke/portal-smoke.spec.ts flows/portal/
    Expected Result: 所有测试PASS
    Failure Indicators: 任何测试FAIL
    Evidence: .sisyphus/evidence/task-6-e2e-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] task-6-e2e-pass.txt — E2E测试运行输出

  **Commit**: YES
  - Message: `test(portal): 添加data-testid并修复E2E页面对象选择器为稳定定位器`
  - Files: `settlement-chat.tsx`, `chat.page.ts`
  - Pre-commit: `cd src/tests/e2e && npx playwright test smoke/portal-smoke.spec.ts`

- [ ] 7. Wave 3 — 新增Playwright E2E测试：自动滚动行为验证

  **What to do**:
  1. 在 `src/tests/e2e/flows/portal/` 创建 `chat-ux.flow.ts` 测试文件
  2. 编写测试用例 `should auto-scroll to bottom on new message`:
     - 使用ChatPage页面对象
     - 先发送多条消息撑满视口
     - 手动滚动到顶部
     - 发送新消息
     - 断言 `chat-viewport` 的scrollTop + clientHeight >= scrollHeight - 50
  3. 编写测试用例 `should auto-scroll during streaming`:
     - 发送消息触发流式响应
     - 在流式传输中多次检查滚动位置
     - 断言视口始终在底部
  4. 确保测试使用 `data-testid` 选择器
  5. 运行测试: `npx playwright test flows/portal/chat-ux.flow.ts`

  **Must NOT do**:
  - 不依赖CSS类名选择器
  - 不修改已有E2E测试文件

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 需要验证滚动行为这个视觉交互特性
  - **Skills**: [`playwright-cli`]
    - `playwright-cli`: 需要编写Playwright测试，操作页面并验证滚动位置

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (与Tasks 6, 8并行)
  - **Blocks**: None
  - **Blocked By**: Task 2（需要自动滚动功能已修复）

  **References**:
  - `src/tests/e2e/pages/portal/chat.page.ts` — ChatPage页面对象
  - `src/tests/e2e/flows/portal/chat-streaming.flow.ts` — 已有流式测试（参考模式）
  - `src/tests/e2e/playwright.config.ts` — Playwright配置
  - data-testid: `[data-testid="chat-viewport"]`, `[data-testid="send-button"]`, `[data-testid="chat-input"]`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: E2E自动滚动测试全部通过
    Tool: Bash
    Preconditions: 自动滚动功能已修复
    Steps:
      1. cd src/tests/e2e
      2. npx playwright test flows/portal/chat-ux.flow.ts --grep "auto-scroll"
    Expected Result: 至少2个测试PASS
    Failure Indicators: 任何测试FAIL
    Evidence: .sisyphus/evidence/task-7-e2e-scroll-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] task-7-e2e-scroll-pass.txt — E2E滚动测试运行输出

  **Commit**: YES
  - Message: `test(e2e): 新增聊天自动滚动行为E2E验证`
  - Files: `src/tests/e2e/flows/portal/chat-ux.flow.ts`
  - Pre-commit: `cd src/tests/e2e && npx playwright test flows/portal/chat-ux.flow.ts --grep "scroll"`

- [ ] 8. Wave 3 — 新增Playwright E2E测试：微调器完成状态验证

  **What to do**:
  1. 在 `chat-ux.flow.ts` 中添加测试用例 `should stop loading spinner after response completes`:
     - 使用ChatPage页面对象
     - 发送消息触发响应
     - 等待 `[data-testid="streaming-indicator"]` 变为hidden（超时60秒）
     - 断言 `[data-testid="loader-icon"]` 不可见
  2. 添加测试用例 `should recover from stuck spinner with timeout`:
     - 模拟后端不发done事件的场景
     - 发送消息
     - 等待最多35秒 `[data-testid="streaming-indicator"]` 变为hidden
     - 断言 `[data-testid="chat-input"]` 恢复可用
  3. 运行测试

  **Must NOT do**:
  - 不修改后端mock数据来模拟异常（仅在测试中wait）

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 验证加载状态转换这个时序敏感的UX行为
  - **Skills**: [`playwright-cli`]
    - `playwright-cli`: Playwright测试编写和waitForSelector超时处理

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (与Tasks 6-7并行)
  - **Blocks**: None
  - **Blocked By**: Task 1（需要微调器修复已完成）

  **References**:
  - `src/tests/e2e/pages/portal/chat.page.ts` — ChatPage页面对象
  - `src/tests/e2e/flows/portal/chat-ux.flow.ts` — 同文件追加测试（与Task 7共享）
  - data-testid: `[data-testid="streaming-indicator"]`, `[data-testid="loader-icon"]`, `[data-testid="chat-input"]`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: E2E微调器完成状态测试全部通过
    Tool: Bash
    Preconditions: 微调器修复已完成
    Steps:
      1. cd src/tests/e2e
      2. npx playwright test flows/portal/chat-ux.flow.ts --grep "spinner"
    Expected Result: 至少2个测试PASS
    Failure Indicators: 任何测试FAIL
    Evidence: .sisyphus/evidence/task-8-e2e-spinner-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] task-8-e2e-spinner-pass.txt — E2E微调器测试运行输出

  **Commit**: YES
  - Message: `test(e2e): 新增微调器完成状态和超时恢复E2E验证`
  - Files: `src/tests/e2e/flows/portal/chat-ux.flow.ts`
  - Pre-commit: `cd src/tests/e2e && npx playwright test flows/portal/chat-ux.flow.ts --grep "spinner"`

- [ ] 9. Wave 4 — 提取 ChatMessageList 组件（消息列表 + 自动滚动 + 视口管理）

  **What to do**:
  1. 创建 `src/apps/portal/src/components/chat/message-list.tsx`
  2. 从 `settlement-chat.tsx` 第692-801行提取消息渲染逻辑，包括：
     - 消息映射渲染（`messages.map`）
     - 流式传输气泡（当前第762-779行，后续将提取为StreamingBubble组件 — 先保持内联，Task 11再替换）
     - 滚动哨兵div
     - ScrollArea包装
     - 加载中状态提示（三个脉冲点）
  3. 定义Props接口：
     ```typescript
     interface ChatMessageListProps {
       messages: Message[]
       isStreaming: boolean
       streamingContent: string
       steps: Step[]
       intentTrace: IntentTrace | null
       onConfirm: (approved: boolean) => void
       pendingConfirmation: ConfirmationRequest | null
     }
     ```
  4. 将 `scrollBottomRef` 和视口滚动逻辑移到 `message-list.tsx` 内部
  5. 在 `settlement-chat.tsx` 中替换原有消息渲染块为 `<ChatMessageList {...props} />`
  6. 确保所有data-testid仍然存在
  7. 运行 `npm run build`

  **Must NOT do**:
  - 不改变消息渲染的视觉效果
  - 不改变IntentTraceCard的渲染方式

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 从920行组件中安全提取约100行逻辑，需要仔细处理props接口和状态传递
  - **Skills**: [`subagent-driven-development`]
    - `subagent-driven-development`: 提取组件涉及props重构，需要仔细检查所有引用

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (与Tasks 10-12并行，各自提取独立部分)
  - **Blocks**: Task 13（vitest测试需要MessageList组件存在）
  - **Blocked By**: Tasks 3, 4（基于修复和紧凑化后的代码）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:692-801` — 消息列表渲染代码
  - `src/apps/portal/src/components/settlement-chat.tsx:344` — scrollBottomRef
  - `src/apps/portal/src/components/settlement-chat.tsx:427-429` — 滚动useEffect
  - `src/apps/portal/src/components/settlement-chat.tsx:664` — ScrollArea
  - `src/apps/portal/src/components/chat/execution-timeline.tsx` — 同目录下已有组件，参考结构模式

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 提取后消息列表功能完全等价
    Tool: Playwright
    Preconditions: 组件已提取
    Steps:
      1. 导航到 http://localhost:3000
      2. 发送一条消息
      3. 检查消息气泡渲染正常: expect(page.locator('[data-testid^="message-bubble"]').first()).toBeVisible()
      4. 等待响应完成
      5. 检查AI回复消息可见
    Expected Result: 消息发送和接收功能正常，视觉无变化
    Evidence: .sisyphus/evidence/task-9-message-list.png
  ```

  **Evidence to Capture**:
  - [ ] task-9-message-list.png — 提取后的消息列表截图

  **Commit**: YES
  - Message: `refactor(portal): 提取ChatMessageList组件 — 消息列表、自动滚动和视口管理`
  - Files: `src/apps/portal/src/components/chat/message-list.tsx`, `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 10. Wave 4 — 提取 ChatInput 组件（输入区域 + 发送按钮 + 快捷问题）

  **What to do**:
  1. 创建 `src/apps/portal/src/components/chat/chat-input.tsx`
  2. 从 `settlement-chat.tsx` 第805-828行提取输入区域逻辑，包括：
     - 文本输入框（textarea）
     - 发送按钮（含加载中微调器）
     - 快捷问题区域（如有）
  3. 定义Props接口：
     ```typescript
     interface ChatInputProps {
       input: string
       setInput: (value: string) => void
       isLoading: boolean
       onSend: () => void
       placeholder?: string
     }
     ```
  4. 在 `settlement-chat.tsx` 中替换原有输入区域为 `<ChatInput {...props} />`
  5. 确保 `data-testid="chat-input"` 和 `data-testid="send-button"` 仍然存在
  6. 运行 `npm run build`

  **Must NOT do**:
  - 不改变输入框行为（Enter发送、Shift+Enter换行等）
  - 不改变发送按钮的禁用逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 提取简单的表单组件，约20行代码

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (与Tasks 9, 11-12并行)
  - **Blocks**: Task 14（vitest测试需要ChatInput组件存在）
  - **Blocked By**: Tasks 3, 4（基于修复和紧凑化后的代码）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:805-828` — 输入区域代码
  - `src/apps/portal/src/components/settlement-chat.tsx:433-498` — `handleSend` 函数（保持在settlement-chat中）
  - `src/apps/portal/src/components/settlement-chat.tsx:340-341` — `input` 和 `setInput` 状态

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 提取后输入功能完全等价
    Tool: Playwright
    Preconditions: 组件已提取
    Steps:
      1. 导航到 http://localhost:3000
      2. 在输入框输入 "测试"
      3. 点击发送按钮
      4. 检查消息已发送: expect(page.locator('[data-testid^="message-bubble"]').first()).toContainText('测试')
    Expected Result: 输入和发送功能正常
    Evidence: .sisyphus/evidence/task-10-chat-input.png
  ```

  **Evidence to Capture**:
  - [ ] task-10-chat-input.png — 输入区域功能截图

  **Commit**: YES
  - Message: `refactor(portal): 提取ChatInput组件 — 输入区域、发送按钮和快捷问题`
  - Files: `src/apps/portal/src/components/chat/chat-input.tsx`, `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 11. Wave 4 — 提取 StreamingBubble 组件（流式传输气泡 + Typewriter动画）

  **What to do**:
  1. 创建 `src/apps/portal/src/components/chat/streaming-bubble.tsx`
  2. 从 `settlement-chat.tsx` 第762-779行提取流式传输气泡逻辑
  3. 该组件包装现有的 `Typewriter` 组件，添加气泡容器样式
  4. 定义Props接口：
     ```typescript
     interface StreamingBubbleProps {
       isStreaming: boolean
       streamingContent: string
       steps: Step[]
     }
     ```
  5. 在 `settlement-chat.tsx` 和 `message-list.tsx` 中替换原有流式气泡为 `<StreamingBubble {...props} />`
  6. 运行 `npm run build`

  **Must NOT do**:
  - 不修改 Typewriter 组件本身
  - 不改变气泡的视觉外观

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 轻量包装组件，主要提取JSX结构

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (与Tasks 9-10, 12并行)
  - **Blocks**: Task 15（vitest测试需要StreamingBubble组件存在）
  - **Blocked By**: Tasks 3, 4（基于修复和紧凑化后的代码）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:762-779` — 流式气泡JSX
  - `src/apps/portal/src/components/chat/typewriter.tsx` — Typewriter组件（被包装）
  - data-testid: `[data-testid="streaming-indicator"]`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 流式传输气泡正常显示并更新
    Tool: Playwright
    Preconditions: 后端可正常响应
    Steps:
      1. 导航到 http://localhost:3000
      2. 发送一条消息
      3. 检查流式指示器可见: expect(page.locator('[data-testid="streaming-indicator"]')).toBeVisible()
      4. 等待流式完成: page.waitForSelector('[data-testid="streaming-indicator"]', { state: 'hidden' })
      5. 检查AI回复已显示完整
    Expected Result: 流式传输过程中气泡可见，完成后消失
    Evidence: .sisyphus/evidence/task-11-streaming-bubble.png
  ```

  **Evidence to Capture**:
  - [ ] task-11-streaming-bubble.png — 流式传输中气泡截图

  **Commit**: YES
  - Message: `refactor(portal): 提取StreamingBubble组件 — 流式传输气泡包装Typewriter`
  - Files: `src/apps/portal/src/components/chat/streaming-bubble.tsx`, `src/apps/portal/src/components/settlement-chat.tsx`, `src/apps/portal/src/components/chat/message-list.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 12. Wave 4 — 提取 chat/helpers.ts（辅助工具函数）

  **What to do**:
  1. 创建 `src/apps/portal/src/components/chat/helpers.ts`
  2. 从 `settlement-chat.tsx` 提取以下纯函数（无状态依赖）：
     - `extractContent` (第124-197行) — 从AgentResponse提取显示内容
     - `buildGuideTrace` — 构建导办追踪数据
     - `mockCandidates` — 候选方案mock数据
     - `intentLabel`（如已在intent-trace-card中则跳过）
  3. 将这些函数改为具名导出
  4. 在 `settlement-chat.tsx` 和需要它们的组件中导入
  5. 运行 `npm run build`，确认所有导入正确

  **Must NOT do**:
  - 不将带状态/副作用的函数移出（如hooks）
  - 不修改函数逻辑（纯移动）
  - 不添加JSDoc注释

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯代码移动，无逻辑变化

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (与Tasks 9-11并行)
  - **Blocks**: Tasks 9-11（其他组件可能导入helpers）
  - **Blocked By**: Tasks 3, 4（基于修复和紧凑化后的代码）

  **References**:
  - `src/apps/portal/src/components/settlement-chat.tsx:109-306` — 辅助函数区域
  - `src/apps/portal/src/components/settlement-chat.tsx:124-197` — `extractContent` 函数
  - `src/apps/portal/src/components/settlement-chat.tsx:237-306` — `mockCandidates` 和 `buildGuideTrace`

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: 辅助函数提取后功能正常
    Tool: Bash
    Preconditions: 函数已提取，导入已修改
    Steps:
      1. cd src/apps/portal
      2. npm run build
    Expected Result: exit code 0，无导入错误
    Failure Indicators: 构建失败，模块未找到
    Evidence: .sisyphus/evidence/task-12-build-pass.txt
  ```

  **Evidence to Capture**:
  - [ ] task-12-build-pass.txt — 构建成功输出

  **Commit**: YES
  - Message: `refactor(portal): 提取chat/helpers.ts — extractContent等辅助函数`
  - Files: `src/apps/portal/src/components/chat/helpers.ts`, `src/apps/portal/src/components/settlement-chat.tsx`
  - Pre-commit: `cd src/apps/portal && npm run build`

- [ ] 13. Wave 5 — vitest测试：ChatMessageList 组件

  **What to do**:
  1. 创建 `src/apps/portal/src/tests/components/message-list.test.tsx`
  2. 编写测试用例：
     - `renders messages correctly`: 传入mock消息数组，验证消息气泡数量正确
     - `shows loading indicator when streaming`: `isStreaming=true`, 验证加载指示器存在
     - `does not show loading when not streaming`: `isStreaming=false`, 验证加载指示器不存在
     - `renders streaming bubble when content is streaming`: `isStreaming=true, streamingContent="..."`
     - `calls onConfirm when confirmation button clicked`: mock `onConfirm`, 点击确认按钮
     - `scroll viewport ref is attached`: 验证视口ref绑定到DOM元素
  3. Mock子组件：Typewriter（简单mock），IntentTraceCard（不在此范围）
  4. Mock `@base-ui/react/scroll-area` 的ScrollArea为简单div
  5. 运行 `npx vitest run src/tests/components/message-list.test.tsx`

  **Must NOT do**:
  - 不测试IntentTraceCard（不在提取范围内）
  - 不测试SSE流逻辑（那是sse-hooks的职责）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要mock第三方UI库、处理React渲染和用户交互测试
  - **Skills**: [`test-driven-development`]
    - `test-driven-development`: 编写测试验证组件行为正确

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (与Tasks 14-15并行)
  - **Blocks**: None
  - **Blocked By**: Task 5（vitest基础设施）, Task 9（MessageList组件存在）

  **References**:
  - `src/apps/portal/src/components/chat/message-list.tsx` — 被测组件
  - `src/apps/portal/src/tests/setup.ts` — 测试环境设置
  - `src/apps/portal/vitest.config.ts` — vitest配置
  - vitest + RTL文档: https://testing-library.com/docs/react-testing-library/intro/

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: ChatMessageList所有vitest测试通过
    Tool: Bash
    Preconditions: 组件已提取，vitest已配置
    Steps:
      1. cd src/apps/portal
      2. npx vitest run src/tests/components/message-list.test.tsx
    Expected Result: 所有测试PASS
    Failure Indicators: 任何测试FAIL
    Evidence: .sisyphus/evidence/task-13-vitest-message-list.txt
  ```

  **Evidence to Capture**:
  - [ ] task-13-vitest-message-list.txt — vitest测试运行输出

  **Commit**: YES
  - Message: `test(portal): ChatMessageList组件vitest单元测试`
  - Files: `src/apps/portal/src/tests/components/message-list.test.tsx`
  - Pre-commit: `cd src/apps/portal && npx vitest run src/tests/components/message-list.test.tsx`

- [ ] 14. Wave 5 — vitest测试：ChatInput 组件

  **What to do**:
  1. 创建 `src/apps/portal/src/tests/components/chat-input.test.tsx`
  2. 编写测试用例：
     - `renders input field and send button`: 验证输入框和按钮存在
     - `calls onSend when send button clicked`: mock `onSend`, 点击发送
     - `calls onSend when Enter pressed`: 模拟Enter按键
     - `disables send button when loading`: `isLoading=true`, 验证按钮禁用
     - `shows loader in button when loading`: `isLoading=true`, 验证微调器存在
     - `input value is controlled`: 验证 `setInput` 回调被调用
  3. 使用 `@testing-library/user-event` 模拟用户输入和点击
  4. 运行 `npx vitest run src/tests/components/chat-input.test.tsx`

  **Must NOT do**:
  - 不测试 `handleSend` 的完整逻辑（那是settlement-chat的职责）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 表单组件测试，标准的输入/点击/状态验证

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (与Tasks 13, 15并行)
  - **Blocks**: None
  - **Blocked By**: Task 5（vitest基础设施）, Task 10（ChatInput组件存在）

  **References**:
  - `src/apps/portal/src/components/chat/chat-input.tsx` — 被测组件
  - `@testing-library/user-event` 文档: https://testing-library.com/docs/user-event/intro/

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: ChatInput所有vitest测试通过
    Tool: Bash
    Preconditions: 组件已提取
    Steps:
      1. cd src/apps/portal
      2. npx vitest run src/tests/components/chat-input.test.tsx
    Expected Result: 所有测试PASS
    Evidence: .sisyphus/evidence/task-14-vitest-chat-input.txt
  ```

  **Evidence to Capture**:
  - [ ] task-14-vitest-chat-input.txt — vitest测试运行输出

  **Commit**: YES
  - Message: `test(portal): ChatInput组件vitest单元测试`
  - Files: `src/apps/portal/src/tests/components/chat-input.test.tsx`
  - Pre-commit: `cd src/apps/portal && npx vitest run src/tests/components/chat-input.test.tsx`

- [ ] 15. Wave 5 — vitest测试：StreamingBubble 组件

  **What to do**:
  1. 创建 `src/apps/portal/src/tests/components/streaming-bubble.test.tsx`
  2. 编写测试用例：
     - `renders nothing when not streaming`: `isStreaming=false`, 验证无输出
     - `renders Typewriter when streaming`: `isStreaming=true, streamingContent="你好"`, 验证内容渲染
     - `shows streaming indicator when streaming`: 验证data-testid存在
  3. Mock Typewriter组件为简单文本渲染
  4. 运行 `npx vitest run src/tests/components/streaming-bubble.test.tsx`

  **Must NOT do**:
  - 不测试Typewriter组件的动画逻辑（那是Typewriter的职责）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 轻量展示组件，测试逻辑简单

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 5 (与Tasks 13-14并行)
  - **Blocks**: None
  - **Blocked By**: Task 5（vitest基础设施）, Task 11（StreamingBubble组件存在）

  **References**:
  - `src/apps/portal/src/components/chat/streaming-bubble.tsx` — 被测组件
  - `src/apps/portal/src/components/chat/typewriter.tsx` — 需mock的子组件

  **Acceptance Criteria**:

  **QA Scenarios**:

  ```
  Scenario: StreamingBubble所有vitest测试通过
    Tool: Bash
    Steps:
      1. cd src/apps/portal
      2. npx vitest run src/tests/components/streaming-bubble.test.tsx
    Expected Result: 所有测试PASS
    Evidence: .sisyphus/evidence/task-15-vitest-streaming-bubble.txt
  ```

  **Evidence to Capture**:
  - [ ] task-15-vitest-streaming-bubble.txt — vitest测试运行输出

  **Commit**: YES
  - Message: `test(portal): StreamingBubble组件vitest单元测试`
  - Files: `src/apps/portal/src/tests/components/streaming-bubble.test.tsx`
  - Pre-commit: `cd src/apps/portal && npx vitest run src/tests/components/streaming-bubble.test.tsx`

---

## Final Verification Wave

> 4个审查代理并行运行。全部必须APPROVE。向用户呈现综合结果并获取明确的"okay"后才能标记完成。
> **在获得用户确认前不自动标记完成。** 拒绝或反馈 → 修复 → 重新运行 → 重新呈现 → 等待确认。

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `npm run lint` + `npm run build`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright-cli` skill)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1**: `fix(portal): 微调器永久旋转 — 添加安全超时和缺失done事件处理` — settlement-chat.tsx
- **2**: `fix(portal): 自动滚动失效 — 使用ScrollArea视口ref替代scrollIntoView` — settlement-chat.tsx
- **3**: `fix(portal): 聊天区域留白过多 — 修正高度计算减少多余空白` — settlement-chat.tsx
- **4**: `style(portal): 紧凑极简UI — 减少全局padding和间距` — settlement-chat.tsx, layout.tsx
- **5**: `chore(portal): 搭建vitest + React Testing Library测试基础设施` — vitest.config.ts, package.json
- **6**: `test(portal): 添加data-testid并修复E2E页面对象选择器` — settlement-chat.tsx, chat.page.ts
- **7**: `test(e2e): 新增聊天自动滚动E2E验证` — chat-ux.flow.ts
- **8**: `test(e2e): 新增微调器完成状态E2E验证` — chat-ux.flow.ts
- **9**: `refactor(portal): 提取ChatMessageList组件` — chat/message-list.tsx, settlement-chat.tsx
- **10**: `refactor(portal): 提取ChatInput组件` — chat/chat-input.tsx, settlement-chat.tsx
- **11**: `refactor(portal): 提取StreamingBubble组件` — chat/streaming-bubble.tsx, settlement-chat.tsx
- **12**: `refactor(portal): 提取chat/helpers.ts辅助函数` — chat/helpers.ts, settlement-chat.tsx
- **13**: `test(portal): ChatMessageList组件vitest测试` — tests/components/message-list.test.tsx
- **14**: `test(portal): ChatInput组件vitest测试` — tests/components/chat-input.test.tsx
- **15**: `test(portal): StreamingBubble组件vitest测试` — tests/components/streaming-bubble.test.tsx

---

## Success Criteria

### 验证命令
```bash
# 构建验证
cd src/apps/portal && npm run build
# 期望: exit code 0

# Lint验证
cd src/apps/portal && npm run lint
# 期望: exit code 0

# 组件测试
cd src/apps/portal && npx vitest run
# 期望: 所有测试PASS

# E2E测试
cd src/tests/e2e && npx playwright test smoke/portal-smoke.spec.ts flows/portal/
# 期望: 所有测试PASS
```

### 最终检查清单
- [ ] 所有"必须做"已完成
- [ ] 所有"必须不做"未被违反
- [ ] 3个Bug各自原子提交且独立可验证
- [ ] 组件提取后功能完全等价
- [ ] E2E选择器已从CSS类迁移为data-testid
- [ ] 构建无错误
- [ ] 所有测试通过
