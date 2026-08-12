from datetime import datetime, timezone

import pytest

from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
)
from src.data_platform.storage.skill.governance_postgres import (
    SKILL_GOVERNANCE_TABLE_SCHEMA,
)
from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)


def _release(
    release_id: str,
    status: SkillReleaseStatus,
    *,
    version_id: str | None = None,
) -> SkillRelease:
    return SkillRelease(
        release_id=release_id,
        skill_id="demo-skill",
        version_id=version_id or f"version-{release_id}",
        environment=SkillReleaseEnvironment.TEST,
        status=status,
        eval_run_id=f"run-{release_id}",
        artifact_hash=(release_id[0] * 64),
        config_hash="f" * 64,
        created_by="developer",
        created_at=datetime.now(timezone.utc),
    )


def test_case_update_requires_increasing_suite_version() -> None:
    storage = InMemorySkillGovernanceStorage()
    first = SkillEvalCase(
        case_id="case-1",
        suite_version=1,
        question_template="统筹自付怎么算",
        expected_skill_id="demo-skill",
        created_by="quality-user",
    )
    storage.save_case(first)

    with pytest.raises(SkillGovernanceConflictError):
        storage.save_case(first.model_copy(update={"question_template": "起付线怎么算"}))

    updated = storage.save_case(
        first.model_copy(
            update={"question_template": "起付线怎么算", "suite_version": 2}
        )
    )
    assert updated.suite_version == 2


def test_release_transition_rejects_stale_revision() -> None:
    storage = InMemorySkillGovernanceStorage()
    candidate = storage.save_release(
        _release("candidate", SkillReleaseStatus.CANDIDATE)
    )
    pending = candidate.model_copy(
        update={
            "status": SkillReleaseStatus.APPROVAL_PENDING,
            "revision": candidate.revision + 1,
        }
    )
    storage.update_release(pending, expected_revision=1)

    with pytest.raises(SkillGovernanceConflictError):
        storage.update_release(pending, expected_revision=1)


def test_activation_retires_previous_active_atomically() -> None:
    storage = InMemorySkillGovernanceStorage()
    old = storage.save_release(_release("a", SkillReleaseStatus.ACTIVE))
    candidate = storage.save_release(
        _release("b", SkillReleaseStatus.APPROVED).model_copy(
            update={"baseline_release_id": old.release_id}
        )
    )

    active = storage.activate_release(candidate.release_id, expected_revision=1)

    assert active.status == SkillReleaseStatus.ACTIVE
    assert active.rollout_percent == 100
    assert storage.get_release(old.release_id).status == SkillReleaseStatus.RETIRED
    assert storage.list_active_releases("demo-skill", "test") == [active]


def test_activation_rejects_stale_revision_without_retiring_active() -> None:
    storage = InMemorySkillGovernanceStorage()
    old = storage.save_release(_release("a", SkillReleaseStatus.ACTIVE))
    candidate = storage.save_release(_release("b", SkillReleaseStatus.APPROVED))

    with pytest.raises(SkillGovernanceConflictError):
        storage.activate_release(candidate.release_id, expected_revision=2)

    assert storage.get_release(old.release_id).status == SkillReleaseStatus.ACTIVE
    assert storage.get_release(candidate.release_id).status == SkillReleaseStatus.APPROVED


def test_activation_rejects_changed_baseline_inside_atomic_switch() -> None:
    storage = InMemorySkillGovernanceStorage()
    old = storage.save_release(_release("a", SkillReleaseStatus.ACTIVE))
    candidate = storage.save_release(_release("b", SkillReleaseStatus.APPROVED))

    with pytest.raises(SkillGovernanceConflictError, match="基线"):
        storage.activate_release(candidate.release_id, expected_revision=1)

    assert storage.get_release(old.release_id).status == SkillReleaseStatus.ACTIVE
    assert storage.get_release(candidate.release_id).status == SkillReleaseStatus.APPROVED


def test_storage_returns_deep_copies() -> None:
    storage = InMemorySkillGovernanceStorage()
    release = storage.save_release(_release("a", SkillReleaseStatus.CANDIDATE))

    assert storage.get_release(release.release_id) is not release
    assert storage.list_releases("demo-skill", "test")[0] is not release


def test_postgres_schema_enforces_one_active_release_per_environment() -> None:
    normalized = " ".join(SKILL_GOVERNANCE_TABLE_SCHEMA.split())

    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_release_active" in normalized
    assert "WHERE status = 'active'" in normalized


def test_approval_and_release_transition_are_atomic() -> None:
    storage = InMemorySkillGovernanceStorage()
    pending = storage.save_release(
        _release("a", SkillReleaseStatus.APPROVAL_PENDING)
    )
    approval = SkillReleaseApproval(
        approval_id="approval-a",
        release_id=pending.release_id,
        artifact_hash=pending.artifact_hash,
        eval_run_id=pending.eval_run_id,
        config_hash=pending.config_hash,
        baseline_release_id=pending.baseline_release_id,
        approved_by="information-admin",
        approver_role="information_department",
        reason="同意",
    )
    approved = pending.model_copy(
        update={"status": SkillReleaseStatus.APPROVED, "revision": 2}
    )

    stored = storage.approve_release(
        approved, approval, expected_revision=pending.revision
    )

    assert stored.status == SkillReleaseStatus.APPROVED
    assert storage.get_approval(pending.release_id) == approval


