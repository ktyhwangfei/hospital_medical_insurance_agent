from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_patient_context_uses_minimum_fields_and_masks_name():
    client = TestClient(create_app())
    response = client.get('/api/v1/medical-insurance-ai-agent/patient-context/P001/E001', params={'user_id': 'u1', 'role': 'cashier'})
    assert response.status_code == 200
    body = response.json()
    assert body['patient']['name'] == '张**'
    assert set(body['visible_fields']) == {'patient_id', 'encounter_id', 'settlement_status'}
    assert 'audit_risks' not in body


def test_medical_office_context_can_include_audit_risks():
    client = TestClient(create_app())
    response = client.get('/api/v1/medical-insurance-ai-agent/patient-context/P001/E001', params={'user_id': 'u1', 'role': 'medical_office'})
    assert response.status_code == 200
    body = response.json()
    assert 'audit_risks' in body['visible_fields']
    assert body['audit_risks'] == []


def test_missing_patient_context_returns_clarification():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={'user_id': 'u1', 'role': 'cashier', 'message': '医保结算失败了，帮我看看'})
    assert response.status_code == 200
    assert response.json()['status'] == 'needs_clarification'
    assert response.json()['missing_fields'] == ['patient_id', 'encounter_id']
