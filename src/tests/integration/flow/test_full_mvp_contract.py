from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.runtime.api.schemas import AgentResponse


def test_all_mvp_contracts_pass_together():
    client = TestClient(create_app())
    openapi = client.get('/openapi.json').json()
    assert '/api/v1/medical-insurance-ai-agent/chat' in openapi['paths']

    settlement = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P001 本次医保结算失败', 'patient_id': 'P001', 'encounter_id': 'E001'
    }).json()
    assert settlement['status'] == 'completed'
    AgentResponse(**settlement)

    qc = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '检查患者 P001 出院前医保风险', 'patient_id': 'P001', 'encounter_id': 'E001'
    }).json()
    assert qc['tasks']
    AgentResponse(**qc)

    degraded = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P002 本次医保结算失败', 'patient_id': 'P002', 'encounter_id': 'E002'
    }).json()
    assert degraded['status'] == 'degraded'
    AgentResponse(**degraded)

    for body in (settlement, qc, degraded):
        assert set(body.keys()) == {'scenario', 'status', 'result', 'citations', 'tasks', 'missing_fields', 'uncertainties', 'blocked_actions', 'audit'}
