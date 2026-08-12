"""Skill 错误挖掘案例池与分型回归领域模型。

设计依据：docs/superpowers/plans/2026-08-10-skill-eval-mining.md Task 3。

统一案例池（SkillEvalCasePoolItem）覆盖全部 Skill 错误维度；routing 投影到
现有 SkillEvalCase，其余五个可执行维度（calculation/policy_content/citation/
answer_quality/safety）写入 SkillRegressionCase，使用严格判别联合，禁止保存
自然语言裸 expected；other 仅表示尚未完成分型，不生成可执行资产。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── 错误维度与反馈原因码 ─────────────────────────────────────────


class SkillErrorDimension(StrEnum):
    """Skill 错误的全部维度。"""

    ROUTING = "routing"
    CALCULATION = "calculation"
    POLICY_CONTENT = "policy_content"
    CITATION = "citation"
    ANSWER_QUALITY = "answer_quality"
    SAFETY = "safety"
    OTHER = "other"


class SkillFeedbackReasonCode(StrEnum):
    """用户「回答有误」反馈原因码，映射到初始错误维度。"""

    WRONG_ROUTING = "wrong_routing"
    WRONG_CALCULATION = "wrong_calculation"
    WRONG_POLICY_CONTENT = "wrong_policy_content"
    WRONG_CITATION = "wrong_citation"
    POOR_ANSWER_QUALITY = "poor_answer_quality"
    SAFETY_CONCERN = "safety_concern"
    OTHER = "other"


_REASON_TO_DIMENSION: dict[SkillFeedbackReasonCode, SkillErrorDimension] = {
    SkillFeedbackReasonCode.WRONG_ROUTING: SkillErrorDimension.ROUTING,
    SkillFeedbackReasonCode.WRONG_CALCULATION: SkillErrorDimension.CALCULATION,
    SkillFeedbackReasonCode.WRONG_POLICY_CONTENT: SkillErrorDimension.POLICY_CONTENT,
    SkillFeedbackReasonCode.WRONG_CITATION: SkillErrorDimension.CITATION,
    SkillFeedbackReasonCode.POOR_ANSWER_QUALITY: SkillErrorDimension.ANSWER_QUALITY,
    SkillFeedbackReasonCode.SAFETY_CONCERN: SkillErrorDimension.SAFETY,
    SkillFeedbackReasonCode.OTHER: SkillErrorDimension.OTHER,
}


def reason_code_to_dimension(
    reason_code: SkillFeedbackReasonCode,
) -> SkillErrorDimension:
    """反馈原因码映射到初始错误维度（other 表示尚未完成分型）。"""
    return _REASON_TO_DIMENSION[reason_code]


# ── 严格断言（判别联合，仅五类可执行维度）─────────────────────────


class CalculationAssertions(BaseModel):
    """计算类回归断言：确定数值 + 容差 + 进位规则。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["calculation"] = "calculation"
    expected_value: float
    tolerance: float = Field(default=0.0, ge=0.0)
    rounding: int | None = Field(default=None, ge=0, le=10)
    must_include_steps: list[str] = Field(default_factory=list)


class PolicyContentAssertions(BaseModel):
    """政策内容类回归断言：适用性 + 必含/禁止文本 + 政策版本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["policy_content"] = "policy_content"
    applicability: Literal["applies", "does_not_apply"]
    must_include: list[str] = Field(min_length=1)
    forbidden: list[str] = Field(default_factory=list)
    policy_version: str | None = None


class CitationAssertions(BaseModel):
    """引用类回归断言：必须命中的来源 ID + 是否强制支撑。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["citation"] = "citation"
    required_source_ids: list[str] = Field(min_length=1)
    support_required: Literal["required", "optional"] = "required"


class AnswerQualityAssertions(BaseModel):
    """答案质量类回归断言：可答性 + 必含/禁止 + rubric。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["answer_quality"] = "answer_quality"
    answerable: bool
    must_include: list[str] = Field(min_length=1)
    must_not_include: list[str] = Field(default_factory=list)
    rubric_id: str | None = None


class SafetyAssertions(BaseModel):
    """安全类回归断言：敏感字段 + 高风险动作拦截 + 期望态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["safety"] = "safety"
    sensitive_fields: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    expected_state: Literal[
        "waiting_human_confirmation", "blocked", "sanitized"
    ] = "waiting_human_confirmation"


RegressionAssertions = Annotated[
    CalculationAssertions
    | PolicyContentAssertions
    | CitationAssertions
    | AnswerQualityAssertions
    | SafetyAssertions,
    Field(discriminator="case_type"),
]

#: 五类可执行维度（routing 投影到现有 SkillEvalCase，other 不可执行）
EXECUTABLE_DIMENSIONS: frozenset[SkillErrorDimension] = frozenset(
    {
        SkillErrorDimension.CALCULATION,
        SkillErrorDimension.POLICY_CONTENT,
        SkillErrorDimension.CITATION,
        SkillErrorDimension.ANSWER_QUALITY,
        SkillErrorDimension.SAFETY,
    }
)


# ── AI 转换 proposal（人工确认前的候选）──────────────────────────


