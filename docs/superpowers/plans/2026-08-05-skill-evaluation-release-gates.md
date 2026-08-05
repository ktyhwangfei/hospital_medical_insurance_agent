# Skill Batch Evaluation and Test Release Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` to implement this plan task-by-task.

**Goal:** 让 Skill 开发者能够用固定、脱敏的路由用例比较候选版本与基线版本，并确保版本只有在必测用例全部通过、证据冻结且人工审批后，才能成为 test 环境唯一的 active release。

**Architecture:** `src/domain/skill` 定义评测运行与发布状态机；`src/skill_infra` 只用不可变 Manifest 快照执行确定性关键词路由评测；`src/data_platform/storage/skill` 通过统一端口提供内存/PostgreSQL 存储；`src/runtime/skill_management` 编排用例、评测、候选、审批和激活；Portal 新增“批量评测”和“测试发布”页签。test active 只作为控制面 shadow 解析结果，不改变现有 `SkillLoader`、`SkillRouter` 或真实业务执行路径。

**Tech Stack:** Python 3.12、Pydantic v2、FastAPI、PostgreSQL JSONB、Next.js 16、React 19、TypeScript、pytest、Vitest、Playwright。

---

## 范围、成功标准与非目标

- 实施详细设计的“阶段 2：批量评测与发布门禁”，仅开放 `dev/test` 环境。
- 固定用例保存脱敏问题模板，不保存患者上下文或原始业务数据。
- 候选路由使用 `SkillVersion.manifest_snapshot`，因此能评测历史不可变版本，不依赖工作区当前文件。
- test 激活必须同时满足：版本校验通过、评测运行通过、评测与候选版本一致、证据未变化、人工审批有效、基线仍一致。
- 同一 `skill_id + environment` 最多一个 active release；激活新版本时旧 active 在同一存储操作中转为 retired。
- Release Resolver 只返回 shadow 选择，不接管当前运行时流量；生产权限、灰度、回滚、运行指标留到阶段 3。
- R4 验证严格按 T1 单元测试 → T2a API 测试 → T2b Flow/E2E 测试顺序执行。

## 文件结构

- Create: `src/domain/skill/governance_models.py` — 评测用例、运行结果、发布、审批和状态枚举。
- Modify: `src/domain/skill/__init__.py` — 导出治理模型。
- Modify: `src/domain/AGENTS.md` — 补充 Skill 治理通用语言和生命周期。
- Modify: `src/skill_infra/unified_router.py` — 保持旧私有入口，抽取可复用的纯关键词评分契约。
- Create: `src/skill_infra/route_evaluator.py` — 基于 Manifest 快照的候选/基线路由与差异指标。
- Create: `src/data_platform/storage/skill/governance_ports.py` — 治理存储端口与冲突异常。
- Create: `src/data_platform/storage/skill/governance_in_memory.py` — 内存实现和原子 active 切换。
- Create: `src/data_platform/storage/skill/governance_postgres.py` — 四张治理表及 PostgreSQL 实现。
- Create: `src/data_platform/storage/skill/governance_factory.py` — 存储工厂。
- Create: `src/runtime/skill_management/governance_service.py` — 评测和发布门禁编排、shadow resolver。
- Create: `src/runtime/api/skill_schemas.py` — 显式评测/发布请求响应 DTO。
- Modify: `src/runtime/api/infra_skill_routes.py` — 新增评测与发布端点。
- Modify: `src/apps/portal/src/lib/types.ts` — 前端治理 DTO。
- Modify: `src/apps/portal/src/lib/api-client.ts` — 评测和发布 API。
- Create: `src/apps/portal/src/components/skills/skill-evaluation-suite.tsx` — 固定用例、运行与差异展示。
- Create: `src/apps/portal/src/components/skills/skill-release-panel.tsx` — test 候选、审批和激活面板。
- Modify: `src/apps/portal/src/components/infra-skill-management.tsx` — 接入两个详情页签。
- Create: `src/tests/unit/domain/skill/test_skill_governance_models.py`
- Create: `src/tests/unit/skill_infra/test_route_evaluator.py`
- Create: `src/tests/unit/data_platform/test_skill_governance_storage.py`
- Create: `src/tests/unit/runtime/skill_management/test_governance_service.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`
- Create: `src/tests/integration/flow/test_skill_evaluation_release_flow.py`
- Create: `src/apps/portal/src/tests/skill-governance.test.ts`
- Modify: `src/tests/e2e/pages/portal/skill-catalog.page.ts`
- Modify: `src/tests/e2e/flows/portal/skill-catalog.flow.ts`
- Modify: `PROGRESS.md`

### Task 1: 评测与发布领域模型

**Files:** `src/domain/skill/governance_models.py`, `src/domain/skill/__init__.py`, `src/domain/AGENTS.md`, `src/tests/unit/domain/skill/test_skill_governance_models.py`

