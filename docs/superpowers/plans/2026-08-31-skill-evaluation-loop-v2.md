# 通用 Skill 评测闭环 V2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `SkillEvalSuite` 上交付版本化端到端任务、真实 Policy QA 运行、确定性验证与可选 Judge、失败归因、Benchmark 对比和改进任务闭环，并以 `mzsettlement_verify_skill` 的 28 条门诊样例完成首个真实 Benchmark。

**Architecture:** 延续现有 Skill 治理聚合，不建设平行评测平台。新增任务、数据集版本、Benchmark 三类持久化资产；任务结果、轨迹、归因和失败簇继续作为 `SkillEvalRun` 的不可变 JSONB 快照，改进任务复用 `runtime/task_closure` 并按运行动态关联。执行器复用真实 `_policy_qa_stream`、既有回归验证器和 `ModelGateway`。

**Tech Stack:** Python 3.13、Pydantic 2、FastAPI、PostgreSQL、Next.js 16、React、TypeScript、pytest、Vitest。

**Design:** `docs/superpowers/specs/2026-08-31-skill-evaluation-center-design.md`

**Execution:** 用户已选择在当前 session 串行执行，不使用子 Agent。

**Risk:** R4。涉及领域模型、PostgreSQL DDL、真实 Policy QA 执行、模型网关、API、发布门禁和 Portal；每个代码任务按 Unit → API → Flow 顺序验证，最终再做 Portal 测试和构建。

**Compatibility:** 旧 `/infra-skills/eval-cases*`、`/infra-skills/{skill_id}/eval-runs*`、路由 `suite_version` 和 Release 证据继续有效；旧门诊 `/self-tests*` 在任务导入完成前保留只读与执行兼容，不删除 YAML。

**Ponytail boundary:** 首版只提供 `after_settlement_loaded` 可恢复 prefix，足以区分取数/上下文问题与后续路由、计算、引用、回答问题。只有真实失败证明需要更细边界时，才增加 `after_skill_selected` 或 `after_policy_retrieved`。

---

## 文件结构与职责

| 文件 | 责任 |
|---|---|
| `src/domain/skill/governance_models.py` | Task、DatasetVersion、Benchmark、任务结果、轨迹、归因及运行扩展 |
| `src/domain/AGENTS.md` | 新领域术语与不可变性规则 |
| `src/data_platform/storage/skill/governance_ports.py` | 三类新资产的存储协议 |
| `src/data_platform/storage/skill/governance_in_memory.py` | 内存实现 |
| `src/data_platform/storage/skill/governance_postgres.py` | 三张新表、运行扩展列及 CREATE/ALTER 兼容 |
| `src/runtime/skill_management/evaluation_runner.py` | 消费真实 Policy QA SSE、规范化输出、prefix 接力和轨迹捕获 |
| `src/runtime/skill_management/evaluation_judge.py` | 通过 ModelGateway 执行一次严格 JSON Rubric Judge |
| `src/runtime/skill_management/evaluation_attribution.py` | 状态派生、稳定归因和失败聚类纯函数 |
| `src/runtime/skill_management/governance_service.py` | Task CRUD、冻结版本、Benchmark、运行、门禁和改进任务动态关联 |
| `src/runtime/api/policy_qa_routes.py` | 增加仅服务端可用的评测观察器和单个 prefix 接力输入 |
| `src/runtime/api/skill_schemas.py` | 显式 API DTO |
| `src/runtime/api/infra_skill_routes.py` | 数据集、任务、Benchmark、运行和改进 API |
| `skills/mzsettlement_verify_skill/self_tests.py` | 28 条 YAML 到通用 Task 的无副作用转换函数 |
| `src/apps/portal/src/lib/types.ts` | 前端 DTO |
| `src/apps/portal/src/lib/api-client.ts` | 新 API 客户端 |
| `src/apps/portal/app/skills/evaluations/page.tsx` | 四工作区页面编排和 Skill 深链锁定 |
| `src/apps/portal/src/components/skills/skill-eval-suite-panel.tsx` | 数据集工作区、版本冻结和停用集恢复 |
| `src/apps/portal/src/components/skills/outpatient-self-test-panel.tsx` | 迁移为门诊任务导入与覆盖摘要，不再独立运行 |
| `src/apps/portal/src/components/skills/skill-eval-launch-panel.tsx` | 绑定 Benchmark 发起真实运行 |
| `src/apps/portal/src/components/skills/skill-eval-run-detail.tsx` | 分维度结果、轨迹、归因、失败簇与改进链接 |
| `src/tests/unit/domain/skill/test_skill_evaluation_dataset.py` | 领域约束、哈希、状态、归因 |
| `src/tests/unit/data_platform/test_skill_governance_storage.py` | 新资产往返和 DDL 覆盖 |
| `src/tests/unit/runtime/skill_management/test_evaluation_runner.py` | SSE 解析、硬断言优先、prefix 诊断、Judge 阻塞 |
| `src/tests/integration/api/test_infra_skill_routes.py` | 新 API、权限、版本绑定和兼容 |
| `src/tests/integration/flow/test_skill_eval_benchmark_flow.py` | 门诊导入→冻结→运行→归因→改进任务→复测闭环 |
| `src/apps/portal/src/tests/components/skill-eval-suite-panel.test.tsx` | 数据集版本交互 |
| `src/apps/portal/src/tests/components/outpatient-self-test-panel.test.tsx` | 门诊导入与覆盖 |
| `src/apps/portal/src/tests/skill-eval-launch-panel.test.tsx` | 深链 Skill 和 Benchmark 运行 |
| `src/apps/portal/src/tests/skill-eval-run-detail.test.tsx` | 分维度与失败归因展示 |
| `PROGRESS.md` | 新最小可验证单元和验证证据 |

