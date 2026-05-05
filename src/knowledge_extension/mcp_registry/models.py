from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus


class McpTransportType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class McpServerStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class McpCapabilityType(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"
    SERVICE = "service"


class McpRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class McpServer(BaseModel):
    server_id: str
    name: str
    endpoint: str
    transport: McpTransportType
    status: McpServerStatus = McpServerStatus.DISABLED
    protocol_version: str | None = None
    auth_headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("server_id", "name", "endpoint")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["auth_headers"] = {
            key: "***" if key.lower() in {"authorization", "api-key", "x-api-key", "token"} else value
            for key, value in self.auth_headers.items()
        }
        return payload


class McpCapability(BaseModel):
    capability_id: str
    server_id: str
    name: str
    capability_type: McpCapabilityType
    description: str
    supported_scenarios: set[str] = Field(default_factory=set)
    required_roles: set[str] = Field(default_factory=set)
    required_permissions: set[str] = Field(default_factory=set)
    risk_level: McpRiskLevel
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    has_external_side_effects: bool = False
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("capability_id", "server_id", "name", "description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    @property
    def requires_human_confirmation(self) -> bool:
        return self.risk_level == McpRiskLevel.HIGH or self.has_external_side_effects


class McpCapabilitySelectionRequest(BaseModel):
    scenario: str
    role: str
    permissions: set[str] = Field(default_factory=set)
    capability_type: McpCapabilityType | None = None
    max_risk_level: McpRiskLevel = McpRiskLevel.LOW


class McpCapabilitySelectionResult(BaseModel):
    status: KnowledgeExtensionStatus
    selected_capabilities: list[McpCapability] = Field(default_factory=list)
    excluded_capabilities: dict[str, str] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
