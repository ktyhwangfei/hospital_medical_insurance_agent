"""可信问题匹配引擎的 DTO（Issue #37）。

匹配结果三态：
- matched：唯一高置信命中，可携带查询计划进入执行
- candidates：存在不确定候选，必须交用户澄清，禁止猜测执行
- no_match：无可信候选，交回长尾受控语义生成
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.domain.trusted_qa.models import TrustedQuestion


class TrustedQuestionMatchOutcome(StrEnum):
    """匹配结果三态。"""

    MATCHED = "matched"
    CANDIDATES = "candidates"
    NO_MATCH = "no_match"


class TrustedQuestionCandidate(BaseModel):
    """候选问题条目：可追溯的打分证据（命中的表达与得分）。"""

    model_config = ConfigDict(frozen=True)

    question_id: str
    standard_question: str
    score: float = Field(ge=0.0, le=1.0)
    matched_expression: str


class TrustedQuestionMatchResult(BaseModel):
    """匹配结果（DTO）。

    matched 时 ``question`` 携带完整可信问题（含查询计划快照）；
    candidates 时 ``candidates`` 非空供澄清选择；
    no_match 时两者均为空。
    """

    model_config = ConfigDict(frozen=True)

    outcome: TrustedQuestionMatchOutcome
    question: TrustedQuestion | None = None
    candidates: list[TrustedQuestionCandidate] = Field(default_factory=list)
