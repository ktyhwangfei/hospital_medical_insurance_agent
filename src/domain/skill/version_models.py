from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillValidationStatus(StrEnum):
    """Skill 制品校验状态。"""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class SkillValidationIssue(BaseModel):
    """Skill 制品的单项校验问题。"""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    path: str | None = None


class SkillArtifactSnapshot(BaseModel):
    """由 Skill 目录内容生成的不可变制品快照。"""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    semantic_version: str
    source_path: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_snapshot: dict[str, Any] = Field(default_factory=dict)
    dependency_snapshot: dict[str, Any] = Field(default_factory=dict)
    file_paths: list[str] = Field(min_length=1)


class SkillVersion(BaseModel):
    """已登记、不可原地修改的 Skill 版本实体。"""

    model_config = ConfigDict(frozen=True)

    version_id: str
    skill_id: str
    semantic_version: str
    source_commit: str
    source_path: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_snapshot: dict[str, Any] = Field(default_factory=dict)
    dependency_snapshot: dict[str, Any] = Field(default_factory=dict)
    file_count: int = Field(ge=1)
    validation_status: SkillValidationStatus = SkillValidationStatus.PENDING
    validation_issues: list[SkillValidationIssue] = Field(default_factory=list)
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
