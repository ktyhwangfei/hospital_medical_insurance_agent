"""Skill AI 编写的严格模型输出与提案契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.common.models import Citation


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillStructuredBasic(_StrictFrozenModel):
    skill_id: str = Field(min_length=1, max_length=128)
    skill_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4000)
    owner: str = Field(default="", max_length=128)


class SkillStructuredBusinessMounting(_StrictFrozenModel):
    business_action: str = Field(min_length=1, max_length=128)
    business_object: str = Field(min_length=1, max_length=128)
    keywords: tuple[str, ...] = ()
    excluded_intents: tuple[str, ...] = ()


class SkillStructuredInput(_StrictFrozenModel):
    metric_code: str = Field(min_length=1, max_length=256)
    alias: str = Field(default="", max_length=128)
    required: bool = True
    purpose: str = Field(default="", max_length=512)


class SkillStructuredSchemas(_StrictFrozenModel):
    input: dict[str, Any]
    output: dict[str, Any]


class SkillStructuredConfig(_StrictFrozenModel):
    """AI 可生成的 Skill 结构化事实源。"""

    basic: SkillStructuredBasic
    business_mounting: SkillStructuredBusinessMounting
    inputs: tuple[SkillStructuredInput, ...] = ()
    schemas: SkillStructuredSchemas


class SkillMetricVersionRef(_StrictFrozenModel):
    """生成时使用的已发布指标及对象版本快照。"""

    metric_code: str = Field(min_length=1, max_length=256)
    object_code: str = Field(min_length=1, max_length=64)
    object_version: int = Field(ge=1)
    status: Literal["published"]


class SkillValidationIssueResponse(_StrictFrozenModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    severity: Literal["blocking", "warning"]
    path: str | None = Field(default=None, max_length=512)


class SkillValidationReportResponse(_StrictFrozenModel):
    issues: tuple[SkillValidationIssueResponse, ...] = ()
    has_blocking: bool
    blocking_ok: bool


class SkillAIModelOutput(_StrictFrozenModel):
    """受控模型可返回的内容，不包含服务端溯源字段。"""

    structured_config: SkillStructuredConfig
    raw_files: dict[str, str]
    citations: tuple[Citation, ...]
    uncertainties: tuple[str, ...]


class SkillAIGenerationProvenance(_StrictFrozenModel):
    model_type: str = Field(min_length=1, max_length=120)
    scene: Literal["skill_authoring"]
    prompt_version: str = Field(min_length=1, max_length=64)
    metric_versions: tuple[SkillMetricVersionRef, ...]
    generated_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillAIGenerationResponse(_StrictFrozenModel):
    """服务端校验后返回的不可变 AI proposal。"""

    generation_id: str = Field(min_length=1, max_length=80)
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structured_config: SkillStructuredConfig
    raw_files: dict[str, str]
    validation_preview: SkillValidationReportResponse
    provenance: SkillAIGenerationProvenance
    citations: tuple[Citation, ...]
    uncertainties: tuple[str, ...]
