from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


class TestE2ELangGraph:
    def test_settlement_normal_flow(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '结算失败E001，请帮我看看',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['scenario'] == 'settlement_exception_guidance'
        assert data['status'] == 'completed'

    def test_pre_discharge_normal_flow(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'medical_office',
            'message': '出院前检查',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['scenario'] == 'pre_discharge_quality_control'
        assert data['status'] == 'completed'

    def test_high_risk_triggers_confirmation(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '退费操作 E001',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'waiting_human_confirmation'
        assert data['blocked_actions']

    def test_confirm_high_risk_task(self):
        client = _client()
        chat_resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '退费操作 E001',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        task_id = chat_resp.json()['tasks'][0]['task_id']

        confirm_resp = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
            'task_id': task_id,
            'action': 'confirm',
            'user_id': 'u1',
        })
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()['status'] == 'confirmed'

    def test_reject_high_risk_task(self):
        client = _client()
        chat_resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '退费操作 E001',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        task_id = chat_resp.json()['tasks'][0]['task_id']

        reject_resp = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
            'task_id': task_id,
            'action': 'reject',
            'user_id': 'u1',
        })
        assert reject_resp.status_code == 200
        assert reject_resp.json()['status'] == 'rejected'

    def test_mention_skill_flow(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '@settlement_exception_guidance 结算失败',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['audit'].get('matched_skill') == 'settlement_exception_guidance'

    def test_invalid_mention_flow(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '@nonexistent_skill test',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'not_implemented'
        assert data['uncertainties']

    def test_agent_response_shape(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '结算失败E001',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        required_keys = {'scenario', 'status', 'result', 'citations', 'tasks',
                         'missing_fields', 'uncertainties', 'blocked_actions', 'audit'}
        assert required_keys.issubset(data.keys())
