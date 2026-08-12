"""Skill 错误案例人工确认投影服务单元测试。

覆盖：routing 投影到 SkillEvalCase、计算类创建 SkillRegressionCase、
other 拒绝、幂等（重复 confirm 返回同一资产）、stale revision。
"""

from __future__ import annotations

import pytest

from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.storage.skill.regression_in_memory import (
    InMemorySkillRegressionStorage,
)
from src.domain.skill.governance_models import SkillEvalCase
from src.domain.skill.regression_models import (
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillFeedbackReasonCode,
    SkillRegressionEvaluatorStatus,
)
from src.runtime.api.skill_schemas import EvalCasePoolConfirmRequest
from src.runtime.skill_management.regression_confirm_service import (
    ConfirmResult,
    RegressionConfirmService,
    SkillRegressionCaseNotExecutableError,
)


def _seed_pool(storage, *, pool_id, status=SkillEvalCasePoolStatus.TRANSFORMED) -> SkillEvalCasePoolItem:
    return storage.create_pool_item(
        SkillEvalCasePoolItem.model_validate(
            {
                "pool_id": pool_id,
                "tenant_id": "tenant-1",
                "source_qa_turn_id": "qat_1",
                "source_user_id": "user-1",
                "reason_code": SkillFeedbackReasonCode.WRONG_CALCULATION,
                "question_excerpt": "起付线",
                "answer_excerpt": "累计",
                "source_selected_skill_id": "deductible",
                "source_hash": "a" * 64,
                "status": status,
                "created_by": "user-1",
            }
        )
    )


def _calculation_proposal():
    return {
        "case_type": "calculation",
        "target_skill_id": "deductible",
        "input_template": {"amount": 1000},
        "assertions": {
            "case_type": "calculation",
            "expected_value": 100.0,
            "tolerance": 0.01,
        },
    }


def _routing_proposal():
    return {
        "case_type": "routing",
        "question_template": "起付线怎么算",
        "expected_skill_id": "deductible",
    }


def build_service(
    *,
    regression_storage=None,
    governance_storage=None,
) -> RegressionConfirmService:
    return RegressionConfirmService(
        regression_storage=regression_storage or InMemorySkillRegressionStorage(),
        governance_storage=governance_storage or InMemorySkillGovernanceStorage(),
    )


def test_confirm_calculation_creates_regression_case() -> None:
    regression = InMemorySkillRegressionStorage()
    _seed_pool(regression, pool_id="pool-calc")
    service = build_service(regression_storage=regression)
    request = EvalCasePoolConfirmRequest(
        expected_revision=1,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal=_calculation_proposal(),
    )
    result = service.confirm(
        "pool-calc", request=request, confirmed_by="quality-user", tenant_id="tenant-1"
    )
    assert result.case_type == "calculation"
    case = regression.get_case(result.case_id)
    assert case.case_type == SkillErrorDimension.CALCULATION
    assert case.evaluator_status == SkillRegressionEvaluatorStatus.BLOCKED_BY_EVALUATOR
    assert case.confirmed_by == "quality-user"
    pool = regression.get_pool_item("pool-calc")
    assert pool.status == SkillEvalCasePoolStatus.CONFIRMED


def test_confirm_routing_projects_to_existing_route_case() -> None:
    governance = InMemorySkillGovernanceStorage()
    regression = InMemorySkillRegressionStorage()
    _seed_pool(regression, pool_id="pool-routing")
    service = build_service(
        regression_storage=regression, governance_storage=governance
    )
    request = EvalCasePoolConfirmRequest(
        expected_revision=1,
        error_dimension="routing",
        target_skill_id="deductible",
        case_proposal=_routing_proposal(),
    )
    result = service.confirm(
        "pool-routing",
        request=request,
        confirmed_by="quality-user",
        tenant_id="tenant-1",
    )
    assert result.case_type == "route"
    cases = governance.list_cases()
    matched = [c for c in cases if c.case_id == result.case_id]
    assert matched
    assert matched[0].source_type == "policy_qa_feedback"
    assert matched[0].source_ref == "qat_1"


def test_confirm_other_is_rejected() -> None:
    regression = InMemorySkillRegressionStorage()
    _seed_pool(regression, pool_id="pool-other")
    service = build_service(regression_storage=regression)
    request = EvalCasePoolConfirmRequest(
        expected_revision=1, error_dimension="other", case_proposal=None
    )
    with pytest.raises(SkillRegressionCaseNotExecutableError):
        service.confirm(
            "pool-other",
            request=request,
            confirmed_by="quality-user",
            tenant_id="tenant-1",
        )


def test_confirm_is_idempotent_by_pool_id() -> None:
    regression = InMemorySkillRegressionStorage()
    _seed_pool(regression, pool_id="pool-calc")
    service = build_service(regression_storage=regression)
    request = EvalCasePoolConfirmRequest(
        expected_revision=1,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal=_calculation_proposal(),
    )
    first = service.confirm(
        "pool-calc", request=request, confirmed_by="quality-user", tenant_id="tenant-1"
    )
    # 重复确认（已是 confirmed 状态）返回同一资产
    second_request = EvalCasePoolConfirmRequest(
        expected_revision=first.revision,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal=_calculation_proposal(),
    )
    second = service.confirm(
        "pool-calc",
        request=second_request,
        confirmed_by="quality-user",
        tenant_id="tenant-1",
    )
    assert second.case_id == first.case_id


def test_confirm_stale_revision_raises_conflict() -> None:
    regression = InMemorySkillRegressionStorage()
    _seed_pool(regression, pool_id="pool-calc")
    service = build_service(regression_storage=regression)
    request = EvalCasePoolConfirmRequest(
        expected_revision=99,
        error_dimension="calculation",
        target_skill_id="deductible",
        case_proposal=_calculation_proposal(),
    )
    with pytest.raises(Exception):
        service.confirm(
            "pool-calc",
            request=request,
            confirmed_by="quality-user",
            tenant_id="tenant-1",
        )
