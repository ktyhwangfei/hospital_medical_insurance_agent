# 通用 Skill 测评中心阶段 A 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立平台级测评集资产和通用 Skill 测评入口，使任意 Skill 都能创建、选择和维护自己的路由测评集，同时保持现有路由评测与发布门禁兼容。

**Architecture:** 在现有 Skill 治理模型、存储、服务和 API 上增加 `SkillEvalSuite`，并给现有路由用例增加不可变的 `suite_id` 归属；默认平台路由测评集承接全部历史用例和旧接口。Portal 为每个 Skill 提供统一“测评”入口，并通过通用测评集面板维护资产。本阶段不引入第二套用例模型，也不迁移门诊 28 个业务行为样例。

**Tech Stack:** Python 3.13、Pydantic 2、FastAPI、PostgreSQL、Next.js 16、React、TypeScript、pytest、Vitest。

**Design:** `docs/superpowers/specs/2026-08-31-skill-evaluation-center-design.md`

**Risk:** R4。修改领域模型、PostgreSQL Schema、API 契约和 Portal；必须按 Unit → API → Flow 顺序验证，并运行 Portal 组件测试与构建。

**Compatibility:** 历史用例自动归入 `EVS_platform_routing`；旧 `/infra-skills/eval-cases*` 和 `/infra-skills/{skill_id}/eval-runs*` 继续可用。现有全局 `suite_version` 与发布门禁本阶段保持不变，避免同时重写运行和发布证据语义。

**Rollback:** 新表和新增列均为向后兼容扩展。代码回滚后旧接口忽略新增数据；数据库保留 `skill_eval_suites` 和 `suite_id` 不影响旧版本读取。使用对应原子提交的 `git revert`，不删除测评资产。

**Phase boundary:** 本计划只交付测评集、路由用例归属、通用入口和兼容 API。`evaluation_contract`、业务数据生成、语义覆盖分析、`behavior` 执行器、门诊 28 例迁移和多维运行指标不在本计划改动范围内。

---

## 文件结构与职责

| 文件 | 责任 |
|---|---|
| `src/domain/skill/governance_models.py` | 测评集领域模型、默认测评集常量、路由用例归属 |
| `src/domain/AGENTS.md` | 增加测评集通用语言 |
| `src/data_platform/storage/skill/governance_ports.py` | 测评集存储端口和带 suite 过滤的用例查询 |
| `src/data_platform/storage/skill/governance_in_memory.py` | 测试/开发环境测评集存储 |
| `src/data_platform/storage/skill/governance_postgres.py` | PostgreSQL DDL、迁移兼容和测评集持久化 |
| `src/runtime/skill_management/governance_service.py` | 测评集 CRUD、Skill 范围校验、用例归属和 ID 生成 |
| `src/runtime/api/skill_schemas.py` | 显式测评集 DTO 与用例 `suite_id` 字段 |
| `src/runtime/api/infra_skill_routes.py` | 测评集 API 和旧用例 API 兼容过滤 |
| `src/apps/portal/src/lib/types.ts` | 前端测评集和用例类型 |
| `src/apps/portal/src/lib/api-client.ts` | 前端测评集 API 客户端 |
| `src/apps/portal/src/components/skills/skill-eval-suite-panel.tsx` | 通用测评集选择、新建和启停界面 |
| `src/apps/portal/app/skills/evaluations/page.tsx` | 将选中测评集接入现有用例列表 |
| `src/apps/portal/src/components/skills/skill-capability-overview.tsx` | 所有 Skill 的统一“测评”入口 |
| `src/tests/unit/data_platform/test_skill_governance_storage.py` | 内存存储、DDL 和并发规则 |
| `src/tests/unit/runtime/skill_management/test_governance_service.py` | 领域服务规则和 ID |
| `src/tests/integration/api/test_infra_skill_routes.py` | 测评集 API、权限和兼容性 |
| `src/tests/integration/flow/test_skill_eval_suite_flow.py` | 从创建测评集到保存路由用例的流程 |
| `src/apps/portal/src/tests/components/skill-eval-suite-panel.test.tsx` | 通用面板交互 |
| `src/apps/portal/src/tests/skill-capability-overview.test.tsx` | 每个 Skill 均有测评入口 |

---

### Task 1: 建立测评集领域模型与通用语言

**Files:**

- Modify: `src/domain/skill/governance_models.py`
- Modify: `src/domain/AGENTS.md`
- Test: `src/tests/unit/data_platform/test_skill_governance_storage.py`

- [ ] **Step 1: 写领域模型失败测试**

在 `test_skill_governance_storage.py` 的 import 中加入 `DEFAULT_ROUTING_SUITE_ID`、`SkillEvalSuite`、`SkillEvalSuiteScope`、`SkillEvalSuiteStatus`，并增加：

```python
def test_eval_suite_requires_skill_id_only_for_skill_scope() -> None:
    platform = SkillEvalSuite(
        suite_id=DEFAULT_ROUTING_SUITE_ID,
        name="平台默认路由测评集",
        scope=SkillEvalSuiteScope.PLATFORM,
        created_by="system",
        updated_by="system",
    )
    assert platform.skill_id is None
    assert platform.status == SkillEvalSuiteStatus.ACTIVE

    with pytest.raises(ValueError, match="skill_id"):
        SkillEvalSuite(
            suite_id="EVS_invalid",
            name="无 Skill 的专属测评集",
            scope=SkillEvalSuiteScope.SKILL,
            created_by="tester",
            updated_by="tester",
        )


def test_eval_case_defaults_to_platform_routing_suite() -> None:
    case = SkillEvalCase(
        case_id="EVC_case",
        suite_version=1,
        question_template="起付线怎么算",
        expected_skill_id="demo-skill",
        created_by="tester",
    )
    assert case.suite_id == DEFAULT_ROUTING_SUITE_ID
```

- [ ] **Step 2: 运行单测确认红灯**

Run:

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: collection 因四个新符号不存在而失败。

- [ ] **Step 3: 增加最小领域模型**

在 `governance_models.py` 中增加：

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_ROUTING_SUITE_ID = "EVS_platform_routing"


class SkillEvalSuiteScope(StrEnum):
    PLATFORM = "platform"
    SKILL = "skill"


class SkillEvalSuiteStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SkillEvalSuite(BaseModel):
    """可命名、可审计的 Skill 测评用例集合。"""

    model_config = ConfigDict(frozen=True)

    suite_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    scope: SkillEvalSuiteScope
    skill_id: str | None = Field(default=None, max_length=128)
    purpose: str = Field(default="", max_length=1000)
    status: SkillEvalSuiteStatus = SkillEvalSuiteStatus.ACTIVE
    revision: int = Field(default=1, ge=1)
    created_by: str = Field(min_length=1, max_length=128)
    updated_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _validate_scope(self) -> "SkillEvalSuite":
        if self.scope == SkillEvalSuiteScope.PLATFORM and self.skill_id is not None:
            raise ValueError("platform 测评集不能设置 skill_id")
        if self.scope == SkillEvalSuiteScope.SKILL and not self.skill_id:
            raise ValueError("skill 测评集必须设置 skill_id")
        return self
