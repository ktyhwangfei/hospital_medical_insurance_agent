from src.data_platform.storage.mcp.ports import McpStorage
from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilitySelectionRequest,
    McpCapabilitySelectionResult,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
)


_RISK_ORDER = {McpRiskLevel.LOW: 1, McpRiskLevel.MEDIUM: 2, McpRiskLevel.HIGH: 3}
_NO_SELECTION_UNCERTAINTY = "未找到满足当前场景、角色、权限和风险约束的 MCP 能力"
_REASON_SERVER_MISSING = "server_missing"
_REASON_SERVER_UNAVAILABLE = "server_unavailable"
_REASON_CAPABILITY_DISABLED = "capability_disabled"
_REASON_TYPE_MISMATCH = "type_mismatch"
_REASON_SCENARIO_MISMATCH = "scenario_mismatch"
_REASON_ROLE_DENIED = "role_denied"
_REASON_PERMISSION_DENIED = "permission_denied"
_REASON_RISK_BLOCKED = "risk_blocked"
_AUTHORIZATION_EXCLUSION_REASONS = {_REASON_ROLE_DENIED, _REASON_PERMISSION_DENIED}


class McpRegistryService:
    def __init__(self, storage: McpStorage) -> None:
        self._storage = storage

    def register_server(self, server: McpServer) -> McpServer:
        self._storage.save_server(server)
        stored = self._storage.get_server(server.server_id)
        if stored is None:
            raise RuntimeError("MCP 服务注册失败")
        return stored

    def register_capability(self, capability: McpCapability) -> McpCapability:
        self._storage.save_capability(capability)
        stored = self._storage.get_capability(capability.capability_id)
        if stored is None:
            raise RuntimeError("MCP 能力注册失败")
        return stored

    def select_capabilities(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult:
        selected: list[McpCapability] = []
        excluded: dict[str, str] = {}
        for capability in self._storage.list_capabilities():
            server = self._storage.get_server(capability.server_id)
            reason = self._exclusion_reason(capability, server, request)
            if reason is None:
                selected.append(capability)
            else:
                excluded[capability.capability_id] = reason

        selected.sort(key=lambda item: item.capability_id)
        if selected:
            return McpCapabilitySelectionResult(
                status=KnowledgeExtensionStatus.SUCCESS,
                selected_capabilities=selected,
                excluded_capabilities=excluded,
                audit_events=[
                    AuditSummary(
                        event_type="mcp_capability_selected",
                        summary={
                            "selected": [item.capability_id for item in selected],
                            "excluded": excluded,
                        },
                    )
                ],
            )

        status = self._empty_selection_status(excluded)
        return McpCapabilitySelectionResult(
            status=status,
            excluded_capabilities=excluded,
            uncertainties=[_NO_SELECTION_UNCERTAINTY],
            audit_events=[
                AuditSummary(
                    event_type="mcp_capability_not_selected",
                    summary={"excluded": excluded},
                )
            ],
        )

    def _empty_selection_status(self, excluded: dict[str, str]) -> KnowledgeExtensionStatus:
        exclusion_reasons = set(excluded.values())
        if exclusion_reasons and exclusion_reasons.issubset(_AUTHORIZATION_EXCLUSION_REASONS):
            return KnowledgeExtensionStatus.PERMISSION_DENIED
        if exclusion_reasons == {_REASON_RISK_BLOCKED}:
            return KnowledgeExtensionStatus.HIGH_RISK_BLOCKED
        return KnowledgeExtensionStatus.NO_HIT

    def _exclusion_reason(
        self,
        capability: McpCapability,
        server: McpServer | None,
        request: McpCapabilitySelectionRequest,
    ) -> str | None:
        if server is None:
            return _REASON_SERVER_MISSING
        if server.status != McpServerStatus.ENABLED:
            return _REASON_SERVER_UNAVAILABLE
        if not capability.enabled:
            return _REASON_CAPABILITY_DISABLED
        if request.capability_type is not None and capability.capability_type != request.capability_type:
            return _REASON_TYPE_MISMATCH
        if capability.supported_scenarios and request.scenario not in capability.supported_scenarios:
            return _REASON_SCENARIO_MISMATCH
        if capability.required_roles and request.role not in capability.required_roles:
            return _REASON_ROLE_DENIED
        if not capability.required_permissions.issubset(request.permissions):
            return _REASON_PERMISSION_DENIED
        if capability.requires_human_confirmation or _RISK_ORDER[capability.risk_level] > _RISK_ORDER[request.max_risk_level]:
            return _REASON_RISK_BLOCKED
        return None
