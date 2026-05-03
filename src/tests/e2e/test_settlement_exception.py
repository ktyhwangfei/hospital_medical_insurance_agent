from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_settlement_exception_guidance_returns_traceable_recommendation():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '患者 P001 本次医保结算失败，帮我看一下原因',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })
    assert response.status_code == 200
    body = response.json()
    assert body['scenario'] == 'settlement_exception_guidance'
    assert body['status'] == 'completed'
    assert body['result']['exception_type'] == '费用上传异常'
    assert body['result']['responsible_role'] == '收费员'
    assert {c['source_type'] for c in body['citations']} >= {'insurance_transaction', 'knowledge_error_code'}
