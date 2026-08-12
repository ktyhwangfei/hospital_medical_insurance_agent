"""Skill 回归案例挖掘应用服务单元测试。

覆盖：服务端按 ID 读取来源、所有权/租户校验、脱敏、二次敏感扫描、去重与幂等。
"""

from __future__ import annotations

import hashlib

import pytest

from src.data_platform.storage.skill.regression_in_memory import (
    InMemorySkillRegressionStorage,
)
from src.domain.skill.regression_models import SkillErrorDimension, SkillFeedbackReasonCode
from src.runtime.skill_management.regression_mining_service import (
    HistoryMiningOutcome,
    HistoryMiningStatus,
    QATurnNotAccessibleError,
    QATurnSource,
    RegressionMiningService,
    RegressionPrincipal,
    SensitiveFeedbackRejectedError,
)


def principal(user_id: str, tenant_id: str) -> RegressionPrincipal:
    return RegressionPrincipal(user_id=user_id, tenant_id=tenant_id, roles=("user",))


def qa_source(
    *,
    qa_turn_id: str = "qat-1",
    user_id: str = "user-1",
    tenant_id: str = "tenant-1",
    question: str = "起付线怎么计算",
    answer: str = "按年度累计计算",
    selected_skill_id: str | None = "deductible",
) -> QATurnSource:
    return QATurnSource(
        qa_turn_id=qa_turn_id,
        user_id=user_id,
        tenant_id=tenant_id,
        question=question,
        answer=answer,
        selected_skill_id=selected_skill_id,
    )


class _FakeReader:
    def __init__(self, source: QATurnSource | None) -> None:
        self._source = source

    def get_qa_turn(self, qa_turn_id: str) -> QATurnSource | None:
        if self._source is None:
            return None
        return self._source if self._source.qa_turn_id == qa_turn_id else None


def build_service(
    *,
    source: QATurnSource | None,
    storage: InMemorySkillRegressionStorage | None = None,
) -> RegressionMiningService:
    return RegressionMiningService(
        storage=storage or InMemorySkillRegressionStorage(),
        qa_source_reader=_FakeReader(source),
    )


def test_feedback_reads_source_by_id_and_ignores_no_client_content() -> None:
    service = build_service(
        source=qa_source(question="起付线怎么计算", selected_skill_id="deductible")
    )
    item = service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment="计算口径不对",
        idempotency_key="feedback-1",
    )
    assert item.source_selected_skill_id == "deductible"
    assert item.error_dimension == SkillErrorDimension.CALCULATION
    assert item.source_qa_turn_id == "qat-1"
    # 服务端未保存原始问题正文以外的客户端伪造正文
    assert item.question_excerpt == "起付线怎么计算"


def test_feedback_rejects_cross_tenant_without_disclosing_existence() -> None:
    service = build_service(source=qa_source(tenant_id="tenant-2"))
    with pytest.raises(QATurnNotAccessibleError):
        service.collect_feedback(
            principal=principal("user-1", "tenant-1"),
            qa_turn_id="qat-1",
            reason_code=SkillFeedbackReasonCode.WRONG_POLICY_CONTENT,
            comment=None,
            idempotency_key="feedback-2",
        )


def test_feedback_rejects_other_user_same_tenant() -> None:
    service = build_service(source=qa_source(user_id="user-1"))
    with pytest.raises(QATurnNotAccessibleError):
        service.collect_feedback(
            principal=principal("user-2", "tenant-1"),
            qa_turn_id="qat-1",
            reason_code=SkillFeedbackReasonCode.WRONG_CITATION,
            comment=None,
            idempotency_key="feedback-3",
        )


def test_feedback_deduplicates_by_tenant_and_qa_turn() -> None:
    storage = InMemorySkillRegressionStorage()
    service = build_service(source=qa_source(), storage=storage)
    first = service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
        idempotency_key="fb-a",
    )
    second = service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
        idempotency_key="fb-b",
    )
    assert second.pool_id == first.pool_id
    assert storage.count_pool_items() == 1