```

给 `SkillEvalCase` 增加兼容字段：

```python
suite_id: str = Field(default=DEFAULT_ROUTING_SUITE_ID, min_length=1, max_length=64)
```

不要改变 `suite_version` 语义；它在阶段 A 继续表示全局路由评测集版本。

- [ ] **Step 4: 更新领域通用语言**

在 `src/domain/AGENTS.md` 的 Skill 治理术语区增加：

```markdown
- **SkillEvalSuite（Skill 测评集）**：按平台或单个 Skill 组织评测用例的可版本化治理资产；不等同于一次评测运行。
- **SkillEvalCase（Skill 路由评测用例）**：归属于一个 SkillEvalSuite、用于验证路由选择的固定脱敏问题模板。
```

- [ ] **Step 5: 运行领域/存储单测确认转绿**

Run:

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: PASS；既有用例无须显式提供 `suite_id`。

- [ ] **Step 6: 提交**

```powershell
git add src/domain/skill/governance_models.py src/domain/AGENTS.md src/tests/unit/data_platform/test_skill_governance_storage.py
git commit -m "feat: 增加 Skill 测评集领域模型"
```

---

### Task 2: 扩展存储端口、内存存储和 PostgreSQL Schema

**Files:**

- Modify: `src/data_platform/storage/skill/governance_ports.py`
- Modify: `src/data_platform/storage/skill/governance_in_memory.py`
- Modify: `src/data_platform/storage/skill/governance_postgres.py`
- Test: `src/tests/unit/data_platform/test_skill_governance_storage.py`

- [ ] **Step 1: 写存储行为失败测试**

在 `test_skill_governance_storage.py` 增加：

```python
def _suite(
    suite_id: str = "EVS_demo",
    *,
    revision: int = 1,
    status: SkillEvalSuiteStatus = SkillEvalSuiteStatus.ACTIVE,
) -> SkillEvalSuite:
    return SkillEvalSuite(
        suite_id=suite_id,
        name="演示 Skill 测评集",
        scope=SkillEvalSuiteScope.SKILL,
        skill_id="demo-skill",
        status=status,
        revision=revision,
        created_by="quality-user",
        updated_by="quality-user",
    )


def test_suite_storage_round_trip_and_filter() -> None:
    storage = InMemorySkillGovernanceStorage()
    stored = storage.save_suite(_suite())

    assert storage.get_suite(stored.suite_id) == stored
    assert {suite.suite_id for suite in storage.list_suites(skill_id="demo-skill")} == {
        DEFAULT_ROUTING_SUITE_ID,
        stored.suite_id,
    }
    assert [
        suite.suite_id for suite in storage.list_suites(skill_id="other-skill")
    ] == [DEFAULT_ROUTING_SUITE_ID]


def test_suite_update_rejects_stale_revision() -> None:
    storage = InMemorySkillGovernanceStorage()
    current = storage.save_suite(_suite())
    updated = current.model_copy(update={"name": "新名称", "revision": 2})
    storage.update_suite(updated, expected_revision=1)

    with pytest.raises(SkillGovernanceConflictError, match="revision"):
        storage.update_suite(updated, expected_revision=1)


def test_cases_can_be_filtered_by_suite() -> None:
    storage = InMemorySkillGovernanceStorage()
    storage.save_suite(_suite())
    storage.save_case(SkillEvalCase(
        case_id="EVC_demo",
        suite_id="EVS_demo",
        suite_version=1,
        question_template="测试问题",
        expected_skill_id="demo-skill",
        created_by="quality-user",
    ))

    assert [case.case_id for case in storage.list_cases(suite_id="EVS_demo")] == ["EVC_demo"]
    assert storage.list_cases(suite_id=DEFAULT_ROUTING_SUITE_ID) == []


def test_postgres_schema_covers_suite_and_case_suite_id() -> None:
    normalized = " ".join(SKILL_GOVERNANCE_TABLE_SCHEMA.split())
    assert "CREATE TABLE IF NOT EXISTS skill_eval_suites" in normalized
    assert "ADD COLUMN IF NOT EXISTS suite_id" in normalized
    assert "INSERT INTO skill_eval_suites" in normalized
    assert DEFAULT_ROUTING_SUITE_ID in SKILL_GOVERNANCE_TABLE_SCHEMA
```

- [ ] **Step 2: 运行测试确认红灯**

Run:

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: storage 不存在 suite CRUD，`list_cases` 不接受 `suite_id`。

- [ ] **Step 3: 扩展存储 Protocol**

在 `governance_ports.py` 导入 `SkillEvalSuite`，给 `SkillGovernanceStorage` 增加：

```python
def save_suite(self, suite: SkillEvalSuite) -> SkillEvalSuite: ...

def get_suite(self, suite_id: str) -> SkillEvalSuite | None: ...

def list_suites(
    self,
    *,
    skill_id: str | None = None,
    include_inactive: bool = True,
) -> list[SkillEvalSuite]: ...

def update_suite(
    self,
    suite: SkillEvalSuite,
    *,
    expected_revision: int,
) -> SkillEvalSuite: ...

def delete_suite(self, suite_id: str) -> bool: ...

def count_cases(self, suite_id: str) -> int: ...
```

将 `list_cases` 改为：

```python
def list_cases(
    self,
    *,
    suite_id: str | None = None,
    enabled_only: bool = False,
) -> list[SkillEvalCase]: ...
```

- [ ] **Step 4: 实现内存存储**

在 `InMemorySkillGovernanceStorage.__init__` 增加默认测评集和字典：

```python
default_suite = SkillEvalSuite(
    suite_id=DEFAULT_ROUTING_SUITE_ID,
    name="平台默认路由测评集",
    scope=SkillEvalSuiteScope.PLATFORM,
    purpose="兼容历史路由评测与发布门禁",
    created_by="system",
    updated_by="system",
)
self._suites: dict[str, SkillEvalSuite] = {
    default_suite.suite_id: default_suite,
}
```

实现以下方法：

```python
def save_suite(self, suite: SkillEvalSuite) -> SkillEvalSuite:
    if suite.suite_id in self._suites:
        raise SkillGovernanceConflictError(f"测评集已存在: {suite.suite_id}")
    stored = self._copy(suite)
    self._suites[stored.suite_id] = stored
    return self._copy(stored)

def get_suite(self, suite_id: str) -> SkillEvalSuite | None:
    suite = self._suites.get(suite_id)
    return None if suite is None else self._copy(suite)

def list_suites(
    self,
    *,
    skill_id: str | None = None,
    include_inactive: bool = True,
) -> list[SkillEvalSuite]:
    suites = [
        self._copy(suite)
        for suite in self._suites.values()
        if (skill_id is None or suite.skill_id in {None, skill_id})
        and (include_inactive or suite.status == SkillEvalSuiteStatus.ACTIVE)
    ]
    return sorted(suites, key=lambda item: (item.scope.value, item.name, item.suite_id))

def update_suite(
    self,
    suite: SkillEvalSuite,
    *,
    expected_revision: int,
) -> SkillEvalSuite:
    current = self._suites.get(suite.suite_id)
    if current is None:
        raise SkillGovernanceNotFoundError(f"测评集不存在: {suite.suite_id}")
    if current.revision != expected_revision:
        raise SkillGovernanceConflictError("测评集 revision 已变化")
    if suite.revision != expected_revision + 1:
        raise SkillGovernanceConflictError("新 revision 必须递增 1")
    stored = self._copy(suite)
    self._suites[stored.suite_id] = stored
    return self._copy(stored)

