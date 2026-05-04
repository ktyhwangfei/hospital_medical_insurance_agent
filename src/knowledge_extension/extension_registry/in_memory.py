from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.extension_registry.models import ExtensionCapability, ExtensionHealth, ExtensionRiskLevel, ExtensionSelectionRequest, ExtensionSelectionResult, ExtensionType


class InMemoryExtensionRegistry:
    def __init__(self, extensions: list[ExtensionCapability]):
        self._extensions = {extension.extension_id: extension for extension in extensions}

    def select(self, request: ExtensionSelectionRequest) -> ExtensionSelectionResult:
        extension = self._extensions.get(request.extension_id)
        if extension is None:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.NO_HIT, uncertainties=["未找到扩展能力"], audit_events=[AuditSummary(event_type="extension_missing", summary=request.model_dump())])
        if not extension.enabled or extension.health is not ExtensionHealth.HEALTHY:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.UNAVAILABLE, uncertainties=["扩展能力不可用"], audit_events=[AuditSummary(event_type="extension_unavailable", summary={"extension_id": extension.extension_id})])
        if extension.scenarios and request.scenario not in extension.scenarios:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.PERMISSION_DENIED, uncertainties=["扩展能力不适用于当前场景"], audit_events=[AuditSummary(event_type="extension_scope_denied", summary={"extension_id": extension.extension_id})])
        if extension.required_roles and request.role not in extension.required_roles:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.PERMISSION_DENIED, uncertainties=["当前角色无权使用该扩展能力"], audit_events=[AuditSummary(event_type="extension_permission_denied", summary={"extension_id": extension.extension_id})])
        if extension.risk_level is ExtensionRiskLevel.HIGH or extension.high_risk_actions:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.HIGH_RISK_BLOCKED, uncertainties=["扩展能力涉及高风险动作，必须转人工确认"], audit_events=[AuditSummary(event_type="extension_high_risk_blocked", summary={"extension_id": extension.extension_id})])
        return ExtensionSelectionResult(status=KnowledgeExtensionStatus.SUCCESS, extension=extension.model_copy(deep=True), audit_events=[AuditSummary(event_type="extension_selected", summary={"extension_id": extension.extension_id})])


def build_default_extension_registry() -> InMemoryExtensionRegistry:
    return InMemoryExtensionRegistry([
        ExtensionCapability(extension_id="tool-fee-analysis", extension_type=ExtensionType.TOOL, name="费用明细分析", description="分析费用明细", scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer", "admin"}, risk_level=ExtensionRiskLevel.LOW, health=ExtensionHealth.HEALTHY),
        ExtensionCapability(extension_id="tool-refund-executor", extension_type=ExtensionType.TOOL, name="退费执行", description="高风险退费执行", scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, risk_level=ExtensionRiskLevel.HIGH, health=ExtensionHealth.HEALTHY, high_risk_actions={"refund"}),
        ExtensionCapability(extension_id="mcp-disabled", extension_type=ExtensionType.MCP, name="不可用 MCP", description="健康检查失败", scenarios={"settlement_exception"}, required_roles={"admin"}, risk_level=ExtensionRiskLevel.LOW, health=ExtensionHealth.UNHEALTHY),
    ])