- [x] **Step 1: 写失败测试，锁定不可变证据与状态值**

```python
def test_release_approval_freezes_all_gate_evidence() -> None:
    approval = SkillReleaseApproval(
        approval_id="approval-1",
        release_id="release-1",
        artifact_hash="a" * 64,
        eval_run_id="run-1",
        config_hash="b" * 64,
        baseline_release_id=None,
        approved_by="quality-user",
        approver_role="quality",
        reason="固定用例全部通过",
    )
    with pytest.raises(ValidationError):
        approval.artifact_hash = "c" * 64


def test_release_rejects_unsupported_rollout_or_environment() -> None:
    with pytest.raises(ValidationError):
        _release(environment="prod")
```

- [x] **Step 2: 运行测试并确认模块不存在**

Run: `uv run --frozen python -m pytest src/tests/unit/domain/skill/test_skill_governance_models.py -q --tb=short`

- [x] **Step 3: 实现最小模型**

模型包括 `SkillEvalCase`、`SkillEvalResult`、`SkillEvalMetrics`、`SkillEvalRun`、`SkillRelease`、`SkillReleaseApproval`，以及 `SkillEvalRunStatus`、`SkillEvalDiff`、`SkillReleaseEnvironment`、`SkillReleaseStatus`。所有证据模型 `ConfigDict(frozen=True)`；哈希限定 64 位小写 SHA-256；环境仅 `dev/test`；发布 revision 从 1 开始。

- [x] **Step 4: 更新领域通用语言字典并运行测试**

Run: `uv run --frozen python -m pytest src/tests/unit/domain/skill/test_skill_governance_models.py -q --tb=short`

Expected: PASS。

Commit: `feat: model skill evaluation and release gates`

### Task 2: 不可变 Manifest 路由评测器

**Files:** `src/skill_infra/unified_router.py`, `src/skill_infra/route_evaluator.py`, `src/tests/unit/skill_infra/test_route_evaluator.py`, `src/tests/unit/skill_infra/test_unified_router.py`

- [x] **Step 1: 写候选/基线差异失败测试**

```python
def test_evaluate_route_suite_marks_new_failure() -> None:
    case = _case(question="统筹自付怎么算", expected_skill_id="settlement")
    baseline = [_manifest("settlement", include_keywords=["统筹自付"])]
    candidate = [_manifest("settlement", include_keywords=["起付线"])]
    run = evaluate_route_suite([case], candidate, baseline)
    assert run.metrics.required_passed == 0
    assert run.metrics.regression_count == 1
    assert run.results[0].diff == SkillEvalDiff.NEW_FAILURE
```

- [x] **Step 2: 运行并确认失败**

Run: `uv run --frozen python -m pytest src/tests/unit/skill_infra/test_route_evaluator.py -q --tb=short`

- [x] **Step 3: 抽取评分 Protocol 并实现评测器**

`unified_router._compute_keyword_score` 保持兼容并委托给公开纯函数；`route_evaluator` 将 Manifest 快照转换为只读候选，使用与线上 keyword router 相同的评分和排序。门禁计算：必测通过率 100%、总体准确率不低于基线、新增误接管 0；差异分类为 `unchanged_pass / unchanged_fail / new_pass / new_failure / route_changed`。

- [x] **Step 4: 运行新旧路由测试**

Run: `uv run --frozen python -m pytest src/tests/unit/skill_infra/test_route_evaluator.py src/tests/unit/skill_infra/test_unified_router.py -q --tb=short`

Expected: PASS，旧线上路由行为不变。

Commit: `feat: evaluate skill routes from immutable manifests`

### Task 3: 治理存储端口与适配器

**Files:** `src/data_platform/storage/skill/governance_ports.py`, `src/data_platform/storage/skill/governance_in_memory.py`, `src/data_platform/storage/skill/governance_postgres.py`, `src/data_platform/storage/skill/governance_factory.py`, `src/tests/unit/data_platform/test_skill_governance_storage.py`

- [x] **Step 1: 写存储契约失败测试**

```python
def test_activation_retires_previous_active_atomically() -> None:
    storage = InMemorySkillGovernanceStorage()
    old = storage.save_release(_release("old", status="active"))
    candidate = storage.save_release(_release("new", status="approved"))
    active = storage.activate_release(candidate.release_id, expected_revision=1)
    assert active.status == SkillReleaseStatus.ACTIVE
    assert storage.get_release(old.release_id).status == SkillReleaseStatus.RETIRED
    assert len(storage.list_active_releases("demo", "test")) == 1


def test_activation_rejects_stale_revision() -> None:
    with pytest.raises(SkillGovernanceConflictError):
        storage.activate_release("new", expected_revision=2)
```