---

### Task 1: 建立端到端任务与 Benchmark 领域契约

**Files:**

- Modify: `src/domain/skill/governance_models.py`
- Modify: `src/domain/AGENTS.md`
- Create: `src/tests/unit/domain/skill/test_skill_evaluation_dataset.py`

- [ ] **Step 1: 写领域失败测试**

```python
from decimal import Decimal

import pytest

from src.domain.skill.governance_models import (
    SkillEvalAssertion,
    SkillEvalDatasetVersion,
    SkillEvalPartition,
    SkillEvalTask,
    SkillEvalTaskInput,
    canonical_eval_hash,
)
from src.domain.skill.regression_models import CalculationAssertions


def _task() -> SkillEvalTask:
    return SkillEvalTask(
        task_id="EVT_person_21",
        suite_id="EVS_mz",
        target_skill_id="mzsettlement_verify_skill",
        name="退休职工门诊费用组成",
        partition=SkillEvalPartition.REGRESSION,
        input=SkillEvalTaskInput(
            question="费用组成",
            settlement_id="011100030X260417004975",
        ),
        assertions=[SkillEvalAssertion(
            assertion_id="self_pay_one",
            dimension="behavior",
            output_adapter="self_pay_one",
            expected=CalculationAssertions(expected_value=510.96, tolerance=0.0),
        )],
        source_type="outpatient_self_test",
        source_ref="person-21",
        created_by="quality-user",
        updated_by="quality-user",
    )


def test_dataset_hash_is_stable_and_version_is_frozen() -> None:
    task = _task()
    first = canonical_eval_hash([task.model_dump(mode="json")])
    second = canonical_eval_hash([task.model_dump(mode="json")])
    assert first == second
    version = SkillEvalDatasetVersion(
        dataset_version_id="EVD_1",
        suite_id=task.suite_id,
        suite_revision=1,
        version_number=1,
        task_snapshots=[task],
        environment_contract_hash="a" * 64,
        evaluator_plan_hash="b" * 64,
        content_hash=first,
        created_by="quality-user",
    )
    with pytest.raises(Exception):
        version.task_snapshots.append(task)


def test_task_rejects_missing_assertions() -> None:
    with pytest.raises(ValueError, match="assertion"):
        SkillEvalTask.model_validate({**_task().model_dump(), "assertions": []})
```

- [ ] **Step 2: 运行测试确认红灯**

Run:

```powershell
uv run python -m pytest src/tests/unit/domain/skill/test_skill_evaluation_dataset.py -q
```

Expected: 新领域符号不存在，测试收集失败。

- [ ] **Step 3: 增加最小领域模型**

在 `governance_models.py` 复用已有 `_utc_now`，增加稳定哈希函数和以下 frozen Pydantic 模型：

```python
def canonical_eval_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SkillEvalPartition(StrEnum):
    REGRESSION = "regression"
    BENCHMARK = "benchmark"
    HOLDOUT = "holdout"


class SkillEvalTaskStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"
    INVALID_DATASET = "invalid_dataset"


class SkillEvalTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question: str = Field(min_length=1, max_length=2000)
    settlement_id: str | None = Field(default=None, max_length=80)
    role: str = Field(default="cashier", max_length=64)


class SkillEvalAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assertion_id: str = Field(min_length=1, max_length=80)
    dimension: Literal[
        "route", "behavior", "calculation", "policy_content",
        "citation", "answer_quality", "safety",
    ]
    output_adapter: Literal[
        "route", "self_pay_one", "public_answer", "citation", "safety"
    ]
    expected: RegressionAssertions
    required: bool = True


class TrajectoryPrefix(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    prefix_id: str = Field(min_length=1, max_length=80)
    boundary_kind: Literal["after_settlement_loaded"]
    state_schema_version: Literal["policy_qa_prefix_v1"] = "policy_qa_prefix_v1"


class SkillEvalTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str = Field(min_length=1, max_length=80)
    suite_id: str = Field(min_length=1, max_length=64)
    target_skill_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    partition: SkillEvalPartition = SkillEvalPartition.REGRESSION
    input: SkillEvalTaskInput
    assertions: list[SkillEvalAssertion] = Field(min_length=1)
    trajectory_prefixes: list[TrajectoryPrefix] = Field(default_factory=list)
    required: bool = True
    enabled: bool = True
    source_type: str = Field(default="manual", max_length=64)
    source_ref: str = Field(default="", max_length=256)
    risk_tags: list[str] = Field(default_factory=list)
    business_tags: list[str] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    created_by: str = Field(min_length=1, max_length=128)
    updated_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class SkillEvalDatasetVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_version_id: str
    suite_id: str
    suite_revision: int = Field(ge=1)
    version_number: int = Field(ge=1)
    task_snapshots: tuple[SkillEvalTask, ...]
    environment_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str
    created_at: datetime = Field(default_factory=_utc_now)


class SkillEvalEnvironmentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    runtime_version: str
    data_source_mode: str
    policy_version: str | None = None
    semantic_version: str | None = None
    tool_registry_version: str | None = None
    security_policy_version: str | None = None


class SkillEvalGateThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    required_hard_pass_rate: float = Field(default=1.0, ge=0, le=1)
    max_new_failures: int = Field(default=0, ge=0)


class SkillEvalBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    benchmark_id: str
    name: str
    skill_id: str
    dataset_version_id: str
    environment_snapshot: SkillEvalEnvironmentSnapshot
    environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_plan_id: str = "deterministic_v1"
    evaluator_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_version: str | None = None
    gate_thresholds: SkillEvalGateThresholds = Field(default_factory=SkillEvalGateThresholds)
    created_by: str
    created_at: datetime = Field(default_factory=_utc_now)
```

