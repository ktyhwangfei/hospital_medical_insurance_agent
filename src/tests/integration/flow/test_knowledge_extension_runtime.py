from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_settlement_exception_response_contains_knowledge_citations():
    client = TestClient(create_app())
    response = client.post("/api/v1/medical-insurance-ai-agent/chat", json={"user_id": "u001", "role": "medical_office", "message": "患者医保结算异常，错误码 E001", "patient_id": "P001", "encounter_id": "E001"})

    assert response.status_code == 200
    data = response.json()
    assert data["citations"] or data["uncertainties"]
    assert "audit" in data
    assert "knowledge_extension" in data["audit"]


def test_pre_discharge_qc_response_contains_rule_explanation_or_uncertainty():
    client = TestClient(create_app())
    response = client.post("/api/v1/medical-insurance-ai-agent/chat", json={"user_id": "u002", "role": "clinician", "message": "请做出院前联合质控，关注 DRG DIP 和病案风险", "patient_id": "P001", "encounter_id": "E001"})

    assert response.status_code == 200
    data = response.json()
    assert data["citations"] or data["uncertainties"]
    assert "knowledge_extension" in data["audit"]
