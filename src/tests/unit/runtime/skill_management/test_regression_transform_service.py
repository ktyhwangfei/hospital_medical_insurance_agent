"""Skill 错误案例 AI 转换服务单元测试。

覆盖：六类可执行 proposal 严格分型、other 降级、proposal/dimension 不一致拒绝、
revision 保护、失败不改状态。
"""

from __future__ import annotations

import pytest

from src.data_platform.storage.skill.regression_in_memory import (
    InMemorySkillRegressionStorage,
)
from src.domain.skill.regression_models import (
    CaseProposal,
    RoutingCaseProposal,
    CalculationCaseProposal,
    PolicyContentCaseProposal,
    CitationCaseProposal,
    AnswerQualityCaseProposal,
    SafetyCaseProposal,
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillFeedbackReasonCode,
)
from src.runtime.skill_management.regression_transform_service import (
    RawTransformOutput,
    RegressionTransformService,
    SkillRegressionTransformError,
)


def _seed_pool(storage, pool_id="pool-1", dimension=None) -> SkillEvalCasePoolItem:
    from src.domain.skill.regression_models import reason_code_to_dimension

    rc = SkillFeedbackReasonCode.WRONG_CALCULATION
    item = SkillEvalCasePoolItem.model_validate(
        {
            "pool_id": pool_id,
            "tenant_id": "tenant-1",
            "source_qa_turn_id": "qat_1",
            "source_user_id": "user-1",
            "reason_code": rc,
            "question_excerpt": "起付线怎么算",
            "answer_excerpt": "累计计算",
            "source_selected_skill_id": "deductible",
            "source_hash": "a" * 64,
            "status": SkillEvalCasePoolStatus.PENDING_TRIAGE,
            "created_by": "user-1",
        }
    )
    return storage.create_pool_item(item)


def _proposal_for(dimension: str) -> dict:
    if dimension == "routing":
        return RoutingCaseProposal(
            question_template="起付线怎么算",
            expected_skill_id="deductible",
        ).model_dump()
    if dimension == "calculation":
        return CalculationCaseProposal(
            target_skill_id="deductible",
            input_template={"amount": 1000},
            assertions={
                "case_type": "calculation",
                "expected_value": 100.0,
                "tolerance": 0.01,
            },
        ).model_dump()
    if dimension == "policy_content":
        return PolicyContentCaseProposal(
            target_skill_id="deductible",
            input_template={},
            assertions={
                "case_type": "policy_content",
                "applicability": "applies",
                "must_include": ["起付线"],
            },
        ).model_dump()
    if dimension == "citation":
        return CitationCaseProposal(
            target_skill_id="deductible",
            input_template={},
            assertions={
                "case_type": "citation",
                "required_source_ids": ["doc-1"],
            },
        ).model_dump()
    if dimension == "answer_quality":
        return AnswerQualityCaseProposal(
            target_skill_id="deductible",
            input_template={},
            assertions={
                "case_type": "answer_quality",
                "answerable": True,
                "must_include": ["起付线"],
            },
        ).model_dump()
    if dimension == "safety":
        return SafetyCaseProposal(
            target_skill_id="deductible",
            input_template={},
            assertions={
                "case_type": "safety",
                "blocked_actions": ["refund"],
                "expected_state": "waiting_human_confirmation",
            },
        ).model_dump()
    raise AssertionError(dimension)


def _raw_output(dimension: str) -> RawTransformOutput:
    return RawTransformOutput.model_validate(
        {
            "error_dimension": dimension,
            "root_cause": "归因说明",
            "target_skill_id": "deductible",
            "case_proposal": None if dimension == "other" else _proposal_for(dimension),
            "citations": [{"source_id": "doc-1"}],
            "uncertainties": [],
        }
    )


def build_transform_service(
    *, model_output: RawTransformOutput, storage=None
) -> RegressionTransformService:
    return RegressionTransformService(
        storage=storage or InMemorySkillRegressionStorage(),
        model_provider=lambda context: model_output,
    )