给 `SkillEvalRun` 增加有默认值的兼容字段：`dataset_version_id`、`benchmark_id`、`environment_snapshot`、`task_results`、`trajectory_summary`、`failure_attributions`、`failure_clusters`、`dimension_summary`。新增 `SkillEvalTrajectoryStep`、`SkillEvalAssertionResult`、`SkillEvalTaskResult`、`FailureAttribution`、`FailureCluster`、`SkillEvalDimensionSummary` frozen DTO，列表字段只引用这些 DTO，不使用裸字典。`SkillEvalAssertion.dimension` 独立表达业务评测维度，`expected` 继续复用现有五类回归断言，避免为首个 Benchmark 新增第六套验证器。

- [ ] **Step 4: 更新通用语言并验证**

在 `src/domain/AGENTS.md` SkillTool 术语表增加 `SkillEvalTask`、`SkillEvalDatasetVersion`、`SkillEvalBenchmark`、`TrajectoryPrefix`、`FailureAttribution`，并明确 DatasetVersion、Benchmark、Run 均不可变。

Run:

```powershell
uv run python -m pytest src/tests/unit/domain/skill/test_skill_evaluation_dataset.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/domain/skill/governance_models.py src/domain/AGENTS.md src/tests/unit/domain/skill/test_skill_evaluation_dataset.py
git commit -m "feat: 增加 Skill 端到端评测契约"
```

---

### Task 2: 持久化任务、数据集版本和 Benchmark

**Files:**

- Modify: `src/data_platform/storage/skill/governance_ports.py`
- Modify: `src/data_platform/storage/skill/governance_in_memory.py`
- Modify: `src/data_platform/storage/skill/governance_postgres.py`
- Modify: `src/tests/unit/data_platform/test_skill_governance_storage.py`

- [ ] **Step 1: 写存储失败测试**

增加一个测试，保存任务、冻结版本和 Benchmark 后分别读取，并断言旧运行字段默认可读；另扩展 `test_skill_eval_runs_insert_columns_covered_by_ddl`，要求 `dataset_version_id`、`benchmark_id`、`environment_snapshot`、`task_results`、`trajectory_summary`、`failure_attributions`、`failure_clusters`、`dimension_summary` 同时出现在 CREATE 和 ALTER 覆盖集合。

```python
def test_dataset_assets_round_trip() -> None:
    storage = InMemorySkillGovernanceStorage()
    suite = storage.save_suite(_suite())
    task = _eval_task(suite.suite_id)
    storage.save_task(task)
    version = _dataset_version(task)
    storage.save_dataset_version(version)
    benchmark = _benchmark(version)
    storage.save_benchmark(benchmark)
    assert storage.list_tasks(suite.suite_id) == [task]
    assert storage.get_dataset_version(version.dataset_version_id) == version
    assert storage.get_benchmark(benchmark.benchmark_id) == benchmark
```

- [ ] **Step 2: 运行测试确认红灯**

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: 新存储方法和 DDL 列不存在。

- [ ] **Step 3: 扩展存储协议和内存实现**

给 `SkillGovernanceStorage` 增加：

```python
def save_task(self, task: SkillEvalTask) -> SkillEvalTask: ...
def get_task(self, task_id: str) -> SkillEvalTask | None: ...
def list_tasks(self, suite_id: str, *, enabled_only: bool = False) -> list[SkillEvalTask]: ...
def update_task(self, task: SkillEvalTask, *, expected_revision: int) -> SkillEvalTask: ...
def save_dataset_version(self, version: SkillEvalDatasetVersion) -> SkillEvalDatasetVersion: ...
def get_dataset_version(self, dataset_version_id: str) -> SkillEvalDatasetVersion | None: ...
def list_dataset_versions(self, suite_id: str) -> list[SkillEvalDatasetVersion]: ...
def save_benchmark(self, benchmark: SkillEvalBenchmark) -> SkillEvalBenchmark: ...
def get_benchmark(self, benchmark_id: str) -> SkillEvalBenchmark | None: ...
def list_benchmarks(self, skill_id: str | None = None) -> list[SkillEvalBenchmark]: ...
```

内存实现使用三个字典和现有 `_copy`；任务更新严格校验 `expected_revision`，DatasetVersion 与 Benchmark 重复 ID 直接冲突。

- [ ] **Step 4: 增加 PostgreSQL DDL**

在现有 schema 中增加三张表：

