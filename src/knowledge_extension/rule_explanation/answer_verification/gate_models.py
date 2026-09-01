"""候选发布答案验证门禁运行模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    KnowledgeAnswerVerificationDimension,
    KnowledgeAnswerVerificationResult,
    utc_now,
)


class AnswerVerificationRun(BaseModel):
    """一次候选 release 的答案验证门禁运行。"""

    run_id: str
    release_id: str
    case_set_version: int
    status: Literal["passed", "failed"]
    blocked_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    quality_run_id: str | None = None


class AnswerVerificationCaseResult(BaseModel):
    """单个经典用例的答案验证门禁结果。"""

    run_id: str
    case_id: str
    status: Literal["passed", "failed"]
    gated_dimensions: list[KnowledgeAnswerVerificationDimension] = Field(
        default_factory=list
    )
    skipped_dimensions: list[KnowledgeAnswerVerificationDimension] = Field(
        default_factory=list
    )
    blocked_reasons: list[str] = Field(default_factory=list)
    verification: KnowledgeAnswerVerificationResult
