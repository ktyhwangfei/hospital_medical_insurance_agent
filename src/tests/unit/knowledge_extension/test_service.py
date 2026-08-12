from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service


def test_removed_facade_returns_no_hit_with_uncertainty():
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="医保结算异常错误码 E001", scenario="settlement_exception", role="medical_insurance_officer", patient_id="P001", rule_code="E001"))

    assert result.status.value == "no_hit"
    assert result.citations == []
    assert result.to_agent_payload()["uncertainties"]


def test_facade_no_evidence_returns_uncertainty():
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="完全不存在的知识", scenario="settlement_exception", role="doctor", patient_id="P001", rule_code="UNKNOWN"))

    assert result.uncertainties
    assert result.to_agent_payload()["uncertainties"]