```sql
CREATE TABLE IF NOT EXISTS skill_eval_tasks (
    task_id VARCHAR(80) PRIMARY KEY,
    suite_id VARCHAR(64) NOT NULL REFERENCES skill_eval_suites(suite_id),
    target_skill_id VARCHAR(128) NOT NULL,
    name VARCHAR(256) NOT NULL,
    partition VARCHAR(16) NOT NULL,
    task_snapshot JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_eval_tasks_suite
    ON skill_eval_tasks(suite_id, enabled, task_id);

CREATE TABLE IF NOT EXISTS skill_eval_dataset_versions (
    dataset_version_id VARCHAR(80) PRIMARY KEY,
    suite_id VARCHAR(64) NOT NULL REFERENCES skill_eval_suites(suite_id),
    version_number INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (suite_id, version_number)
);

CREATE TABLE IF NOT EXISTS skill_eval_benchmarks (
    benchmark_id VARCHAR(80) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL,
    dataset_version_id VARCHAR(80) NOT NULL
        REFERENCES skill_eval_dataset_versions(dataset_version_id),
    benchmark_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```

给 `skill_eval_runs` 的 CREATE 和 ALTER 同步增加上述八个兼容列，JSONB 默认 `[]` 或 `{}`，两个 ID 允许 NULL。

- [ ] **Step 5: 实现 PostgreSQL 映射并验证**

三个资产整对象写入 JSONB，索引列只保留筛选和唯一性所需字段；读取用 `model_validate(_json_value(...))`。扩展 `save_run` 和 `_row_to_run` 对新 frozen DTO 列表做显式转换。

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: PASS，DDL 列覆盖检查通过。

- [ ] **Step 6: 提交**

```powershell
git add src/data_platform/storage/skill/governance_ports.py src/data_platform/storage/skill/governance_in_memory.py src/data_platform/storage/skill/governance_postgres.py src/tests/unit/data_platform/test_skill_governance_storage.py
git commit -m "feat: 持久化 Skill 评测数据集资产"
```

---

### Task 3: 数据集工作区、门诊导入与不可变版本

**Files:**

- Modify: `skills/mzsettlement_verify_skill/self_tests.py`
- Modify: `src/runtime/skill_management/governance_service.py`
- Modify: `src/tests/unit/domain/skill/test_skill_evaluation_dataset.py`
- Modify: `src/tests/unit/runtime/skill_management/test_governance_service.py`

- [ ] **Step 1: 写门诊转换和冻结失败测试**

```python
def test_outpatient_cases_convert_to_generic_tasks() -> None:
    tasks = build_eval_tasks(created_by="quality-user")
    assert len(tasks) == 28
    person_21 = next(t for t in tasks if t.input.settlement_id == "011100030X260417004975")
    calc = next(a for a in person_21.assertions if a.output_adapter == "self_pay_one")
    assert calc.expected.expected_value == 510.96
    assert person_21.target_skill_id == "mzsettlement_verify_skill"


def test_freeze_dataset_is_immutable_and_idempotent_for_same_content(service) -> None:
    suite = service.create_suite(
        name="门诊基准集", scope="skill", skill_id="mzsettlement_verify_skill",
        purpose="门诊费用解释", created_by="quality-user",
    )
    service.import_outpatient_tasks(suite.suite_id, created_by="quality-user")
    first = service.freeze_dataset(suite.suite_id, created_by="quality-user")
    second = service.freeze_dataset(suite.suite_id, created_by="quality-user")
    assert first.dataset_version_id == second.dataset_version_id
    assert len(first.task_snapshots) == 28
```

- [ ] **Step 2: 运行测试确认红灯**

```powershell
uv run python -m pytest skills/mzsettlement_verify_skill/tests/test_self_tests.py src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

Expected: 转换和冻结方法不存在。

- [ ] **Step 3: 将 YAML 转为通用 Task**

`build_eval_tasks` 只读 YAML，不写数据库：

```python
def build_eval_tasks(created_by: str) -> list[SkillEvalTask]:
    tasks: list[SkillEvalTask] = []
    for case in load_self_test_cases():
        tasks.append(SkillEvalTask(
            task_id=f"EVT_mz_{case.case_id.replace('-', '_')}",
            suite_id="EVS_mzsettlement_benchmark",
            target_skill_id="mzsettlement_verify_skill",
            name=f"{case.context.person_type or '未知人群'}·{case.context.service_type or '门诊'}费用组成",
            input=SkillEvalTaskInput(question="费用组成", settlement_id=case.settlement_id),
            assertions=[
                SkillEvalAssertion(
                    assertion_id="self_pay_one",
                    dimension="behavior",
                    output_adapter="self_pay_one",
                    expected=CalculationAssertions(
                        expected_value=float(case.expected_self_pay_one), tolerance=0.0
                    ),
                ),
                SkillEvalAssertion(
                    assertion_id="reported_value_only",
                    dimension="answer_quality",
                    output_adapter="public_answer",
                    expected=AnswerQualityAssertions(
                        answerable=True,
                        must_include=[str(case.expected_self_pay_one)],
                        must_not_include=["医保范围内金额 - 基金支付总金额"],
                    ),
                ),
            ],
            trajectory_prefixes=[TrajectoryPrefix(
                prefix_id="after_settlement_loaded",
                boundary_kind="after_settlement_loaded",
            )],
            enabled=case.enabled,
            source_type="outpatient_self_test",
            source_ref=case.case_id,
            business_tags=[
                value for value in (
                    case.context.person_type,
                    case.context.insurance_type,
                    case.context.service_type,
                    *case.payment_channels,
                ) if value
            ],
            created_by=created_by,
            updated_by=created_by,
        ))
    return tasks
