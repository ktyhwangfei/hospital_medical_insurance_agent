"""候选 Skill 行为评测端口；宿主进程不得执行候选代码。"""

from __future__ import annotations

from typing import Any, Literal, Protocol, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from src.runtime.skill_management.ai_authoring.candidate_evaluation import (
        SkillCandidateArtifact,
    )


class SkillCandidateBehaviorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=128)
    case_type: str = Field(min_length=1, max_length=64)
    input: dict[str, Any]
    assertions: dict[str, Any]


class SkillCandidateBehaviorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=128)
    status: Literal["passed", "failed", "blocked_by_evaluator"]
    passed: bool
    output: dict[str, Any] | None = None
    blocked_reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _validate_status(self) -> "SkillCandidateBehaviorResult":
        if self.passed != (self.status == "passed"):
            raise ValueError("passed must match status")
        if self.status == "blocked_by_evaluator" and not self.blocked_reason:
            raise ValueError("blocked result requires blocked_reason")
        return self


class CandidateExecutionPort(Protocol):
    def execute(
        self,
        artifact: "SkillCandidateArtifact",
        request: SkillCandidateBehaviorRequest,
    ) -> SkillCandidateBehaviorResult: ...


class DisabledCandidateExecutionAdapter:
    """未配置隔离执行器时明确阻断，绝不回退到宿主执行。"""

    def __init__(self, reason: str = "sandbox_unavailable") -> None:
        self._reason = reason

    def execute(
        self,
        artifact: "SkillCandidateArtifact",
        request: SkillCandidateBehaviorRequest,
    ) -> SkillCandidateBehaviorResult:
        del artifact
        return SkillCandidateBehaviorResult(
            case_id=request.case_id,
            status="blocked_by_evaluator",
            passed=False,
            blocked_reason=self._reason,
        )
