"""政策知识构建任务及单元占用模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""
    return datetime.now(timezone.utc)


BuildTaskStatus = Literal[
    "QUEUED",
    "RUNNING",
    "WAITING_REVIEW",
    "APPROVED_PENDING_RELEASE",
    "PUBLISHED",
    "RETURNED",
    "REJECTED",
    "FAILED",
    "CANCELLED",
]
BuildMode = Literal["INITIAL", "REBUILD"]
UnitBuildStatus = Literal["PENDING", "BUILT", "FAILED"]


class KnowledgeBuildTaskUnit(BaseModel):
    doc_id: str
    doc_title: str
    unit_id: str
    unit_revision_id: str
    path: list[str] = Field(default_factory=list)
    status: UnitBuildStatus = "PENDING"
    candidate_result_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class KnowledgeBuildTask(BaseModel):
    task_id: str
    name: str
    status: BuildTaskStatus
    build_mode: BuildMode
    semantic_contract_version: str
    pipeline_version: str
    model_scene: str
    config_hash: str
    rebuild_reason: str | None = None
    created_by: str
    units: list[KnowledgeBuildTaskUnit]
    processed_units: int = 0
    result_change_set_id: str | None = None
    result_summary: dict[str, int] = Field(default_factory=dict)
    issue_count: int = 0
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class UnitBuildClaim(BaseModel):
    doc_id: str
    unit_id: str
    unit_revision_id: str
    task_id: str
    claimed_at: datetime = Field(default_factory=utc_now)