```

- [ ] **Step 4: 实现工作区服务**

在 `SkillGovernanceService` 增加 `create_task`、`update_task`、`list_tasks`、`import_outpatient_tasks`、`freeze_dataset`。导入按稳定 `task_id` 幂等更新；冻结只含启用任务，先校验目标 Skill 与 suite 范围一致，再计算内容哈希。相同 suite revision 和内容哈希返回已有版本，不制造空版本。

- [ ] **Step 5: 验证并提交**

```powershell
uv run python -m pytest skills/mzsettlement_verify_skill/tests/test_self_tests.py src/tests/unit/domain/skill/test_skill_evaluation_dataset.py src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

Expected: PASS。

```powershell
git add skills/mzsettlement_verify_skill/self_tests.py src/runtime/skill_management/governance_service.py src/tests/unit/domain/skill/test_skill_evaluation_dataset.py src/tests/unit/runtime/skill_management/test_governance_service.py
git commit -m "feat: 将门诊自测迁入版本化数据集"
```

---

### Task 4: 提供任务、版本和 Benchmark API

**Files:**

- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 写 API 失败测试**

增加一条完整 API 用例：创建 Skill suite → 导入 28 例 → 查询任务 → 冻结版本 → 创建 Benchmark。断言所有写接口缺 `skill:evaluate` 时为 401/403，冻结后任务修改不改变旧快照。

```python
def test_outpatient_dataset_can_be_imported_frozen_and_bound_to_benchmark(client) -> None:
    headers = _eval_case_headers()
    suite = client.post(f"{PREFIX}/infra-skills/eval-suites", headers=headers, json={
        "name": "门诊结算基准集", "scope": "skill",
        "skill_id": "mzsettlement_verify_skill", "purpose": "费用组成",
    }).json()
    imported = client.post(
        f"{PREFIX}/infra-skills/eval-suites/{suite['suite_id']}/import-outpatient",
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["total"] == 28
    frozen = client.post(
        f"{PREFIX}/infra-skills/eval-suites/{suite['suite_id']}/dataset-versions",
        headers=headers,
    )
    assert frozen.status_code == 201
    benchmark = client.post(f"{PREFIX}/infra-skills/eval-benchmarks", headers=headers, json={
        "name": "门诊 V1", "skill_id": "mzsettlement_verify_skill",
        "dataset_version_id": frozen.json()["dataset_version_id"],
        "environment_snapshot": {
            "runtime_version": "test",
            "data_source_mode": "memory",
        },
        "evaluator_plan_id": "deterministic_v1",
    })
    assert benchmark.status_code == 201
```

- [ ] **Step 2: 运行 API 测试确认红灯**

```powershell
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q
```

Expected: 新路径 404。

- [ ] **Step 3: 增加显式 DTO 和路由**

实现以下端点，所有响应字段均来自 Pydantic DTO：

```text
GET/POST /infra-skills/eval-suites/{suite_id}/tasks
GET/PUT  /infra-skills/eval-tasks/{task_id}
POST     /infra-skills/eval-suites/{suite_id}/import-outpatient
GET/POST /infra-skills/eval-suites/{suite_id}/dataset-versions
GET/POST /infra-skills/eval-benchmarks
```

Benchmark 创建由服务端计算 `environment_hash` 和 `evaluator_plan_hash`，客户端不能提交哈希；只允许注册的 `deterministic_v1` 或 `deterministic_judge_v1`。

- [ ] **Step 4: 验证兼容 API**

```powershell
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q
uv run python -m pytest src/tests/integration/flow/test_skill_eval_suite_flow.py -q
```

Expected: 两组 PASS，旧 suite/case 流仍可用。

- [ ] **Step 5: 提交**

```powershell
git add src/runtime/api/skill_schemas.py src/runtime/api/infra_skill_routes.py src/tests/integration/api/test_infra_skill_routes.py
git commit -m "feat: 提供 Skill 评测数据集 API"
```

---

### Task 5: 执行真实 Policy QA、确定性验证和 prefix 诊断

**Files:**

- Create: `src/runtime/skill_management/evaluation_runner.py`
- Create: `src/runtime/skill_management/evaluation_attribution.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/runtime/skill_management/regression_evaluators.py`
- Modify: `src/runtime/skill_management/governance_service.py`
- Create: `src/tests/unit/runtime/skill_management/test_evaluation_runner.py`

- [ ] **Step 1: 写 runner 失败测试**

测试使用假的 SSE callable，不连 SQL Server/Milvus：

```python
@pytest.mark.asyncio
async def test_runner_uses_public_result_and_hard_failure_wins() -> None:
    runner = PolicyQAEvaluationRunner(stream_factory=fake_stream_with_self_pay_one("127.74"))
    result = await runner.run(_person_21_task())
    assert result.status == SkillEvalTaskStatus.FAILED
    assert "CALCULATION_TOLERANCE_EXCEEDED" in result.failure_codes
    assert result.selected_skill_id == "mzsettlement_verify_skill"


@pytest.mark.asyncio
async def test_prefix_success_attributes_failure_before_boundary() -> None:
    runner = PolicyQAEvaluationRunner(
        stream_factory=fake_full_failure,
        resume_factory=fake_prefix_success,
    )
    result = await runner.run(_person_21_task())
    assert result.attribution.stage == "data_resolution"
    assert result.attribution.owner_type == "agent"
```

