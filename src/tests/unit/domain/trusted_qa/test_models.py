"""可信问题领域模型单元测试（Issue #37 Slice 1）。

覆盖：状态机合法/非法流转、可编辑状态判定、模型不可变性与默认值。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.domain.trusted_qa.models import (
    ALLOWED_TRANSITIONS,
    EDITABLE_STATUSES,
    TrustedQuestion,
    TrustedQuestionInvalidTransitionError,
    TrustedQuestionStatus,
    TrustedQuestionSynonym,
    ensure_editable,
    validate_transition,
)


class TestTrustedQuestionModel:
    def test_default_status_is_draft(self) -> None:
        q = TrustedQuestion(question_id="tq_1", standard_question="门诊报销比例是多少")
        assert q.status == TrustedQuestionStatus.DRAFT
        assert q.version == 1
        assert q.synonyms == []
        assert q.query_plan is None
        assert q.expected_result_traits == {}

    def test_question_id_required(self) -> None:
        with pytest.raises(ValidationError):
            TrustedQuestion(question_id="", standard_question="x")

    def test_standard_question_required(self) -> None:
        with pytest.raises(ValidationError):
            TrustedQuestion(question_id="tq_1", standard_question="")

    def test_model_is_frozen(self) -> None:
        q = TrustedQuestion(question_id="tq_1", standard_question="x")
        with pytest.raises(ValidationError):
            setattr(q, "status", TrustedQuestionStatus.ACTIVE)

    def test_synonym_requires_expression(self) -> None:
        with pytest.raises(ValidationError):
            TrustedQuestionSynonym(expression="")


class TestStatusMachine:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TrustedQuestionStatus.DRAFT, TrustedQuestionStatus.PENDING_REVIEW),
            (TrustedQuestionStatus.PENDING_REVIEW, TrustedQuestionStatus.ACTIVE),
            (TrustedQuestionStatus.PENDING_REVIEW, TrustedQuestionStatus.DRAFT),
            (TrustedQuestionStatus.ACTIVE, TrustedQuestionStatus.RETIRED),
        ],
    )
    def test_valid_transitions(
        self, current: TrustedQuestionStatus, target: TrustedQuestionStatus
    ) -> None:
        validate_transition(current, target)  # 不抛异常即合法

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TrustedQuestionStatus.DRAFT, TrustedQuestionStatus.ACTIVE),
            (TrustedQuestionStatus.DRAFT, TrustedQuestionStatus.RETIRED),
            (TrustedQuestionStatus.ACTIVE, TrustedQuestionStatus.PENDING_REVIEW),
            (TrustedQuestionStatus.ACTIVE, TrustedQuestionStatus.DRAFT),
            (TrustedQuestionStatus.RETIRED, TrustedQuestionStatus.DRAFT),
            (TrustedQuestionStatus.RETIRED, TrustedQuestionStatus.ACTIVE),
        ],
    )
    def test_invalid_transitions_raise(
        self, current: TrustedQuestionStatus, target: TrustedQuestionStatus
    ) -> None:
        with pytest.raises(TrustedQuestionInvalidTransitionError):
            validate_transition(current, target)

    def test_transition_table_covers_all_statuses(self) -> None:
        assert set(ALLOWED_TRANSITIONS) == set(TrustedQuestionStatus)

    def test_editable_statuses(self) -> None:
        assert EDITABLE_STATUSES == {
            TrustedQuestionStatus.DRAFT,
            TrustedQuestionStatus.PENDING_REVIEW,
        }
        ensure_editable(TrustedQuestionStatus.DRAFT)
        ensure_editable(TrustedQuestionStatus.PENDING_REVIEW)
        with pytest.raises(TrustedQuestionInvalidTransitionError):
            ensure_editable(TrustedQuestionStatus.ACTIVE)
        with pytest.raises(TrustedQuestionInvalidTransitionError):
            ensure_editable(TrustedQuestionStatus.RETIRED)
