import pytest
from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import get_skill_version_service
from src.runtime.skill_management.version_service import SkillVersionService
from src.skill_infra.skill_loader import get_loader


PREFIX = "/api/v1/medical-insurance-ai-agent"

@pytest.fixture
def client():
    app = create_app()
    service = SkillVersionService(
        storage=InMemorySkillVersionStorage(),
        loader=get_loader(),
        skills_root=SKILLS_DIR,
        source_commit_resolver=lambda: "abc1234",
    )
    app.dependency_overrides[get_skill_version_service] = lambda: service
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


def test_catalog_is_paginated_without_breaking_legacy_list(client: TestClient) -> None:
    legacy = client.get(f"{PREFIX}/infra-skills")
    catalog = client.get(f"{PREFIX}/infra-skills/catalog?page=1&page_size=20")

    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert catalog.status_code == 200
    body = catalog.json()
    assert {"items", "page", "page_size", "total"}.issubset(body)
    assert body["items"]
    assert body["items"][0]["artifact_status"] == "unregistered"


def test_sync_and_read_version_evidence(client: TestClient) -> None:
    skill_id = client.get(f"{PREFIX}/infra-skills/catalog").json()["items"][0]["skill_id"]

    synced = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/versions/sync",
        json={"created_by": "tester"},
    )
    assert synced.status_code == 201

    versions = client.get(f"{PREFIX}/infra-skills/{skill_id}/versions")
    evidence = client.get(
        f"{PREFIX}/infra-skills/{skill_id}/versions/{synced.json()['version_id']}"
    )

    assert versions.status_code == 200
    assert evidence.status_code == 200
    assert versions.json()[0]["artifact_hash"] == synced.json()["artifact_hash"]
    assert evidence.json()["source_commit"] == "abc1234"


def test_sync_rejects_invalid_source_commit(client: TestClient) -> None:
    skill_id = client.get(f"{PREFIX}/infra-skills/catalog").json()["items"][0]["skill_id"]

    response = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/versions/sync",
        json={"source_commit": "not-a-git-sha", "created_by": "tester"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "SKILL_VERSION_INVALID"