- [ ] **Step 2: 运行测试确认红灯**

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_evaluation_runner.py -q
```

Expected: runner 和归因模块不存在。

- [ ] **Step 3: 给真实 Policy QA 增加服务端观察器**

给 `_policy_qa_stream` 增加两个仅内部参数，HTTP 入口仍只传 request：

```python
PolicyQAEvalObserver = Callable[[str, dict[str, Any]], None]


async def _policy_qa_stream(
    request: PolicyQARequest,
    *,
    evaluation_observer: PolicyQAEvalObserver | None = None,
    evaluation_prefix: PolicyQAEvalPrefix | None = None,
) -> AsyncGenerator[str, None]:
    ...
```

观察器只接收经 `_sanitize` 后的 `settlement_loaded`、`context_rewritten`、`skill_selected`、`policy_retrieved`、`result_verified`。`PolicyQAEvalPrefix` 仅支持 `after_settlement_loaded`，携带本次运行内的预取语义结果和重写问题；prefix 接力跳过重复取数，但仍执行路由、政策、Skill 和公开结果验证。不得保存患者姓名、证件、SQL、表名、连接信息或模型隐藏推理。

- [ ] **Step 4: 实现 SSE runner 和输出适配**

`PolicyQAEvaluationRunner` 逐条解析 `event:`/`data:`，保存公开步骤和观察器快照；必须看到 `result` 与 `done` 才算执行完成。输出适配规则固定为：

```python
def adapt_output(adapter: str, public_result: PolicyQAPublicResult, selected_skill_id: str) -> dict[str, Any]:
    if adapter == "route":
        return {"selected_skill_id": selected_skill_id}
    if adapter == "self_pay_one":
        item = next(
            (x for x in public_result.field_explanations if x.field_name == "个人自付一"),
            None,
        )
        return {"amount": None if item is None else item.value}
    if adapter == "citation":
        return {
            "sources": [item.title for item in public_result.policy_evidence],
            "supports_answer": bool(public_result.citations),
        }
    if adapter == "safety":
        return {"status": public_result.action_status or public_result.answer_status, "actions": []}
    return {"answer": public_result.answer}
```

每个断言继续通过 `SkillRegressionEvaluatorRegistry` 执行。补充 `BehaviorEvaluator`；确定性 required 失败直接把任务设为 failed，任何 Judge 结果不得覆盖。

- [ ] **Step 5: 实现稳定归因与聚类纯函数**

`failure_code` 前缀映射：`SETTLEMENT_→data_resolution`、`ROUTE_→routing`、`POLICY_→policy_retrieval`、`CALCULATION_→calculation`、`CITATION_→citation`、`QUALITY_→answer_composition`、`SAFETY_→safety`、数据/验证器 schema 错误→`evaluator_or_dataset`。prefix 成功时将失败定位到边界之前；prefix 仍失败时保留确定性失败阶段。

- [ ] **Step 6: 在治理服务中创建 Benchmark run**

新增 async `create_benchmark_run`：预检数据集/Skill/候选版本/执行器 → 对任务串行执行 → 汇总分维度状态 → 生成稳定失败簇 → 一次保存不可变 `SkillEvalRun`。首版任务量只有 28 条，不引入队列；环境瞬时错误由 Policy QA 自身最多重试一次。

- [ ] **Step 7: 验证并提交**

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_evaluation_runner.py src/tests/unit/runtime/skill_management/test_regression_evaluators.py -q
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
```

Expected: PASS；公开 Policy QA 契约没有新增字段。

```powershell
git add src/runtime/skill_management/evaluation_runner.py src/runtime/skill_management/evaluation_attribution.py src/runtime/api/policy_qa_routes.py src/runtime/skill_management/regression_evaluators.py src/runtime/skill_management/governance_service.py src/tests/unit/runtime/skill_management/test_evaluation_runner.py
git commit -m "feat: 执行端到端 Skill Benchmark"
```

---

### Task 6: 可选 Judge、运行 API、发布门禁和改进任务

**Files:**

- Create: `src/runtime/skill_management/evaluation_judge.py`
- Modify: `src/runtime/skill_management/governance_service.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/unit/runtime/skill_management/test_evaluation_runner.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 写 Judge 和改进闭环失败测试**

```python
def test_judge_cannot_override_deterministic_failure() -> None:
    result = derive_task_status(
        deterministic_failures=["CALCULATION_TOLERANCE_EXCEEDED"],
        judge=SkillEvalJudgeResult(status="passed", rubric_scores={"clarity": 4}),
    )
    assert result == SkillEvalTaskStatus.FAILED


def test_judge_unavailable_blocks_only_open_dimension() -> None:
    result = derive_task_status(
        deterministic_failures=[],
        judge=SkillEvalJudgeResult(status="blocked", rubric_scores={}),
        judge_required=False,
    )
    assert result == SkillEvalTaskStatus.PASSED
```

- [ ] **Step 2: 实现严格 JSON Judge**

`SkillEvalJudge` 使用 `ModelGateway.generate(messages, model_type="text", scene="skill_eval_judge")`，请求只含脱敏问题、公开答案、允许的引用和 Rubric。响应 DTO：

```python
class SkillEvalJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["passed", "failed", "blocked", "needs_review"]
    rubric_scores: dict[str, int]
    evidence_refs: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    model_name: str | None = None
