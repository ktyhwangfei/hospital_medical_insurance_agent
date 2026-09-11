"""可信问题库领域模型测试 — issue #37（归一化 + 草稿元数据一致性校验）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.domain.question_library.models import TrustedQuestionDraft, normalize_question_text


def _plan(**overrides):
    plan = {
        "object_code": "mzjyxx",
        "scope": {"query_scope": "whole_settlement"},
        "metrics": ["fund_pay_total"],
        "group_by": [],
        "filters": [],
        "order_by": [],
        "limit": 100,
    }
    plan.update(overrides)
    return plan


class TestNormalizeQuestionText:
    def test_fullwidth_and_punctuation_folded(self):
        # 全角问号/顿号 + 尾部标点 + 空白全部折叠
        assert normalize_question_text("个人支付总额是多少？") == normalize_question_text("个人支付总额是多少")
        assert normalize_question_text("ＤＲＧ结算　规则") == normalize_question_text("drg结算规则")

    def test_lowercase_ascii(self):
        assert normalize_question_text("DRG Rules") == normalize_question_text("drgrules")

    def test_empty_and_none_safe(self):
        assert normalize_question_text("") == ""
        assert normalize_question_text("？！。 ") == ""


class TestTrustedQuestionDraftValidation:
    def test_valid_draft_passes(self):
        draft = TrustedQuestionDraft(
            standard_question="本年度医保基金支付总额是多少",
            synonyms=["今年基金支付总额"],
            roles=["information_department"],
            object_code="mzjyxx",
            metrics=["fund_pay_total"],
            dimensions=[],
            query_plan=_plan(),
        )
        assert draft.object_code == "mzjyxx"

    def test_object_code_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="object_code"):
            TrustedQuestionDraft(
                standard_question="问法",
                object_code="mzjyxx",
                metrics=["fund_pay_total"],
                query_plan=_plan(object_code="other"),
            )

    def test_metrics_metadata_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="metrics"):
            TrustedQuestionDraft(
                standard_question="问法",
                object_code="mzjyxx",
                metrics=["self_pay_total"],
                query_plan=_plan(),
            )

    def test_dimensions_must_mirror_group_by(self):
        with pytest.raises(ValidationError, match="dimensions"):
            TrustedQuestionDraft(
                standard_question="问法",
                object_code="mzjyxx",
                metrics=["fund_pay_total"],
                dimensions=["mz_trade.insurance_type"],
                query_plan=_plan(),
            )

    def test_scope_required(self):
        with pytest.raises(ValidationError, match="scope"):
            TrustedQuestionDraft(
                standard_question="问法",
                object_code="mzjyxx",
                metrics=["fund_pay_total"],
                query_plan={"object_code": "mzjyxx", "metrics": ["fund_pay_total"], "scope": {}},
            )

    def test_blank_synonym_rejected(self):
        with pytest.raises(ValidationError, match="同义表达"):
            TrustedQuestionDraft(
                standard_question="问法",
                object_code="mzjyxx",
                metrics=["fund_pay_total"],
                synonyms=["  "],
                query_plan=_plan(),
            )
