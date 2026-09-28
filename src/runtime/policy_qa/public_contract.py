"""Policy QA 面向调用方的安全公开结果契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PolicyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    excerpt: str
    doc_id: str = ""
    source_excerpt: str = ""  # 命中单元的原文段落（溯源页高亮用）


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_checked: bool
    calculation_checked: bool
    policy_count: int = Field(ge=0)
    message: str


class PolicyQACaseContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_type: str | None = None
    insurance_type: str | None = None
    service_type: str | None = None
    hospital_level: str | None = None
    deductible: float | None = None
    yearly_cycle_count: int | None = None
    basic_pooling_payment: float | None = None
    basic_pooling_self_pay: float | None = None
    large_amount_payment: float | None = None
    large_amount_self_pay: float | None = None
    personal_total_pay: float | None = None
    total_amount: float | None = None
    query_scope: Literal[
        "whole_admission", "segment", "whole_settlement", "fee_item"
    ] | None = None
    segment_count: int | None = Field(default=None, ge=0)
    matched_segment_count: int | None = Field(default=None, ge=0)
    coverage_status: Literal["complete", "partial", "unavailable"] | None = None
    stay_start_date: str | None = None
    stay_end_date: str | None = None


class PolicyQACalculationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_name: str | None = None
    description: str | None = None
    label: str | None = None
    formula: str | None = None
    result: str | None = None
    calculation: str | None = None
    note: str | None = None


class PolicyQADefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    plain_text: str = ""
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    excerpt: str
    score: float | None = Field(default=None, allow_inf_nan=False)
    doc_id: str = ""


class OutpatientContextCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str | float | int | bool | None = None
    status: Literal["present", "missing"]


class OutpatientAmountCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    equation: str
    # 数值算式（带单位的操作数展示），与 Skill 内部 AmountCheck.detail 对齐
    detail: str | None = None
    actual: float | None = None
    expected: float | None = None
    difference: float | None = None
    tolerance: float
    status: Literal["passed", "failed", "not_evaluable"]


class OutpatientFieldExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    value: float | None = None
    state: Literal["non_zero", "reported_zero", "missing", "not_applicable"]
    applicable: bool | None = None
    explanation: str
    citations: list[str] = Field(min_length=1)


class DecompositionFieldView(BaseModel):
    """费用分解单字段公开视图（设计 §10/§11；金额为十进制字符串）。"""

    model_config = ConfigDict(extra="forbid")

    field_code: str
    label: str
    check_type: str
    check_status: str
    observed_amount: str | None = None
    calculated_amount: str | None = None
    difference: str | None = None
    explanation_level: str


class DecompositionUncertaintyView(BaseModel):
    """费用分解不确定性公开视图（缺规则/缺数据显式列出）。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class DecompositionCoverageView(BaseModel):
    """费用分解覆盖统计（设计 §11 coverage）。"""

    model_config = ConfigDict(extra="forbid")

    target_field_count: int = Field(ge=0)
    independently_explained_count: int = Field(ge=0)
    amount_reconciled_count: int = Field(ge=0)
    observed_only_count: int = Field(ge=0)


class FeeDecompositionPublic(BaseModel):
    """结算费用分解公开结果（Issue #78，schema 版本化；不含审计级分支/计算细节）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    algorithm_version: str
    execution_status: Literal["complete", "partial", "unavailable"]
    reconciliation_status: str
    summary_text: str = ""
    summary_source: Literal["template", "model"] = "template"
    may_claim_full_explanation: bool = False
    fields: list[DecompositionFieldView] = Field(default_factory=list)
    uncertainties: list[DecompositionUncertaintyView] = Field(default_factory=list)
    coverage: DecompositionCoverageView | None = None


class PolicyQAPublicResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    answer_status: Literal["complete", "partial", "unavailable"]
    case_context: PolicyQACaseContext | None = None
    calculation_steps: list[PolicyQACalculationStep] = Field(default_factory=list)
    definition: PolicyQADefinition | None = None
    warnings: list[str] = Field(default_factory=list)
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    verification_summary: VerificationSummary
    is_broad: bool = False
    scenario_id: str | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    context_checks: list[OutpatientContextCheck] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    amount_checks: list[OutpatientAmountCheck] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    field_explanations: list[OutpatientFieldExplanation] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    anomalies: list[str] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    next_actions: list[str] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    action_status: Literal["waiting_human_confirmation"] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    fee_decomposition: FeeDecompositionPublic | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
