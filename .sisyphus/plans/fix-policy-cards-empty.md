# 修复 /policy-qa 页面"相关政策查询为空"

## TL;DR

> **Quick Summary**: 修复 policy-qa 页面政策卡片不显示的 3 个 Bug：后端 SSE 步事件缺失 `policy_cards` 字段 + 前端 SSE 解析 `eventType` 丢失 + 技能接口 `PolicyRule` 缺 `source_text` 导致解释生成崩溃。
>
> **Deliverables**:
> - `src/runtime/api/policy_qa_routes.py` — 步事件补全 `policy_cards`
> - `src/apps/portal/src/components/policy-qa-chat.tsx` — 修复 SSE eventType
> - `skills/policy_fee_explanation/tool_interfaces.py` — 补全 `source_text` 字段
>
> **Estimated Effort**: Quick (3 文件，~10 行代码)
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Bug C → Bug A → Bug B（依赖链：Bug C 先修确保数据正确 → Bug A 让数据出现在步事件 → Bug B 让前端正确消费）

---

## Context

### 原始问题
用户在 `/policy-qa` 页面输入"为什么统筹自付这么多"，政策查询结果为空。

### 验证过程
通过 `curl` 直接测试 SSE 端点，发现：
- 后端正常返回 10 条政策规则（`rules_count: 10`, `rag_miss: false`）
- `result` 事件中包含 10 条 `policy_evidence`
- 但 `search_policy_rules` 步 done 事件中没有 `policy_cards` 字段
- `generate_explanation` 报错：`'PolicyRule' object has no attribute 'source_text'`

### 根因分析（3 个 Bug）

**Bug A（主因）**: `policy_qa_routes.py:177-189` 构建 `public_step` 时遗漏 `policy_cards`
- 前端的 `data.policy_cards` 永远为 `undefined` → 政策面板永远为空

**Bug B（次因）**: `policy-qa-chat.tsx:333` SSE 解析 `eventType` 在每行循环内重新初始化
- `event: result` 设置的 `eventType` 被 `data:` 行的 `let eventType = "step"` 覆盖
- `result` 事件中的 `policy_evidence` 被静默丢弃

**Bug C（崩溃）**: `tool_interfaces.py:PolicyRule` 缺少 `source_text` 字段
- `tool_adapters.py:21` 导入 `policy_fee_explanation/tool_interfaces.py` 的 `PolicyRule`（仅 6 字段）
- `ExplanationGenerator` 访问 `rule.source_text` → `AttributeError`
- 解释文本显示 "生成解释时出错" 而非正常内容

### Metis 审查
关键发现：`tool_adapters.py` 导入的 `PolicyRule` 来自 `skills/policy_fee_explanation/tool_interfaces.py`（无 `source_text`），而非 `models.py`（有 `source_text`）。修复步骤：Bug C → Bug A → Bug B（确保数据完整性后再修复数据流通）。

---

## Work Objectives

### Core Objective
修复政策卡片在 `/policy-qa` 页面正常显示，解释文本不再报错。

### Concrete Deliverables
- 政策卡片在步事件 `search_policy_rules` done 时携带并渲染
- 政策卡片在 result 事件中正确降级消费
- 解释生成输出正常文本（非错误信息）

### Definition of Done
- [ ] `curl` 验证 `search_policy_rules` 步事件包含 `policy_cards` 数组
- [ ] Playwright 验证前端政策面板显示政策卡片
- [ ] `curl` 验证解释文本不包含 "生成解释时出错"
- [ ] 现有单元测试全部通过

### Must Have
- `policy_cards` 字段加入 `public_step`（Bug A）
- SSE `eventType` 修复（Bug B）
- `source_text` 加入接口 dataclass（Bug C）

### Must NOT Have (Guardrails)
- 不重构 SSE 解析循环结构
- 不修改 `PolicyCardItem` / `PolicyQAResponse` 类型定义
- 不修改 policy-answer-card.tsx 渲染逻辑
- 不添加新特性（重试、缓存等）

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES（pytest 单元测试 + API 测试）
- **Automated tests**: Tests-after（少量修改，优先验证）
- **Framework**: pytest
- **Agent-Executed QA**: 每个任务包含 curl + Playwright 验证

### QA Policy
- 后端：curl 直接验证 SSE 输出
- 前端：Playwright 打开页面验证渲染
- 单元测试：修补后运行 `pytest src/tests/unit/runtime/policy_qa -v`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (同时修复 - 3 个独立文件，无代码依赖):
├── Task 1: Bug C 修复 — tool_interfaces.py 补 source_text [quick]
├── Task 2: Bug A 修复 — policy_qa_routes.py 补 policy_cards [quick]
└── Task 3: Bug B 修复 — policy-qa-chat.tsx 修 eventType [quick]

