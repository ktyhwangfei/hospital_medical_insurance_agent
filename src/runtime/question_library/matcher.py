"""可信问题匹配引擎 — issue #37。

借 SuperSonic Schema Mapper 的三段结构（术语识别→对齐→校正）落地为
确定性文本匹配，不引入模型调用：

1. 校正（normalize）：NFKC 折叠全角/兼容形式 + 小写 + 去标点空白；
2. 术语识别（exact tier）：归一化文本与标准问题或任一同义表达完全一致
   → 命中。这是唯一自动执行通道——「文本一致 + 计划人工审核」双约束
   保证命中结果 100% 正确；
3. 对齐（fuzzy tier）：字符 bigram Jaccard 相似度排序，产出候选问题列表
   供澄清选择，**任何模糊分数都不自动执行**（验收：不确定时必须澄清）。
"""
from __future__ import annotations

from src.domain.question_library.models import (
    QuestionMatchCandidate,
    QuestionMatchKind,
    QuestionMatchOutcome,
    TrustedQuestion,
    normalize_question_text,
)

# 候选下限：低于该分数的模糊对齐结果不进入候选列表（避免噪声）
MIN_CANDIDATE_SCORE = 0.35
# 候选上限：澄清列表最多展示的候选数
MAX_CANDIDATES = 5


def _bigrams(normalized: str) -> set[str]:
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i:i + 2] for i in range(len(normalized) - 1)}


def _similarity(left_normalized: str, right_normalized: str) -> float:
    left, right = _bigrams(left_normalized), _bigrams(right_normalized)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class QuestionMatcher:
    """确定性匹配器：命中=归一化完全一致；其余一律澄清。"""

    def match(
        self,
        asked_text: str,
        questions: list[TrustedQuestion],
        *,
        roles: list[str] | None = None,
    ) -> QuestionMatchOutcome:
        asked_normalized = normalize_question_text(asked_text)
        applicable = [q for q in questions if q.applies_to_roles(roles)]

        # 术语识别：标准问题或同义表达归一化后完全一致才命中
        for question in applicable:
            matched_text = question.standard_question
            if asked_normalized == normalize_question_text(matched_text):
                return QuestionMatchOutcome(
                    kind=QuestionMatchKind.HIT,
                    asked_text=asked_text,
                    question=question,
                    matched_text=matched_text,
                )
            for synonym in question.synonyms:
                if asked_normalized == normalize_question_text(synonym):
                    return QuestionMatchOutcome(
                        kind=QuestionMatchKind.HIT,
                        asked_text=asked_text,
                        question=question,
                        matched_text=synonym,
                    )

        # 对齐：模糊相似度只产出候选，不猜测执行
        scored: list[QuestionMatchCandidate] = []
        for question in applicable:
            best_score, best_text = 0.0, question.standard_question
            for text in [question.standard_question, *question.synonyms]:
                score = _similarity(asked_normalized, normalize_question_text(text))
                if score > best_score:
                    best_score, best_text = score, text
            if best_score >= MIN_CANDIDATE_SCORE:
                scored.append(
                    QuestionMatchCandidate(
                        question_id=question.question_id,
                        standard_question=question.standard_question,
                        score=round(best_score, 4),
                        matched_text=best_text,
                    )
                )
        scored.sort(key=lambda item: item.score, reverse=True)
        return QuestionMatchOutcome(
            kind=QuestionMatchKind.CLARIFY,
            asked_text=asked_text,
            candidates=scored[:MAX_CANDIDATES],
        )
