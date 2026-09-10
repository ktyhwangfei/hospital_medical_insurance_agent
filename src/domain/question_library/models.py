"""可信问题库领域模型 — issue #37（设计 §14.1：标准问题/同义表达/适用角色/
指标/维度/时间口径/筛选/查询计划/允许下钻/预期结果特征/审核人/版本）。

匹配语义（验收）：
- 归一化文本与标准问题或任一同义表达完全一致 → 命中（hit），执行绑定的
  已审核查询计划——结果 100% 正确依赖「文本一致 + 计划人工审核」双约束；
- 其余（含高相似模糊匹配）一律降级为候选问题列表（clarify），不猜测执行。
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrustedQuestionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class QuestionMatchKind(StrEnum):
    HIT = "hit"
    CLARIFY = "clarify"


class QuestionMatchEventOutcome(StrEnum):
    HIT = "hit"
    CLARIFY = "clarify"
    SELECTED = "selected"


def new_question_id() -> str:
    return f"tq_{uuid.uuid4().hex[:12]}"


def new_match_event_id() -> str:
    return f"qme_{uuid.uuid4().hex[:12]}"


_PUNCT_RE = re.compile(r"[\W_]+", flags=re.UNICODE)


def normalize_question_text(text: str) -> str:
    """匹配归一化：NFKC（全角→半角、兼容形式折叠）+ 小写 + 去标点空白。

    中文属 \\w 不受影响；「个人支付总额是多少？」与「个人支付总额是多少」
    归一化后相等。
    """
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    return _PUNCT_RE.sub("", normalized)


class TrustedQuestionDraft(BaseModel):
    """创建草稿的输入；query_plan 是 SemanticQuery 形状的绑定查询计划。"""

    standard_question: str = Field(min_length=1, max_length=500)
    synonyms: list[str] = Field(default_factory=list, max_length=50)
    roles: list[str] = Field(default_factory=list, max_length=20)
    object_code: str = Field(min_length=1, max_length=128)
    metrics: list[str] = Field(min_length=1, max_length=20)
    dimensions: list[str] = Field(default_factory=list, max_length=20)
    time_scope: str | None = Field(default=None, max_length=200)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    query_plan: dict[str, Any]
    allow_drilldown: bool = False
    expected_result: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _plan_metadata_consistent(self) -> "TrustedQuestionDraft":
        # 指标/维度元数据必须与绑定计划一致，防止目录展示与实际执行漂移
        plan_object = str(self.query_plan.get("object_code") or "")
        if plan_object != self.object_code:
            raise ValueError(f"query_plan.object_code({plan_object}) 与 object_code({self.object_code}) 不一致")
        plan_metrics = [str(m) for m in (self.query_plan.get("metrics") or [])]
        if sorted(plan_metrics) != sorted(self.metrics):
            raise ValueError("query_plan.metrics 与 metrics 元数据不一致")
        plan_group_by = [str(g) for g in (self.query_plan.get("group_by") or [])]
        if sorted(plan_group_by) != sorted(self.dimensions):
            raise ValueError("query_plan.group_by 与 dimensions 元数据不一致")
        scope = self.query_plan.get("scope")
        if not isinstance(scope, dict) or not scope:
            raise ValueError("query_plan.scope 缺失（SemanticQuery 需携带查询口径）")
        for synonym in self.synonyms:
            if not synonym.strip():
                raise ValueError("同义表达不能为空白")
        return self


class TrustedQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    standard_question: str
    synonyms: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    object_code: str
    metrics: list[str]
    dimensions: list[str] = Field(default_factory=list)
    time_scope: str | None = None
    filters: list[dict[str, Any]] = Field(default_factory=list)
    query_plan: dict[str, Any]
    allow_drilldown: bool = False
    expected_result: dict[str, Any] = Field(default_factory=dict)
    reviewer: str | None = None
    version: int = Field(default=1, ge=1)
    status: TrustedQuestionStatus = TrustedQuestionStatus.DRAFT
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime

    def applies_to_roles(self, roles: list[str] | None) -> bool:
        """适用角色：未声明角色=全角色适用；声明则取交集。"""
        if not self.roles or roles is None:
            return True
        return bool(set(self.roles) & set(roles))


class TrustedQuestionPage(BaseModel):
    items: list[TrustedQuestion]
    total: int
    page: int
    page_size: int


class QuestionMatchCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    standard_question: str
    score: float = Field(ge=0.0, le=1.0)
    matched_text: str


class QuestionMatchOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: QuestionMatchKind
    asked_text: str
    question: TrustedQuestion | None = None
    matched_text: str | None = None
    candidates: list[QuestionMatchCandidate] = Field(default_factory=list)


class QuestionMatchEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    asked_text: str
    outcome: QuestionMatchEventOutcome
    matched_question_id: str | None = None
    created_at: datetime


class QuestionMatchEventPage(BaseModel):
    items: list[QuestionMatchEvent]
    total: int
    page: int
    page_size: int


class ColdStartCandidate(BaseModel):
    """冷启动候选：政策问答历史高频问题（issue #37：一期 50~100 条）。"""

    model_config = ConfigDict(frozen=True)

    question_text: str
    frequency: int = Field(ge=1)


class QuestionLibraryStats(BaseModel):
    question_counts: dict[str, int]
    match_event_counts: dict[str, int]


class TrustedQuestionNotFoundError(Exception):
    def __init__(self, question_id: str) -> None:
        self.question_id = question_id
        super().__init__(f"可信问题不存在: {question_id}")


class InvalidQuestionTransitionError(Exception):
    def __init__(self, question_id: str, action: str, current_status: TrustedQuestionStatus) -> None:
        self.question_id = question_id
        self.action = action
        self.current_status = current_status
        super().__init__(f"问题 {question_id} 当前状态 {current_status.value} 不允许执行 {action}")


class QuestionRevisionConflictError(Exception):
    def __init__(self, question_id: str, expected_revision: int, actual_revision: int) -> None:
        self.question_id = question_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"问题 {question_id} 修订冲突：期望 revision={expected_revision}，实际 revision={actual_revision}"
        )


class QuestionSynonymConflictError(Exception):
    def __init__(self, synonym: str, existing_question_id: str) -> None:
        self.synonym = synonym
        self.existing_question_id = existing_question_id
        super().__init__(f"表达已绑定到问题 {existing_question_id}: {synonym}")


class QuestionRoleForbiddenError(Exception):
    def __init__(self, question_id: str, roles: list[str]) -> None:
        self.question_id = question_id
        self.roles = roles
        super().__init__(f"问题 {question_id} 不适用于角色 {roles}")
