from src.knowledge_extension.common.models import Citation
from src.knowledge_extension.extension_registry.in_memory import build_default_extension_registry
from src.knowledge_extension.extension_registry.models import ExtensionSelectionRequest


def test_public_citation_does_not_expose_internal_locator():
    citation = Citation(source_id="a1", source_type="policy", title="内部政策", version="1", evidence="依据", internal_locator="D:/secret/file.pdf")

    public = citation.to_public_dict()

    assert "internal_locator" not in public
    assert "D:/secret" not in str(public)


def test_high_risk_extension_is_not_selected_for_execution():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-refund-executor", role="medical_insurance_officer", scenario="settlement_exception"))

    assert result.status.value == "high_risk_blocked"
    assert result.extension is None
