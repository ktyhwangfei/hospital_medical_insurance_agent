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

    @classmethod
    def _missing_(cls, value: object) -> "McpRiskLevel | None":
        """Case-insensitive lookup — accepts 'LOW', 'Medium', 'HIGH', etc."""
        if isinstance(value, str):
            value_lower = value.lower()
            for member in cls:
                if member.value == value_lower:
                    return member
        return None


class McpAuthType(StrEnum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BEARER = "bearer"


class McpDiscoverySource(StrEnum):
    AUTO_TOOLS_LIST = "auto_tools_list"
    MANUAL = "manual"
    EXTERNAL = "external"


class McpDiscoveryStatus(StrEnum):
    NOT_DISCOVERED = "not_discovered"
    DISCOVERED = "discovered"
    SUCCESS = "success"
    FAILED = "failed"


class McpServer(BaseModel):
    server_id: str
    name: str
    endpoint: str
    transport: McpTransportType
    status: McpServerStatus = McpServerStatus.DISABLED
    protocol_version: str | None = None
    auth_headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    connection_config: dict[str, Any] | None = None
    discovery_status: McpDiscoveryStatus = McpDiscoveryStatus.NOT_DISCOVERED
    last_error: str | None = None

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
    title: str | None = None
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
    annotations: dict[str, Any] = Field(default_factory=dict)
    invocation_config: dict[str, Any] = Field(default_factory=dict)
    discovery_source: str | None = Field(default=None, description="Source of discovery (auto_tools_list, manual, external)")
    discovery_payload: dict[str, Any] | None = Field(default=None)
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


class McpHandshakeResult(BaseModel):
    status: KnowledgeExtensionStatus
    protocol_version: str | None = None
    discovered_capabilities: list[McpCapability] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)


class McpToolInvocationResult(BaseModel):
    status: KnowledgeExtensionStatus
    output: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
