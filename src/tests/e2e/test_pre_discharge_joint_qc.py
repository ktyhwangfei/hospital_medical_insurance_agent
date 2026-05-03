from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_pre_discharge_quality_control_creates_tasks_with_citations():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '帮我检查患者 P001 出院前医保风险', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    body = response.json()
    assert body['scenario'] == 'pre_discharge_quality_control'
    assert body['status'] == 'completed'
    risk_types = {risk['risk_type'] for risk in body['result']['risks']}
    assert risk_types >= {'合规拒付风险', 'DRG/DIP 支付风险', '病案首页风险'}
    assert body['tasks']
    assert all(task['status'] == 'pending' for task in body['tasks'])
    assert body['citations']