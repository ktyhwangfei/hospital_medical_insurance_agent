"""Policy QA 面向调用方的安全公开结果契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PolicyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    excerpt: str


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
