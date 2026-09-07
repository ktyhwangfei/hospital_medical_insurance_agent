"""可信问题领域模型（Issue #37 可信问题库与匹配引擎）。

可信问题（TrustedQuestion）：经人工审核、绑定确定性查询计划的标准问题。
生产运行时优先匹配可信问题；匹配不确定时必须澄清，不猜测执行。

审核流状态机（唯一权威定义在本模块，存储层与服务层共用）：
    draft → pending_review → active → retired
    驳回： pending_review → draft
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TrustedQuestionStatus(StrEnum):
    """可信问题审核流状态。"""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    RETIRED = "retired"


class TrustedQuestionInvalidTransitionError(ValueError):
    """非法的可信问题状态流转，或当前状态不允许内容编辑。"""


# 状态机合法转移表
ALLOWED_TRANSITIONS: dict[TrustedQuestionStatus, frozenset[TrustedQuestionStatus]] = {
    TrustedQuestionStatus.DRAFT: frozenset({TrustedQuestionStatus.PENDING_REVIEW}),
    TrustedQuestionStatus.PENDING_REVIEW: frozenset(
        {TrustedQuestionStatus.ACTIVE, TrustedQuestionStatus.DRAFT}
    ),
    TrustedQuestionStatus.ACTIVE: frozenset({TrustedQuestionStatus.RETIRED}),
    TrustedQuestionStatus.RETIRED: frozenset(),
}

# 内容可编辑状态：仅草稿与待审核；active 需先退役，retired 只读
EDITABLE_STATUSES: frozenset[TrustedQuestionStatus] = frozenset(
    {TrustedQuestionStatus.DRAFT, TrustedQuestionStatus.PENDING_REVIEW}
)


def validate_transition(
    current: TrustedQuestionStatus, target: TrustedQuestionStatus
) -> None:
    """校验状态流转合法性，非法时抛 TrustedQuestionInvalidTransitionError。"""
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise TrustedQuestionInvalidTransitionError(
            f"非法状态流转: {current.value} → {target.value}"
        )


def ensure_editable(status: TrustedQuestionStatus) -> None:
    """校验当前状态允许内容编辑（同义表达运营不受此限，active 也可运营）。"""
    if status not in EDITABLE_STATUSES:
        raise TrustedQuestionInvalidTransitionError(
            f"当前状态 {status.value} 不允许编辑内容"
        )


class TrustedQuestionSynonym(BaseModel):
    """同义表达（Value Object）：标准问题的一种等价问法，记录运营来源。"""

    model_config = ConfigDict(frozen=True)

    expression: str = Field(min_length=1, max_length=512)
    added_by: str = Field(default="", max_length=64)
    added_at: datetime = Field(default_factory=_utc_now)


class TrustedQuestion(BaseModel):
    """可信问题（Entity）：经审核、可确定性回答的标准问题。

    携带乐观锁 ``version``，任何内容变更（含同义表达运营、状态流转）递增；
    存储层冲突时抛 ``TrustedQuestionConflictError``。
    ``query_plan`` 为语义层 ``LogicalQueryPlan`` 的不透明快照（JSONB），
    领域层不依赖 semantic_layer，由服务层负责构造与回放。
    """

    model_config = ConfigDict(frozen=True)

    question_id: str = Field(min_length=1, max_length=64)
    standard_question: str = Field(min_length=1)
    synonyms: list[TrustedQuestionSynonym] = Field(default_factory=list)
    applicable_roles: list[str] = Field(default_factory=list)
    metric_codes: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    query_plan: dict[str, Any] | None = None
    allowed_drilldowns: list[str] = Field(default_factory=list)
    expected_result_traits: dict[str, Any] = Field(default_factory=dict)
    status: TrustedQuestionStatus = TrustedQuestionStatus.DRAFT
    created_by: str = Field(default="", max_length=64)
    reviewed_by: str | None = Field(default=None, max_length=64)
    reviewed_at: datetime | None = None
    review_note: str | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
