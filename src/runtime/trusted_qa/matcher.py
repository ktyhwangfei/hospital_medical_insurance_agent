"""可信问题匹配引擎（Issue #37，纯确定性 v1）。

结构借鉴 SuperSonic Schema Mapper 三段式，但实现完全确定性、可追溯，
不引入 LLM / embedding：

1. 术语识别：归一化（NFKC 全半角、标点剥离、空白折叠、小写化），
   以库内 active 可信问题的标准问题 + 同义表达为词典。
2. 对齐：归一化精确相等记 1.0；否则取字符级相似度（SequenceMatcher）
   与字符 bigram Jaccard 的较大值作为候选得分。
3. 校正：阈值判定——
   - top ≥ HIT 且与次高分拉开 margin → matched
   - top ≥ HIT 但次高逼近（歧义）→ candidates（不猜测执行）
   - CLARIFY ≤ top < HIT → candidates（澄清）
   - top < CLARIFY → no_match（交回长尾）
同一问题多条表达取最高分，并记录命中表达以保证可追溯。
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from src.domain.trusted_qa.models import TrustedQuestion
from src.runtime.trusted_qa.models import (
    TrustedQuestionCandidate,
    TrustedQuestionMatchOutcome,
    TrustedQuestionMatchResult,
)

# 默认阈值：命中需高置信且拉开差距；中间带必须澄清；低于澄清带视为无匹配
DEFAULT_HIT_THRESHOLD = 0.92
DEFAULT_CLARIFY_THRESHOLD = 0.60
DEFAULT_MIN_MARGIN = 0.05
DEFAULT_MAX_CANDIDATES = 5

# 归一化时剥离的字符：空白与常见中英文标点（CJK 与字母数字保留）
_STRIP_CHARS = (
    " \t\r\n"
    "，。！？、；：""''（）【】《》〈〉「」『』—…·~"
    ",.!?;:()[]{}<>-"
)
_STRIP_PATTERN = re.compile("[" + re.escape(_STRIP_CHARS) + "]+")


def normalize_question(text: str) -> str:
    """问题归一化：NFKC 全半角统一 → 小写 → 剥离标点与空白。"""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return _STRIP_PATTERN.sub("", normalized)


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _similarity(a: str, b: str) -> float:
    """归一化文本的确定性相似度：字符级 ratio 与 bigram Jaccard 取大。"""
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    bigrams_a, bigrams_b = _bigrams(a), _bigrams(b)
    union = bigrams_a | bigrams_b
    jaccard = len(bigrams_a & bigrams_b) / len(union) if union else 0.0
    return max(ratio, jaccard)


class TrustedQuestionMatcher:
    """可信问题匹配器（无状态，线程安全）。

    候选过滤（仅 active、按角色过滤等）由调用方完成，
    本类只对传入候选集合做纯函数式匹配，保证可测试与确定性。
    """

    def __init__(
        self,
        *,
        hit_threshold: float = DEFAULT_HIT_THRESHOLD,
        clarify_threshold: float = DEFAULT_CLARIFY_THRESHOLD,
        min_margin: float = DEFAULT_MIN_MARGIN,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> None:
        if not 0.0 <= clarify_threshold < hit_threshold <= 1.0:
            raise ValueError("阈值必须满足 0 <= clarify < hit <= 1")
        self._hit = hit_threshold
        self._clarify = clarify_threshold
        self._margin = min_margin
        self._max_candidates = max_candidates

    def match(
        self, question: str, candidates: list[TrustedQuestion]
    ) -> TrustedQuestionMatchResult:
        """对传入候选集合执行三段式匹配，返回三态结果。"""
        normalized_input = normalize_question(question)
        if not normalized_input or not candidates:
            return TrustedQuestionMatchResult(outcome=TrustedQuestionMatchOutcome.NO_MATCH)

        # 对齐：每个可信问题取其标准问题与全部同义表达的最高分
        scored: list[TrustedQuestionCandidate] = []
        exact: list[TrustedQuestionCandidate] = []
        for candidate in candidates:
            best_score = 0.0
            best_expression = candidate.standard_question
            for expression in self._expressions_of(candidate):
                normalized_expr = normalize_question(expression)
                if not normalized_expr:
                    continue
                score = (
                    1.0
                    if normalized_expr == normalized_input
                    else _similarity(normalized_input, normalized_expr)
                )
                if score > best_score:
                    best_score = score
                    best_expression = expression
            entry = TrustedQuestionCandidate(
                question_id=candidate.question_id,
                standard_question=candidate.standard_question,
                score=round(best_score, 6),
                matched_expression=best_expression,
            )
            if best_score >= 1.0:
                exact.append(entry)
            elif best_score >= self._clarify:
                scored.append(entry)

        # 校正①：精确命中——唯一则直接 matched；多个等价命中属歧义，降级澄清
        if len(exact) == 1:
            question_map = {q.question_id: q for q in candidates}
            return TrustedQuestionMatchResult(
                outcome=TrustedQuestionMatchOutcome.MATCHED,
                question=question_map[exact[0].question_id],
                candidates=exact,
            )
        if len(exact) > 1:
            return TrustedQuestionMatchResult(
                outcome=TrustedQuestionMatchOutcome.CANDIDATES,
                candidates=self._rank(exact),
            )

        if not scored:
            return TrustedQuestionMatchResult(outcome=TrustedQuestionMatchOutcome.NO_MATCH)

        ranked = self._rank(scored)
        top = ranked[0]
        second_score = ranked[1].score if len(ranked) > 1 else 0.0

        # 校正②：高置信且与次高拉开差距 → matched
        if top.score >= self._hit and top.score - second_score >= self._margin:
            question_map = {q.question_id: q for q in candidates}
            return TrustedQuestionMatchResult(
                outcome=TrustedQuestionMatchOutcome.MATCHED,
                question=question_map[top.question_id],
                candidates=[top],
            )

        # 校正③：其余一律澄清，不猜测执行
        return TrustedQuestionMatchResult(
            outcome=TrustedQuestionMatchOutcome.CANDIDATES,
            candidates=ranked,
        )

    @staticmethod
    def _expressions_of(question: TrustedQuestion) -> list[str]:
        return [question.standard_question] + [s.expression for s in question.synonyms]

    def _rank(
        self, candidates: list[TrustedQuestionCandidate]
    ) -> list[TrustedQuestionCandidate]:
        # 得分倒序，question_id 升序兜底，保证确定性
        ranked = sorted(
            candidates, key=lambda c: (-c.score, c.question_id)
        )
        return ranked[: self._max_candidates]