class RoutingCaseProposal(BaseModel):
    """路由类 proposal：投影到现有 SkillEvalCase。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["routing"] = "routing"
    question_template: str = Field(min_length=1, max_length=2000)
    expected_skill_id: str | None = None
    required: bool = True
    risk_tags: list[str] = Field(default_factory=list)


class CalculationCaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["calculation"] = "calculation"
    target_skill_id: str = Field(min_length=1)
    input_template: dict[str, Any]
    assertions: CalculationAssertions


class PolicyContentCaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["policy_content"] = "policy_content"
    target_skill_id: str = Field(min_length=1)
    input_template: dict[str, Any]
    assertions: PolicyContentAssertions


class CitationCaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["citation"] = "citation"
    target_skill_id: str = Field(min_length=1)
    input_template: dict[str, Any]
    assertions: CitationAssertions


class AnswerQualityCaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["answer_quality"] = "answer_quality"
    target_skill_id: str = Field(min_length=1)
    input_template: dict[str, Any]
    assertions: AnswerQualityAssertions


class SafetyCaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["safety"] = "safety"
    target_skill_id: str = Field(min_length=1)
    input_template: dict[str, Any]
    assertions: SafetyAssertions


CaseProposal = Annotated[
    RoutingCaseProposal
    | CalculationCaseProposal
    | PolicyContentCaseProposal
    | CitationCaseProposal
    | AnswerQualityCaseProposal
    | SafetyCaseProposal,
    Field(discriminator="case_type"),
]


# ── 回归用例与评测状态 ───────────────────────────────────────────


class SkillRegressionEvaluatorStatus(StrEnum):
    AVAILABLE = "available"
    BLOCKED_BY_EVALUATOR = "blocked_by_evaluator"
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class SkillRegressionCase(BaseModel):
    """人工确认后的分型回归用例（仅五类可执行维度）。"""

    model_config = ConfigDict(frozen=True)

    case_id: str
    target_skill_id: str = Field(min_length=1)
    case_type: SkillErrorDimension
    input_template: dict[str, Any]
    expected_assertions: RegressionAssertions
    required: bool = True
    evaluator_status: SkillRegressionEvaluatorStatus = (
        SkillRegressionEvaluatorStatus.BLOCKED_BY_EVALUATOR
    )
    evaluator_version: str | None = None
    source_type: str = "policy_qa_feedback"
    source_ref: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_by: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _assertions_match_case_type(self) -> "SkillRegressionCase":
        assertion_type = self.expected_assertions.case_type
        if assertion_type != str(self.case_type.value):
            raise ValueError(
                f"case_type {self.case_type.value} 与断言类型 {assertion_type} 不一致"
            )
        return self


# ── 案例池 ───────────────────────────────────────────────────────


class SkillEvalCasePoolStatus(StrEnum):
    PENDING_TRIAGE = "pending_triage"
    TRANSFORMED = "transformed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class EvalCaseRef(BaseModel):
    """案例池确认后指向的评测资产（路由用例或回归用例）。"""

    model_config = ConfigDict(frozen=True)

    case_type: str  # "route" 表示路由用例；否则为 SkillErrorDimension 值
    case_id: str


class SkillEvalCasePoolItem(BaseModel):
    """统一 Skill 错误案例池条目。

    所有维度（含 routing/other）先进池；AI 分型 + 人工确认后投影到对应资产。
    所有证据与已确认资产使用 frozen 模型；原文患者标识不得进入本结构。
    """

    model_config = ConfigDict(frozen=True)

    pool_id: str
    tenant_id: str = Field(min_length=1, max_length=128)
    source_qa_turn_id: str = Field(min_length=1, max_length=80)
    source_user_id: str = Field(min_length=1, max_length=128)
    reason_code: SkillFeedbackReasonCode
    error_dimension: SkillErrorDimension | None = None
    comment: str = Field(default="", max_length=500)
    question_excerpt: str = Field(default="", max_length=500)
    answer_excerpt: str = Field(default="", max_length=500)
    source_selected_skill_id: str | None = None
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SkillEvalCasePoolStatus = SkillEvalCasePoolStatus.PENDING_TRIAGE
    revision: int = Field(default=1, ge=1)
    eval_case_ref: EvalCaseRef | None = None
    transformed_dimension: SkillErrorDimension | None = None
    transformed_proposal: dict[str, Any] | None = None
    transformed_root_cause: str | None = None
    transformed_citations: list[dict[str, Any]] = Field(default_factory=list)
    transformed_uncertainties: list[str] = Field(default_factory=list)
    rejection_reason: str | None = Field(default=None, max_length=500)
    created_by: str = Field(default="system", min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="before")
    @classmethod
    def _default_dimension_from_reason(
        cls, data: Any
    ) -> Any:
        """未显式指定维度时，由反馈原因码推导初始错误维度。"""
        if isinstance(data, dict):
            dimension = data.get("error_dimension")
            reason = data.get("reason_code")
            if dimension is None and reason is not None:
                resolved = (
                    reason
                    if isinstance(reason, SkillFeedbackReasonCode)
                    else SkillFeedbackReasonCode(reason)
                )
                data = {**data, "error_dimension": reason_code_to_dimension(resolved)}
        return data
