from enum import StrEnum

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus


class ExtensionType(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    MCP = "mcp"
    A2A = "a2a"


class ExtensionRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExtensionHealth(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ExtensionCapability(BaseModel):
    extension_id: str
    extension_type: ExtensionType
    name: str
    description: str
    scenarios: set[str] = Field(default_factory=set)
    required_roles: set[str] = Field(default_factory=set)
    risk_level: ExtensionRiskLevel
    health: ExtensionHealth
    enabled: bool = True
    high_risk_actions: set[str] = Field(default_factory=set)


class ExtensionSelectionRequest(BaseModel):
    extension_id: str
    role: str
    scenario: str


class ExtensionSelectionResult(BaseModel):
    status: KnowledgeExtensionStatus
    extension: ExtensionCapability | None = None
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
