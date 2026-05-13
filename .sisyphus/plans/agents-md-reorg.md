# AGENTS.md 文档重组：消除重复，纯化编码指引定位

## TL;DR

> **Quick Summary**: 将根 AGENTS.md 中与 steering docs 重复的 API 表、数据库表、存储架构等内容删除，替换为精简引用；删除测试约定细节（保留硬性约束），指向 tests/AGENTS.md。实现 "纯 Agent 编码指引" 定位。
>
> **Deliverables**:
> - 根 AGENTS.md 瘦身约 94 行（从 357 行降至约 263 行）
> - 零与 steering docs 重复的内容
> - 测试内容严格分离（根仅保留硬性约束）
> - tests/AGENTS.md 引用一致性验证通过
>
> **Estimated Effort**: Quick
> **Parallel Execution**: NO - 单文件顺序编辑
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5

---

## Context

### Original Request
用户发现根 AGENTS.md 包含大量与 `docs/steering/` 下文档重复的内容（API 表 ~64 行、数据库表 ~24 行、存储架构 ~5 行），以及与 `src/tests/AGENTS.md` 重叠的测试内容。要求重组为 "纯 Agent 编码指引"。

### Interview Summary
**Key Discussions**:
- AGENTS.md 定位 = "纯 Agent 编码指引"（非综合参考文档）
- 测试内容 = "严格分离"（根只保留硬性约束，其余指向 tests/AGENTS.md）
- API/DB 表 = 直接删除，加引用指向 steering docs
- 重组范围 = 仅根 AGENTS.md + 最小化 tests/AGENTS.md 检查
- 编码规范/陷阱 = 全部保留在根
- 工具调用规则 = 保留（项目级规则）
- 技术债务 = 保留（Agent 编码时的关键上下文）

**Research Findings**:
- 8 个子模块 AGENTS.md 无 steering docs 重复，本次不动
- tests/AGENTS.md 无对根 AGENTS.md 的交叉引用，无需更新
- 核心约定（line 64）已有 steering docs 引用，删除后不会丢失引用

### Metis Review
**Identified Gaps** (addressed):
- 前端应用路由块（L139-144）在两个删除区间之间会孤立 → 保留并放在 API 引用之后
- 测试约定（L188-200）与硬性约束（L202-287）的边界 → 删除测试约定，保留硬性约束
- 已知陷阱中混合了测试/开发相关项 → 全部保留（均为 Agent 编码时的注意事项）
- 工具调用规则来源不明 → 经审查为项目级规则，保留

---

## Work Objectives

### Core Objective
消除根 AGENTS.md 中与 steering docs 和 tests/AGENTS.md 的内容重复，将其定位为 "纯 Agent 编码指引"。

### Concrete Deliverables
- 修改后的根 AGENTS.md（~263 行，删除 ~94 行重复内容）
- 引用一致性验证通过（所有 `docs/steering/` 引用指向存在的文件）

### Definition of Done
- [x] `Select-String -Path "AGENTS.md" -Pattern "^\| .*POST\|^\| .*GET\|^\| .*PUT\|^\| .*DELETE"` 返回 0 行
- [x] `Select-String -Path "AGENTS.md" -Pattern "^\| .*patients\|^\| .*insurance_transactions\|^\| .*workflows"` 返回 0 行
- [x] `Select-String -Path "AGENTS.md" -Pattern "tests/AGENTS.md"` 返回 ≥1 行
- [x] AGENTS.md Markdown 渲染正常（无断裂表格/孤立标题）

### Must Have
- API 路由前缀保留在根 AGENTS.md
- 前端应用路由信息保留在根 AGENTS.md
- 硬性验证流程和缺陷驱动规则完整保留
- 所有删除的 steering docs 内容有对应引用

### Must NOT Have (Guardrails)
- ❌ 不修改 8 个子模块 AGENTS.md 文件
- ❌ 不修改 docs/steering/ 下任何文件
- ❌ 不添加新的非引用内容到 AGENTS.md
- ❌ 不调整保留内容的节顺序（除删除后的自然衔接）
- ❌ 不修改 tests/AGENTS.md 内容（仅验证引用一致性）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: N/A（文档重组任务，非代码）
- **Automated tests**: None
- **Framework**: N/A

