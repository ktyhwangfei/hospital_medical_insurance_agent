from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


class TestSkillMentionFlow:
    def test_mention_skill_and_execute(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '@settlement_exception_guidance 结算失败',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['scenario'] == 'settlement_exception_guidance'
        assert data['audit'].get('matched_skill') == 'settlement_exception_guidance'

    def test_mention_invalid_skill(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '@nonexistent_skill test',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'not_implemented'
        assert '未找到技能' in data['uncertainties'][0]

    def test_mention_skill_unauthorized_role(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'medical_record_staff',
            'message': '@settlement_exception_guidance test',
        })
        assert resp.status_code == 403

    def test_mention_skill_in_request_body(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '结算失败',
            'patient_id': 'P001', 'encounter_id': 'E001',
            'mentioned_skill_ids': ['settlement_exception_guidance'],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['audit'].get('matched_skill') == 'settlement_exception_guidance'

    def test_multiple_mentions_in_message(self):
        from src.runtime.skill_registry.parser import parse_message
        result = parse_message('@skill_a @skill_b test message')
        assert 'skill_a' in result.mentioned_skill_ids
        assert 'skill_b' in result.mentioned_skill_ids
        assert result.clean_message == 'test message'