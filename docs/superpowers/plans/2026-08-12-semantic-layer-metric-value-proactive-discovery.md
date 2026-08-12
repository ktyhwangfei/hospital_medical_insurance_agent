# 语义层指标与值域主动发现实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成设计定义的 V1/S1 最小纵向闭环：政策抽取未知概念汇总为可合并、可审核的指标/值域提议，并在发布后立即进入语义注册表契约。S2–S4 按设计 §11–§12 留作增量信号源。

**Architecture:** 复用 `SemanticAlignmentService` 作为唯一提议服务，复用现有 registry 与 alignment store，不另建平行门户或自动发布路径。所有信号先转换为 `DiscoverySignal`，由一个确定性路由生成指标或值域提议；审核 API 通过现有认证器门禁，发布动作写 registry 并刷新 `zcgz` 对象快照。

**Tech Stack:** Python 3、Pydantic、FastAPI、PostgreSQL/内存双存储、Next.js 16、React、Vitest。

---

### Task 1: 提议领域模型、合并、状态机与发布

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/semantic_alignment.py`
- Modify: `src/data_platform/storage/postgresql/semantic_alignment_store.py`
- Modify: `src/semantic_layer/registry.py`
- Test: `src/tests/unit/knowledge_extension/test_semantic_alignment.py`

- [x] **Step 1: Write the failing tests**

覆盖：新概念→指标提议、枚举轴新值→值域提议、已有标准值别名→仅映射；稳定概念键合并证据与置信度；合法/非法状态转移；Enum/Derived/值域提议发布后 registry 与 extraction schema 立即可读。

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest -p no:asyncio src/tests/unit/knowledge_extension/test_semantic_alignment.py -v`

Expected: FAIL because proactive proposal APIs and states do not exist.

- [x] **Step 3: Write minimal implementation**

在现有文件中增加 `DiscoverySignal`、`TriggerSource`、提议状态、结构化证据与建议映射字段；以稳定 ID 作为去重键，存储增加 list/save；发布时分别保存 `Metric`、`ValueDomain`、`ValueDomainMapping`，Derived 公式写入 `Metric.transformation`。

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest -p no:asyncio src/tests/unit/knowledge_extension/test_semantic_alignment.py -v`

Expected: PASS.

### Task 2: S1 抽取钩子（S2–S4 明确延后）

**Files:**
- Modify: `src/semantic_layer/extraction_contract.py`
- Modify: `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py`
- Test: `src/tests/unit/semantic_layer/test_extraction_contract.py`
- Test: `src/tests/unit/knowledge_extension/test_pipeline_orchestrator.py`

- [x] **Step 1: Write failing signal-source tests**

断言 schema prompt 要求 LLM 返回 `unknown_concepts`；抽取持久化后发送 `EXTRACTION_UNKNOWN`。S2 `DEMAND_GAP`、S3 `DATA_SCAN`、S4 `DERIVATION_PATTERN` 依设计作为后续增量排队，不在 S1 用户故事完成前扩展。

- [x] **Step 2: Run focused tests and observe expected failures**

Run the exact new test nodes with `python -m pytest -p no:asyncio ... -v`.

- [x] **Step 3: Add one-line hooks at authoritative aggregation points**

信号源只负责构造 `DiscoverySignal` 并调用统一 intake；失败仅记录日志，不得破坏原抽取、问答、扫描或编译主流程。

- [x] **Step 4: Re-run focused tests**

Expected: PASS.

### Task 3: 审核 API 与权限、变更门禁

**Files:**
- Modify: `src/runtime/api/semantic_alignment_routes.py`
- Modify: `src/runtime/api/semantic_routes.py`
- Test: `src/tests/integration/api/test_semantic_alignment_api.py`
- Test: `src/tests/integration/flow/test_semantic_proposal_flow.py`

- [x] **Step 1: Write failing API/flow tests**

覆盖指标/值域列表；打开进入 reviewing；接受、发布、驳回及归档；未授权写操作 401/403；发布后 extraction schema 可读；修改 `semantic_type` 或 `indexed` 时强制 `schema_version + 1` 并返回存量重提取标记。

- [x] **Step 2: Run API test and verify failure**

Run: `python -m pytest -p no:asyncio src/tests/integration/api/test_semantic_alignment_api.py -v`

- [x] **Step 3: Implement minimal endpoints and shared auth dependency**

读取列表可保持只读；review/accept/publish/reject 使用 `semantic:review` 权限并从认证身份取得审核人，禁止请求体伪造审核人。

- [x] **Step 4: Run API then Flow tests**

Run API first; only after green run `python -m pytest -p no:asyncio src/tests/integration/flow/test_semantic_proposal_flow.py -v`.

### Task 4: Portal 统一审核区

**Files:**
- Create: `src/apps/portal/app/semantic-layer/proposals/page.tsx`
- Modify: `src/apps/portal/app/semantic-layer/layout.tsx`
- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Create: `src/apps/portal/src/tests/semantic-layer/semantic-proposals-page.test.tsx`

- [x] **Step 1: Write the failing Vitest**

覆盖双 tab、证据展开、可信度、建议映射、通过/驳回、状态刷新和错误提示。

- [x] **Step 2: Run and observe failure**

Run: `npm test -- --run src/tests/semantic-layer/semantic-proposals-page.test.tsx` from `src/apps/portal`.

- [x] **Step 3: Implement one page using existing fetch and visual patterns**

不引入新依赖；所有服务端字段保持 snake_case；写操作携带现有开发认证头约定。

- [x] **Step 4: Run Vitest and TypeScript**

Run the focused Vitest, then `npx tsc --noEmit`.

### Task 5: 文档、回归与完成审计

**Files:**
- Modify: `src/domain/AGENTS.md`
- Modify: `PROGRESS.md`
- Modify: `docs/steering/政策知识治理-需求迭代记录.md`
- Create: `src/tests/performance/scenarios/semantic_alignment_api.py`
- Create: `src/tests/e2e/pages/portal/semantic-proposals.page.ts`
- Create: `src/tests/e2e/flows/portal/semantic-proposals.flow.ts`

- [x] **Step 1: Update glossary and progress evidence**

登记主动发现信号、指标提议、值域提议及生命周期；不声称未运行的测试通过。

- [x] **Step 2: Run R4 verification strictly in order**

T1 focused semantic/alignment/signal tests → T2a semantic alignment API → T2b proposal flow → T3 Locust → T4 Playwright；Portal Vitest、TypeScript/build 同步验证。

- [x] **Step 3: Requirement-by-requirement audit**

逐项核对设计 §1.4、§4–§8、§10–§12；检查提议绝不自动写 registry、输出证据可追溯、敏感字段不暴露、发布后契约无需额外同步。
