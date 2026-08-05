"""政策知识经典测试、候选版本与质量门禁模型。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyQATestCase(BaseModel):
    case_id: str
    name: str
    query: str
    mode: Literal["precise", "semantic", "hybrid"]
    expected_knowledge_ids: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    active: bool = True
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
    quality_score: float | None = Field(default=None, ge=0, le=1)
    consistency_score: float | None = Field(default=None, ge=0, le=1)
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
