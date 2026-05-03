from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_permission_denied_for_clinician_settlement_exception():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-clinician-001', 'role': 'clinician', 'message': '患者 P001 医保结算失败', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    assert response.status_code == 403
    assert response.json()['detail']['error_code'] == 'PERMISSION_DENIED'


def test_high_risk_refund_and_reversal_are_blocked():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '请直接给患者 P001 执行退费冲正', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    body = response.json()
    assert body['status'] == 'waiting_human_confirmation'
    assert set(body['blocked_actions']) == {'退费', '冲正'}
    assert body['tasks'][0]['task_type'] == 'human_confirmation'