def test_suite_version_is_allocated_by_storage() -> None:
    storage = InMemorySkillGovernanceStorage()

    assert storage.current_suite_version() == 0
    assert storage.next_suite_version() == 1
    assert storage.next_suite_version() == 2
    assert storage.current_suite_version() == 2


def test_activation_rechecks_suite_version_inside_storage_boundary() -> None:
    storage = InMemorySkillGovernanceStorage()
    candidate = storage.save_release(_release("a", SkillReleaseStatus.APPROVED))
    storage.next_suite_version()

    with pytest.raises(SkillGovernanceConflictError):
        storage.activate_release(
            candidate.release_id,
            expected_revision=1,
            expected_suite_version=0,
        )


def test_eval_run_round_trips_regression_results_and_summary() -> None:
    """SkillEvalRun 新增的 regression_results/regression_summary 经存储原样往返。"""
    from src.domain.skill.governance_models import (
        SkillEvalRun,
        SkillEvalRunStatus,
        SkillRegressionEvalRecord,
        SkillRegressionSummary,
        SkillEvalMetrics,
    )

    storage = InMemorySkillGovernanceStorage()
    run = SkillEvalRun(
        run_id="run-1",
        skill_id="demo-skill",
        version_id="version-1",
        baseline_version_id=None,
        suite_version=1,
        config_hash="a" * 64,
        routing_manifest_hash="b" * 64,
        status=SkillEvalRunStatus.PASSED,
        metrics=SkillEvalMetrics(
            total=1, passed=1, required_total=1, required_passed=1,
            top1_accuracy=1.0, baseline_top1_accuracy=1.0,
            regression_count=0, new_false_takeover_count=0, gate_passed=True,
        ),
        regression_results=[
            SkillRegressionEvalRecord(
                case_id="case-c",
                case_type="calculation",
                candidate_version_id="version-1",
                case_snapshot_hash="c" * 64,
                evaluator_version="1.0.0",
                passed=True,
                status="passed",
                failure_codes=[],
                required=True,
            )
        ],
        regression_summary=SkillRegressionSummary(
            total=1, passed=1, failed=0, blocked=0,
            required_total=1, required_passed=1, required_blocked=0,
            gate_passed=True,
        ),
        created_by="quality-user",
    )
    saved = storage.save_run(run)
    fetched = storage.get_run("demo-skill", "run-1")
    assert fetched is not None
    assert len(fetched.regression_results) == 1
    assert fetched.regression_results[0].case_id == "case-c"
    assert fetched.regression_summary is not None
    assert fetched.regression_summary.gate_passed is True
    # 深拷贝：修改返回值不影响存储
    assert saved is not fetched


def test_skill_eval_runs_insert_columns_covered_by_ddl() -> None:
    """防回归：save_run INSERT 列必须 ⊆ DDL 列（CREATE + ALTER ADD COLUMN）。

    旧库已建表时 CREATE TABLE IF NOT EXISTS 不补列，必须配 ALTER ADD COLUMN IF NOT EXISTS。
    （发起评测曾因 regression_results/regression_summary 漏配 ALTER 报 UndefinedColumn 500）
    """
    import inspect
    import re

    from src.data_platform.storage.skill.governance_postgres import (
        PostgresSkillGovernanceStorage,
    )

    ddl = SKILL_GOVERNANCE_TABLE_SCHEMA
    create_block = re.search(
        r"CREATE TABLE IF NOT EXISTS skill_eval_runs \((.*?)\)\s*;", ddl, re.DOTALL
    )
    assert create_block, "未找到 skill_eval_runs CREATE TABLE 块"
    create_cols = set()
    for line in create_block.group(1).splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token.isidentifier():
            create_cols.add(token)
    alter_cols = set(
        re.findall(
            r"ALTER TABLE skill_eval_runs\s+ADD COLUMN IF NOT EXISTS (\w+)", ddl
        )
    )
    ddl_cols = create_cols | alter_cols

    src = inspect.getsource(PostgresSkillGovernanceStorage.save_run)
    insert_match = re.search(r"INSERT INTO skill_eval_runs \(([^)]*)\)", src, re.DOTALL)
    assert insert_match, "未找到 save_run INSERT 语句"
    insert_cols = {
        c.strip().split()[0] for c in insert_match.group(1).split(",") if c.strip()
    }

    missing = insert_cols - ddl_cols
    assert not missing, (
        f"save_run INSERT 列未在 DDL（CREATE+ALTER）定义: {missing}。"
        "旧库 CREATE IF NOT EXISTS 不补列，必须配 ALTER ADD COLUMN IF NOT EXISTS。"
    )
