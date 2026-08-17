"""模型治理控制面的类型安全资产与版本对象。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from string import Formatter
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_ASSET_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,127}$"
_VARIABLE_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
_SAFE_FIELD = re.compile(_VARIABLE_PATTERN)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GovernanceAssetType(StrEnum):
    PROMPT = "prompt"
    MODEL_PROFILE = "model_profile"
    ROUTE_RULE = "route_rule"


class GovernanceDraftStatus(StrEnum):
    EDITING = "editing"
    VALIDATED = "validated"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"


class GovernanceEnvironment(StrEnum):
    DEV = "dev"
    TEST = "test"


class GovernanceReleaseStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class GovernanceRuntimeStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    STATIC_SOURCE = "static_source"


class PromptVariable(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=_VARIABLE_PATTERN)
    required: bool = True
    description: str = Field(default="", max_length=500)


class PromptAssetContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_type: Literal["prompt"] = "prompt"
    asset_id: str = Field(pattern=_ASSET_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    scene: str = Field(min_length=1, max_length=64)
    model_type: str = Field(default="llm", min_length=1, max_length=32)
    system_prompt: str = Field(default="", max_length=20_000)
    user_prompt_template: str = Field(min_length=1, max_length=20_000)
    variables: list[PromptVariable] = Field(default_factory=list)
    output_mode: Literal["text", "json"] = "text"

    @model_validator(mode="after")
    def variable_names_are_unique(self) -> PromptAssetContent:
        names = [variable.name for variable in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("提示词变量名不能重复")
        return self


class ModelProfileAssetContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_type: Literal["model_profile"] = "model_profile"
    asset_id: str = Field(pattern=_ASSET_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    provider_id: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=2048)
    model_name: str = Field(min_length=1, max_length=256)
    credential_ref: str = Field(pattern=_ASSET_ID_PATTERN)
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=1, le=65_536)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise ValueError("base_url 必须是有效 HTTP(S) URL") from exc
        if (
            value != value.strip()
            or any(character.isspace() for character in value)
            or parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("base_url 仅允许不含用户信息的 HTTP(S) URL")
        return value.rstrip("/")


class RouteRuleAssetContent(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_type: Literal["route_rule"] = "route_rule"
    asset_id: str = Field(pattern=_ASSET_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    scene: str = Field(min_length=1, max_length=64)
    model_type: str = Field(default="llm", min_length=1, max_length=32)
    profile_id: str = Field(pattern=_ASSET_ID_PATTERN)
    fallback_profile_ids: list[str] = Field(default_factory=list)
    enabled: bool = True


GovernanceAssetContent = Annotated[
    PromptAssetContent | ModelProfileAssetContent | RouteRuleAssetContent,
    Field(discriminator="asset_type"),
]


class GovernanceValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    path: str = ""


class GovernanceValidationError(ValueError):
    """资产无法安全预览。"""


class GovernanceAssetPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_type: GovernanceAssetType
    asset_id: str
    rendered_system_prompt: str | None = None
    rendered_user_prompt: str | None = None
    profile_id: str | None = None
    fallback_profile_ids: list[str] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None


class GovernanceDraft(BaseModel):
    draft_id: str
    asset_id: str
    asset_type: GovernanceAssetType
    content: GovernanceAssetContent
    status: GovernanceDraftStatus = GovernanceDraftStatus.EDITING
    revision: int = Field(default=1, ge=1)
    validation_issues: list[GovernanceValidationIssue] = Field(default_factory=list)
    created_by: str = Field(min_length=1, max_length=128)
    last_edited_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class GovernanceVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str
    asset_id: str
    asset_type: GovernanceAssetType
    version_number: int = Field(ge=1)
    content: GovernanceAssetContent
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: str
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)


class GovernanceCredential(BaseModel):
    model_config = ConfigDict(frozen=True)

    credential_id: str = Field(pattern=_ASSET_ID_PATTERN)
    encrypted_api_key: str = Field(min_length=1)
    secret_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    endpoint_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    revision: int = Field(default=1, ge=1)
    updated_by: str = Field(min_length=1, max_length=128)
    updated_at: datetime = Field(default_factory=_utc_now)


class GovernanceReleaseCredentialBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    release_id: str
    credential_id: str = Field(pattern=_ASSET_ID_PATTERN)
    credential_revision: int = Field(ge=1)
    credential_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class GovernanceConnectionTest(BaseModel):
    model_config = ConfigDict(frozen=True)

    test_id: UUID
    asset_id: str = Field(pattern=_ASSET_ID_PATTERN)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    credential_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    succeeded: bool
    latency_ms: int = Field(ge=0)
    safe_message: str = Field(max_length=500)
    tested_by: str = Field(min_length=1, max_length=128)
    tested_at: datetime = Field(default_factory=_utc_now)


class GovernanceApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    draft_id: str
    asset_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    approved_at: datetime = Field(default_factory=_utc_now)


class GovernanceRelease(BaseModel):
    model_config = ConfigDict(frozen=True)

    release_id: str
    asset_id: str
    asset_type: GovernanceAssetType
    version_id: str
    environment: GovernanceEnvironment
    status: GovernanceReleaseStatus = GovernanceReleaseStatus.ACTIVE
    previous_release_id: str | None = None
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    retired_at: datetime | None = None


class PublishedGovernanceAsset(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    asset_type: GovernanceAssetType
    version_id: str
    release_id: str
    content_hash: str
    content: GovernanceAssetContent
    runtime_status: GovernanceRuntimeStatus = GovernanceRuntimeStatus.NOT_CONNECTED


class PublishedGovernanceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    environment: GovernanceEnvironment
    assets: list[PublishedGovernanceAsset] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utc_now)


class GovernanceImportCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt: int = Field(default=0, ge=0)
    model_profile: int = Field(default=0, ge=0)
    route_rule: int = Field(default=0, ge=0)


class GovernanceImportResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    drafts: list[GovernanceDraft] = Field(default_factory=list)
    created_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    counts: GovernanceImportCounts


def content_hash(content: GovernanceAssetContent) -> str:
    payload = content.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _prompt_fields(template: str) -> tuple[set[str], list[GovernanceValidationIssue]]:
    fields: set[str] = set()
    issues: list[GovernanceValidationIssue] = []
    try:
        parts = Formatter().parse(template)
        for _, field_name, format_spec, conversion in parts:
            if field_name is None:
                continue
            if (
                not _SAFE_FIELD.fullmatch(field_name)
                or format_spec
                or conversion is not None
            ):
                issues.append(
                    GovernanceValidationIssue(
                        code="UNSAFE_TEMPLATE_FIELD",
                        message=f"模板字段不安全: {field_name}",
                        path="user_prompt_template",
                    )
                )
                continue
            fields.add(field_name)
    except ValueError as exc:
        issues.append(
            GovernanceValidationIssue(
                code="INVALID_TEMPLATE",
                message=f"模板格式无效: {exc}",
                path="user_prompt_template",
            )
        )
    return fields, issues


def validate_asset(content: GovernanceAssetContent) -> list[GovernanceValidationIssue]:
    if isinstance(content, PromptAssetContent):
        fields, issues = _prompt_fields(
            f"{content.system_prompt}\n{content.user_prompt_template}"
        )
        declared = {variable.name for variable in content.variables}
        for field in sorted(fields - declared):
            issues.append(
                GovernanceValidationIssue(
                    code="UNDECLARED_TEMPLATE_VARIABLE",
                    message=f"模板变量未声明: {field}",
                    path="variables",
                )
            )
        return issues

    if isinstance(content, RouteRuleAssetContent):
        issues = []
        if content.profile_id in content.fallback_profile_ids:
            issues.append(
                GovernanceValidationIssue(
                    code="SELF_FALLBACK_NOT_ALLOWED",
                    message="主模型档案不能同时作为备用模型",
                    path="fallback_profile_ids",
                )
            )
        if len(content.fallback_profile_ids) != len(set(content.fallback_profile_ids)):
            issues.append(
                GovernanceValidationIssue(
                    code="DUPLICATE_FALLBACK_PROFILE",
                    message="备用模型档案不能重复",
                    path="fallback_profile_ids",
                )
            )
        return issues

    return []


def preview_asset(
    content: GovernanceAssetContent,
    variables: dict[str, str] | None = None,
) -> GovernanceAssetPreview:
    issues = validate_asset(content)
    if issues:
        raise GovernanceValidationError("；".join(issue.message for issue in issues))

    if isinstance(content, PromptAssetContent):
        values = variables or {}
        declared = {variable.name for variable in content.variables}
        required = {
            variable.name for variable in content.variables if variable.required
        }
        missing = sorted(required - values.keys())
        extra = sorted(values.keys() - declared)
        if missing:
            raise GovernanceValidationError(f"缺少变量: {', '.join(missing)}")
        if extra:
            raise GovernanceValidationError(f"未声明变量: {', '.join(extra)}")
        return GovernanceAssetPreview(
            asset_type=GovernanceAssetType.PROMPT,
            asset_id=content.asset_id,
            rendered_system_prompt=content.system_prompt.format_map(values),
            rendered_user_prompt=content.user_prompt_template.format_map(values),
        )

    if isinstance(content, ModelProfileAssetContent):
        return GovernanceAssetPreview(
            asset_type=GovernanceAssetType.MODEL_PROFILE,
            asset_id=content.asset_id,
            temperature=content.temperature,
            max_tokens=content.max_tokens,
        )

    return GovernanceAssetPreview(
        asset_type=GovernanceAssetType.ROUTE_RULE,
        asset_id=content.asset_id,
        profile_id=content.profile_id,
        fallback_profile_ids=content.fallback_profile_ids,
    )
