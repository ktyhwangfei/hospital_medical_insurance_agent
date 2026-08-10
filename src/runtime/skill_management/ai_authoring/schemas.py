"""Skill AI 编写的严格模型输出与提案契约。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_validator,
)

from src.domain.common.models import Citation


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _freeze_json(value: Any) -> Any:
    """递归冻结 JSON 容器，避免生成后绕过 Pydantic frozen 修改内容。"""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """序列化时恢复标准 JSON object/array 形状。"""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


FrozenJSONMapping = Annotated[
    Mapping[str, Any],
    AfterValidator(_freeze_json),
    PlainSerializer(_thaw_json, return_type=dict[str, Any]),
]
FrozenStringMapping = Annotated[
    Mapping[str, str],
    AfterValidator(_freeze_json),
    PlainSerializer(_thaw_json, return_type=dict[str, str]),
]
NonEmptyUncertainty = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


class SkillStructuredBasic(_StrictFrozenModel):
    skill_id: str = Field(min_length=1, max_length=128)
    skill_name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4000)
    owner: str = Field(default="", max_length=128)


class SkillStructuredBusinessMounting(_StrictFrozenModel):
    business_action: str = Field(min_length=1, max_length=128)
    business_object: str = Field(min_length=1, max_length=128)
    include_keywords: tuple[str, ...] = ()
    excluded_intents: tuple[str, ...] = ()


class SkillStructuredInput(_StrictFrozenModel):
    metric_code: str = Field(min_length=1, max_length=256)
    alias: str = Field(default="", max_length=128)
    required: bool = True
    purpose: str = Field(default="", max_length=512)


class SkillStructuredSchemas(_StrictFrozenModel):
    input: FrozenJSONMapping
    output: FrozenJSONMapping


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

    @model_validator(mode="after")
    def _validate_summary(self) -> "SkillValidationReportResponse":
        has_blocking = any(issue.severity == "blocking" for issue in self.issues)
        if (
            self.has_blocking != has_blocking
            or self.blocking_ok != (not has_blocking)
        ):
            raise ValueError("校验摘要必须与 issues 的 blocking 级别一致")
        return self


class _TraceableAIOutput(_StrictFrozenModel):
    citations: tuple[Citation, ...]
    uncertainties: tuple[NonEmptyUncertainty, ...]

    @model_validator(mode="after")
    def _require_traceability(self) -> "_TraceableAIOutput":
        if not self.citations and not self.uncertainties:
            raise ValueError("AI 输出必须携带 citation 或声明 uncertainty")
        return self


class SkillAIModelOutput(_TraceableAIOutput):
    """受控模型可返回的内容，不包含服务端溯源字段。"""

    structured_config: SkillStructuredConfig
    raw_files: FrozenStringMapping


class SkillAIGenerationProvenance(_StrictFrozenModel):
    model_type: str = Field(min_length=1, max_length=120)
    scene: Literal["skill_authoring"]
    prompt_version: str = Field(min_length=1, max_length=64)
    metric_versions: tuple[SkillMetricVersionRef, ...]
    generated_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def _normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at 必须包含时区")
        return value.astimezone(timezone.utc)


class SkillAIGenerationResponse(_TraceableAIOutput):
    """服务端校验后返回的不可变 AI proposal。"""

    generation_id: str = Field(min_length=1, max_length=80)
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structured_config: SkillStructuredConfig
    raw_files: FrozenStringMapping
    validation_preview: SkillValidationReportResponse
    provenance: SkillAIGenerationProvenance