- [x] **Step 2: 运行并确认失败**

Run: `uv run --frozen python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q --tb=short`

- [x] **Step 3: 实现端口、深拷贝内存实现和 PostgreSQL 表**

PostgreSQL 新增 `skill_eval_cases`、`skill_eval_runs`、`skill_releases`、`skill_release_approvals`。逐案结果以内嵌 JSONB 保存在 run 中，避免本阶段引入第五张表；不保存患者上下文。active 唯一性通过部分唯一索引保证：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_release_active
ON skill_releases(skill_id, environment)
WHERE status = 'active';
```

激活在一个事务内锁定候选与当前 active，校验 revision，退休旧 active，再激活候选。工厂遵循 `USE_MEMORY_STORAGE`。

- [x] **Step 4: 运行存储测试**

Run: `uv run --frozen python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q --tb=short`

Expected: PASS。

Commit: `feat: persist skill evaluation and release state`

### Task 4: 评测与发布应用服务

**Files:** `src/runtime/skill_management/governance_service.py`, `src/tests/unit/runtime/skill_management/test_governance_service.py`

- [x] **Step 1: 写完整门禁失败测试**

覆盖：新增/更新用例递增 suite version；创建运行从 immutable version manifest 执行；必测失败时 run 为 failed；失败 run 不能创建 candidate；未申请审批不能 approve；未 approve 不能 activate；基线变化或审批证据变化拒绝 activate；通过路径成为唯一 test active。

- [x] **Step 2: 运行并确认失败**

Run: `uv run --frozen python -m pytest src/tests/unit/runtime/skill_management/test_governance_service.py -q --tb=short`

- [x] **Step 3: 实现服务和 shadow resolver**

核心流程：

```text
create_eval_run(version_id, baseline_version_id?)
  → snapshot enabled cases + suite_version
  → assemble runtime manifests and replace target with immutable candidate/baseline snapshot
  → evaluate + hash gate config
  → persist completed passed/failed run

create_candidate(version_id, eval_run_id, environment=test)
  → validate version/run/gate/baseline
request_approval(release_id, expected_revision)
  → freeze artifact/eval/config/baseline evidence
approve(release_id, approver, role, reason, expected_revision)
  → save immutable approval + approved release
activate(release_id, expected_revision)
  → revalidate evidence and baseline + atomic active switch
resolve_shadow(skill_id, environment)
  → return active release/version without changing actual execution
```

- [x] **Step 4: 运行应用服务及前置单元测试**

Run: `uv run --frozen python -m pytest src/tests/unit/domain/skill/test_skill_governance_models.py src/tests/unit/skill_infra/test_route_evaluator.py src/tests/unit/data_platform/test_skill_governance_storage.py src/tests/unit/runtime/skill_management/test_governance_service.py -q --tb=short`

Expected: PASS。

Commit: `feat: enforce skill test release gates`

### Task 5: 控制面 API

**Files:** `src/runtime/api/skill_schemas.py`, `src/runtime/api/infra_skill_routes.py`, `src/tests/integration/api/test_infra_skill_routes.py`

- [x] **Step 1: 写 API 失败测试**

测试用户故事：创建脱敏用例 → 同步版本 → `POST eval-runs` 返回 202 且结果 passed → 创建 test candidate → 未审批激活返回 409 + `gate_failures` → request-approval → approve → activate → 查询只有一个 active。额外覆盖敏感样本拒绝 422、失败评测拒绝 candidate、stale revision 返回 409。

- [x] **Step 2: 运行并确认新增端点 404**

Run: `uv run --frozen python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

- [x] **Step 3: 实现显式 DTO 和端点**

新增端点必须声明在 `/{skill_id}` 动态详情路由之前：

```text
GET/POST /infra-skills/eval-cases
PUT      /infra-skills/eval-cases/{case_id}
GET/POST /infra-skills/{skill_id}/eval-runs
GET      /infra-skills/{skill_id}/eval-runs/{run_id}
GET/POST /infra-skills/{skill_id}/releases
POST     /infra-skills/{skill_id}/releases/{release_id}/request-approval
POST     /infra-skills/{skill_id}/releases/{release_id}/approve
POST     /infra-skills/{skill_id}/releases/{release_id}/activate
```

评测计算是本地确定性操作，API 以 `202 Accepted` 返回已经落库的终态 run，保留未来替换后台任务的契约。所有冲突使用 `error_detail()`；门禁错误的 `audit_event` 包含结构化 `gate_failures`，不拼接患者内容。

- [x] **Step 4: 按 T1 → T2a 顺序验证并提交**

Run 1: Task 4 的单元测试命令。

Run 2: `uv run --frozen python -m pytest src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_infra_skill_workbench_api.py -q --tb=short`

