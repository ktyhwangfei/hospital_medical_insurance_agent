"""可信问题匹配引擎测试 — issue #37（命中语义 + 澄清降级 + 角色适用）。"""
from __future__ import annotations

from datetime import UTC, datetime

from src.domain.question_library.models import (
    QuestionMatchKind,
    TrustedQuestion,
    TrustedQuestionStatus,
)
from src.runtime.question_library.matcher import QuestionMatcher

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def _question(
    question_id: str,
    standard: str,
    synonyms: list[str] | None = None,
    roles: list[str] | None = None,
) -> TrustedQuestion:
    return TrustedQuestion(
        question_id=question_id,
        standard_question=standard,
        synonyms=synonyms or [],
        roles=roles or [],
        object_code="mzjyxx",
        metrics=["fund_pay_total"],
        query_plan={},
        status=TrustedQuestionStatus.PUBLISHED,
        created_at=NOW,
        updated_at=NOW,
    )


class TestExactHit:
    def test_standard_question_normalized_hit(self):
        matcher = QuestionMatcher()
        outcome = matcher.match(
            "本年度医保基金支付总额是多少？",
            [_question("q1", "本年度医保基金支付总额是多少")],
        )
        assert outcome.kind is QuestionMatchKind.HIT
        assert outcome.question is not None and outcome.question.question_id == "q1"
        assert outcome.matched_text == "本年度医保基金支付总额是多少"

    def test_synonym_hit(self):
        matcher = QuestionMatcher()
        outcome = matcher.match(
            "今年基金支付了多少",
            [_question("q1", "本年度医保基金支付总额是多少", synonyms=["今年基金支付了多少"])],
        )
        assert outcome.kind is QuestionMatchKind.HIT
        assert outcome.matched_text == "今年基金支付了多少"

    def test_high_similarity_still_not_hit(self):
        # 验收：不确定时必须澄清——高相似但非完全一致，绝不自动执行
        matcher = QuestionMatcher()
        outcome = matcher.match(
            "本年度医保基金支付总额",
            [_question("q1", "本年度医保基金支付总额是多少")],
        )
        assert outcome.kind is QuestionMatchKind.CLARIFY
        assert outcome.question is None


class TestClarifyCandidates:
    def test_similar_question_ranked_as_candidate(self):
        matcher = QuestionMatcher()
        outcome = matcher.match(
            "本年度医保基金支付总额",
            [_question("q1", "本年度医保基金支付总额是多少")],
        )
        assert outcome.kind is QuestionMatchKind.CLARIFY
        assert len(outcome.candidates) == 1
        assert outcome.candidates[0].question_id == "q1"
        assert outcome.candidates[0].score >= 0.35

    def test_unrelated_question_yields_empty_candidates(self):
        matcher = QuestionMatcher()
        outcome = matcher.match("住院床位费怎么算", [_question("q1", "本年度医保基金支付总额是多少")])
        assert outcome.kind is QuestionMatchKind.CLARIFY
        assert outcome.candidates == []

    def test_candidates_capped_and_sorted(self):
        matcher = QuestionMatcher()
        questions = [
            _question("q1", "医保基金支付总额年度汇总"),
            _question("q2", "医保基金支付总额月度趋势"),
            _question("q3", "个人支付总额年度汇总"),
            _question("q4", "医保基金支付总额科室分布"),
            _question("q5", "医保基金支付总额险种分布"),
            _question("q6", "医保基金支付总额医院分布"),
        ]
        outcome = matcher.match("医保基金支付总额", questions)
        assert outcome.kind is QuestionMatchKind.CLARIFY
        assert len(outcome.candidates) <= 5
        scores = [c.score for c in outcome.candidates]
        assert scores == sorted(scores, reverse=True)


class TestRoleApplicability:
    def test_role_declared_filters_candidates_and_hits(self):
        matcher = QuestionMatcher()
        questions = [
            _question("q1", "本年度医保基金支付总额是多少", roles=["information_department"]),
            _question("q2", "个人支付总额是多少"),
        ]
        # doctor 角色不适用 q1：即使文本完全一致也不能命中（避免越权暴露）
        outcome = matcher.match("本年度医保基金支付总额是多少", questions, roles=["doctor"])
        assert outcome.kind is QuestionMatchKind.CLARIFY
        assert all(c.question_id != "q1" for c in outcome.candidates)

    def test_no_roles_argument_means_all_applicable(self):
        matcher = QuestionMatcher()
        questions = [_question("q1", "本年度医保基金支付总额是多少", roles=["information_department"])]
        outcome = matcher.match("本年度医保基金支付总额是多少", questions)
        assert outcome.kind is QuestionMatchKind.HIT

    def test_role_intersection_hit(self):
        matcher = QuestionMatcher()
        questions = [_question("q1", "本年度医保基金支付总额是多少", roles=["information_department", "doctor"])]
        outcome = matcher.match("本年度医保基金支付总额是多少", questions, roles=["doctor"])
        assert outcome.kind is QuestionMatchKind.HIT
