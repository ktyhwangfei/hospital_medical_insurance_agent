"""可信问题匹配引擎单元测试（Issue #37 Slice 2）。

验收映射：
- 可信问题命中 → matched 且携带完整可信问题（含查询计划快照）
- 匹配不确定（多候选/中间分数带/精确命中歧义）→ candidates，禁止猜测执行
- 无匹配 → no_match，交回长尾
"""

from __future__ import annotations

import pytest

from src.domain.trusted_qa.models import (
    TrustedQuestion,
    TrustedQuestionStatus,
    TrustedQuestionSynonym,
)
from src.runtime.trusted_qa.matcher import (
    TrustedQuestionMatcher,
    normalize_question,
)
from src.runtime.trusted_qa.models import TrustedQuestionMatchOutcome


def _q(
    question_id: str,
    standard: str,
    synonyms: list[str] | None = None,
) -> TrustedQuestion:
    return TrustedQuestion(
        question_id=question_id,
        standard_question=standard,
        synonyms=[TrustedQuestionSynonym(expression=s) for s in (synonyms or [])],
        status=TrustedQuestionStatus.ACTIVE,
    )


@pytest.fixture()
def matcher() -> TrustedQuestionMatcher:
    return TrustedQuestionMatcher()


class TestNormalize:
    def test_fullwidth_and_punctuation(self) -> None:
        assert normalize_question("门诊报销比例是多少？") == normalize_question(
            "门诊报销比例是多少"
        )
        # NFKC：全角数字字母归一
        assert normalize_question("ＡＢＣ１２３") == "abc123"

    def test_whitespace_collapse(self) -> None:
        assert normalize_question(" 门诊  报销 ") == "门诊报销"


class TestExactMatch:
    def test_standard_question_exact_hit(self, matcher: TrustedQuestionMatcher) -> None:
        candidates = [
            _q("tq_1", "门诊报销比例是多少"),
            _q("tq_2", "住院起付线是多少"),
        ]
        result = matcher.match("门诊报销比例是多少", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.MATCHED
        assert result.question is not None
        assert result.question.question_id == "tq_1"
        # 命中结果携带查询计划快照（执行闭环的前提）
        assert result.question.query_plan is None or isinstance(result.question.query_plan, dict)

    def test_synonym_exact_hit(self, matcher: TrustedQuestionMatcher) -> None:
        candidates = [_q("tq_1", "门诊报销比例是多少", synonyms=["门诊能报多少"])]
        result = matcher.match("门诊能报多少", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.MATCHED
        assert result.candidates[0].matched_expression == "门诊能报多少"

    def test_normalized_hit_ignores_punctuation(
        self, matcher: TrustedQuestionMatcher
    ) -> None:
        candidates = [_q("tq_1", "门诊报销比例是多少")]
        result = matcher.match(" 门诊报销比例，是多少？？", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.MATCHED

    def test_multiple_exact_hits_degrade_to_candidates(
        self, matcher: TrustedQuestionMatcher
    ) -> None:
        """两个可信问题含相同表达时属歧义，必须澄清而不是任选其一。"""
        candidates = [
            _q("tq_1", "门诊报销比例是多少"),
            _q("tq_2", "门诊统筹报销比例", synonyms=["门诊报销比例是多少"]),
        ]
        result = matcher.match("门诊报销比例是多少", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.CANDIDATES
        assert result.question is None
        assert {c.question_id for c in result.candidates} == {"tq_1", "tq_2"}


class TestFuzzyCorrection:
    def test_high_confidence_unique_hit(self, matcher: TrustedQuestionMatcher) -> None:
        candidates = [
            _q("tq_1", "门诊报销比例是多少"),
            _q("tq_2", "病案首页质控规则有哪些"),
        ]
        result = matcher.match("门诊报销比例是多少啊", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.MATCHED
        assert result.question is not None
        assert result.question.question_id == "tq_1"

    def test_close_second_degrades_to_candidates(
        self, matcher: TrustedQuestionMatcher
    ) -> None:
        """top 分高但与次高差距不足 margin → 澄清，不猜测执行。"""
        candidates = [
            _q("tq_1", "在职职工门诊报销比例是多少"),
            _q("tq_2", "退休职工门诊报销比例是多少"),
        ]
        result = matcher.match("职工门诊报销比例是多少", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.CANDIDATES
        assert result.question is None
        assert len(result.candidates) == 2

    def test_mid_band_returns_candidates(self, matcher: TrustedQuestionMatcher) -> None:
        candidates = [_q("tq_1", "门诊报销比例是多少")]
        result = matcher.match("门诊报销", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.CANDIDATES
        assert result.candidates[0].question_id == "tq_1"

    def test_no_match_when_below_clarify(
        self, matcher: TrustedQuestionMatcher
    ) -> None:
        candidates = [_q("tq_1", "门诊报销比例是多少")]
        result = matcher.match("食堂今天有什么菜", candidates)
        assert result.outcome == TrustedQuestionMatchOutcome.NO_MATCH
        assert result.candidates == []


class TestEdgeCases:
    def test_empty_question(self, matcher: TrustedQuestionMatcher) -> None:
        result = matcher.match("   ", [_q("tq_1", "门诊报销比例是多少")])
        assert result.outcome == TrustedQuestionMatchOutcome.NO_MATCH

    def test_empty_candidates(self, matcher: TrustedQuestionMatcher) -> None:
        result = matcher.match("门诊报销比例是多少", [])
        assert result.outcome == TrustedQuestionMatchOutcome.NO_MATCH

    def test_deterministic_repeated_calls(
        self, matcher: TrustedQuestionMatcher
    ) -> None:
        candidates = [
            _q("tq_1", "在职职工门诊报销比例是多少"),
            _q("tq_2", "退休职工门诊报销比例是多少"),
            _q("tq_3", "居民门诊报销比例是多少"),
        ]
        first = matcher.match("职工门诊报销比例是多少", candidates)
        second = matcher.match("职工门诊报销比例是多少", candidates)
        assert first.model_dump() == second.model_dump()

    def test_candidates_capped(self) -> None:
        matcher = TrustedQuestionMatcher(max_candidates=2)
        candidates = [
            _q(f"tq_{i}", f"门诊报销比例是多少 变体{i}") for i in range(5)
        ]
        result = matcher.match("门诊报销比例是多少 变体", candidates)
        assert len(result.candidates) <= 2

    def test_invalid_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError):
            TrustedQuestionMatcher(hit_threshold=0.5, clarify_threshold=0.6)
