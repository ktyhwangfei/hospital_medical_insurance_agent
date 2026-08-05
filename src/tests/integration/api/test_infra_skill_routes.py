import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.data_platform.storage.skill.governance_in_memory import InMemorySkillGovernanceStorage
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    _idempotent_release_mutation,
    get_skill_control_principal,
    get_skill_evaluation_principal,
    get_skill_governance_service,
    get_skill_idempotency_store,
    get_skill_version_service,
)
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.domain.skill.governance_models import SkillRelease, SkillReleaseStatus
from src.runtime.skill_management.version_service import SkillVersionService
from src.skill_infra.skill_loader import get_loader


PREFIX = "/api/v1/medical-insurance-ai-agent"


def _control_token(
    user_id: str = "information-admin",
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
) -> str:
    payload = {
        "sub": user_id,
        "roles": roles or ["information_department"],
        "permissions": permissions or ["skill:release:test"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.signature"


def test_idempotent_mutation_recovers_after_result_cache_failure() -> None:
    class _FailingCompleteStore(InMemoryCacheClient):
        def complete(self, key, value, ttl_seconds):
            raise RuntimeError("cache write failed")

    store = _FailingCompleteStore()
    release = SkillRelease(
        release_id="recovered-release",
        skill_id="demo-skill",
        version_id="version-1",
        environment="test",
        status=SkillReleaseStatus.CANDIDATE,
        eval_run_id="run-1",
        artifact_hash="a" * 64,
        config_hash="b" * 64,
        created_by="developer",
    )
    calls = 0
    persisted: SkillRelease | None = None

    def operation() -> SkillRelease:
        nonlocal calls, persisted
        calls += 1
        persisted = release
        return release

    first = _idempotent_release_mutation(
        store=store,
        scope="demo:candidate",
        idempotency_key="stable-key",
        request_payload={"version_id": "version-1"},
        operation=operation,
        recovery=lambda: persisted,
    )
    second = _idempotent_release_mutation(
        store=store,
        scope="demo:candidate",
        idempotency_key="stable-key",
        request_payload={"version_id": "version-1"},
        operation=operation,
        recovery=lambda: persisted,
    )

    assert first.release_id == second.release_id == "recovered-release"
    assert calls == 1

    with pytest.raises(HTTPException) as exc_info:
        _idempotent_release_mutation(
            store=store,
            scope="demo:candidate",
            idempotency_key="stable-key",
            request_payload={"version_id": "different-version"},
            operation=operation,
            recovery=lambda: persisted,
        )
    assert exc_info.value.status_code == 409


def test_skill_release_controls_are_disabled_without_explicit_dev_mode(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SKILL_CONTROL_DEV_MODE", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_skill_control_principal(f"Bearer {_control_token()}")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == "SKILL_CONTROL_DISABLED"

    with pytest.raises(HTTPException) as eval_exc_info:
        get_skill_evaluation_principal(f"Bearer {_control_token()}")
    assert eval_exc_info.value.status_code == 403


def test_skill_evaluation_rejects_missing_permission(monkeypatch) -> None:
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")

    with pytest.raises(HTTPException) as exc_info:
        get_skill_evaluation_principal(
            f"Bearer {_control_token('developer', ['developer'])}"
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error_code"] == "SKILL_CONTROL_FORBIDDEN"

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
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
    idempotency_store = InMemoryCacheClient()
    app.dependency_overrides[get_skill_idempotency_store] = lambda: idempotency_store
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
        headers={
            "Authorization": f"Bearer {_control_token('quality-user', ['quality'], ['skill:evaluate'])}"
        },
        json={
            "question_template": question,
            "expected_skill_id": skill_id,
            "required": True,
            "risk_tags": [],
            "business_tags": ["settlement"],
            "source_type": "manual",
            "source_ref": "api-test",
            "contains_sensitive_data": False,
        },
    )
    version = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/versions/sync",
        json={"created_by": "developer"},
    )
    run = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/eval-runs",
        headers={
            "Authorization": f"Bearer {_control_token('quality-user', ['quality'], ['skill:evaluate'])}"
        },
        json={
            "version_id": version.json()["version_id"],
        },
    )

    assert case.status_code == 201
    assert case.json()["created_by"] == "quality-user"
    assert version.status_code == 201
    assert run.status_code == 202
    assert run.json()["created_by"] == "quality-user"
    assert run.json()["status"] == "passed"

    candidate = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases",
        headers={
            "Idempotency-Key": "candidate-api-test",
            "Authorization": f"Bearer {_control_token('developer', ['developer'])}",
        },
        json={
            "version_id": version.json()["version_id"],
            "eval_run_id": run.json()["run_id"],
            "environment": "test",
        },
    )
    assert candidate.status_code == 201
    assert candidate.json()["created_by"] == "developer"
    release_id = candidate.json()["release_id"]
    duplicate_candidate = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases",
        headers={
            "Idempotency-Key": "candidate-api-test",
            "Authorization": f"Bearer {_control_token('developer', ['developer'])}",
        },
        json={
            "version_id": version.json()["version_id"],
            "eval_run_id": run.json()["run_id"],
            "environment": "test",
        },
    )
    assert duplicate_candidate.status_code == 201
    assert duplicate_candidate.json()["release_id"] == release_id

    blocked = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/activate",
        headers={
            "Idempotency-Key": "blocked-api-test",
            "Authorization": f"Bearer {_control_token('developer', ['developer'])}",
        },
        json={"expected_revision": candidate.json()["revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["audit_event"]["gate_failures"] == [
        "manual_approval_required"
    ]

    pending = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/request-approval",
        headers={
            "Idempotency-Key": "request-api-test",
            "Authorization": f"Bearer {_control_token('developer', ['developer'])}",
        },
        json={"expected_revision": candidate.json()["revision"]},
    )
    unauthenticated = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/approve",
        headers={"Idempotency-Key": "approve-without-auth-api-test"},
        json={
            "expected_revision": pending.json()["revision"],
            "reason": "固定评测通过",
        },
    )
    assert unauthenticated.status_code == 401

    approved = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/approve",
        headers={
            "Idempotency-Key": "approve-api-test",
            "Authorization": f"Bearer {_control_token()}",
        },
        json={
            "expected_revision": pending.json()["revision"],
            "reason": "固定评测通过",
        },
    )
    active = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{release_id}/activate",
        headers={
            "Idempotency-Key": "activate-api-test",
            "Authorization": f"Bearer {_control_token('developer', ['developer'])}",
        },
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
    active_item = next(
        item for item in releases.json()["items"] if item["status"] == "active"
    )
    assert active_item["approval"]["approved_by"] == "information-admin"
    assert active_item["approval"]["approver_role"] == "information_department"
    assert "reason" not in active_item["approval"]


def test_sensitive_eval_case_is_rejected(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        headers={
            "Authorization": f"Bearer {_control_token('quality-user', ['quality'], ['skill:evaluate'])}"
        },
        json={
            "question_template": "患者张三的结算信息",
            "expected_skill_id": None,
            "contains_sensitive_data": True,
        },
    )

    assert response.status_code == 422


def test_sensitive_eval_case_content_is_rejected_by_server_detector(
    client: TestClient,
) -> None:
    response = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        headers={
            "Authorization": f"Bearer {_control_token('quality-user', ['quality'], ['skill:evaluate'])}"
        },
        json={
            "question_template": "查询身份证号 11010519491231002X 的待遇",
            "expected_skill_id": None,
            "contains_sensitive_data": False,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["audit_event"]["gate_failures"] == [
        "sensitive_data_detected"
    ]


def test_release_transition_rejects_missing_idempotency_key(
    client: TestClient,
) -> None:
    response = client.post(
        f"{PREFIX}/infra-skills/demo/releases/missing/request-approval",
        headers={"Authorization": f"Bearer {_control_token('developer', ['developer'])}"},
        json={"expected_revision": 1},
    )

    assert response.status_code == 422
