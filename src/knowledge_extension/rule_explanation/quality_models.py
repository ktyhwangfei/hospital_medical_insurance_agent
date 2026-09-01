"""政策知识经典测试、候选版本与质量门禁模型。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    AnswerCitation,
    AnswerEvidenceRef,
    KnowledgeAnswerVerificationDimension,
    QueryPlanItem,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnswerVerificationFixture(BaseModel):
    """经典问答用例上的答案验证夹具，声明公开答案与期望内部证据。"""

    model_config = ConfigDict(frozen=True)

    answer: str
    citations: list[AnswerCitation] = Field(default_factory=list)
    expected_evidence: list[AnswerEvidenceRef] = Field(default_factory=list)
    scenario: str = ""
    planned_queries: list[QueryPlanItem] = Field(default_factory=list)
    missing_required_rules: list[str] = Field(default_factory=list)
    calculation_trace: dict[str, Any] | None = None
    gated_dimensions: list[KnowledgeAnswerVerificationDimension] = Field(
        default_factory=list
    )


class PolicyQATestCase(BaseModel):
    case_id: str
    name: str
    query: str
    mode: Literal["precise", "semantic", "hybrid"]
    expected_knowledge_ids: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    active: bool = True
    answer_verification: AnswerVerificationFixture | None = None
    case_set_version: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


ReleaseStatus = Literal[
    "building", "ready", "testing", "passed", "failed", "active", "retired"
]


class KnowledgeRelease(BaseModel):
    release_id: str
    status: ReleaseStatus = "building"
    facts_collection: str
    rules_collection: str
    contract_version: str
    case_set_version: int
    config_hash: str
    source_change_set_id: str | None = None
    quality_run_id: str | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    consistency_score: float | None = Field(default=None, ge=0, le=1)
    build_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    promoted_at: datetime | None = None
    promoted_by: str | None = None


class QualityCaseResult(BaseModel):
    run_id: str
    target: Literal["candidate", "baseline"]
    case_id: str
    repeat_index: int = Field(ge=0)
    result_knowledge_ids: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=1)
    passed: bool
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class QualityRun(BaseModel):
    run_id: str
    release_id: str
    baseline_release_id: str | None = None
    case_set_version: int
    config_hash: str
    repeat_count: int = Field(default=3, ge=3)
    status: Literal["queued", "running", "passed", "failed"] = "queued"
    candidate_score: float | None = Field(default=None, ge=0, le=1)
    baseline_score: float | None = Field(default=None, ge=0, le=1)
    consistency_score: float | None = Field(default=None, ge=0, le=1)
    blocked_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class GateDecision(BaseModel):
    passed: bool
    candidate_score: float
    baseline_score: float | None = None
    consistency_score: float
    blocked_reasons: list[str] = Field(default_factory=list)