```

每任务最多调用一次；模型未配置、超时或解析失败返回 blocked，不伪造通过。只有 `deterministic_judge_v1` 且任务声明 `rubric_id` 时调用。

- [ ] **Step 3: 增加运行与改进 API**

实现：

```text
POST /infra-skills/eval-benchmarks/{benchmark_id}/runs
GET  /infra-skills/eval-runs/{run_id}
GET  /infra-skills/eval-runs/{run_id}/failure-clusters
POST /infra-skills/eval-failure-clusters/{cluster_id}/improvement-task
POST /infra-skills/eval-runs/{run_id}/retest
```

改进端点调用现有 `runtime.task_closure.service.create_task`，`workflow_id=run_id`，`task_type="skill_evaluation_improvement"`，`input_data` 只放 run/cluster/证据引用和建议目标。失败簇接口通过现有 `list_tasks_by_workflow(run_id)` 动态返回关联任务；不修改原运行，也不创建派生运行。

- [ ] **Step 4: 让正式 Benchmark 驱动既有发布门禁**

`create_candidate` 与 `_validate_frozen_evidence` 分支规则：旧 run 沿用 `suite_version/config_hash` 校验；有 `benchmark_id` 的 run 校验 DatasetVersion、Benchmark、候选制品、环境和 evaluator 哈希，同时要求全部 hard gate 通过且无 required `needs_review`。

- [ ] **Step 5: API 验证并提交**

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_evaluation_runner.py -q
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q
```

Expected: PASS。

```powershell
git add src/runtime/skill_management/evaluation_judge.py src/runtime/skill_management/governance_service.py src/runtime/api/skill_schemas.py src/runtime/api/infra_skill_routes.py src/tests/unit/runtime/skill_management/test_evaluation_runner.py src/tests/integration/api/test_infra_skill_routes.py
git commit -m "feat: 闭合 Skill 评测归因与改进流程"
```

---

### Task 7: 将 Portal 重组为四个连续工作区

**Files:**