@pytest.mark.parametrize(
    "dimension, expected_type",
    [
        ("routing", RoutingCaseProposal),
        ("calculation", CalculationCaseProposal),
        ("policy_content", PolicyContentCaseProposal),
        ("citation", CitationCaseProposal),
        ("answer_quality", AnswerQualityCaseProposal),
        ("safety", SafetyCaseProposal),
    ],
)
def test_transform_returns_typed_proposal(dimension, expected_type) -> None:
    storage = InMemorySkillRegressionStorage()
    _seed_pool(storage, pool_id="pool-1")
    service = build_transform_service(model_output=_raw_output(dimension), storage=storage)
    result = service.transform("pool-1", expected_revision=1, tenant_id="tenant-1")
    assert isinstance(result.case_proposal, expected_type)
    assert result.transformed_dimension == SkillErrorDimension(dimension)
    pool = storage.get_pool_item("pool-1")
    assert pool.status == SkillEvalCasePoolStatus.TRANSFORMED
    assert pool.revision == 2


def test_transform_other_carries_no_executable_proposal() -> None:
    storage = InMemorySkillRegressionStorage()
    _seed_pool(storage, pool_id="pool-1")
    service = build_transform_service(model_output=_raw_output("other"), storage=storage)
    result = service.transform("pool-1", expected_revision=1, tenant_id="tenant-1")
    assert result.transformed_dimension == SkillErrorDimension.OTHER
    assert result.case_proposal is None
    assert result.uncertainties == []


def test_transform_rejects_other_with_proposal() -> None:
    bad = RawTransformOutput.model_validate(
        {
            "error_dimension": "other",
            "root_cause": "x",
            "target_skill_id": "deductible",
            "case_proposal": _proposal_for("calculation"),
            "citations": [],
            "uncertainties": [],
        }
    )
    storage = InMemorySkillRegressionStorage()
    _seed_pool(storage, pool_id="pool-1")
    service = build_transform_service(model_output=bad, storage=storage)
    with pytest.raises(SkillRegressionTransformError):
        service.transform("pool-1", expected_revision=1, tenant_id="tenant-1")
    # 失败不改状态
    assert (
        storage.get_pool_item("pool-1").status == SkillEvalCasePoolStatus.PENDING_TRIAGE
    )


def test_transform_rejects_executable_without_proposal() -> None:
    bad = RawTransformOutput.model_validate(
        {
            "error_dimension": "calculation",
            "root_cause": "x",
            "target_skill_id": "deductible",
            "case_proposal": None,
            "citations": [],
            "uncertainties": [],
        }
    )
    storage = InMemorySkillRegressionStorage()
    _seed_pool(storage, pool_id="pool-1")
    service = build_transform_service(model_output=bad, storage=storage)
    with pytest.raises(SkillRegressionTransformError):
        service.transform("pool-1", expected_revision=1, tenant_id="tenant-1")


def test_transform_rejects_dimension_proposal_mismatch() -> None:
    bad = RawTransformOutput.model_validate(
        {
            "error_dimension": "calculation",
            "root_cause": "x",
            "target_skill_id": "deductible",
            "case_proposal": _proposal_for("citation"),
            "citations": [],
            "uncertainties": [],
        }
    )
    storage = InMemorySkillRegressionStorage()
    _seed_pool(storage, pool_id="pool-1")
    service = build_transform_service(model_output=bad, storage=storage)
    with pytest.raises(SkillRegressionTransformError):
        service.transform("pool-1", expected_revision=1, tenant_id="tenant-1")


def test_transform_stale_revision_raises_conflict() -> None:
    storage = InMemorySkillRegressionStorage()
    _seed_pool(storage, pool_id="pool-1")
    service = build_transform_service(model_output=_raw_output("calculation"), storage=storage)
    with pytest.raises(Exception):
        service.transform("pool-1", expected_revision=99, tenant_id="tenant-1")
