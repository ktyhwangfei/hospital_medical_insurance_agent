from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapabilitySelectionRequest, McpCapabilitySelectionResult
from src.knowledge_extension.mcp_registry.ports import McpRegistry


class McpRuntimeIntegration:
    def __init__(self, registry: McpRegistry):
        self._registry = registry

    def select_for_step(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult:
        result = self._registry.select_capabilities(request)
        audit_events = [AuditSummary(event_type="mcp_runtime_selection", summary={"scenario": request.scenario, "role": request.role, "selected": [item.capability_id for item in result.selected_capabilities], "excluded": result.excluded_capabilities}), *result.audit_events]
        status = KnowledgeExtensionStatus.NO_HIT if result.status is KnowledgeExtensionStatus.HIGH_RISK_BLOCKED else result.status
        return result.model_copy(update={"status": status, "audit_events": audit_events}, deep=True)