- Modify: `src/apps/portal/src/lib/types.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Modify: `src/apps/portal/app/skills/evaluations/page.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-eval-suite-panel.tsx`
- Modify: `src/apps/portal/src/components/skills/outpatient-self-test-panel.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-eval-launch-panel.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-eval-run-detail.tsx`
- Modify: `src/apps/portal/src/tests/components/skill-eval-suite-panel.test.tsx`
- Modify: `src/apps/portal/src/tests/components/outpatient-self-test-panel.test.tsx`
- Modify: `src/apps/portal/src/tests/skill-eval-launch-panel.test.tsx`
- Modify: `src/apps/portal/src/tests/skill-eval-run-detail.test.tsx`

- [ ] **Step 1: 写页面行为失败测试**

覆盖四个用户事实：深链 Skill 不再二次选择；发起按钮提交 `benchmark_id`；门诊面板导入通用任务并冻结版本；运行详情按计算/政策/引用/质量/安全分维度展示失败簇和“创建改进任务”。

```tsx
render(
  <SkillEvalLaunchPanel
    skillId="mzsettlement_verify_skill"
    benchmarkId="EVB_1"
    taskCount={28}
    onLaunched={onLaunched}
  />,
)
expect(screen.queryByTestId('eval-launch-skill')).not.toBeInTheDocument()
await user.selectOptions(screen.getByTestId('eval-launch-version'), 'v1')
await user.click(screen.getByTestId('eval-launch-button'))
expect(mocks.run).toHaveBeenCalledWith('EVB_1', { version_id: 'v1' })
```

- [ ] **Step 2: 运行 Vitest 确认红灯**

```powershell
Set-Location src/apps/portal
npm test -- src/tests/components/skill-eval-suite-panel.test.tsx src/tests/components/outpatient-self-test-panel.test.tsx src/tests/skill-eval-launch-panel.test.tsx src/tests/skill-eval-run-detail.test.tsx
```

Expected: props、API 和新标签不存在。

- [ ] **Step 3: 扩展前端 DTO 和 API client**

TypeScript 字段与后端 snake_case 原样一致；为 Task、DatasetVersion、Benchmark、TaskResult、DimensionSummary、FailureAttribution、FailureCluster、ImprovementLink 建显式 interface。新增 API 函数直接映射 Task 4/6 路径，不增加客户端状态库。

- [ ] **Step 4: 重组页面**

页面顶部固定显示 Skill、suite、dataset version、Benchmark、候选、基线和任务数。用原生 button tab 实现四区：

```text
数据集：suite + 任务/覆盖 + 门诊导入 + 冻结版本
运行与实验：锁定 Skill + 选择 Benchmark/候选/基线 + 启动
Benchmark 分析：运行列表 + 分维度结果 + 轨迹/失败簇下钻
问题与改进：失败簇 + 归因证据 + 创建改进任务 + 复测
```

移除页面中无说明混排的“28 条固定自测 + 路由用例 + 路由运行”；历史路由用例放到数据集区的“路由断言”折叠详情。停用 suite 仍可在下拉框中选中并点击启用。

- [ ] **Step 5: 页面聚焦验证**

```powershell
Set-Location src/apps/portal
npm test -- src/tests/components/skill-eval-suite-panel.test.tsx src/tests/components/outpatient-self-test-panel.test.tsx src/tests/skill-eval-launch-panel.test.tsx src/tests/skill-eval-run-detail.test.tsx
npx tsc --noEmit
npx eslint app/skills/evaluations/page.tsx src/components/skills/skill-eval-suite-panel.tsx src/components/skills/outpatient-self-test-panel.tsx src/components/skills/skill-eval-launch-panel.tsx src/components/skills/skill-eval-run-detail.tsx src/lib/api-client.ts src/lib/types.ts
npm run build
```

Expected: Vitest PASS、TypeScript 零错误、scoped ESLint 零错误、Next build 成功。

- [ ] **Step 6: 提交**

```powershell
git add src/apps/portal/app/skills/evaluations/page.tsx src/apps/portal/src/components/skills/skill-eval-suite-panel.tsx src/apps/portal/src/components/skills/outpatient-self-test-panel.tsx src/apps/portal/src/components/skills/skill-eval-launch-panel.tsx src/apps/portal/src/components/skills/skill-eval-run-detail.tsx src/apps/portal/src/lib/api-client.ts src/apps/portal/src/lib/types.ts src/apps/portal/src/tests/components/skill-eval-suite-panel.test.tsx src/apps/portal/src/tests/components/outpatient-self-test-panel.test.tsx src/apps/portal/src/tests/skill-eval-launch-panel.test.tsx src/apps/portal/src/tests/skill-eval-run-detail.test.tsx
git commit -m "feat: 重构 Skill 评测闭环工作区"
```

---

### Task 8: 跑通门诊真实闭环并记录证据

**Files:**

- Create: `src/tests/integration/flow/test_skill_eval_benchmark_flow.py`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 写 Flow 测试**

Flow 只验证一条高价值主链：导入 28 例 → 冻结 → 建 Benchmark → 用假的真实执行端口让 `person-21` 返回错误金额 → 归因为 calculation → 创建改进任务 → 修复端口输出 `510.96` → 影响集和完整 Benchmark 通过。外部 SQL/Milvus 不进入自动化 Flow；真实环境在 Step 5 单独验证。

- [ ] **Step 2: 严格按层执行后端验证**

```powershell
uv run python -m pytest src/tests/unit/domain/skill/test_skill_evaluation_dataset.py src/tests/unit/data_platform/test_skill_governance_storage.py src/tests/unit/runtime/skill_management/test_evaluation_runner.py src/tests/unit/runtime/skill_management/test_regression_evaluators.py src/tests/unit/runtime/skill_management/test_governance_service.py -q
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_policy_qa_routes.py -q
uv run python -m pytest src/tests/integration/flow/test_skill_eval_suite_flow.py src/tests/integration/flow/test_skill_eval_benchmark_flow.py src/tests/integration/flow/test_skill_evaluation_release_flow.py -q
```

Expected: Unit → API → Flow 依次 PASS；任一层失败先修复，不跳层。

- [ ] **Step 3: 完整审查闭环**

按需求和设计逐项审查 diff，重点检查：旧 API 兼容、CREATE+ALTER 双写、无患者敏感数据、无 chain-of-thought、Judge 不翻硬错误、blocked 不计 Agent 失败、发布门禁不被绕过、页面任务数等于运行快照任务数。修复后重新执行受影响的 Unit → API → Flow。

- [ ] **Step 4: 运行 Portal 验证**

```powershell
Set-Location src/apps/portal
npm test -- src/tests/components/skill-eval-suite-panel.test.tsx src/tests/components/outpatient-self-test-panel.test.tsx src/tests/skill-eval-launch-panel.test.tsx src/tests/skill-eval-run-detail.test.tsx
npx tsc --noEmit
npm run build
```

Expected: PASS。

- [ ] **Step 5: 真实服务端到端验证**

只通过中央脚本启动：

```powershell
Set-Location C:\Users\于金宝\orca\workspaces\hospital_medical_insurance_agent\issue-20
..\ws.ps1 restart issue-20
..\ws.ps1 url all
```

在 `/skills/evaluations?skill=mzsettlement_verify_skill` 导入并冻结门诊数据集，使用交易号 `011100030X260417004975` 的任务运行正式 Benchmark。验收：个人自付一 `510.96`；不出现通用反推公式；28 条任务结果可见；政策缺失显示 blocked/uncertainty 而不是伪通过；运行可展示环境、版本、轨迹、归因和失败簇。

- [ ] **Step 6: 更新进度并提交**

在 `PROGRESS.md` 技能管理新增单元 `7.11 Skill 端到端评测闭环`，记录实际通过数、环境阻塞和真实运行 ID，不复制设计说明。

```powershell
git add src/tests/integration/flow/test_skill_eval_benchmark_flow.py PROGRESS.md
git commit -m "test: 验证门诊 Skill 评测闭环"
```

---

## 最终成功标准

1. `/skills/evaluations?skill=mzsettlement_verify_skill` 自动锁定 Skill，用户能导入、维护和冻结 28 条通用任务。
2. 运行请求真实绑定 `dataset_version_id` 和 `benchmark_id`，页面任务数等于运行快照任务数。
3. `011100030X260417004975` 的个人自付一以结算单原值 `510.96` 确定性核验，错误公式会失败。
4. 硬断言优先，Judge 不可翻案；模型不可用时开放维度 blocked，不伪造分数。
5. 失败具有 owner、stage、failure_code、证据和稳定聚类，可创建现有任务闭环的改进任务。
6. 修复先跑影响集，再跑完整 Benchmark；正式 Benchmark 可继续驱动既有 Release 门禁。
7. 历史路由用例、旧运行、旧 Release 和门诊 self-test API 保持兼容。
8. Unit → API → Flow、Portal 聚焦测试、TypeScript 和构建依次通过。
