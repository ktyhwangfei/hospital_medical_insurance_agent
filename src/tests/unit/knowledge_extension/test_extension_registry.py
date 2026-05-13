from src.knowledge_extension.extension_registry.in_memory import build_default_extension_registry
from src.knowledge_extension.extension_registry.models import ExtensionSelectionRequest


def test_selects_available_extension_for_allowed_role():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-fee-analysis", role="medical_insurance_officer", scenario="settlement_exception"))

    assert result.status.value == "success"
    assert result.extension.extension_id == "tool-fee-analysis"


def test_denies_extension_for_wrong_role():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-fee-analysis", role="doctor", scenario="settlement_exception"))

    assert result.status.value == "permission_denied"
    assert result.audit_events


def test_blocks_high_risk_extension():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-refund-executor", role="medical_insurance_officer", scenario="settlement_exception"))

    assert result.status.value == "high_risk_blocked"
    assert "人工" in result.uncertainties[0]


def test_unhealthy_extension_degrades():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="mcp-disabled", role="admin", scenario="settlement_exception"))

    assert result.status.value == "unavailable"