def delete_suite(self, suite_id: str) -> bool:
    return self._suites.pop(suite_id, None) is not None

def count_cases(self, suite_id: str) -> int:
    return sum(case.suite_id == suite_id for case in self._cases.values())
```

将 `list_cases` 的过滤条件改为：

```python
cases = [
    self._copy(case)
    for case in self._cases.values()
    if (suite_id is None or case.suite_id == suite_id)
    and (not enabled_only or case.enabled)
]
```

- [ ] **Step 5: 增加 PostgreSQL DDL 和兼容迁移**

在 `SKILL_GOVERNANCE_TABLE_SCHEMA` 的 `skill_eval_cases` 之前创建并灌入默认测评集：

```sql
CREATE TABLE IF NOT EXISTS skill_eval_suites (
    suite_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    scope VARCHAR(16) NOT NULL,
    skill_id VARCHAR(128),
    purpose TEXT NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    revision INTEGER NOT NULL DEFAULT 1,
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (
        (scope = 'platform' AND skill_id IS NULL)
        OR (scope = 'skill' AND skill_id IS NOT NULL)
    )
);

INSERT INTO skill_eval_suites (
    suite_id, name, scope, skill_id, purpose, status, revision,
    created_by, updated_by, created_at, updated_at
) VALUES (
    'EVS_platform_routing', '平台默认路由测评集', 'platform', NULL,
    '兼容历史路由评测与发布门禁', 'active', 1,
    'system', 'system', NOW(), NOW()
) ON CONFLICT (suite_id) DO NOTHING;
```

给 `skill_eval_cases` 的新库定义增加：

```sql
suite_id VARCHAR(64) NOT NULL DEFAULT 'EVS_platform_routing'
    REFERENCES skill_eval_suites(suite_id),
```

并为旧库增加：

```sql
ALTER TABLE skill_eval_cases
    ADD COLUMN IF NOT EXISTS suite_id VARCHAR(64)
    NOT NULL DEFAULT 'EVS_platform_routing';
CREATE INDEX IF NOT EXISTS idx_skill_eval_cases_suite_version
    ON skill_eval_cases(suite_id, suite_version, case_id);
```

阶段 A 不在旧表上补外键约束，避免已有异常数据使启动迁移失败；应用服务和新库外键共同保证新写入完整性。

- [ ] **Step 6: 实现 PostgreSQL suite CRUD 与 case 过滤**

复用现有 `_json_value` 和 row mapper 风格，增加 `_row_to_suite`：

```python
@staticmethod
def _row_to_suite(row: dict[str, Any]) -> SkillEvalSuite:
    return SkillEvalSuite.model_validate(row)
