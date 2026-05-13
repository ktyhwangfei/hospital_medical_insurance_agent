from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service


def test_facade_returns_deduped_citations_and_uncertainties():
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="医保结算异常错误码 E001", scenario="settlement_exception", role="medical_insurance_officer", patient_id="P001", rule_code="E001"))

    keys = [citation.dedupe_key() for citation in result.citations]
    assert result.status.value == "success"
    assert len(keys) == len(set(keys))
    assert result.to_agent_payload()["citations"]


def test_facade_no_evidence_returns_uncertainty():
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="完全不存在的知识", scenario="settlement_exception", role="doctor", patient_id="P001", rule_code="UNKNOWN"))

    assert result.uncertainties
    assert result.to_agent_payload()["uncertainties"]