def test_feedback_sanitizes_pii_before_persisting() -> None:
    storage = InMemorySkillRegressionStorage()
    service = build_service(
        source=qa_source(question="身份证 110101199003071234 起付线", answer="手机 13800138000"),
        storage=storage,
    )
    item = service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
        idempotency_key="fb-pii",
    )
    assert "110101199003071234" not in item.question_excerpt
    assert "13800138000" not in item.answer_excerpt
    assert "[身份证号]" in item.question_excerpt
    assert "[手机号]" in item.answer_excerpt


def test_feedback_blocks_residual_sensitive(monkeypatch) -> None:
    # 二次扫描仍命中时阻断入池
    from src.runtime.skill_management import regression_mining_service as svc_mod

    monkeypatch.setattr(
        svc_mod,
        "detect_residual_sensitive",
        lambda text: ["residual"] if "RESIDUAL_SECRET" in text else [],
    )
    service = build_service(
        source=qa_source(question="RESIDUAL_SECRET 起付线", answer=""),
    )
    with pytest.raises(SensitiveFeedbackRejectedError):
        service.collect_feedback(
            principal=principal("user-1", "tenant-1"),
            qa_turn_id="qat-1",
            reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
            comment=None,
            idempotency_key="fb-residual",
        )


def test_collect_from_history_returns_per_item_results() -> None:
    storage = InMemorySkillRegressionStorage()

    class MultiReader:
        def __init__(self, sources):
            self._sources = {s.qa_turn_id: s for s in sources}

        def get_qa_turn(self, qa_turn_id):
            return self._sources.get(qa_turn_id)

    reader = MultiReader(
        [
            qa_source(qa_turn_id="qat-1"),
            qa_source(qa_turn_id="qat-2", user_id="user-1", question="统筹自付"),
            qa_source(qa_turn_id="qat-3", tenant_id="tenant-2"),
        ]
    )
    service = RegressionMiningService(storage=storage, qa_source_reader=reader)
    results = service.collect_from_history(
        principal=principal("user-1", "tenant-1"),
        qa_turn_ids=["qat-1", "qat-2", "qat-3", "qat-missing"],
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
    )
    by_status = {r.qa_turn_id: r.status for r in results}
    assert by_status["qat-1"] == HistoryMiningStatus.CREATED
    assert by_status["qat-2"] == HistoryMiningStatus.CREATED
    assert by_status["qat-3"] == HistoryMiningStatus.FORBIDDEN
    assert by_status["qat-missing"] == HistoryMiningStatus.FORBIDDEN
    assert storage.count_pool_items() == 2


def test_collect_from_history_merges_duplicates() -> None:
    storage = InMemorySkillRegressionStorage()
    service = build_service(source=qa_source(), storage=storage)
    service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
        idempotency_key="fb-1",
    )
    results = service.collect_from_history(
        principal=principal("user-1", "tenant-1"),
        qa_turn_ids=["qat-1"],
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
    )
    assert results[0].status == HistoryMiningStatus.DUPLICATE
    assert storage.count_pool_items() == 1


def test_collect_from_history_enforces_batch_limit() -> None:
    service = build_service(source=qa_source())
    too_many = [f"qat-{i}" for i in range(101)]
    with pytest.raises(ValueError):
        service.collect_from_history(
            principal=principal("user-1", "tenant-1"),
            qa_turn_ids=too_many,
            reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
            comment=None,
        )


def test_source_hash_is_stable_and_sha256() -> None:
    service = build_service(source=qa_source(question="起付线", answer="累计"))
    item = service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment=None,
        idempotency_key="fb-hash",
    )
    expected = hashlib.sha256(
        "起付线|累计||deductible".encode("utf-8")
    ).hexdigest()
    assert item.source_hash == expected
