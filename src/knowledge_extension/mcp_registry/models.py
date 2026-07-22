"""MCP Registry domain models — runtime essentials kept after admin removal."""

from enum import StrEnum

from pydantic import BaseModel, Field


class McpRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class McpTransportType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class McpCapabilityType(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"
    SERVICE = "service"


class McpServer(BaseModel):
    server_id: str
    name: str = ""
    endpoint: str = ""
    transport: McpTransportType = McpTransportType.STDIO
    status: str = "enabled"
    auth_headers: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class McpCapability(BaseModel):
    capability_id: str
    server_id: str = ""
    capability_type: McpCapabilityType = McpCapabilityType.TOOL
    name: str = ""
    description: str = ""
    risk_level: McpRiskLevel = McpRiskLevel.LOW
    requires_human_confirmation: bool = False
    payload_json: dict | None = None


class McpCapabilitySelectionRequest(BaseModel):
    """MCP 能力选择请求 — 用于运行时场景执行。"""
    scenario: str = ""
    target_tool: str = ""
    risk_level: McpRiskLevel = McpRiskLevel.LOW
    filters: dict = Field(default_factory=dict)
