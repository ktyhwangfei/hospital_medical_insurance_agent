from datetime import datetime, timezone

import pytest

from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceNotFoundError,
)
from src.data_platform.storage.skill.version_in_memory import (
    InMemorySkillVersionStorage,
)
from src.domain.skill.governance_models import (
    DEFAULT_ROUTING_SUITE_ID,
    SkillEvalRunStatus,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.runtime.skill_management.governance_service import (
    SkillGovernanceGateError,
    SkillGovernanceService,
)
from src.skill_infra.skill_loader import LoadedSkill


class _Loader:
    def __init__(self, manifests: list[dict[str, object]]) -> None:
        self._skills = {
            str(manifest["skill_id"]): LoadedSkill(
                skill_id=str(manifest["skill_id"]),
                skill_name=str(manifest["skill_name"]),
                assembler=None,
                manifest=manifest,
                include_keywords=list(manifest.get("supported_intents", [])),
                excluded_intents=[],
            )
            for manifest in manifests
        }

    def get_all(self) -> dict[str, LoadedSkill]:
        return dict(self._skills)


def _manifest(version: str, keywords: list[str]) -> dict[str, object]:
    return {
        "skill_id": "demo-skill",
        "skill_name": "演示技能",
        "version": version,
        "supported_intents": keywords,
        "excluded_intents": [],
    }


def _version(
    version_id: str,
    semantic_version: str,
    keywords: list[str],
) -> SkillVersion:
    return SkillVersion(
        version_id=version_id,
        skill_id="demo-skill",
        semantic_version=semantic_version,
        source_commit="abc1234",
        source_path="skills/demo-skill",
        artifact_hash=version_id[0] * 64,
        manifest_snapshot=_manifest(semantic_version, keywords),
        dependency_snapshot={},
        file_count=2,
        validation_status=SkillValidationStatus.PASSED,
        created_by="developer",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def service() -> SkillGovernanceService:
    versions = InMemorySkillVersionStorage()
    versions.save_version(_version("a-version", "1.0.0", ["统筹自付"]))
    versions.save_version(_version("b-version", "2.0.0", ["起付线"]))
    return SkillGovernanceService(
        storage=InMemorySkillGovernanceStorage(),
        version_storage=versions,
        loader=_Loader([_manifest("runtime", ["统筹自付"])]),
    )


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
    base = {
        "question_template": "起付线怎么算",
        "expected_skill_id": "demo-skill",
        "required": True,
        "risk_tags": [],
        "business_tags": [],
        "source_type": "manual",
        "source_ref": "",
        "contains_sensitive_data": False,
        "created_by": "quality-user",
    }
    first = service.create_case(suite_id=first_suite.suite_id, **base)
    second = service.create_case(suite_id=second_suite.suite_id, **base)

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


def test_case_changes_increment_global_suite_version(
    service: SkillGovernanceService,
) -> None:
    first = service.create_case(
        question_template="统筹自付怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=["settlement"],
        source_type="manual",
        source_ref="quality-1",
        contains_sensitive_data=False,
        created_by="quality-user",
    )
    second = service.update_case(
        first.case_id,
        question_template="统筹自付为什么这么多",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=["high"],
        business_tags=["settlement"],
        source_type="manual",
        source_ref="quality-2",
        enabled=True,
        contains_sensitive_data=False,
    )

    assert first.suite_version == 1
    assert second.suite_version == 2


def test_eval_run_uses_immutable_candidate_manifest(
    service: SkillGovernanceService,
) -> None:
    service.create_case(
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

    passed = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id=None,
        created_by="quality-user",
    )
    failed = service.create_eval_run(
        "demo-skill",
        version_id="b-version",
        baseline_version_id="a-version",
        created_by="quality-user",
    )

    assert passed.status == SkillEvalRunStatus.PASSED
    assert failed.status == SkillEvalRunStatus.FAILED
    assert failed.metrics.regression_count == 1


def test_failed_run_cannot_create_candidate(
    service: SkillGovernanceService,
) -> None:
    service.create_case(
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
    failed = service.create_eval_run(
        "demo-skill",
        version_id="b-version",
        baseline_version_id="a-version",
        created_by="quality-user",
    )

    with pytest.raises(SkillGovernanceGateError, match="评测未通过"):
        service.create_candidate(
            "demo-skill",
            version_id="b-version",
            eval_run_id=failed.run_id,
            environment=SkillReleaseEnvironment.TEST,
            created_by="developer",
        )


def test_candidate_rejects_evaluation_against_non_active_baseline(
    service: SkillGovernanceService,
) -> None:
    service.create_case(
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
    run = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id="a-version",
        created_by="quality-user",
    )

    with pytest.raises(SkillGovernanceGateError) as exc_info:
        service.create_candidate(
            "demo-skill",
            version_id="a-version",
            eval_run_id=run.run_id,
            environment="test",
            created_by="developer",
        )

    assert exc_info.value.gate_failures == ["evaluation_baseline_mismatch"]


def test_candidate_requires_manual_approval_before_test_activation(
    service: SkillGovernanceService,
) -> None:
    service.create_case(
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
    run = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id=None,
        created_by="quality-user",
    )
    candidate = service.create_candidate(
        "demo-skill",
        version_id="a-version",
        eval_run_id=run.run_id,
        environment=SkillReleaseEnvironment.TEST,
        created_by="developer",
    )

    with pytest.raises(SkillGovernanceGateError, match="人工审批"):
        service.activate_release(
            "demo-skill",
            candidate.release_id,
            expected_revision=candidate.revision,
        )

    pending = service.request_approval(
        "demo-skill",
        candidate.release_id,
        expected_revision=candidate.revision,
    )
    approved = service.approve_release(
        "demo-skill",
        candidate.release_id,
        expected_revision=pending.revision,
        approved_by="information-admin",
        approver_role="information_department",
        reason="固定评测通过，同意 test shadow 激活",
    )
    active = service.activate_release(
        "demo-skill",
        candidate.release_id,
        expected_revision=approved.revision,
    )

    assert active.status == SkillReleaseStatus.ACTIVE
    assert active.rollout_percent == 100
    assert service.resolve_shadow("demo-skill", "test") == active
    assert service.list_releases("demo-skill", "test")[0] == active


def test_eval_suite_change_invalidates_existing_approval(
    service: SkillGovernanceService,
) -> None:
    service.create_case(
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
    run = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id=None,
        created_by="quality-user",
    )
    candidate = service.create_candidate(
        "demo-skill",
        version_id="a-version",
        eval_run_id=run.run_id,
        environment="test",
        created_by="developer",
    )
    pending = service.request_approval(
        "demo-skill", candidate.release_id, expected_revision=1
    )
    approved = service.approve_release(
        "demo-skill",
        candidate.release_id,
        expected_revision=pending.revision,
        approved_by="information-admin",
        approver_role="information_department",
        reason="同意",
    )
    service.create_case(
        question_template="今天天气怎么样",
        expected_skill_id=None,
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="",
        contains_sensitive_data=False,
        created_by="quality-user",
    )

    with pytest.raises(SkillGovernanceGateError) as exc_info:
        service.activate_release(
            "demo-skill",
            candidate.release_id,
            expected_revision=approved.revision,
        )

    assert exc_info.value.gate_failures == ["eval_suite_changed"]


def test_candidate_creator_cannot_self_approve(
    service: SkillGovernanceService,
) -> None:
    service.create_case(
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
    run = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id=None,
        created_by="quality-user",
    )
    candidate = service.create_candidate(
        "demo-skill",
        version_id="a-version",
        eval_run_id=run.run_id,
        environment="test",
        created_by="developer",
    )
    pending = service.request_approval(
        "demo-skill", candidate.release_id, expected_revision=1
    )

    with pytest.raises(SkillGovernanceGateError) as exc_info:
        service.approve_release(
            "demo-skill",
            candidate.release_id,
            expected_revision=pending.revision,
            approved_by="developer",
            approver_role="information_department",
            reason="自己审批",
        )

    assert exc_info.value.gate_failures == ["self_approval_forbidden"]


@pytest.mark.parametrize(
    "question_template",
    [
        "请查询患者身份证号 11010519491231002X 的医保待遇",
        "联系患者手机号 13800138000 确认结算情况",
    ],
)
def test_eval_case_rejects_sensitive_content_even_when_client_marks_safe(
    service: SkillGovernanceService,
    question_template: str,
) -> None:
    with pytest.raises(SkillGovernanceGateError) as exc_info:
        service.create_case(
            question_template=question_template,
            expected_skill_id="demo-skill",
            required=True,
            risk_tags=[],
            business_tags=[],
            source_type="manual",
            source_ref="",
            contains_sensitive_data=False,
            created_by="tester",
        )

    assert exc_info.value.gate_failures == ["sensitive_data_detected"]


def test_eval_run_keeps_immutable_case_snapshot(
    service: SkillGovernanceService,
) -> None:
    case = service.create_case(
        question_template="统筹自付怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="original",
        contains_sensitive_data=False,
        created_by="quality-user",
    )
    run = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id=None,
        created_by="quality-user",
    )
    service.update_case(
        case.case_id,
        question_template="起付线怎么算",
        expected_skill_id="demo-skill",
        required=True,
        risk_tags=[],
        business_tags=[],
        source_type="manual",
        source_ref="changed",
        enabled=True,
        contains_sensitive_data=False,
    )

    stored_run = service.get_eval_run("demo-skill", run.run_id)

    assert stored_run.case_snapshots[0].question_template == "统筹自付怎么算"
    assert stored_run.case_snapshots[0].source_ref == "original"


def test_candidate_rejects_changed_routing_manifest_corpus() -> None:
    versions = InMemorySkillVersionStorage()
    versions.save_version(_version("a-version", "1.0.0", ["统筹自付"]))
    loader = _Loader([_manifest("runtime", ["统筹自付"])])
    service = SkillGovernanceService(
        storage=InMemorySkillGovernanceStorage(),
        version_storage=versions,
        loader=loader,
    )
    service.create_case(
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
    run = service.create_eval_run(
        "demo-skill",
        version_id="a-version",
        baseline_version_id=None,
        created_by="quality-user",
    )
    loader._skills["competing-skill"] = LoadedSkill(
        skill_id="competing-skill",
        skill_name="竞争技能",
        assembler=None,
        manifest={
            "skill_id": "competing-skill",
            "skill_name": "竞争技能",
            "supported_intents": ["统筹自付"],
            "excluded_intents": [],
        },
        include_keywords=["统筹自付"],
        excluded_intents=[],
    )

    with pytest.raises(SkillGovernanceGateError) as exc_info:
        service.create_candidate(
            "demo-skill",
            version_id="a-version",
            eval_run_id=run.run_id,
            environment="test",
            created_by="developer",
        )

    assert "routing_manifest_changed" in exc_info.value.gate_failures
