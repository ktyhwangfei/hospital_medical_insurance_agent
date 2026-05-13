import re
from typing import Any

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from src.knowledge_extension.mcp_registry.models import McpRiskLevel


class ToolOwner(StrEnum):
    CASHIER = "cashier"
    MEDICAL_OFFICE = "medical_office"
    INFORMATION_DEPARTMENT = "information_department"
    MEDICAL_RECORD_STAFF = "medical_record_staff"


class SkillMetadata(BaseModel):
    author: str = ""
    version: str = "1.0.0"
    mcp_server: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class SkillStep(BaseModel):
    step_id: str
    tool_id: str
    depends_on: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    skill_id: str
    name: str
    description: str
    owner: ToolOwner
    steps: list[SkillStep] = Field(default_factory=list)
    intent_keywords: list[str] = Field(default_factory=list)
    required_roles: set[str] = Field(default_factory=set)
    enabled: bool = True
    risk_level: McpRiskLevel = McpRiskLevel.LOW
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    skill_metadata: SkillMetadata = Field(default_factory=SkillMetadata)

    @field_validator("skill_id")
    @classmethod
    def _kebab_or_snake_case(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9]+([-_][a-z0-9]+)*", value):
            raise ValueError("技能ID必须使用 kebab-case 或 snake_case 格式（小写字母、连字符、下划线、数字）")
        return value

    @field_validator("name", "description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    @field_validator("description")
    @classmethod
    def _description_max_length(cls, value: str) -> str:
        if len(value) > 1024:
            raise ValueError("描述不能超过1024个字符")
        return value

    @field_validator("compatibility")
    @classmethod
    def _compatibility_max_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            raise ValueError("兼容性说明不能超过500个字符")
        return value
