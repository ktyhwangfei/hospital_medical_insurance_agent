"""可信问题冷启动挖掘单元测试（Issue #37 Slice 4）。"""

from __future__ import annotations

from src.domain.trusted_qa.models import TrustedQuestionStatus
from src.runtime.trusted_qa.cold_start import (
    build_draft_questions,
    mine_frequent_questions,
)


class TestMineFrequentQuestions:
    def test_groups_normalized_variants(self) -> None:
        questions = [
            "门诊报销比例是多少？",
            "门诊报销比例是多少",
            "门诊报销比例是多少？?",
            "住院起付线是多少",
        ]
        mined = mine_frequent_questions(questions)
        assert len(mined) == 2
        top = mined[0]
        assert top.frequency == 3
        # 代表形：组内频次并列时取更短形态（无标点写法）
        assert top.standard_question == "门诊报销比例是多少"
        assert set(top.variants) == {"门诊报销比例是多少？", "门诊报销比例是多少？?"}

    def test_frequency_order_and_limit(self) -> None:
        questions = ["高频问题"] * 5 + ["中频问题"] * 3 + ["低频问题"]
        mined = mine_frequent_questions(questions, limit=2)
        assert [m.standard_question for m in mined] == ["高频问题", "中频问题"]
        assert [m.frequency for m in mined] == [5, 3]

    def test_min_frequency_filter(self) -> None:
        questions = ["甲", "甲", "乙"]
        mined = mine_frequent_questions(questions, min_frequency=2)
        assert [m.standard_question for m in mined] == ["甲"]

    def test_empty_and_blank_ignored(self) -> None:
        assert mine_frequent_questions(["", "   ", "？？？"]) == []

    def test_deterministic_tie_break(self) -> None:
        """同频并列按 standard_question 字典序稳定排序，跨运行结果一致。"""
        questions = ["甲问题", "乙问题"]
        first = mine_frequent_questions(questions)
        second = mine_frequent_questions(list(reversed(questions)))
        assert first == second
        # 乙（U+4E59）字典序小于甲（U+7532）
        assert [m.standard_question for m in first] == ["乙问题", "甲问题"]


class TestBuildDraftQuestions:
    def test_drafts_are_draft_status(self) -> None:
        mined = mine_frequent_questions(["门诊报销比例是多少", "门诊报销比例是多少？"])
        drafts = build_draft_questions(mined)
        assert len(drafts) == 1
        draft = drafts[0]
        # 冷启动候选一律 draft，必须人工审核
        assert draft.status == TrustedQuestionStatus.DRAFT
        assert draft.created_by == "cold-start"
        assert draft.question_id.startswith("tq_seed_")
        # 归一化变体进入同义表达候选
        assert [s.expression for s in draft.synonyms] == ["门诊报销比例是多少？"]

    def test_question_id_idempotent(self) -> None:
        """同一问题重复挖掘产生同一 ID（存储层 ConflictError 幂等跳过）。"""
        first = build_draft_questions(mine_frequent_questions(["门诊报销比例是多少"]))
        second = build_draft_questions(mine_frequent_questions(["门诊报销比例是多少?"]))
        assert first[0].question_id == second[0].question_id
