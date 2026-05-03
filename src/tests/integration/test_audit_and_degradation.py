from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_adapter_failure_returns_degraded_result_with_uncertainty():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P002 本次医保结算失败，帮我看一下原因', 'patient_id': 'P002', 'encounter_id': 'E002'
    })
    body = response.json()
    assert body['status'] == 'degraded'
    assert any('医保接口' in item for item in body['uncertainties'])
    assert body['audit']['steps']