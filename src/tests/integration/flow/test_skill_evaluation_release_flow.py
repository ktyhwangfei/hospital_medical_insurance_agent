import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi.testclient import TestClient

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.governance_in_memory import (
    InMemorySkillGovernanceStorage,
)
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.skill.version_in_memory import (
    InMemorySkillVersionStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    get_skill_governance_service,
    get_skill_idempotency_store,
    get_skill_version_service,
)
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.runtime.skill_management.version_service import SkillVersionService
from src.skill_infra.skill_loader import get_loader


PREFIX = "/api/v1/medical-insurance-ai-agent"


def _workbench_item(client: TestClient, skill_id: str) -> dict[str, object]:
    response = client.get(
        f"{PREFIX}/infra-skills/workbench?query={quote(skill_id, safe='')}"
    )
    assert response.status_code == 200
    return next(item for item in response.json()["items"] if item["skill_id"] == skill_id)


def _control_token(
    user_id: str,
    roles: list[str],
    permissions: list[str] | None = None,
) -> str:
    payload = {
        "sub": user_id,
        "roles": roles,
        "permissions": permissions or ["skill:release:test"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.signature"


def test_fixed_suite_to_test_shadow_active_flow(monkeypatch) -> None:
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
    app = create_app()
    versions = InMemorySkillVersionStorage()
    governance = InMemorySkillGovernanceStorage()
    version_service = SkillVersionService(
        storage=versions,
        loader=get_loader(),
        skills_root=SKILLS_DIR,
        source_commit_resolver=lambda: "abc1234",
    )
    governance_service = SkillGovernanceService(
        storage=governance,
        version_storage=versions,
        loader=get_loader(),
    )
    app.dependency_overrides[get_skill_version_service] = lambda: version_service
    app.dependency_overrides[get_skill_governance_service] = lambda: governance_service
    idempotency_store = InMemoryCacheClient()
    app.dependency_overrides[get_skill_idempotency_store] = lambda: idempotency_store
    client = TestClient(app)

    catalog_item = client.get(f"{PREFIX}/infra-skills/catalog").json()["items"][0]
    skill_id = catalog_item["skill_id"]
    question = f"{catalog_item['include_keywords'][0]}怎么算"
    version = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/versions/sync",
        json={"created_by": "flow-developer"},
    ).json()
    assert _workbench_item(client, skill_id)["next_action"] == "run_evaluation"
    case_response = client.post(
        f"{PREFIX}/infra-skills/eval-cases",
        headers={
            "Authorization": f"Bearer {_control_token('flow-quality-user', ['quality'], ['skill:evaluate'])}"
        },
        json={
            "question_template": question,
            "expected_skill_id": skill_id,
            "required": True,
            "contains_sensitive_data": False,
        },
    )
    run_response = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/eval-runs",
        headers={
            "Authorization": f"Bearer {_control_token('flow-quality-user', ['quality'], ['skill:evaluate'])}"
        },
        json={
            "version_id": version["version_id"],
        },
    )

    assert case_response.status_code == 201
    assert run_response.status_code == 202
    assert run_response.json()["metrics"]["gate_passed"] is True
    assert _workbench_item(client, skill_id)["next_action"] == "create_candidate"

    candidate = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases",
        headers={
            "Idempotency-Key": "flow-candidate",
            "Authorization": f"Bearer {_control_token('flow-developer', ['developer'])}",
        },
        json={
            "version_id": version["version_id"],
            "eval_run_id": run_response.json()["run_id"],
            "environment": "test",
        },
    ).json()
    assert _workbench_item(client, skill_id)["next_action"] == "request_approval"
    pending = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{candidate['release_id']}/request-approval",
        headers={
            "Idempotency-Key": "flow-request",
            "Authorization": f"Bearer {_control_token('flow-developer', ['developer'])}",
        },
        json={"expected_revision": candidate["revision"]},
    ).json()
    assert _workbench_item(client, skill_id)["next_action"] == "review_approval"
    approved = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{candidate['release_id']}/approve",
        headers={
            "Idempotency-Key": "flow-approve",
            "Authorization": f"Bearer {_control_token('flow-information-admin', ['information_department'])}",
        },
        json={
            "expected_revision": pending["revision"],
            "reason": "固定评测通过",
        },
    ).json()
    assert _workbench_item(client, skill_id)["next_action"] == "activate_test_shadow"
    active_response = client.post(
        f"{PREFIX}/infra-skills/{skill_id}/releases/{candidate['release_id']}/activate",
        headers={
            "Idempotency-Key": "flow-activate",
            "Authorization": f"Bearer {_control_token('flow-developer', ['developer'])}",
        },
        json={"expected_revision": approved["revision"]},
    )

    assert active_response.status_code == 200
    active = active_response.json()
    assert active["status"] == "active"
    assert active["runtime_mode"] == "shadow"
    active_item = _workbench_item(client, skill_id)
    assert active_item["current_stage"] == "healthy"
    assert active_item["next_action"] == "view_evidence"
    assert governance_service.resolve_shadow(skill_id, "test").version_id == version[
        "version_id"
    ]
    releases = client.get(
        f"{PREFIX}/infra-skills/{skill_id}/releases?environment=test"
    ).json()["items"]
    assert sum(release["status"] == "active" for release in releases) == 1