Expected: PASS，旧端点保持兼容。

Commit: `feat: expose skill evaluation and test releases`

### Task 6: Portal 批量评测与测试发布页签

**Files:** `src/apps/portal/src/lib/types.ts`, `src/apps/portal/src/lib/api-client.ts`, `src/apps/portal/src/components/skills/skill-evaluation-suite.tsx`, `src/apps/portal/src/components/skills/skill-release-panel.tsx`, `src/apps/portal/src/components/infra-skill-management.tsx`, `src/apps/portal/src/tests/skill-governance.test.ts`

- [x] **Step 1: 写前端 API 客户端失败测试**

验证路径编码、snake_case DTO、`Idempotency-Key` 和 `expected_revision` 请求体；为评测运行和发布激活动作各覆盖一个请求。

- [x] **Step 2: 运行并确认导出不存在**

Run: `npm exec vitest run src/tests/skill-governance.test.ts` (workdir `src/apps/portal`)

- [x] **Step 3: 实现类型、客户端和两个最小组件**

“批量评测”页签展示用例总数、最近运行、必测通过率、候选/基线差异和失败原因；允许新增脱敏问题并对已登记版本运行评测。“测试发布”页签展示门禁状态、revision、审批证据和 shadow 标识；按钮严格按 candidate → approval_pending → approved → active 启用，不在前端自行推导服务端门禁。

- [x] **Step 4: 接入详情工作区，处理局部错误而不清空其他页签**

组件仅接收 `skillId` 与 `versions`，自行维护局部 loading/error/mutation 状态。

- [x] **Step 5: 运行 Vitest、目标 ESLint 和构建**

Run 1: `npm exec vitest run src/tests/skill-catalog.test.ts src/tests/skill-governance.test.ts`

Run 2: `npm exec eslint src/lib/api-client.ts src/lib/types.ts src/components/infra-skill-management.tsx src/components/skills/skill-evaluation-suite.tsx src/components/skills/skill-release-panel.tsx src/tests/skill-governance.test.ts`

Run 3: `npm run build`

Expected: PASS。

Commit: `feat: manage skill evaluations and test releases`

### Task 7: Flow、浏览器验证与进度

**Files:** `src/tests/integration/flow/test_skill_evaluation_release_flow.py`, `src/tests/e2e/pages/portal/skill-catalog.page.ts`, `src/tests/e2e/flows/portal/skill-catalog.flow.ts`, `PROGRESS.md`

- [ ] **Step 1: 写后端 Flow 测试**

完整故事使用内存存储：登记版本 → 创建必测用例 → 评测通过 → candidate → request approval → approve → test active → shadow resolver 返回该版本；另断言第二个 active 不会共存。

- [ ] **Step 2: 先运行 T1，再运行 API，再运行 Flow**

Run 1: Task 4 单元测试命令。

Run 2: Task 5 API 测试命令。

Run 3: `uv run --frozen python -m pytest src/tests/integration/flow/test_skill_evaluation_release_flow.py -q --tb=short`

Expected: 三阶段全部 PASS。

- [ ] **Step 3: 扩展 Portal E2E**

浏览器流程验证：打开 `/skills` → 选择 Skill → 查看“批量评测” → 运行固定用例 → 查看“测试发布”门禁 → 完成人工审批 → 页面显示 `test active / shadow`。API 数据使用测试专用内存存储，测试后停止服务器。

- [ ] **Step 4: 使用项目脚本启动并执行浏览器验证**

Run 1: `.\start-servers.ps1`

Run 2: 运行 `src/tests/e2e/flows/portal/skill-catalog.flow.ts` 对应 Playwright 命令。

Run 3: `.\stop-servers.ps1`

Expected: PASS，且浏览器控制台无本功能新增错误。

- [ ] **Step 5: 更新 PROGRESS 并最终复验**

记录阶段 2 的文件、提交、T1/T2a/T2b/前端/E2E 证据；预存失败只如实记录，不扩大修改范围。

- [ ] **Step 6: 提交**

Commit: `test: verify skill evaluation release flow`

## 计划自审

- 领域、存储、API、前端字段统一使用 snake_case；无裸 `dict` 作为新增后端返回类型。
- 历史版本评测只读取不可变 Manifest 快照，不把工作区当前内容误当历史制品。
- 评测问题是脱敏模板；新增请求显式拒绝 `contains_sensitive_data=true`。
- 人工审批绑定 `artifact_hash + eval_run_id + config_hash + baseline_release_id`，激活前重新校验。
- active 唯一性由领域服务、存储事务和数据库唯一索引三层保证。
- 阶段 2 不接管真实运行时，不引入 prod、灰度或回滚，避免越过已批准范围。
- 每个实现任务均先写失败测试，最终验证严格遵守 T1 → T2a → T2b。
