from typing import Any

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpHandshakeResult,
    McpServer,
    McpToolInvocationResult,
)


class InMemoryMcpClientGateway:
    def __init__(
        self,
        discovered_capabilities: list[McpCapability] | None = None,
        tool_results: dict[str, dict[str, Any]] | None = None,
    ):
        self._discovered_capabilities = [item.model_copy(deep=True) for item in discovered_capabilities or []]
        self._tool_results = tool_results or {}

    def handshake(self, server: McpServer) -> McpHandshakeResult:
        return McpHandshakeResult(
            status=KnowledgeExtensionStatus.SUCCESS,
            protocol_version=server.protocol_version or "2025-03-26",
            discovered_capabilities=[item.model_copy(deep=True) for item in self._discovered_capabilities],
            audit_events=[AuditSummary(event_type="mcp_handshake_success", summary={"server_id": server.server_id})],
        )

    def invoke_tool(
        self,
        server: McpServer,
        capability: McpCapability,
        arguments: dict[str, Any],
    ) -> McpToolInvocationResult:
        if capability.requires_human_confirmation:
            return McpToolInvocationResult(
                status=KnowledgeExtensionStatus.HIGH_RISK_BLOCKED,
                uncertainties=["MCP 能力涉及高风险动作，必须转人工确认"],
                audit_events=[
                    AuditSummary(
                        event_type="mcp_tool_high_risk_blocked",
                        summary={"server_id": server.server_id, "capability_id": capability.capability_id},
                    )
                ],
            )
        return McpToolInvocationResult(
            status=KnowledgeExtensionStatus.SUCCESS,
            output=self._tool_results.get(capability.capability_id, {}).copy(),
            audit_events=[
                AuditSummary(
                    event_type="mcp_tool_invoked",
                    summary={
                        "server_id": server.server_id,
                        "capability_id": capability.capability_id,
                        "argument_keys": sorted(arguments),
                    },
                )
            ],
        )