```

新增完整方法：

```python
def save_suite(self, suite: SkillEvalSuite) -> SkillEvalSuite:
    try:
        rows = self._get_client().execute(
            """
            INSERT INTO skill_eval_suites (
                suite_id, name, scope, skill_id, purpose, status, revision,
                created_by, updated_by, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                suite.suite_id,
                suite.name,
                suite.scope.value,
                suite.skill_id,
                suite.purpose,
                suite.status.value,
                suite.revision,
                suite.created_by,
                suite.updated_by,
                suite.created_at,
                suite.updated_at,
            ),
        )
    except Exception as exc:
        raise SkillGovernanceConflictError(
            f"测评集 ID 已存在: {suite.suite_id}"
        ) from exc
    return self._row_to_suite(rows[0])

def get_suite(self, suite_id: str) -> SkillEvalSuite | None:
    rows = self._get_client().execute(
        "SELECT * FROM skill_eval_suites WHERE suite_id = %s",
        (suite_id,),
    )
    return None if not rows else self._row_to_suite(rows[0])

def list_suites(
    self,
    *,
    skill_id: str | None = None,
    include_inactive: bool = True,
) -> list[SkillEvalSuite]:
    clauses: list[str] = []
    params: list[object] = []
    if skill_id is not None:
        clauses.append("(scope = 'platform' OR skill_id = %s)")
        params.append(skill_id)
    if not include_inactive:
        clauses.append("status = 'active'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = self._get_client().execute(
        f"""
        SELECT * FROM skill_eval_suites {where}
        ORDER BY scope, name, suite_id
        """,
        tuple(params),
    )
    return [self._row_to_suite(row) for row in rows]

def update_suite(
    self,
    suite: SkillEvalSuite,
    *,
    expected_revision: int,
) -> SkillEvalSuite:
    rows = self._get_client().execute(
        """
        UPDATE skill_eval_suites
        SET name = %s, purpose = %s, status = %s, revision = %s,
            updated_by = %s, updated_at = %s
        WHERE suite_id = %s AND revision = %s
        RETURNING *
        """,
        (
            suite.name,
            suite.purpose,
            suite.status.value,
            suite.revision,
            suite.updated_by,
            suite.updated_at,
            suite.suite_id,
            expected_revision,
        ),
    )
    if not rows:
        raise SkillGovernanceConflictError("测评集 revision 已变化")
    return self._row_to_suite(rows[0])

def delete_suite(self, suite_id: str) -> bool:
    rows = self._get_client().execute(
        "DELETE FROM skill_eval_suites WHERE suite_id = %s RETURNING suite_id",
        (suite_id,),
    )
    return bool(rows)

def count_cases(self, suite_id: str) -> int:
    rows = self._get_client().execute(
        "SELECT COUNT(*) AS n FROM skill_eval_cases WHERE suite_id = %s",
        (suite_id,),
    )
    return int(rows[0]["n"]) if rows else 0
```

`list_suites(skill_id=...)` 的 SQL 条件必须是：

```sql
WHERE (scope = 'platform' OR skill_id = %s)
```

`save_case` 的 INSERT/UPDATE/参数增加 `suite_id`；`list_cases` 使用参数化分支，不拼接 `suite_id`：

```python
clauses: list[str] = []
params: list[object] = []
if suite_id is not None:
    clauses.append("suite_id = %s")
    params.append(suite_id)
if enabled_only:
    clauses.append("enabled = TRUE")
where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
rows = self._get_client().execute(
    f"SELECT * FROM skill_eval_cases {where} ORDER BY suite_version, case_id",
    tuple(params),
)
```

- [ ] **Step 7: 运行存储单测**

Run:

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: PASS，包括默认测评集、过滤、revision 冲突和 CREATE + ALTER DDL 覆盖。

- [ ] **Step 8: 提交**

```powershell
git add src/data_platform/storage/skill/governance_ports.py src/data_platform/storage/skill/governance_in_memory.py src/data_platform/storage/skill/governance_postgres.py src/tests/unit/data_platform/test_skill_governance_storage.py
git commit -m "feat: 持久化 Skill 测评集"
```

---

### Task 3: 在治理服务中实现测评集 CRUD 和用例归属

**Files:**

- Modify: `src/runtime/skill_management/governance_service.py`
- Test: `src/tests/unit/runtime/skill_management/test_governance_service.py`

- [ ] **Step 1: 写服务层失败测试**

在 `test_governance_service.py` 增加：

```python
def test_create_skill_suite_generates_prefixed_id(service: SkillGovernanceService) -> None:
    suite = service.create_suite(
        name="演示 Skill 回归",
        scope="skill",
        skill_id="demo-skill",
        purpose="验证演示 Skill 路由",
        created_by="quality-user",
    )

    assert suite.suite_id.startswith("EVS_")
    assert suite.skill_id == "demo-skill"
    assert suite.revision == 1


def test_create_suite_rejects_unknown_skill(service: SkillGovernanceService) -> None:
    with pytest.raises(SkillGovernanceNotFoundError, match="Skill 不存在"):
        service.create_suite(
            name="未知 Skill 回归",
            scope="skill",
            skill_id="missing-skill",
            purpose="",
            created_by="quality-user",
        )


def test_route_case_belongs_to_selected_suite(service: SkillGovernanceService) -> None:
    suite = service.create_suite(
        name="演示 Skill 路由",
        scope="skill",
        skill_id="demo-skill",
        purpose="",
        created_by="quality-user",
    )
    case = service.create_case(
        suite_id=suite.suite_id,
        question_template="统筹自付怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="",
        contains_sensitive_data=False,
        created_by="quality-user",
    )

    assert case.case_id.startswith("EVC_")
    assert case.suite_id == suite.suite_id
    assert service.list_cases(suite_id=suite.suite_id) == [case]


def test_same_question_is_deduplicated_only_inside_same_suite(
    service: SkillGovernanceService,
) -> None:
    first_suite = service.create_suite(
        name="第一套",
        scope="skill",
        skill_id="demo-skill",
        purpose="",
        created_by="quality-user",
    )
    second_suite = service.create_suite(
        name="第二套",
        scope="skill",
        skill_id="demo-skill",
        purpose="",
        created_by="quality-user",
    )
    first = service.create_case(
        suite_id=first_suite.suite_id,
        question_template="起付线怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="",
        contains_sensitive_data=False,
        created_by="quality-user",
    )
    second = service.create_case(
        suite_id=second_suite.suite_id,
        question_template="起付线怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="",
        contains_sensitive_data=False,
        created_by="quality-user",
    )
    assert first.case_id != second.case_id


def test_non_empty_or_default_suite_cannot_be_deleted(
    service: SkillGovernanceService,
) -> None:
    with pytest.raises(SkillGovernanceGateError, match="默认"):
        service.delete_suite(DEFAULT_ROUTING_SUITE_ID)

    suite = service.create_suite(
        name="非空测评集",
        scope="skill",
        skill_id="demo-skill",
        purpose="",
        created_by="quality-user",
    )
    service.create_case(
        suite_id=suite.suite_id,
        question_template="起付线怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="",
        contains_sensitive_data=False,
        created_by="quality-user",
    )
    with pytest.raises(SkillGovernanceGateError, match="包含用例"):
        service.delete_suite(suite.suite_id)


def test_default_routing_suite_cannot_be_inactivated(
    service: SkillGovernanceService,
) -> None:
    with pytest.raises(SkillGovernanceGateError, match="默认"):
        service.update_suite(
            DEFAULT_ROUTING_SUITE_ID,
            name="平台默认路由测评集",
            purpose="兼容历史路由评测与发布门禁",
            status="inactive",
            expected_revision=1,
            updated_by="quality-user",
        )
```

同时从 `governance_ports` 导入 `SkillGovernanceNotFoundError`，从领域模型导入 `DEFAULT_ROUTING_SUITE_ID`。

- [ ] **Step 2: 运行服务单测确认红灯**

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

Expected: `create_suite`、`delete_suite` 和 `create_case(suite_id=...)` 尚不存在。

- [ ] **Step 3: 实现测评集服务方法**

在 `SkillGovernanceService` 增加：

```python
def list_suites(
    self,
    *,
    skill_id: str | None = None,
    include_inactive: bool = True,
) -> list[SkillEvalSuite]:
    return self._storage.list_suites(
        skill_id=skill_id,
        include_inactive=include_inactive,
    )

def get_suite(self, suite_id: str) -> SkillEvalSuite:
    suite = self._storage.get_suite(suite_id)
    if suite is None:
        raise SkillGovernanceNotFoundError(f"测评集不存在: {suite_id}")
    return suite

def create_suite(
    self,
    *,
    name: str,
    scope: SkillEvalSuiteScope | str,
    skill_id: str | None,
    purpose: str,
    created_by: str,
) -> SkillEvalSuite:
    resolved_scope = SkillEvalSuiteScope(scope)
    if resolved_scope == SkillEvalSuiteScope.SKILL:
        if not skill_id or skill_id not in self._loader.get_all():
            raise SkillGovernanceNotFoundError(f"Skill 不存在: {skill_id}")
    else:
        skill_id = None
    now = datetime.now(timezone.utc)
    return self._storage.save_suite(SkillEvalSuite(
        suite_id=f"EVS_{uuid4().hex}",
        name=name.strip(),
        scope=resolved_scope,
        skill_id=skill_id,
        purpose=purpose.strip(),
        created_by=created_by.strip(),
        updated_by=created_by.strip(),
        created_at=now,
        updated_at=now,
    ))

def update_suite(
    self,
    suite_id: str,
    *,
    name: str,
    purpose: str,
    status: SkillEvalSuiteStatus | str,
    expected_revision: int,
    updated_by: str,
) -> SkillEvalSuite:
    current = self.get_suite(suite_id)
    resolved_status = SkillEvalSuiteStatus(status)
    if (
        suite_id == DEFAULT_ROUTING_SUITE_ID
        and resolved_status != SkillEvalSuiteStatus.ACTIVE
    ):
        raise SkillGovernanceGateError(
            "平台默认路由测评集不能停用",
            ["default_eval_suite_protected"],
        )
    updated = current.model_copy(update={
        "name": name.strip(),
        "purpose": purpose.strip(),
        "status": resolved_status,
        "revision": expected_revision + 1,
        "updated_by": updated_by.strip(),
        "updated_at": datetime.now(timezone.utc),
    })
    return self._storage.update_suite(updated, expected_revision=expected_revision)

def delete_suite(self, suite_id: str) -> None:
    if suite_id == DEFAULT_ROUTING_SUITE_ID:
        raise SkillGovernanceGateError(
            "平台默认路由测评集不能删除",
            ["default_eval_suite_protected"],
        )
    self.get_suite(suite_id)
    if self._storage.count_cases(suite_id) > 0:
        raise SkillGovernanceGateError(
            "测评集包含用例，只能停用",
            ["eval_suite_not_empty"],
        )
    if not self._storage.delete_suite(suite_id):
        raise SkillGovernanceNotFoundError(f"测评集不存在: {suite_id}")
```

- [ ] **Step 4: 将路由用例归入测评集**

将 `list_cases` 改为接受 `suite_id` 并转发；给 `create_case` 增加首个 keyword-only 参数：

```python
suite_id: str = DEFAULT_ROUTING_SUITE_ID,
```

创建前：

```python
suite = self.get_suite(suite_id)
if suite.status != SkillEvalSuiteStatus.ACTIVE:
    raise SkillGovernanceGateError("测评集已停用", ["eval_suite_inactive"])
if (
    suite.scope == SkillEvalSuiteScope.SKILL
    and expected_skill_id != suite.skill_id
):
    raise SkillGovernanceGateError(
        "路由用例的期望 Skill 与测评集不一致",
        ["eval_case_skill_mismatch"],
    )
```

去重条件增加：

```python
existing.suite_id == suite_id
```

创建模型改为：

```python
case_id=f"EVC_{uuid4().hex}",
suite_id=suite_id,
```

`dedupe_cases` 的 key 改为 `(suite_id, question_template.strip(), expected_skill_id)`。`seed_golden_cases` 显式写入 `DEFAULT_ROUTING_SUITE_ID`。

- [ ] **Step 5: 运行服务单测**

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

Expected: PASS；现有未传 `suite_id` 的测试继续使用默认平台测评集。

- [ ] **Step 6: 提交**

```powershell
git add src/runtime/skill_management/governance_service.py src/tests/unit/runtime/skill_management/test_governance_service.py
git commit -m "feat: 管理 Skill 测评集与路由用例归属"
```

---

### Task 4: 提供测评集 API 并保持旧用例 API 兼容

**Files:**

- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Test: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 写 API 失败测试**

在 `test_infra_skill_routes.py` 增加：

```python
def test_eval_suite_crud_and_case_filter(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/infra-skills/eval-suites",
        headers=_eval_case_headers(),
        json={
            "name": "门诊解释路由回归",
            "scope": "skill",
            "skill_id": "settlement_explain_skill",
            "purpose": "验证门诊结算问题进入目标 Skill",
        },
    )
    assert created.status_code == 201
    suite = created.json()
    assert suite["suite_id"].startswith("EVS_")
    assert suite["revision"] == 1

    case = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        headers=_eval_case_headers(),
        json={
            "suite_id": suite["suite_id"],
            "question_template": "这笔门诊费用怎么组成",
            "expected_skill_id": "settlement_explain_skill",
        },
    )
    assert case.status_code == 201
    assert case.json()["suite_id"] == suite["suite_id"]
    assert case.json()["case_id"].startswith("EVC_")

    listed = client.get(
        f"{PREFIX}/infra-skills/eval-cases",
        params={"suite_id": suite["suite_id"]},
    )
    assert listed.status_code == 200
    assert [item["case_id"] for item in listed.json()["items"]] == [
        case.json()["case_id"]
    ]

    updated = client.put(
        f"{PREFIX}/infra-skills/eval-suites/{suite['suite_id']}",
        headers=_eval_case_headers(),
        json={
            "name": "门诊解释路由回归（停用）",
            "purpose": suite["purpose"],
            "status": "inactive",
            "expected_revision": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "inactive"
    assert updated.json()["revision"] == 2


def test_eval_suite_write_requires_skill_evaluate(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/infra-skills/eval-suites",
        json={
            "name": "无权限测评集",
            "scope": "platform",
            "purpose": "",
        },
    )
    assert response.status_code in {401, 403}


def test_eval_suite_rejects_stale_revision(client: TestClient) -> None:
    created = client.post(
        f"{PREFIX}/infra-skills/eval-suites",
        headers=_eval_case_headers(),
        json={
            "name": "并发测试",
            "scope": "platform",
            "purpose": "",
        },
    ).json()
    payload = {
        "name": "第一次更新",
        "purpose": "",
        "status": "active",
        "expected_revision": 1,
    }
    assert client.put(
        f"{PREFIX}/infra-skills/eval-suites/{created['suite_id']}",
        headers=_eval_case_headers(),
        json=payload,
    ).status_code == 200
    stale = client.put(
        f"{PREFIX}/infra-skills/eval-suites/{created['suite_id']}",
        headers=_eval_case_headers(),
        json=payload,
    )
    assert stale.status_code == 409
```

- [ ] **Step 2: 运行 API 测试确认红灯**

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q -k "eval_suite"
```

Expected: `/eval-suites` 返回 404。

- [ ] **Step 3: 增加显式 DTO**

在 `skill_schemas.py` 增加：

```python
class SkillEvalSuiteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    scope: Literal["platform", "skill"]
    skill_id: str | None = Field(default=None, max_length=128)
    purpose: str = Field(default="", max_length=1000)


class SkillEvalSuiteUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    purpose: str = Field(default="", max_length=1000)
    status: Literal["active", "inactive"]
    expected_revision: int = Field(ge=1)


class SkillEvalSuiteResponse(BaseModel):
    suite_id: str
    name: str
    scope: str
    skill_id: str | None
    purpose: str
    status: str
    revision: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class SkillEvalSuiteListResponse(BaseModel):
    items: list[SkillEvalSuiteResponse]
    total: int
```

给 `SkillEvalCaseCreateRequest` 增加：

```python
suite_id: str = Field(default="EVS_platform_routing", min_length=1, max_length=64)
```

给 `SkillEvalCaseResponse` 增加：

```python
suite_id: str
```

- [ ] **Step 4: 增加测评集路由**

在 `infra_skill_routes.py` 增加：

```python
@router.get(
    "/infra-skills/eval-suites",
    response_model=SkillEvalSuiteListResponse,
)
def list_skill_eval_suites(
    service: SkillGovernanceServiceDependency,
    skill_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=True),
) -> SkillEvalSuiteListResponse:
    suites = service.list_suites(
        skill_id=skill_id,
        include_inactive=include_inactive,
    )
    return SkillEvalSuiteListResponse(
        items=[SkillEvalSuiteResponse.model_validate(item.model_dump()) for item in suites],
        total=len(suites),
    )


@router.post(
    "/infra-skills/eval-suites",
    response_model=SkillEvalSuiteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_skill_eval_suite(
    request: SkillEvalSuiteCreateRequest,
    service: SkillGovernanceServiceDependency,
    principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalSuiteResponse:
    try:
        suite = service.create_suite(
            **request.model_dump(),
            created_by=principal.user_id,
        )
    except (SkillGovernanceConflictError, SkillGovernanceGateError, SkillGovernanceNotFoundError) as exc:
        raise _governance_error(exc) from exc
    return SkillEvalSuiteResponse.model_validate(suite.model_dump())


@router.put(
    "/infra-skills/eval-suites/{suite_id}",
    response_model=SkillEvalSuiteResponse,
)
def update_skill_eval_suite(
    suite_id: str,
    request: SkillEvalSuiteUpdateRequest,
    service: SkillGovernanceServiceDependency,
    principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalSuiteResponse:
    try:
        suite = service.update_suite(
            suite_id,
            **request.model_dump(),
            updated_by=principal.user_id,
        )
    except (SkillGovernanceConflictError, SkillGovernanceGateError, SkillGovernanceNotFoundError) as exc:
        raise _governance_error(exc) from exc
    return SkillEvalSuiteResponse.model_validate(suite.model_dump())


@router.delete(
    "/infra-skills/eval-suites/{suite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_skill_eval_suite(
    suite_id: str,
    service: SkillGovernanceServiceDependency,
    _principal: SkillEvaluationPrincipalDependency,
) -> None:
    try:
        service.delete_suite(suite_id)
    except (SkillGovernanceConflictError, SkillGovernanceGateError, SkillGovernanceNotFoundError) as exc:
        raise _governance_error(exc) from exc
```

`list_skill_eval_cases` 增加 `suite_id: str | None = Query(default=None)` 并转发。`create_skill_eval_case` 已通过 `request.model_dump()` 自动把 `suite_id` 传给服务。

- [ ] **Step 5: 运行 API 测试**

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q -k "eval_suite or eval_case"
```

Expected: PASS；旧的无 `suite_id` 请求仍归入默认平台测评集。

- [ ] **Step 6: 运行 OpenAPI 契约测试**

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_openapi_contract.py -q
```

Expected: PASS，新增端点出现在 OpenAPI 且错误响应格式未变化。

- [ ] **Step 7: 提交**

```powershell
git add src/runtime/api/skill_schemas.py src/runtime/api/infra_skill_routes.py src/tests/integration/api/test_infra_skill_routes.py
git commit -m "feat: 提供 Skill 测评集治理接口"
```

---

### Task 5: 将 Portal 改为所有 Skill 的通用测评入口

**Files:**

- Modify: `src/apps/portal/src/lib/types.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Create: `src/apps/portal/src/components/skills/skill-eval-suite-panel.tsx`
- Modify: `src/apps/portal/app/skills/evaluations/page.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-capability-overview.tsx`
- Create: `src/apps/portal/src/tests/components/skill-eval-suite-panel.test.tsx`
- Modify: `src/apps/portal/src/tests/skill-capability-overview.test.tsx`

- [ ] **Step 1: 将现有专属入口测试改为通用入口测试**

把 `skill-capability-overview.test.tsx` 最后一个用例替换为：

```tsx
it('每个 Skill 卡片都提供通用测评入口', async () => {
  mockGetSkillGovernanceWorkbench.mockResolvedValueOnce({
    ...response,
    items: [baseItem, draftItem],
  })

  render(<SkillCapabilityOverview />)

  const settlement = await screen.findByTestId('skill-overview-settlement_explain_skill')
  const outpatient = screen.getByTestId('skill-overview-mzsettlement_verify_skill')
  expect(within(settlement).getByRole('link', { name: '测评' })).toHaveAttribute(
    'href',
    '/skills/evaluations?skill=settlement_explain_skill',
  )
  expect(within(outpatient).getByRole('link', { name: '测评' })).toHaveAttribute(
    'href',
    '/skills/evaluations?skill=mzsettlement_verify_skill',
  )
})
```

- [ ] **Step 2: 写测评集面板失败测试**

创建 `skill-eval-suite-panel.test.tsx`：

```tsx
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillEvalSuitePanel from '@/components/skills/skill-eval-suite-panel'
import { createSkillEvalSuite, listSkillEvalSuites, updateSkillEvalSuite } from '@/lib/api-client'

vi.mock('@/lib/api-client', () => ({
  createSkillEvalSuite: vi.fn(),
  listSkillEvalSuites: vi.fn(),
  updateSkillEvalSuite: vi.fn(),
}))

const platformSuite = {
  suite_id: 'EVS_platform_routing',
  name: '平台默认路由测评集',
  scope: 'platform' as const,
  skill_id: null,
  purpose: '兼容历史路由评测与发布门禁',
  status: 'active' as const,
  revision: 1,
  created_by: 'system',
  updated_by: 'system',
  created_at: '2026-08-31T00:00:00Z',
  updated_at: '2026-08-31T00:00:00Z',
}

const skillSuite = {
  ...platformSuite,
  suite_id: 'EVS_skill',
  name: '门诊路由回归',
  scope: 'skill' as const,
  skill_id: 'mzsettlement_verify_skill',
}

describe('SkillEvalSuitePanel', () => {
  beforeEach(() => {
    vi.mocked(listSkillEvalSuites).mockResolvedValue({ items: [platformSuite], total: 1 })
    vi.mocked(createSkillEvalSuite).mockResolvedValue({
      ...platformSuite,
      suite_id: 'EVS_created',
      name: '门诊路由回归',
      scope: 'skill',
      skill_id: 'mzsettlement_verify_skill',
    })
    vi.mocked(updateSkillEvalSuite).mockResolvedValue({
      ...skillSuite,
      status: 'inactive',
      revision: 2,
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('列出、选择并新建当前 Skill 的测评集', async () => {
    const onSelect = vi.fn()
    render(
      <SkillEvalSuitePanel
        skillId="mzsettlement_verify_skill"
        selectedSuiteId={null}
        onSelect={onSelect}
      />,
    )

    expect(await screen.findByText('平台默认路由测评集')).toBeVisible()
    fireEvent.change(screen.getByLabelText('测评集名称'), {
      target: { value: '门诊路由回归' },
    })
    fireEvent.click(screen.getByRole('button', { name: '新建测评集' }))

    await waitFor(() => expect(createSkillEvalSuite).toHaveBeenCalledWith({
      name: '门诊路由回归',
      scope: 'skill',
      skill_id: 'mzsettlement_verify_skill',
      purpose: '',
    }))
    expect(onSelect).toHaveBeenCalledWith('EVS_created')
  })

  it('停用当前 Skill 的非默认测评集', async () => {
    vi.mocked(listSkillEvalSuites).mockResolvedValueOnce({
      items: [platformSuite, skillSuite],
      total: 2,
    })
    render(
      <SkillEvalSuitePanel
        skillId="mzsettlement_verify_skill"
        selectedSuiteId="EVS_skill"
        onSelect={vi.fn()}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: '停用测评集' }))
    await waitFor(() => expect(updateSkillEvalSuite).toHaveBeenCalledWith(
      'EVS_skill',
      {
        name: '门诊路由回归',
        purpose: '兼容历史路由评测与发布门禁',
        status: 'inactive',
        expected_revision: 1,
      },
    ))
  })
})
```

- [ ] **Step 3: 运行 Portal 测试确认红灯**

Run:

```powershell
Set-Location src/apps/portal
npm test -- src/tests/skill-capability-overview.test.tsx src/tests/components/skill-eval-suite-panel.test.tsx
```

Expected: 通用入口断言失败，新组件和 API 函数不存在。

- [ ] **Step 4: 增加前端类型和 API**

在 `types.ts` 增加：

```ts
export interface SkillEvalSuiteResponse {
  suite_id: string
  name: string
  scope: 'platform' | 'skill'
  skill_id?: string | null
  purpose: string
  status: 'active' | 'inactive'
  revision: number
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
}

export interface SkillEvalSuiteListResponse {
  items: SkillEvalSuiteResponse[]
  total: number
}

export interface SkillEvalSuiteCreateRequest {
  name: string
  scope: 'platform' | 'skill'
  skill_id?: string | null
  purpose: string
}

export interface SkillEvalSuiteUpdateRequest {
  name: string
  purpose: string
  status: 'active' | 'inactive'
  expected_revision: number
}
```

给 `SkillEvalCaseResponse` 和 `SkillEvalCaseCreateRequest` 增加 `suite_id`。在 `api-client.ts` 增加：

```ts
export async function listSkillEvalSuites(params?: {
  skillId?: string
  includeInactive?: boolean
}): Promise<SkillEvalSuiteListResponse> {
  const search = new URLSearchParams()
  if (params?.skillId) search.set('skill_id', params.skillId)
  if (params?.includeInactive !== undefined) {
    search.set('include_inactive', String(params.includeInactive))
  }
  const query = search.size ? `?${search.toString()}` : ''
  return requestJson<SkillEvalSuiteListResponse>(`/infra-skills/eval-suites${query}`)
}

export async function createSkillEvalSuite(
  request: SkillEvalSuiteCreateRequest,
): Promise<SkillEvalSuiteResponse> {
  return requestJson<SkillEvalSuiteResponse>('/infra-skills/eval-suites', {
    method: 'POST',
    headers: skillEvaluationHeaders(),
    body: JSON.stringify(request),
  })
}

export async function updateSkillEvalSuite(
  suiteId: string,
  request: SkillEvalSuiteUpdateRequest,
): Promise<SkillEvalSuiteResponse> {
  return requestJson<SkillEvalSuiteResponse>(
    `/infra-skills/eval-suites/${encodeURIComponent(suiteId)}`,
    {
      method: 'PUT',
      headers: skillEvaluationHeaders(),
      body: JSON.stringify(request),
    },
  )
}
```

将 `listSkillEvalCases` 改为接受 `{ suiteId?: string }` 并生成 `suite_id` 查询参数。

- [ ] **Step 5: 实现通用测评集面板**

`skill-eval-suite-panel.tsx` 只负责加载当前 Skill 可见测评集、选择测评集和新建测评集。完整实现为：

```tsx
import { useEffect, useState } from 'react'

import {
  createSkillEvalSuite,
  listSkillEvalSuites,
  updateSkillEvalSuite,
} from '@/lib/api-client'
import { ApiClientError } from '@/lib/types'
import type { SkillEvalSuiteResponse } from '@/lib/types'

interface SkillEvalSuitePanelProps {
  skillId: string | null
  selectedSuiteId: string | null
  onSelect: (suiteId: string) => void
}

function message(error: unknown): string {
  return error instanceof ApiClientError ? error.detail.message : '测评集操作失败'
}

export default function SkillEvalSuitePanel({
  skillId,
  selectedSuiteId,
  onSelect,
}: SkillEvalSuitePanelProps) {
  const [suites, setSuites] = useState<SkillEvalSuiteResponse[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setError(null)
    listSkillEvalSuites({
      skillId: skillId ?? undefined,
      includeInactive: true,
    })
      .then((response) => {
        if (!active) return
        setSuites(response.items)
        if (!selectedSuiteId) {
          const first = response.items.find((item) => item.status === 'active')
          if (first) onSelect(first.suite_id)
        }
      })
      .catch((reason) => {
        if (active) setError(message(reason))
      })
    return () => { active = false }
  }, [onSelect, selectedSuiteId, skillId])

  async function createSuite(): Promise<void> {
    const normalized = name.trim()
    if (!normalized) return
    setBusy(true)
    setError(null)
    try {
      const created = await createSkillEvalSuite({
        name: normalized,
        scope: skillId ? 'skill' : 'platform',
        skill_id: skillId,
        purpose: '',
      })
      setSuites((current) => [...current, created])
      setName('')
      onSelect(created.suite_id)
    } catch (reason) {
      setError(message(reason))
    } finally {
      setBusy(false)
    }
  }

  async function toggleSelected(): Promise<void> {
    const selected = suites.find((item) => item.suite_id === selectedSuiteId)
    if (!selected || selected.suite_id === 'EVS_platform_routing') return
    setBusy(true)
    setError(null)
    try {
      const updated = await updateSkillEvalSuite(selected.suite_id, {
        name: selected.name,
        purpose: selected.purpose,
        status: selected.status === 'active' ? 'inactive' : 'active',
        expected_revision: selected.revision,
      })
      setSuites((current) => current.map((item) => (
        item.suite_id === updated.suite_id ? updated : item
      )))
      if (updated.status === 'inactive') {
        const fallback = suites.find((item) => (
          item.suite_id !== updated.suite_id && item.status === 'active'
        ))
        if (fallback) onSelect(fallback.suite_id)
      }
    } catch (reason) {
      setError(message(reason))
    } finally {
      setBusy(false)
    }
  }

  const selected = suites.find((item) => item.suite_id === selectedSuiteId)

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end">
        <label className="text-xs font-medium text-slate-600">
          选择测评集
          <select
            aria-label="选择测评集"
            value={selectedSuiteId ?? ''}
            onChange={(event) => onSelect(event.target.value)}
            className="mt-1 h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
          >
            <option value="" disabled>请选择测评集</option>
            {suites.map((suite) => (
              <option
                key={suite.suite_id}
                value={suite.suite_id}
                disabled={suite.status === 'inactive'}
              >
                {suite.name}{suite.status === 'inactive' ? '（已停用）' : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600">
          测评集名称
          <input
            aria-label="测评集名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 h-9 w-full rounded-md border border-slate-200 px-2 text-sm"
            maxLength={256}
          />
        </label>
        <button
          type="button"
          onClick={() => void createSuite()}
          disabled={busy || !name.trim()}
          className="h-9 rounded-md bg-blue-600 px-3 text-sm font-medium text-white disabled:opacity-50"
        >
          新建测评集
        </button>
        <button
          type="button"
          onClick={() => void toggleSelected()}
          disabled={busy || !selected || selected.suite_id === 'EVS_platform_routing'}
          className="h-9 rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-700 disabled:opacity-50"
        >
          {selected?.status === 'inactive' ? '启用测评集' : '停用测评集'}
        </button>
      </div>
      {error ? <p role="alert" className="mt-2 text-xs text-rose-700">{error}</p> : null}
    </section>
  )
}
```

界面必须包含：

- `aria-label="选择测评集"` 的 `<select>`；
- `aria-label="测评集名称"` 的 `<input>`；
- “新建测评集”按钮；
- API 错误使用 `role="alert"`；
- inactive 测评集显示“已停用”，且不允许作为新增用例目标。

不在本组件中实现业务数据生成、覆盖分析、门诊金额字段或运行逻辑。

- [ ] **Step 6: 接入评测中心页面**

在 `EvaluationsContent` 增加：

```tsx
const [selectedSuiteId, setSelectedSuiteId] = useState<string | null>(null)
```

在 header 后渲染：

```tsx
<SkillEvalSuitePanel
  skillId={skillFilter}
  selectedSuiteId={selectedSuiteId}
  onSelect={setSelectedSuiteId}
/>
```

`load` 调用 `listSkillEvalCases({ suiteId: selectedSuiteId ?? undefined })`，依赖数组增加 `selectedSuiteId`。新增用例请求增加：

```tsx
suite_id: selectedSuiteId ?? 'EVS_platform_routing',
```

阶段 A 保留 `OutpatientSelfTestPanel` 条件渲染；它在门诊用例完成正式迁移前仍是旧样例的唯一维护入口。

- [ ] **Step 7: 将能力卡片入口通用化**

把 `skill-capability-overview.tsx` 中 `item.skill_id === 'mzsettlement_verify_skill'` 条件块替换为所有卡片都渲染：

```tsx
<Link
  href={`/skills/evaluations?skill=${encodeURIComponent(item.skill_id)}`}
  className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1.5 font-medium text-white hover:bg-blue-700"
>
  <FlaskConical className="size-3.5" aria-hidden="true" />
  测评
</Link>
```

- [ ] **Step 8: 运行 Portal 组件测试**

Run:

```powershell
Set-Location src/apps/portal
npm test -- src/tests/skill-capability-overview.test.tsx src/tests/components/skill-eval-suite-panel.test.tsx
```

Expected: PASS。

- [ ] **Step 9: 运行 Portal 构建**

Run:

```powershell
Set-Location src/apps/portal
npm run build
```

Expected: Next.js build 完成，无 TypeScript 错误。

- [ ] **Step 10: 提交**

```powershell
git add src/apps/portal/src/lib/types.ts src/apps/portal/src/lib/api-client.ts src/apps/portal/src/components/skills/skill-eval-suite-panel.tsx src/apps/portal/app/skills/evaluations/page.tsx src/apps/portal/src/components/skills/skill-capability-overview.tsx src/apps/portal/src/tests/components/skill-eval-suite-panel.test.tsx src/apps/portal/src/tests/skill-capability-overview.test.tsx
git commit -m "feat: 提供通用 Skill 测评集入口"
```

---

### Task 6: 补齐端到端 Flow、审查闭环和分层验证

**Files:**

- Create: `src/tests/integration/flow/test_skill_eval_suite_flow.py`
- Modify only if review finds a confirmed defect: files changed in Tasks 1-5

- [ ] **Step 1: 写完整 Flow 测试**

创建 `test_skill_eval_suite_flow.py`：

```python
import pytest
from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.version_in_memory import (
    InMemorySkillVersionStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    SkillControlPrincipal,
    get_skill_evaluation_principal,
    get_skill_governance_service,
)
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.skill_infra.skill_loader import SkillLoader


PREFIX = "/api/v1/medical-insurance-ai-agent"
EVALUATION_HEADERS: dict[str, str] = {}


@pytest.fixture
def client() -> TestClient:
    loader = SkillLoader(SKILLS_DIR)
    loader.discover()
    app = create_app()
    service = SkillGovernanceService(
        storage=InMemorySkillGovernanceStorage(),
        version_storage=InMemorySkillVersionStorage(),
        loader=loader,
    )
    app.dependency_overrides[get_skill_governance_service] = lambda: service
    app.dependency_overrides[get_skill_evaluation_principal] = lambda: (
        SkillControlPrincipal(user_id="quality-user", roles=("quality",))
    )
    return TestClient(app)


def test_skill_eval_suite_can_be_created_populated_and_listed(client: TestClient) -> None:
    suite = client.post(
        f"{PREFIX}/infra-skills/eval-suites",
        headers=EVALUATION_HEADERS,
        json={
            "name": "费用解释路由回归",
            "scope": "skill",
            "skill_id": "settlement_explain_skill",
            "purpose": "验证费用解释问题路由",
        },
    )
    assert suite.status_code == 201
    suite_id = suite.json()["suite_id"]

    case = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        headers=EVALUATION_HEADERS,
        json={
            "suite_id": suite_id,
            "question_template": "为什么统筹自付这么多",
            "expected_skill_id": "settlement_explain_skill",
            "required": True,
            "risk_tags": ["settlement"],
            "business_tags": ["personal-liability"],
            "source_type": "manual",
            "source_ref": "flow-test",
            "contains_sensitive_data": False,
        },
    )
    assert case.status_code == 201

    listed = client.get(
        f"{PREFIX}/infra-skills/eval-cases",
        params={"suite_id": suite_id},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["question_template"] == "为什么统筹自付这么多"

    protected = client.delete(
        f"{PREFIX}/infra-skills/eval-suites/{suite_id}",
        headers=EVALUATION_HEADERS,
    )
    assert protected.status_code == 409
    assert protected.json()["detail"]["error_code"] == "SKILL_RELEASE_GATE_FAILED"
```

该夹具只使用内存存储，不连接 PostgreSQL、Milvus 或 SQL Server。

- [ ] **Step 2: 运行 T1 单元测试**

Run:

```powershell
uv run python -m pytest src/tests/unit/data_platform/test_skill_governance_storage.py src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

Expected: PASS。失败则停止，不运行 API 测试。

- [ ] **Step 3: 运行 T2a API 测试**

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_openapi_contract.py -q
```

Expected: PASS。失败则停止，不运行 Flow 测试。

- [ ] **Step 4: 运行 T2b Flow 测试**

Run:

```powershell
uv run python -m pytest src/tests/integration/flow/test_skill_eval_suite_flow.py -q
```

Expected: PASS。

- [ ] **Step 5: 执行完整审查闭环**

按以下清单审查 `git diff`：

```text
1. 所有 Skill 卡片是否都有同一“测评”入口。
2. Portal 测评中心是否没有新增任何门诊业务字段。
3. 历史用例和旧 API 是否默认归入 EVS_platform_routing。
4. 新测评集和新用例 ID 是否分别以 EVS_、EVC_ 开头。
5. skill scope 是否拒绝未知 Skill 和错误 expected_skill_id。
6. suite 写操作是否都经过 skill:evaluate。
7. revision 冲突是否返回 409。
8. 非空测评集和默认测评集是否不能删除。
9. PostgreSQL 新列是否同时存在于 CREATE 和 ALTER。
10. 运行和发布门禁是否仍使用原全局 suite_version，未被意外改写。
```

发现问题时先在对应测试文件增加失败断言，再做最小修复，然后从 Step 2 重新串行验证。

- [ ] **Step 6: 运行 Portal 验证**

Run:

```powershell
Set-Location src/apps/portal
npm test -- src/tests/skill-capability-overview.test.tsx src/tests/components/skill-eval-suite-panel.test.tsx
npm run build
```

Expected: 两个 Vitest 文件通过，Next.js build 成功。

- [ ] **Step 7: 检查格式与改动边界**

Run:

```powershell
git diff --check
git status --short
```

Expected: `git diff --check` 无输出；`git status --short` 只包含本阶段计划列出的文件以及工作开始前已存在的用户改动。本阶段不得提交用户已有改动。

- [ ] **Step 8: 提交 Flow 与审查修复**

```powershell
git add src/tests/integration/flow/test_skill_eval_suite_flow.py
git commit -m "test: 覆盖 Skill 测评集维护流程"
```

若 Step 5 产生确认有效的修复，将修复文件和对应测试按问题拆成独立 Angular 提交，不与 Flow 测试提交混合。

---

## 阶段 A 完成定义

以下条件全部满足才可进入下一独立阶段：

- PostgreSQL 和内存存储都存在默认平台路由测评集。
- 旧路由用例无需迁移脚本即可归入默认测评集。
- 可为任意已存在 Skill 创建专属测评集，并生成 `EVS_*`。
- 可在指定测评集中创建路由用例，并生成 `EVC_*`。
- 同问题只在同一测评集内去重，不影响其他测评集。
- 所有 Skill 卡片都显示“测评”，进入同一 `/skills/evaluations` 页面。
- 页面可选择和新建测评集；现有路由用例列表按所选测评集过滤。
- 现有路由运行和发布门禁行为未改变。
- Unit → API → Flow → Portal 测试和构建全部通过。