### QA Policy
每项编辑后通过 PowerShell `Select-String` 验证删除完整性 + 引用有效性。

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (顺序执行 - 同一文件不可并行):
├── Task 1: 删除 API 表 (L75-138) + 保留路由前缀和前端应用路由 [quick]
├── Task 2: 删除 数据库表一览 + 存储分层架构 (L146-175) [quick]
└── Task 3: 删除 测试约定 (L188-200) + 添加 tests/AGENTS.md 引用 [quick]

Wave FINAL (验证 - 可并行):
├── Task 4: 根 AGENTS.md 内容完整性验证 [quick]
├── Task 5: tests/AGENTS.md 引用一致性验证 [quick]

Critical Path: Task 1 → Task 2 → Task 3 → Task 4+5
```

### Dependency Matrix

- **1**: - - 2,3, 1
- **2**: 1 - 3, 1
- **3**: 2 - 4,5, 1
- **4**: 3 - -, FINAL
- **5**: 3 - -, FINAL

### Agent Dispatch Summary

- **Wave 1**: **1 sequential** - T1→T2→T3 each → `quick`
- **FINAL**: **2 parallel** - T4 → `quick`, T5 → `quick`

---

## TODOs

- [x] 1. 删除 API 表格（L75-138），保留路由前缀和前端应用路由

  **What to do**:
  - 保留 L71-73（`### API` 标题 + 路由前缀 + steering docs 引用）
  - 删除 L75-138（6 个 API 表格：业务入口、模型服务管理、技能管理、MCP 管理、知识管理、系统）
  - 保留 L139-144（前端应用目录路由信息），紧接在路由前缀引用之后
  - 最终该节结构：
    ```
    ### API

    路由前缀: `/api/v1/medical-insurance-ai-agent`（除 `/health` 外）。完整接口清单见 `docs/steering/接口设计文档.md`。

    前端应用目录: `src/apps/` 下三个独立 Next.js 16 应用：
    - **portal/** — ...
    - **admin/** — ...
    - **embed/** — ...

    三个应用各自独立构建、独立运行，共享同一后端 API（`/api/v1/medical-insurance-ai-agent/*`）。
    ```

  **Must NOT do**:
  - 不删除路由前缀行（L73）
  - 不删除前端应用路由块（L139-144）
  - 不修改 steering docs 引用文字

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件精确删除，不涉及逻辑判断
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `playwright`: 无浏览器交互需求

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (sequential, first)
  - **Blocks**: Task 2, Task 3
  - **Blocked By**: None

  **References**:
  - `AGENTS.md:71-144` — API 完整区块（需精确保留 L71-73 + L139-144，删除 L75-138）
  - `docs/steering/接口设计文档.md` — 被引用的 steering doc，确认文件存在

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: API 表已完全删除
    Tool: Bash (PowerShell Select-String)
    Preconditions: AGENTS.md 存在且可读
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "^\| (POST|GET|PUT|DELETE)"
      2. 统计匹配行数
    Expected Result: 0 行匹配
    Failure Indicators: 任何匹配行存在（说明 API 表未完全删除）
    Evidence: .sisyphus/evidence/task-1-api-tables-removed.txt

  Scenario: 路由前缀保留
    Tool: Bash (PowerShell Select-String)
    Preconditions: AGENTS.md 存在
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "路由前缀"
      2. 确认返回恰好 1 行
    Expected Result: 1 行匹配，内容包含 `/api/v1/medical-insurance-ai-agent`
    Failure Indicators: 0 行（路由前缀被误删）或 >1 行（重复）
    Evidence: .sisyphus/evidence/task-1-routing-prefix-preserved.txt

  Scenario: 前端应用路由保留
    Tool: Bash (PowerShell Select-String)
    Preconditions: AGENTS.md 存在
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "portal/|admin/|embed/"
      2. 确认返回 ≥3 行（三个应用各至少一行）
    Expected Result: ≥3 行匹配
    Failure Indicators: <3 行匹配（前端应用信息不完整）
    Evidence: .sisyphus/evidence/task-1-frontend-routes-preserved.txt
  ```

  **Commit**: NO (groups with Task 3)

---

- [x] 2. 删除 数据库表一览 + 存储分层架构（L146-175）

  **What to do**:
  - 删除 L146-175（`### 数据库表一览` 标题 + 18 行表格 + `### 存储分层架构` 标题 + 3 行描述）
  - 注意：L148 已有引用 `详细表定义见 docs/steering/数据库设计文档.md`，删除后该引用也一并删除
  - 删除后无需添加替代引用——因为 L64（核心约定）已包含 `docs/steering/ 数据库设计文档.md（18张表定义）` 的引用
  - 确保删除后上一节（前端应用路由）和下一节（编码规范）自然衔接

  **Must NOT do**:
  - 不添加新的引用（L64 已有引用）
  - 不修改 L64 的核心约定内容
  - 不删除 L145 之前的空行

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件精确删除，范围明确
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (sequential, after Task 1)
  - **Blocks**: Task 3
  - **Blocked By**: Task 1

  **References**:
  - `AGENTS.md:146-175` — 数据库表一览 + 存储分层架构（需完整删除）
  - `AGENTS.md:64` — 核心约定中已有的数据库文档引用（确认不需额外添加引用）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: DB 表已完全删除
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 1 已完成
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "^\| .*\|.*postgres\.py"
      2. 统计匹配行数
    Expected Result: 0 行匹配
    Failure Indicators: 任何匹配行存在
    Evidence: .sisyphus/evidence/task-2-db-tables-removed.txt

  Scenario: 存储分层已删除
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 1 已完成
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "^### 存储分层架构"
      2. 确认返回 0 行
    Expected Result: 0 行匹配
    Failure Indicators: 标题仍存在
    Evidence: .sisyphus/evidence/task-2-storage-section-removed.txt

  Scenario: 核心约定中 DB 引用仍有效
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 1 已完成
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "数据库设计文档"
      2. 确认返回 ≥1 行（核心约定中的引用仍在）
    Expected Result: ≥1 行匹配
    Failure Indicators: 0 行（引用被误删）
    Evidence: .sisyphus/evidence/task-2-db-ref-in-core-conventions.txt
  ```

  **Commit**: NO (groups with Task 3)

---

- [x] 3. 删除测试约定（L188-200），添加 tests/AGENTS.md 引用指针

  **What to do**:
  - 删除 L188-200（`### 测试约定` 标题 + 测试目录描述 + API/单元/LangGraph 测试模式 + 辅助函数说明 + 运行命令）
  - 在 `## 编码规范` 节末尾（L186 之后）添加一行引用指针：
    ```
    > 测试目录结构、命令速查、模块↔测试映射、测试编写模式等详见 `src/tests/AGENTS.md`。
    ```
  - 确保删除后 `## 编码规范` 的内容直接衔接到 `### 开发完成验证流程（硬性，不可跳过）`

  **Must NOT do**:
  - 不删除 L202-287（硬性验证流程 + 缺陷驱动规则）
  - 不修改 L180 中 `__init__.py` 规则的 pytest 说明（这是编码规范，不是测试内容）
  - 不添加除引用指针外的任何新内容

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单文件精确编辑，范围明确
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1 (sequential, after Task 2)
  - **Blocks**: Task 4, Task 5
  - **Blocked By**: Task 2

  **References**:
  - `AGENTS.md:188-200` — 测试约定子节（需完整删除）
  - `AGENTS.md:177-187` — 编码规范（引用指针添加位置）
  - `AGENTS.md:202-287` — 硬性验证流程 + 缺陷驱动规则（必须保留不动）
  - `src/tests/AGENTS.md` — 引用目标，确认文件存在

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 测试约定已删除
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 2 已完成
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "^### 测试约定"
      2. 确认返回 0 行
    Expected Result: 0 行匹配
    Failure Indicators: 标题仍存在
    Evidence: .sisyphus/evidence/task-3-test-conventions-removed.txt

  Scenario: tests/AGENTS.md 引用存在
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 2 已完成
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "tests/AGENTS.md"
      2. 确认返回 ≥1 行
    Expected Result: ≥1 行匹配
    Failure Indicators: 0 行（引用指针未添加）
    Evidence: .sisyphus/evidence/task-3-tests-ref-added.txt

  Scenario: 硬性验证流程完整保留
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 2 已完成
    Steps:
      1. 运行: Select-String -Path "AGENTS.md" -Pattern "开发完成验证流程"
      2. 确认返回 1 行
      3. 运行: Select-String -Path "AGENTS.md" -Pattern "缺陷驱动的测试强化铁律"
      4. 确认返回 1 行
    Expected Result: 两个标题各返回 1 行
    Failure Indicators: 任一标题缺失
    Evidence: .sisyphus/evidence/task-3-hard-constraints-preserved.txt

  Scenario: Markdown 无断裂结构
    Tool: Bash (Read file)
    Preconditions: Task 2 已完成
    Steps:
      1. 读取 AGENTS.md 完整内容
      2. 检查删除区域前后节标题层级正确（`## 编码规范` → `### 开发完成验证流程`）
      3. 确认无孤立的表格行（`|` 开头但无对应表头）
    Expected Result: 节标题层级正确，无孤立行
    Failure Indicators: 层级跳跃（如 `##` 直接到 `##` 无内容）、孤立表格行
    Evidence: .sisyphus/evidence/task-3-markdown-structure-valid.txt
  ```

  **Commit**: YES
  - Message: `docs: 重组 AGENTS.md — 消除与 steering docs 重复，纯化编码指引定位`
  - Files: `AGENTS.md`

---

- [x] 4. 根 AGENTS.md 内容完整性验证

  **What to do**:
  - 运行全套验证命令（见 Success Criteria）
  - 确认删除完整性和保留完整性
  - 检查 steering docs 引用路径有效性

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯验证，运行命令 + 检查结果
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave FINAL (with Task 5)
  - **Blocks**: None
  - **Blocked By**: Task 3

  **References**:
  - `AGENTS.md` — 验证目标文件
  - `docs/steering/接口设计文档.md` — 引用路径有效性
  - `docs/steering/数据库设计文档.md` — 引用路径有效性
  - `docs/steering/架构设计.md` — 引用路径有效性

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 全套验证命令通过
    Tool: Bash (PowerShell)
    Preconditions: Task 3 已完成
    Steps:
      1. 运行 Success Criteria 中全部 7 条验证命令
      2. 每条结果与预期值对比
    Expected Result: 全部 7 条命令返回预期值
    Failure Indicators: 任何一条命令返回值不符
    Evidence: .sisyphus/evidence/task-4-full-verification.txt

  Scenario: 引用路径有效性
    Tool: Bash (PowerShell Test-Path)
    Preconditions: Task 3 已完成
    Steps:
      1. Test-Path "docs/steering/接口设计文档.md" → True
      2. Test-Path "docs/steering/数据库设计文档.md" → True
      3. Test-Path "docs/steering/架构设计.md" → True
    Expected Result: 全部 True
    Failure Indicators: 任何 False（引用指向不存在的文件）
    Evidence: .sisyphus/evidence/task-4-references-valid.txt
  ```

  **Commit**: NO

---

- [x] 5. tests/AGENTS.md 引用一致性验证

  **What to do**:
  - 确认 tests/AGENTS.md 未被修改
  - 确认 tests/AGENTS.md 无对根 AGENTS.md 已删除内容的失效引用
  - 确认 8 个子模块 AGENTS.md 零改动

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯验证，grep 检查
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave FINAL (with Task 4)
  - **Blocks**: None
  - **Blocked By**: Task 3

  **References**:
  - `src/tests/AGENTS.md` — 确认无引用断裂
  - `src/runtime/AGENTS.md`, `src/knowledge_extension/AGENTS.md`, `src/data_platform/AGENTS.md`, `src/adapters/AGENTS.md`, `src/domain/AGENTS.md`, `src/apps/portal/AGENTS.md`, `src/apps/admin/AGENTS.md`, `src/apps/embed/AGENTS.md` — 确认零改动

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: tests/AGENTS.md 零改动
    Tool: Bash (git diff)
    Preconditions: Task 3 已完成
    Steps:
      1. 运行: git diff --name-only
      2. 确认输出中不含 src/tests/AGENTS.md
    Expected Result: src/tests/AGENTS.md 不在变更列表中
    Failure Indicators: src/tests/AGENTS.md 出现在变更列表中
    Evidence: .sisyphus/evidence/task-5-tests-agents-unchanged.txt

  Scenario: 子模块 AGENTS.md 零改动
    Tool: Bash (git diff)
    Preconditions: Task 3 已完成
    Steps:
      1. 运行: git diff --name-only
      2. 确认输出中不含任何子模块 AGENTS.md 路径
    Expected Result: 仅 AGENTS.md（根目录）出现在变更列表中
    Failure Indicators: 任何子模块 AGENTS.md 被修改
    Evidence: .sisyphus/evidence/task-5-sub-modules-unchanged.txt

  Scenario: tests/AGENTS.md 无失效引用
    Tool: Bash (PowerShell Select-String)
    Preconditions: Task 3 已完成
    Steps:
      1. 运行: Select-String -Path "src/tests/AGENTS.md" -Pattern "根 AGENTS|上级.*AGENTS|见.*AGENTS\.md"
      2. 如有匹配，确认引用内容在根 AGENTS.md 中仍存在
    Expected Result: 无匹配 或 匹配内容在根 AGENTS.md 中仍有效
    Failure Indicators: 引用了已被删除的内容
    Evidence: .sisyphus/evidence/task-5-no-stale-refs.txt
  ```

  **Commit**: NO

---

## Final Verification Wave

- [x] F1. **内容完整性审计** — `quick`
  运行全部验证命令：API 表行数为 0、DB 表行为 0、tests/AGENTS.md 引用存在、steering docs 引用路径有效。视觉检查 Markdown 渲染：无断裂表格、无孤立标题、节之间自然衔接。
  Output: `API表 [0行] | DB表 [0行] | 引用 [N条全有效] | 渲染 [正常] | VERDICT: APPROVE/REJECT`

- [x] F2. **Scope Fidelity Check** — `quick`
  用 `git diff` 确认仅修改了根 AGENTS.md 一个文件。8 个子模块 AGENTS.md 零改动。tests/AGENTS.md 零改动。docs/steering/ 零改动。
  Output: `Changed [1 file] | Unchanged [8+1+3 sub-dirs] | VERDICT: APPROVE/REJECT`

---

## Commit Strategy

- **Single commit**: `docs: 重组 AGENTS.md — 消除与 steering docs 重复，纯化编码指引定位` - AGENTS.md

---

## Success Criteria

### Verification Commands
```powershell
# API 表已删除（应返回 0 行）
Select-String -Path "AGENTS.md" -Pattern "^\| (POST|GET|PUT|DELETE)" | Measure-Object | Select-Object -ExpandProperty Count
# Expected: 0

# DB 表已删除（应返回 0 行）
Select-String -Path "AGENTS.md" -Pattern "^\| .*\|.*postgres\.py" | Measure-Object | Select-Object -ExpandProperty Count
# Expected: 0

# tests/AGENTS.md 引用存在（应返回 ≥1 行）
Select-String -Path "AGENTS.md" -Pattern "tests/AGENTS.md" | Measure-Object | Select-Object -ExpandProperty Count
# Expected: ≥1

# 路由前缀保留（应返回 1 行）
Select-String -Path "AGENTS.md" -Pattern "路由前缀" | Measure-Object | Select-Object -ExpandProperty Count
# Expected: 1

# 前端应用路由保留（应返回 ≥3 行）
Select-String -Path "AGENTS.md" -Pattern "portal/|admin/|embed/" | Measure-Object | Select-Object -ExpandProperty Count
# Expected: ≥3

# steering docs 引用有效
Test-Path "docs/steering/接口设计文档.md"   # Expected: True
Test-Path "docs/steering/数据库设计文档.md"  # Expected: True
Test-Path "docs/steering/架构设计.md"        # Expected: True
```

### Final Checklist
- [x] 所有 "Must Have" 存在
- [x] 所有 "Must NOT Have" 不存在
- [x] 仅 1 个文件被修改（根 AGENTS.md）
