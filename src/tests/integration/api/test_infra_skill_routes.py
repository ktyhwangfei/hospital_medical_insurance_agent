import pytest
from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.data_platform.storage.skill.governance_in_memory import InMemorySkillGovernanceStorage
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    get_skill_governance_service,
    get_skill_version_service,
)
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.runtime.skill_management.version_service import SkillVersionService
from src.skill_infra.skill_loader import get_loader


PREFIX = "/api/v1/medical-insurance-ai-agent"

@pytest.fixture
def client():
    app = create_app()
    version_storage = InMemorySkillVersionStorage()
    service = SkillVersionService(
        storage=version_storage,
        loader=get_loader(),
        skills_root=SKILLS_DIR,
        source_commit_resolver=lambda: "abc1234",
    )
    app.dependency_overrides[get_skill_version_service] = lambda: service
    governance_service = SkillGovernanceService(
        storage=InMemorySkillGovernanceStorage(),
        version_storage=version_storage,
        loader=get_loader(),
    )
    app.dependency_overrides[get_skill_governance_service] = (
        lambda: governance_service
    )
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


def test_eval_and_manual_approval_are_required_for_test_activation(
    client: TestClient,
) -> None:
    catalog_item = client.get(f"{PREFIX}/infra-skills/catalog").json()["items"][0]
    skill_id = catalog_item["skill_id"]
    question = f"{catalog_item['include_keywords'][0]}怎么算"
    case = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        json={
            "question_template": question,
            "expected_skill_id": skill_id,
            "required": True,
            "risk_tags": [],
            "business_tags": ["settlement"],
            "source_type": "manual",
            "source_ref": "api-test",
            "contains_sensitive_data": False,
            "created_by": "quality-user",
        },
    )
    version = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/versions/sync",
        json={"created_by": "developer"},
    )
    run = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/eval-runs",
        json={
            "version_id": version.json()["version_id"],
            "created_by": "quality-user",
        },
    )

    assert case.status_code == 201
    assert version.status_code == 201
    assert run.status_code == 202
    assert run.json()["status"] == "passed"

    candidate = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases",
        headers={"Idempotency-Key": "candidate-api-test"},
        json={
            "version_id": version.json()["version_id"],
            "eval_run_id": run.json()["run_id"],
            "environment": "test",
            "created_by": "developer",
        },
    )
    assert candidate.status_code == 201
    release_id = candidate.json()["release_id"]

    blocked = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/activate",
        headers={"Idempotency-Key": "blocked-api-test"},
        json={"expected_revision": candidate.json()["revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["audit_event"]["gate_failures"] == [
        "manual_approval_required"
    ]

    pending = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/request-approval",
        headers={"Idempotency-Key": "request-api-test"},
        json={"expected_revision": candidate.json()["revision"]},
    )
    approved = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/approve",
        headers={"Idempotency-Key": "approve-api-test"},
        json={
            "expected_revision": pending.json()["revision"],
            "approved_by": "information-admin",
            "approver_role": "information_department",
            "reason": "固定评测通过",
        },
    )
    active = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/activate",
        headers={"Idempotency-Key": "activate-api-test"},
        json={"expected_revision": approved.json()["revision"]},
    )
    releases = client.get(
        f"{PREFIX}/infra-skills/{skill_id}/releases?environment=test"
    )

    assert pending.json()["status"] == "approval_pending"
    assert approved.json()["status"] == "approved"
    assert active.status_code == 200
    assert active.json()["status"] == "active"
    assert active.json()["runtime_mode"] == "shadow"
    assert sum(item["status"] == "active" for item in releases.json()["items"]) == 1


def test_sensitive_eval_case_is_rejected(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        json={
            "question_template": "患者张三的结算信息",
            "expected_skill_id": None,
            "contains_sensitive_data": True,
            "created_by": "quality-user",
        },
    )

    assert response.status_code == 422


def test_release_transition_rejects_missing_idempotency_key(
    client: TestClient,
) -> None:
    response = client.post(
        f"{PREFIX}/infra-skills/demo/releases/missing/request-approval",
        json={"expected_revision": 1},
    )

    assert response.status_code == 422
