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


class PolicyQAPublicResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    answer_status: Literal["complete", "partial", "unavailable"]
    case_context: dict[str, str | int | float | bool | None] | None = None
    calculation_steps: list[dict[str, str]] = Field(default_factory=list)
    definition: dict[str, str | list[str]] | None = None
    warnings: list[str] = Field(default_factory=list)
    policy_evidence: list[dict[str, str | float | None]] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    verification_summary: VerificationSummary
