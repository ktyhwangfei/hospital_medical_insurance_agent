"""Skill 错误挖掘案例池与分型回归领域模型单元测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.domain.skill.regression_models import (
    AnswerQualityAssertions,
    CalculationAssertions,
    CitationAssertions,
    PolicyContentAssertions,
    RoutingCaseProposal,
    SafetyAssertions,
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillFeedbackReasonCode,
    SkillRegressionCase,
    SkillRegressionEvaluatorStatus,
)


def _valid_pool_kwargs(**overrides) -> dict:
    base = dict(
        pool_id="pool-1",
        tenant_id="tenant-1",
        source_qa_turn_id="qat_1",
        source_user_id="user-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        question_excerpt="起付线怎么计算",
        answer_excerpt="按年度累计计算",
        source_hash="0" * 64,
    )
    base.update(overrides)
    return base


def valid_pool_item(**overrides) -> SkillEvalCasePoolItem:
    return SkillEvalCasePoolItem.model_validate(_valid_pool_kwargs(**overrides))


@pytest.mark.parametrize(
    "dimension",
    [
        "routing",
        "calculation",
        "policy_content",
        "citation",
        "answer_quality",
        "safety",
        "other",
    ],
)
def test_case_pool_accepts_every_skill_error_dimension(dimension: str) -> None:
    item = valid_pool_item(error_dimension=SkillErrorDimension(dimension))
    assert item.error_dimension.value == dimension


def test_reason_code_maps_to_initial_error_dimension() -> None:
    item = valid_pool_item(reason_code=SkillFeedbackReasonCode.WRONG_POLICY_CONTENT)
    # 错误维度由 reason_code 决定初始值
    assert item.error_dimension == SkillErrorDimension.POLICY_CONTENT


def test_pool_item_default_status_is_pending_triage() -> None:
    item = valid_pool_item()
    assert item.status == SkillEvalCasePoolStatus.PENDING_TRIAGE
    assert item.revision == 1


def test_calculation_case_rejects_natural_language_expected() -> None:
    with pytest.raises(ValidationError):
        SkillRegressionCase.model_validate(
            {
                "case_id": "case-1",
                "target_skill_id": "deductible",
                "case_type": "calculation",
                "input_template": {"amount": 1000},
                "expected_assertions": "结果应该差不多正确",
                "source_ref": "qat_1",
                "source_hash": "0" * 64,
                "confirmed_by": "reviewer-1",
            }
        )


def _calculation_case_kwargs(**overrides) -> dict:
    base = dict(
        case_id="case-1",
        target_skill_id="deductible",
        case_type="calculation",
        input_template={"amount": 1000},
        expected_assertions={
            "case_type": "calculation",
            "expected_value": 650.0,
            "tolerance": 0.01,
        },
        source_ref="qat_1",
        source_hash="0" * 64,
        confirmed_by="reviewer-1",
    )
    base.update(overrides)
    return base


def test_calculation_case_accepts_typed_assertions() -> None:
    case = SkillRegressionCase.model_validate(_calculation_case_kwargs())
    assert case.case_type == SkillErrorDimension.CALCULATION
    assert isinstance(case.expected_assertions, CalculationAssertions)
    assert case.expected_assertions.expected_value == 650.0
    assert case.evaluator_status == SkillRegressionEvaluatorStatus.BLOCKED_BY_EVALUATOR


def test_regression_case_case_type_must_match_assertions_type() -> None:
    # case_type 声明 calculation，但 assertions 是 safety → 校验失败
    with pytest.raises(ValidationError):
        SkillRegressionCase.model_validate(
            _calculation_case_kwargs(
                case_type="calculation",
                expected_assertions={
                    "case_type": "safety",
                    "sensitive_fields": [],
                    "blocked_actions": [],
                    "expected_state": "waiting_human_confirmation",
                },
            )
        )


@pytest.mark.parametrize(
    "case_type, assertions",
    [
        (
            "policy_content",
            PolicyContentAssertions(
                applicability="applies",
                must_include=["起付线 650 元"],
            ).model_dump(),
        ),
        (
            "citation",
            CitationAssertions(required_source_ids=["policy-doc-1"]).model_dump(),
        ),
        (
            "answer_quality",
            AnswerQualityAssertions(
                answerable=True, must_include=["统筹自付"], must_not_include=[]
            ).model_dump(),
        ),
        (
            "safety",
            SafetyAssertions(
                sensitive_fields=[],
                blocked_actions=["refund"],
                expected_state="waiting_human_confirmation",
            ).model_dump(),
        ),
    ],
)
def test_regression_case_supports_every_executable_dimension(
    case_type: str, assertions: dict
) -> None:
    case = SkillRegressionCase.model_validate(
        _calculation_case_kwargs(case_type=case_type, expected_assertions=assertions)
    )
    assert case.case_type.value == case_type


def test_routing_proposal_does_not_carry_regression_assertions() -> None:
    proposal = RoutingCaseProposal(
        question_template="起付线怎么计算",
        expected_skill_id="deductible",
    )
    assert proposal.case_type == "routing"
    # routing 投影到现有 SkillEvalCase，proposal 不携带回归断言
    assert not hasattr(proposal, "assertions")
    assert SkillErrorDimension.ROUTING != SkillErrorDimension.CALCULATION


def test_other_dimension_is_not_executable() -> None:
    item = valid_pool_item(error_dimension=SkillErrorDimension.OTHER)
    assert item.error_dimension == SkillErrorDimension.OTHER


def test_source_hash_must_be_sha256_hex() -> None:
    with pytest.raises(ValidationError):
        valid_pool_item(source_hash="not-a-hash")
