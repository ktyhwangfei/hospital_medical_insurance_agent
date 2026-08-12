"""Skill 回归案例池与回归用例存储适配器单元测试（内存实现）。"""

from __future__ import annotations

import pytest

from src.data_platform.storage.skill.regression_ports import (
    SkillRegressionConflictError,
    SkillRegressionNotFoundError,
)
from src.data_platform.storage.skill.regression_in_memory import (
    InMemorySkillRegressionStorage,
)
from src.domain.skill.regression_models import (
    CalculationAssertions,
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillFeedbackReasonCode,
    SkillRegressionCase,
)


def _pool_item(**overrides) -> SkillEvalCasePoolItem:
    base = dict(
        pool_id="pool-1",
        tenant_id="tenant-1",
        source_qa_turn_id="qat_1",
        source_user_id="user-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        question_excerpt="起付线怎么计算",
        answer_excerpt="按年度累计计算",
        source_hash="a" * 64,
    )
    base.update(overrides)
    return SkillEvalCasePoolItem.model_validate(base)


def _regression_case(**overrides) -> SkillRegressionCase:
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
        source_hash="a" * 64,
        confirmed_by="reviewer-1",
    )
    base.update(overrides)
    return SkillRegressionCase.model_validate(base)


# ── 案例池去重 ──────────────────────────────────────────────────


def test_pool_deduplicates_by_tenant_and_qa_turn() -> None:
    storage = InMemorySkillRegressionStorage()
    first = storage.create_pool_item(_pool_item(pool_id="pool-1"))
    second = storage.create_pool_item(
        _pool_item(pool_id="pool-2", comment="另一条反馈")
    )

    # 同一 (tenant_id, source_qa_turn_id) 合并到首条，不产生第二条
    assert second.pool_id == first.pool_id
    assert storage.count_pool_items() == 1


def test_pool_dedup_is_tenant_scoped() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1", tenant_id="tenant-1"))
    other = storage.create_pool_item(
        _pool_item(pool_id="pool-2", tenant_id="tenant-2")
    )
    # 不同租户的同一 qa_turn 各自独立
    assert other.pool_id == "pool-2"
    assert storage.count_pool_items() == 2


def test_get_pool_item_returns_deep_copy() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1"))
    fetched = storage.get_pool_item("pool-1")
    assert fetched is not None
    fetched_mutated = fetched.model_copy(update={"comment": "篡改"})
    again = storage.get_pool_item("pool-1")
    assert again.comment == ""


# ── transform / confirm / reject 状态机 ───────────────────────────


def test_transform_updates_payload_and_revision() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1"))
    transformed = storage.transform_pool_item(
        "pool-1",
        tenant_id="tenant-1",
        transformed_dimension=SkillErrorDimension.CALCULATION,
        transformed_proposal={"case_type": "calculation"},
        transformed_root_cause="计算口径错误",
        transformed_citations=[],
        transformed_uncertainties=[],
        expected_revision=1,
    )
    assert transformed.status == SkillEvalCasePoolStatus.TRANSFORMED
    assert transformed.revision == 2
    assert transformed.transformed_root_cause == "计算口径错误"


def test_transform_rejects_stale_revision() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1"))
    with pytest.raises(SkillRegressionConflictError):
        storage.transform_pool_item(
            "pool-1",
            tenant_id="tenant-1",
            transformed_dimension=SkillErrorDimension.CALCULATION,
            transformed_proposal=None,
            transformed_root_cause=None,
            transformed_citations=[],
            transformed_uncertainties=[],
            expected_revision=99,
        )


