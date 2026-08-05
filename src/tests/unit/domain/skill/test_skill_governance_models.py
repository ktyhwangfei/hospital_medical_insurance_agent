from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalMetrics,
    SkillEvalRun,
    SkillEvalRunStatus,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)


def _metrics() -> SkillEvalMetrics:
    return SkillEvalMetrics(
        total=1,
        passed=1,
        required_total=1,
        required_passed=1,
        top1_accuracy=1.0,
        baseline_top1_accuracy=1.0,
        regression_count=0,
        new_false_takeover_count=0,
        gate_passed=True,
    )


def test_eval_case_rejects_sensitive_sample() -> None:
    with pytest.raises(ValidationError):
        SkillEvalCase(
            case_id="case-1",
            suite_version=1,
            question_template="患者张三的身份证号是什么",
            expected_skill_id=None,
            contains_sensitive_data=True,
            created_by="quality-user",
        )


def test_eval_run_requires_sha256_config_hash() -> None:
    with pytest.raises(ValidationError):
        SkillEvalRun(
            run_id="run-1",
            skill_id="demo-skill",
            version_id="version-1",
            suite_version=1,
            config_hash="bad",
            status=SkillEvalRunStatus.PASSED,
            metrics=_metrics(),
            created_by="quality-user",
        )


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


def test_release_rejects_prod_in_phase_two() -> None:
    with pytest.raises(ValidationError):
        SkillRelease(
            release_id="release-1",
            skill_id="demo-skill",
            version_id="version-1",
            environment="prod",
            status=SkillReleaseStatus.CANDIDATE,
            eval_run_id="run-1",
            artifact_hash="a" * 64,
            config_hash="b" * 64,
            created_by="developer",
        )


def test_release_defaults_to_revision_one_and_shadow_mode() -> None:
    release = SkillRelease(
        release_id="release-1",
        skill_id="demo-skill",
        version_id="version-1",
        environment=SkillReleaseEnvironment.TEST,
        status=SkillReleaseStatus.CANDIDATE,
        eval_run_id="run-1",
        artifact_hash="a" * 64,
        config_hash="b" * 64,
        created_by="developer",
        created_at=datetime.now(timezone.utc),
    )

    assert release.revision == 1
    assert release.runtime_mode == "shadow"
