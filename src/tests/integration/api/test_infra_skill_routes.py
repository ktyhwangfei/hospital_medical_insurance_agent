import pytest
from fastapi.testclient import TestClient
from src.runtime.api.app import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

def test_list_infra_skills(client):
    response = client.get("/api/v1/medical-insurance-ai-agent/infra-skills")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        skill = data[0]
        assert "skill_id" in skill
        assert "skill_name" in skill
        assert "include_keywords" in skill
        assert "excluded_intents" in skill

def test_get_infra_skill_details(client):
    # 先获取列表拿到一个存在的 skill_id
    list_response = client.get("/api/v1/medical-insurance-ai-agent/infra-skills")
    skills = list_response.json()
    if not skills:
        pytest.skip("No infra skills found to test details")
        
    skill_id = skills[0]["skill_id"]
    response = client.get(f"/api/v1/medical-insurance-ai-agent/infra-skills/{skill_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["skill_id"] == skill_id
    assert "manifest" in data
    assert "files_structure" in data
    assert "readme" in data

def test_test_infra_skill_routing(client):
    payload = {
        "question": "我的统筹自付为什么这么多？"
    }
    response = client.post("/api/v1/medical-insurance-ai-agent/infra-skills/route-test", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["question"] == payload["question"]
    # 可能会匹配到 settlement_explain_skill 或者 None，不强求，但字段必须存在
    assert "matched_skill_id" in data

def test_test_infra_skill_execution_not_found(client):
    payload = {
        "question": "测试"
    }
    response = client.post("/api/v1/medical-insurance-ai-agent/infra-skills/non_existent_skill_123/test", json=payload)
    assert response.status_code == 404