def test_confirm_pool_item_is_idempotent_and_revision_checked() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1"))
    storage.transform_pool_item(
        "pool-1",
        tenant_id="tenant-1",
        transformed_dimension=SkillErrorDimension.CALCULATION,
        transformed_proposal={"case_type": "calculation"},
        transformed_root_cause=None,
        transformed_citations=[],
        transformed_uncertainties=[],
        expected_revision=1,
    )
    first = storage.confirm_pool_item(
        "pool-1",
        tenant_id="tenant-1",
        case_type="calculation",
        case_id="case-1",
        expected_revision=2,
    )
    assert first.status == SkillEvalCasePoolStatus.CONFIRMED
    assert first.eval_case_ref is not None
    assert first.eval_case_ref.case_id == "case-1"
    assert first.revision == 3

    # 同一目标幂等：返回同一 ref，不递增
    second = storage.confirm_pool_item(
        "pool-1",
        tenant_id="tenant-1",
        case_type="calculation",
        case_id="case-1",
        expected_revision=first.revision,
    )
    assert second.eval_case_ref.case_id == first.eval_case_ref.case_id
    assert second.revision == first.revision

    # stale revision 冲突
    with pytest.raises(SkillRegressionConflictError):
        storage.confirm_pool_item(
            "pool-1",
            tenant_id="tenant-1",
            case_type="calculation",
            case_id="case-1",
            expected_revision=2,
        )


def test_confirm_conflict_when_target_differs() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1"))
    storage.confirm_pool_item(
        "pool-1",
        tenant_id="tenant-1",
        case_type="calculation",
        case_id="case-1",
        expected_revision=1,
    )
    with pytest.raises(SkillRegressionConflictError):
        storage.confirm_pool_item(
            "pool-1",
            tenant_id="tenant-1",
            case_type="policy_content",
            case_id="case-2",
            expected_revision=2,
        )


def test_reject_pool_item_records_reason() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1"))
    rejected = storage.reject_pool_item(
        "pool-1",
        tenant_id="tenant-1",
        reason="误报，无需入池",
        expected_revision=1,
    )
    assert rejected.status == SkillEvalCasePoolStatus.REJECTED
    assert rejected.rejection_reason == "误报，无需入池"


# ── 跨租户隔离 ──────────────────────────────────────────────────


def test_cross_tenant_access_does_not_disclose_existence() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(_pool_item(pool_id="pool-1", tenant_id="tenant-1"))
    # 跨租户查询返回 None（不泄露存在性）
    assert storage.get_pool_item("pool-1", tenant_id="tenant-2") is None
    with pytest.raises(SkillRegressionNotFoundError):
        storage.confirm_pool_item(
            "pool-1",
            tenant_id="tenant-2",
            case_type="calculation",
            case_id="case-1",
            expected_revision=1,
        )


# ── 回归用例存储 ────────────────────────────────────────────────


def test_create_and_get_regression_case() -> None:
    storage = InMemorySkillRegressionStorage()
    case = storage.create_case(_regression_case(case_id="case-1"))
    assert case.case_id == "case-1"
    assert storage.get_case("case-1").case_id == "case-1"
    assert storage.count_cases() == 1


def test_regression_case_unique_by_source_and_type() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_case(_regression_case(case_id="case-1"))
    # 同一 (source_type, source_ref, case_type) 视为重复
    with pytest.raises(SkillRegressionConflictError):
        storage.create_case(_regression_case(case_id="case-2"))
    # 不同 case_type 允许共存
    other = storage.create_case(
        _regression_case(
            case_id="case-3",
            case_type="policy_content",
            expected_assertions={
                "case_type": "policy_content",
                "applicability": "applies",
                "must_include": ["起付线"],
            },
        )
    )
    assert other.case_id == "case-3"
    assert storage.count_cases() == 2


def test_list_pool_items_supports_filters() -> None:
    storage = InMemorySkillRegressionStorage()
    storage.create_pool_item(
        _pool_item(pool_id="p-1", reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION)
    )
    storage.create_pool_item(
        _pool_item(
            pool_id="p-2",
            source_qa_turn_id="qat_2",
            reason_code=SkillFeedbackReasonCode.WRONG_POLICY_CONTENT,
        )
    )
    calc = storage.list_pool_items(
        tenant_id="tenant-1", error_dimension=SkillErrorDimension.CALCULATION
    )
    assert [item.pool_id for item in calc] == ["p-1"]
    assert storage.count_pool_items() == 2
