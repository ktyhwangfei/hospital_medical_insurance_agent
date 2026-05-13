from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


class TestSkillRoleAccess:
    def test_list_skills_by_role_cashier(self):
        client = _client()
        resp = client.get('/api/v1/medical-insurance-ai-agent/skills/by-role/cashier')
        assert resp.status_code == 200
        skills = resp.json()
        assert len(skills) > 0
        for skill in skills:
            assert skill['owner'] == 'cashier' or 'cashier' in skill['required_roles']

    def test_list_skills_by_role_medical_office(self):
        client = _client()
        resp = client.get('/api/v1/medical-insurance-ai-agent/skills/by-role/medical_office')
        assert resp.status_code == 200
        skills = resp.json()
        assert len(skills) > 0

    def test_create_and_delete_skill(self):
        client = _client()
        create_resp = client.post('/api/v1/medical-insurance-ai-agent/skills', json={
            'skill_id': 'test-skill-001',
            'name': '测试技能',
            'description': '用于测试的技能',
            'owner': 'cashier',
            'steps': [{'step_id': 's1', 'tool_id': 'query_transaction'}],
            'execution_strategy': 'sequential',
            'intent_keywords': ['测试'],
            'required_roles': ['cashier'],
        })
        assert create_resp.status_code == 200
        data = create_resp.json()
        assert data['skill_id'] == 'test-skill-001'

        get_resp = client.get('/api/v1/medical-insurance-ai-agent/skills/test-skill-001')
        assert get_resp.status_code == 200

        delete_resp = client.delete('/api/v1/medical-insurance-ai-agent/skills/test-skill-001')
        assert delete_resp.status_code == 200

    def test_create_skill_with_nonexistent_tool(self):
        """Skill creation no longer validates tool existence (tools table removed)."""
        client = _client()
        resp = client.post('/api/v1/medical-insurance-ai-agent/skills', json={
            'skill_id': 'test-skill-bad',
            'name': 'Bad Skill',
            'description': 'References nonexistent tool (tools table removed, skipped)',
            'owner': 'cashier',
            'steps': [{'step_id': 's1', 'tool_id': 'nonexistent_tool'}],
            'execution_strategy': 'sequential',
        })
        assert resp.status_code == 200

    def test_get_nonexistent_skill_returns_404(self):
        client = _client()
        resp = client.get('/api/v1/medical-insurance-ai-agent/skills/nonexistent')
        assert resp.status_code == 404

