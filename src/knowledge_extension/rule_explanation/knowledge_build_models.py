"""政策知识构建任务及单元占用模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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

# ── 迭代 18：知识审核重提取覆盖配置 ──────────────────────────────
# 单次重新提取的提示词 / 模型覆盖。未提供（None）时全部走默认
# （schema 提示词 + 默认模型路由）。
PromptMode = Literal["schema", "legacy", "custom"]


class ExtractionOverride(BaseModel):
    """单次重新提取的提示词 / 模型覆盖配置。

    - ``prompt_mode="custom"`` 时 ``custom_prompt`` 必填，且指标不会被自动注入
      （由调用方在 ``custom_prompt`` 中自行包含需要的指标口径）。
    - ``model_name`` 非空时绕过 ``ModelRouter`` 直接用该模型（关闭 fallback）。
    """

    model_config = ConfigDict(frozen=True)

    prompt_mode: PromptMode | None = None
    custom_prompt: str | None = None
    model_name: str | None = None
    max_tokens: int | None = None
    operator: str | None = None

    @model_validator(mode="after")
    def _require_custom_prompt(self) -> "ExtractionOverride":
        if self.prompt_mode == "custom" and not (
            self.custom_prompt and self.custom_prompt.strip()
        ):
            raise ValueError("prompt_mode=custom 时 custom_prompt 不能为空")
        return self


class ReextractItemResult(BaseModel):
    """单次重新提取中一个提取单元（extraction）的结果。

    多个变更项可能共享同一 extraction（knowledge_id = hash(extraction_id, rule)），
    故按 extraction 聚合，``item_ids`` 记录触发本次重提取的原始变更项。
    """

    extraction_id: str
    item_ids: list[str] = Field(default_factory=list)
    success: bool
    error: str | None = None
    model_used: str | None = None
    prompt_mode_used: PromptMode | None = None
    new_knowledge_count: int = 0


class ReextractReport(BaseModel):
    """变更集重新提取报告（迭代 18 S2，原地刷新策略）。"""

    change_set_id: str
    total: int
    succeeded: int
    failed: int
    items: list[ReextractItemResult] = Field(default_factory=list)
    override_applied: dict | None = None


class KnowledgeBuildUnitRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    unit_id: str
    unit_revision_id: str

    @field_validator("doc_id", "unit_id", "unit_revision_id")
    @classmethod
    def _require_nonblank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标识不能为空")
        return value


class CreateKnowledgeBuildTaskRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    created_by: str
    build_mode: BuildMode
    rebuild_reason: str | None = None
    unit_revisions: tuple[KnowledgeBuildUnitRevision, ...] = Field(min_length=1)

    @field_validator("name", "created_by")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("字段不能为空")
        return stripped

    @field_validator("rebuild_reason")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _require_unique_units(self) -> "CreateKnowledgeBuildTaskRequest":
        logical_units = {
            (selection.doc_id, selection.unit_id)
            for selection in self.unit_revisions
        }
        if len(logical_units) != len(self.unit_revisions):
            raise ValueError("构建任务不能重复选择同一政策单元")
        return self


class EligibleKnowledgeUnit(BaseModel):
    doc_id: str
    doc_title: str
    unit_id: str
    unit_revision_id: str
    path: list[str] = Field(default_factory=list)
    source_preview: str
    status: Literal["reviewed", "published"]
    knowledge_count: int
    availability: Literal["AVAILABLE", "CLAIMED", "REBUILD_REQUIRED"]
    occupied_by: str | None = None
    target_href: str | None = None


class KnowledgeBuildBlocker(BaseModel):
    code: Literal[
        "UNIT_NOT_APPROVED",
        "UNIT_REVISION_CHANGED",
        "UNIT_ALREADY_CLAIMED",
        "SEMANTIC_CONTRACT_MISMATCH",
        "REBUILD_MODE_REQUIRED",
        "REBUILD_REASON_REQUIRED",
    ]
    message: str
    doc_id: str | None = None
    unit_id: str | None = None
    unit_revision_id: str | None = None
    task_id: str | None = None
    target_href: str | None = None


class KnowledgeBuildWarning(BaseModel):
    code: Literal["REBUILDING_PUBLISHED_UNIT"]
    message: str
    doc_id: str
    unit_id: str


class KnowledgeBuildPreflight(BaseModel):
    selected_count: int
    buildable_count: int
    blocking_count: int
    rebuild_count: int
    can_submit: bool
    semantic_contract_version: str | None = None
    blockers: list[KnowledgeBuildBlocker] = Field(default_factory=list)
    warnings: list[KnowledgeBuildWarning] = Field(default_factory=list)


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