Wave 2 (验证 — 依赖 Wave 1 全部完成):
├── Task 4: curl 验证后端 SSE 输出 [quick]
├── Task 5: Playwright 验证前端渲染 [visual-engineering]
└── Task 6: 单元测试回归 [quick]
```

---

## TODOs

- [ ] 1. **Bug C 修复** — `tool_interfaces.py` 补全 `source_text` 字段

  **What to do**:
  - 在 `skills/policy_fee_explanation/tool_interfaces.py` 的 `PolicyRule` dataclass（第 24-32 行）中添加 `source_text: str = ""`
  - 放在 `rule_type` 和 `score` 之间，保持与 `models.py:PolicyRule` 的字段顺序一致

  **Must NOT do**:
  - 不修改 `models.py:PolicyRule`（它已经有 `source_text`）
  - 不修改 `tool_adapters.py` 的适配逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单行 dataclass 字段添加，零风险
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 Task 2、Task 3 并行）
  - **Blocks**: Task 4（curl 验证）
  - **Blocked By**: None

  **References**:
  - `skills/policy_fee_explanation/tool_interfaces.py:24-32` — `PolicyRule` dataclass 当前定义（仅 6 字段）
  - `src/runtime/policy_qa/models.py:79` — `source_text: str = ""` 参考字段定义
  - `src/runtime/policy_qa/tool_adapters.py:21` — 导入 `PolicyRule as SkillPolicyRule` 的行
  - `src/runtime/policy_qa/explanation_generator.py:251,259,300,375` — 4 处 `rule.source_text` 访问点

  **Acceptance Criteria**:
  - [ ] `tool_interfaces.py:PolicyRule` 包含 `source_text: str = ""`
  - [ ] Python 语法检查通过（`python -m py_compile skills/policy_fee_explanation/tool_interfaces.py`）

  **QA Scenarios**:
  ```
  Scenario: 解释生成不再报 source_text AttributeError
    Tool: Bash (curl)
    Preconditions: 后端服务运行中，所有 3 个 Bug 修复完成
    Steps:
      1. curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream -H "Content-Type: application/json" -d '{"question":"为什么统筹自付这么多","settlement_id":"1671213","session_id":"diag-test"}'
      2. 等待完整 SSE 输出
      3. 检查 generate_explanation streaming 事件的 chunk 内容
    Expected Result: 不包含 "生成解释时出错" 或 "source_text" 错误信息
    Failure Indicators: 任何包含 "生成解释时出错" 的 chunk
    Evidence: .sisyphus/evidence/task-1-source-text-fix.txt (curl 输出)
  ```

  **Commit**: YES
  - Message: `fix: add source_text field to tool_interfaces.py PolicyRule dataclass`
  - Files: `skills/policy_fee_explanation/tool_interfaces.py`

- [ ] 2. **Bug A 修复** — `policy_qa_routes.py` 补全 `policy_cards` 到步事件

  **What to do**:
  - 在 `src/runtime/api/policy_qa_routes.py` 的 `public_step` 构建块（第 177-189 行），添加：`if response.policy_cards: public_step["policy_cards"] = response.policy_cards`
  - 插入位置：在 `if response.error:` 块之后，在 `if response.status == "done":` 块之前

  **Must NOT do**:
  - 不改变 `public_step` 的现有字段顺序
  - 不修改 `result` 事件的 `policy_evidence` 字段名

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 2 行条件代码添加，已有明确插入位置
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 Task 1、Task 3 并行）
  - **Blocks**: Task 4（curl 验证）
  - **Blocked By**: None

  **References**:
  - `src/runtime/api/policy_qa_routes.py:176-189` — `public_step` 构建代码块
  - `src/runtime/api/policy_qa_routes.py:197-198` — 如何捕获 `response.policy_cards` 到 result 事件（参考实现）
  - `src/runtime/policy_qa/orchestrator.py:186-196` — orchestrator 设置 `policy_cards` 的位置
  - `src/runtime/policy_qa/models.py:215` — `PolicyQAResponse.policy_cards` 字段定义
  - `src/apps/portal/src/components/policy-qa-chat.tsx:388-399` — 前端消费 `data.policy_cards` 的位置

  **Acceptance Criteria**:
  - [ ] `public_step` 包含 `policy_cards` 当 `response.policy_cards` 非空
  - [ ] `policy_cards` 内容为 dict 数组（非空数组）

  **QA Scenarios**:
  ```
  Scenario: search_policy_rules done 事件包含 policy_cards
    Tool: Bash (curl)
    Preconditions: 后端服务运行中
    Steps:
      1. curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream -H "Content-Type: application/json" -d '{"question":"为什么统筹自付这么多","settlement_id":"1671213","session_id":"diag-test"}'
      2. 过滤 search_policy_rules done 事件
    Expected Result: 步事件 JSON 包含 "policy_cards":[ 且数组非空
    Failure Indicators: 步事件无 "policy_cards" 键，或值为空数组 []
    Evidence: .sisyphus/evidence/task-2-policy-cards-in-event.txt
  ```

  **Commit**: YES
  - Message: `fix: include policy_cards in SSE step event for search_policy_rules`
  - Files: `src/runtime/api/policy_qa_routes.py`

- [ ] 3. **Bug B 修复** — `policy-qa-chat.tsx` 修复 SSE eventType

  **What to do**:
  - 在 `src/apps/portal/src/components/policy-qa-chat.tsx` 中，将 `let eventType = "step"` 从 `for (const line of lines)` 循环内（第 333 行）移到循环之前
  - 即：先声明 `let eventType = "step"`，再进入 `for` 循环，这样 `event:` 行设置的 eventType 能延续到 `data:` 行

  **Must NOT do**:
  - 不重构 SSE 解析循环的其余部分
  - 不添加新的状态管理

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 前端 TypeScript/React 代码修改，需要 JS/TS 上下文
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1（与 Task 1、Task 2 并行）
  - **Blocks**: Task 5（Playwright 验证）
  - **Blocked By**: None

  **References**:
  - `src/apps/portal/src/components/policy-qa-chat.tsx:330-346` — SSE 解析循环代码
  - `src/apps/portal/src/components/policy-qa-chat.tsx:355-371` — result 事件处理器（当前死代码）
  - `src/apps/portal/src/components/policy-qa-chat.tsx:388-399` — step 事件处理器（policy_cards 消费点）

  **Acceptance Criteria**:
  - [ ] `result` 事件能进入 `if (eventType === 'result')` 分支
  - [ ] `npm run build` 无 TypeScript 错误
  - [ ] 现有 step 事件处理不受影响

  **QA Scenarios**:
  ```
  Scenario: 政策卡片在前端页面中正确渲染
    Tool: Playwright
    Preconditions: 后端服务运行，前端 dev server 运行（port 3000）
    Steps:
      1. 导航到 http://localhost:3000/policy-qa
      2. 在输入框输入 "为什么统筹自付这么多"
      3. 按 Enter 发送
      4. 等待 search_policy_rules 步骤完成
      5. 检查页面中"相关政策知识"面板
    Expected Result: 面板显示 N 条政策卡片（标题、条文、证据文字），非"暂未检索到相关政策和证据"
    Failure Indicators: 面板显示空状态"暂未检索到相关政策和证据"
    Evidence: .sisyphus/evidence/task-3-policy-cards-visible.png (screenshot)
  ```

  **Commit**: YES
  - Message: `fix: fix SSE eventType parsing to preserve result event type`
  - Files: `src/apps/portal/src/components/policy-qa-chat.tsx`

- [ ] 4. **curl 端到端验证** — 验证 3 个 Bug 全部修复

  **What to do**:
  - 运行 curl 测试 SSE 端点，保存完整输出
  - 检查 `search_policy_rules` 步 done 事件包含 `policy_cards`
  - 检查 `generate_explanation` 不再包含 "生成解释时出错"
  - 检查 `result` 事件包含 `policy_evidence`

  **Must NOT do**:
  - 不修改任何代码

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 Task 5 并行）
  - **Parallel Group**: Wave 2
  - **Blocks**: Final Verification Wave
  - **Blocked By**: Task 1, Task 2, Task 3

  **Acceptance Criteria**:
  - [ ] SSE 输出包含 `policy_cards`
  - [ ] SSE 输出不包含 "生成解释时出错"

  **QA Scenarios**:
  ```
  Scenario: SSE 端点输出完整且正确
    Tool: Bash (curl)
    Preconditions: 后端服务运行中
    Steps:
      1. curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream -H "Content-Type: application/json" -d '{"question":"why is this so much","settlement_id":"1671213","session_id":"diag-test"}' --max-time 30 2>&1 > .sisyphus/evidence/task-4-full-sse.txt
      2. Select-String -Path .sisyphus/evidence/task-4-full-sse.txt -Pattern "policy_cards" -SimpleMatch
      3. Select-String -Path .sisyphus/evidence/task-4-full-sse.txt -Pattern "生成解释时出错" -SimpleMatch
    Expected Result: 步骤2有匹配，步骤3无匹配
    Evidence: .sisyphus/evidence/task-4-full-sse.txt
  ```

  **Commit**: NO

- [ ] 5. **Playwright 前端渲染验证** — 验证政策卡片在页面中可见

  **What to do**:
  - 使用 Playwright 导航到 `/policy-qa`
  - 输入问题发送
  - 等待 SSE 流式完成
  - 截图验证政策面板显示卡片

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
  - **Skills**: `["playwright-cli"]`

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 Task 4 并行）
  - **Parallel Group**: Wave 2
  - **Blocks**: Final Verification Wave
  - **Blocked By**: Task 1, Task 2, Task 3

  **Acceptance Criteria**:
  - [ ] 政策面板不显示空状态
  - [ ] 政策卡片有可见内容

  **QA Scenarios**:
  ```
  Scenario: 前端页面显示政策卡片
    Tool: Playwright
    Preconditions: 后端运行(8000)，前端运行(3000)
    Steps:
      1. 导航到 http://localhost:3000/policy-qa
      2. 等待页面加载(timeout: 10s)
      3. 在输入框输入 "为什么统筹自付这么多" 并发送
      4. 等待搜索步骤完成
      5. 截图保存
    Expected Result: 政策面板显示政策卡片
    Failure Indicators: 面板显示"暂未检索到相关政策和证据"
    Evidence: .sisyphus/evidence/task-5-policy-cards-visible.png
  ```

  **Commit**: NO

- [ ] 6. **单元测试回归** — 确保现有测试全部通过

  **What to do**:
  - 运行 policy_qa 模块的单元测试

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `[]`

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 Task 4、Task 5 并行）
  - **Parallel Group**: Wave 2
  - **Blocked By**: Task 1, Task 2

  **QA Scenarios**:
  ```
  Scenario: 所有 policy_qa 单元测试通过
    Tool: Bash
    Steps:
      1. python -m pytest src/tests/unit/runtime/policy_qa -v --tb=short
    Expected Result: 所有测试 PASSED
    Evidence: .sisyphus/evidence/task-6-unit-tests.txt
  ```

  **Commit**: NO

---

## Final Verification Wave

> 4 个审查代理并行运行。ALL 必须 APPROVE。

- [ ] F1. **Plan Compliance Audit** — `oracle`
  逐项检查：Must Have (3/3): `source_text` 字段 → `policy_cards` 在步事件 → `eventType` 正确；Must NOT Have: 无重构、无类型修改、无 UI 修改。
  Output: `Must Have [3/3] | Must NOT Have [3/3] | Tasks [6/6] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  检查 3 个修改文件有无 `as any`、空 catch、console.log、未使用 import。
  Output: `Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  从干净状态开始。执行 Task 4 + Task 5 的 QA 场景，捕获证据。
  Output: `Scenarios [N/N pass] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  对比 plan 与 git diff：是否只修改 3 个文件？修改是否精准（不超过 10 行）？
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

| Wave | Task | Message | Files |
|------|------|---------|-------|
| 1 | 1 | `fix: add source_text field to tool_interfaces.py PolicyRule dataclass` | `skills/policy_fee_explanation/tool_interfaces.py` |
| 1 | 2 | `fix: include policy_cards in SSE step event for search_policy_rules` | `src/runtime/api/policy_qa_routes.py` |
| 1 | 3 | `fix: fix SSE eventType parsing to preserve result event type` | `src/apps/portal/src/components/policy-qa-chat.tsx` |

---

## Success Criteria

### Verification Commands
```bash
# Bug A+B: 验证 policy_cards 在 SSE 步事件中
curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream -H "Content-Type: application/json" -d '{"question":"为什么统筹自付这么多","settlement_id":"1671213","session_id":"diag"}' 2>&1 | Select-String "policy_cards"

# Bug C: 验证无 source_text 错误
curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream -H "Content-Type: application/json" -d '{"question":"为什么统筹自付这么多","settlement_id":"1671213","session_id":"diag"}' 2>&1 | Select-String "生成解释时出错"

# 单元测试回归
python -m pytest src/tests/unit/runtime/policy_qa -v --tb=short
```

### Final Checklist
- [ ] 政策面板不再为空，显示 N 条政策卡片
- [ ] 解释文本正常，不包含错误信息
- [ ] `curl` 步事件包含 `policy_cards` 数组
- [ ] 所有单元测试通过
- [ ] 无 TypeScript 编译错误
- [ ] 不在 3 个目标文件中引入新问题


