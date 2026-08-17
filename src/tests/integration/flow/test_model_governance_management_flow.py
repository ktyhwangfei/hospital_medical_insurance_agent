import base64
import json

from fastapi.testclient import TestClient

from src.model_service.governance_service import ModelGovernanceService


PREFIX = "/api/v1/medical-insurance-ai-agent/model-governance"


def _headers(subject: str, permission: str) -> dict[str, str]:
    payload = {
        "sub": subject,
        "roles": ["information_department"],
        "permissions": [permission],
        "exp": 4102444800,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer test.{encoded}.signature"}


def _publish(client: TestClient, content: dict) -> dict:
    created = client.post(
        f"{PREFIX}/drafts",
        json={"content": content},
        headers=_headers("editor", "model_governance:write"),
    )
    assert created.status_code == 201
    draft = created.json()["result"]
    validated = client.post(
        f"{PREFIX}/drafts/{draft['draft_id']}/validate",
        json={"expected_revision": draft["revision"]},
        headers=_headers("editor", "model_governance:write"),
    ).json()["result"]
    pending = client.post(
        f"{PREFIX}/drafts/{draft['draft_id']}/request-review",
        json={"expected_revision": validated["revision"]},
        headers=_headers("editor", "model_governance:write"),
    ).json()["result"]
    approved = client.post(
        f"{PREFIX}/drafts/{draft['draft_id']}/approve",
        json={"expected_revision": pending["revision"], "reason": "流程审核通过"},
        headers=_headers("reviewer", "model_governance:review"),
    ).json()["result"]
    response = client.post(
        f"{PREFIX}/drafts/{draft['draft_id']}/publish",
        json={"expected_revision": approved["revision"], "environment": "dev"},
        headers=_headers("editor", "model_governance:publish"),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_model_governance_management_publish_snapshot_and_rollback(monkeypatch):
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv("MODEL_GOVERNANCE_ENV", "dev")
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_session",
        no_op_session,
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_audit",
        no_op_audit,
    )
    from src.runtime.api.app import create_app
    from src.runtime.api.model_governance_routes import get_model_governance_service
    from src.data_platform.storage.model_governance.factory import (
        get_model_governance_storage,
    )
    from src.runtime.intent.prompts import build_intent_prompt
    from src.runtime.intent.registry import get_intent_registry

    get_model_governance_storage.cache_clear()
    app = create_app()
    service = ModelGovernanceService(get_model_governance_storage())
    app.dependency_overrides[get_model_governance_service] = lambda: service
    client = TestClient(app)

    imported_response = client.post(
        f"{PREFIX}/import-current",
        headers=_headers("editor", "model_governance:write"),
    )
    assert imported_response.status_code == 201
    imported = imported_response.json()["result"]
    imported_prompt = next(
        item for item in imported["drafts"] if item["asset_id"] == "intent.classify"
    )
    edited_response = client.patch(
        f"{PREFIX}/drafts/{imported_prompt['draft_id']}",
        json={
            "expected_revision": imported_prompt["revision"],
            "content": {
                **imported_prompt["content"],
                "name": "意图分类（已纳管）",
            },
        },
        headers=_headers("editor", "model_governance:write"),
    )
    assert edited_response.status_code == 200
    assert edited_response.json()["result"]["revision"] == 2

    _publish(
        client,
        {
            "asset_type": "model_profile",
            "asset_id": "profile.flow",
            "name": "流程模型",
            "provider_id": "openai-compatible",
            "model_name": "flow-model",
            "credential_ref": "MODEL_API_KEY",
            "temperature": 0.1,
            "max_tokens": 4096,
            "enabled": True,
        },
    )
    _publish(
        client,
        {
            "asset_type": "route_rule",
            "asset_id": "route.flow",
            "name": "流程路由",
            "scene": "flow_scene",
            "profile_id": "profile.flow",
            "fallback_profile_ids": [],
        },
    )
    prompt = {
        "asset_type": "prompt",
        "asset_id": "prompt.flow",
        "name": "流程提示词",
        "scene": "flow_scene",
        "system_prompt": "只输出可追溯事实",
        "user_prompt_template": "问题：{question}",
        "variables": [{"name": "question"}],
    }
    first = _publish(client, prompt)
    second = _publish(client, {**prompt, "system_prompt": "只输出有引用的事实"})
    assert first["version_id"] != second["version_id"]

    governed_prompt = {
        "asset_type": "prompt",
        "asset_id": "intent.classify",
        "name": "意图分类",
        "scene": "intent_recognition",
        "system_prompt": "",
        "user_prompt_template": "FLOW_INTENT_V1 {message}",
        "variables": [{"name": "intents_text"}, {"name": "message"}],
    }
    old_intent = _publish(client, governed_prompt)
    new_intent = _publish(
        client,
        {**governed_prompt, "user_prompt_template": "FLOW_INTENT_V2 {message}"},
    )
    assert "FLOW_INTENT_V2" in build_intent_prompt("Q", get_intent_registry())

    intent_rollback = client.post(
        f"{PREFIX}/releases/{old_intent['release_id']}/rollback",
        headers=_headers("editor", "model_governance:publish"),
    )
    assert intent_rollback.status_code == 200
    assert "FLOW_INTENT_V1" in build_intent_prompt("Q", get_intent_registry())

    rollback = client.post(
        f"{PREFIX}/releases/{first['release_id']}/rollback",
        headers=_headers("editor", "model_governance:publish"),
    )
    assert rollback.status_code == 200
    assert rollback.json()["result"]["version_id"] == first["version_id"]

    snapshot = client.get(
        f"{PREFIX}/published-snapshot?environment=dev",
        headers=_headers("reader", "model_governance:read"),
    )
    assert snapshot.status_code == 200
    result = snapshot.json()["result"]
    assert {item["asset_type"] for item in result["assets"]} == {
        "prompt",
        "model_profile",
        "route_rule",
    }
    assert {item["runtime_status"] for item in result["assets"]} == {
        "not_connected"
    }
    active_prompt = next(
        item for item in result["assets"] if item["asset_id"] == "prompt.flow"
    )
    assert active_prompt["version_id"] == first["version_id"]
    get_model_governance_storage.cache_clear()
