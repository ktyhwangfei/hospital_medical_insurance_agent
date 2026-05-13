from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


class TestSkillIntentMatching:
    def test_settlement_intent_matches_skill(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '结算失败怎么办',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['scenario'] == 'settlement_exception_guidance'

    def test_pre_discharge_intent_matches_skill(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'medical_office',
            'message': '出院前检查',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['scenario'] == 'pre_discharge_quality_control'

    def test_mcp_intent_matches_skill(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'information_department',
            'message': '画架构图',
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['scenario'] == 'mcp_tool_invocation' or data.get('audit', {}).get('matched_skill') == 'mcp_tool_invocation'

    def test_unauthorized_role_cannot_access_skill(self):
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
            'user_id': 'u1', 'role': 'cashier',
            'message': '出院前检查',
            'patient_id': 'P001', 'encounter_id': 'E001',
        })
        assert resp.status_code == 403

    def test_intent_matcher_keywords(self):
        from src.runtime.intent.skill_matcher import match_skill_by_intent
        from src.data_platform.storage.skill.factory import create_skill_storage
        from src.data_platform.storage.skill.seed import seed_default_skills

        skill_storage = create_skill_storage()
        seed_default_skills(skill_storage)

        result = match_skill_by_intent('结算失败怎么办', 'cashier', skill_storage)
        assert result is not None
        assert result.skill_id == 'settlement_exception_guidance'
        assert '结算失败' in result.matched_keywords

        result2 = match_skill_by_intent('这是什么', 'cashier', skill_storage)
        assert result2 is None