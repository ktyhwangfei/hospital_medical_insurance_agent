import base64
import json

from fastapi.testclient import TestClient


SNAPSHOT_PATH = "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"


def _token(*, permissions: list[str], subject: str = "governance-reader") -> str:
    payload = {
        "sub": subject,
        "roles": ["information_department"],
        "permissions": permissions,
        "exp": 4102444800,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"test.{encoded}.signature"


def _headers(permission: str, *, subject: str = "editor") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(permissions=[permission], subject=subject)}"
    }


def _prompt_payload() -> dict:
    return {
        "content": {
            "asset_type": "prompt",
            "asset_id": "prompt.api-demo",
            "name": "API 演示提示词",
            "scene": "policy_qa",
            "system_prompt": "只输出可追溯事实",
            "user_prompt_template": "问题：{question}",
            "variables": [{"name": "question", "required": True}],
        }
    }


def _management_client(monkeypatch) -> TestClient:
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

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

    return TestClient(create_app())


def test_model_governance_snapshot_requires_permission_and_returns_typed_envelope(
    monkeypatch,
):
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.delenv("MODEL_GOVERNANCE_DEV_MODE", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "temporary-secret-key")
    monkeypatch.setenv(
        "MODEL_BASE_URL", "https://user:password@example.test:8443/v1?q=1"
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_session",
        no_op_session,
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_audit",
        no_op_audit,
    )

    from src.runtime.api.app import create_app

    client = TestClient(create_app())
    disabled = client.get(SNAPSHOT_PATH)
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["error_code"] == "MODEL_GOVERNANCE_DISABLED"
    assert "真实认证未接入" in disabled.json()["detail"]["message"]

    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "true")
    assert client.get(SNAPSHOT_PATH).status_code == 401
    forbidden = client.get(
        SNAPSHOT_PATH,
        headers={"Authorization": f"Bearer {_token(permissions=[])}"},
    )
    assert forbidden.status_code == 403

    authorization = {
        "Authorization": f"Bearer {_token(permissions=['model_governance:read'])}"
    }
    response = client.get(SNAPSHOT_PATH, headers=authorization)

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "model_governance"
    assert payload["status"] == "success"
    assert isinstance(payload["citations"], list)
    assert payload["uncertainties"] == payload["result"]["uncertainties"]
    assert set(payload["result"]) == {
        "prompts", "models", "routes", "providers", "citations", "uncertainties"
    }
    assert {prompt["prompt_id"] for prompt in payload["result"]["prompts"]} >= {
        "intent.classify",
        "policy.fact_extract",
    }
    routes = {
        (route["scene"], route["model_type"]): route
        for route in payload["result"]["routes"]
    }
    active_scenes = {
        "intent_recognition",
        "skill_routing",
        "policy_qa",
        "fee_explanation",
        "policy_fact_extraction",
    }
    assert active_scenes <= {
        scene
        for (scene, model_type), route in routes.items()
        if model_type == "llm" and route["explicit"] is True
    }
    serialized = response.text
    assert "temporary-secret-key" not in serialized
    assert "user:password" not in serialized
    assert "/v1" not in serialized
    assert "q=1" not in serialized
    assert client.post(SNAPSHOT_PATH, headers=authorization).status_code == 405


def test_governance_write_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_GOVERNANCE_DEV_MODE", raising=False)
    client = _management_client(monkeypatch)

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/model-governance/drafts",
        json=_prompt_payload(),
        headers=_headers("model_governance:write"),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "MODEL_GOVERNANCE_DISABLED"


def test_governance_rejects_missing_permission_and_stale_revision(monkeypatch):
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    client = _management_client(monkeypatch)
    path = "/api/v1/medical-insurance-ai-agent/model-governance/drafts"

    forbidden = client.post(
        path,
        json=_prompt_payload(),
        headers=_headers("model_governance:read"),
    )
    assert forbidden.status_code == 403

    missing_identity = client.post(
        path,
        json=_prompt_payload(),
        headers=_headers("model_governance:write", subject=""),
    )
    assert missing_identity.status_code == 401

    created_response = client.post(
        path,
        json=_prompt_payload(),
        headers=_headers("model_governance:write"),
    )
    assert created_response.status_code == 201
    created = created_response.json()["result"]
    update_body = {"content": created["content"], "expected_revision": 1}
    saved = client.patch(
        f"{path}/{created['draft_id']}",
        json=update_body,
        headers=_headers("model_governance:write"),
    )
    assert saved.status_code == 200
    assert saved.json()["result"]["revision"] == 2

    stale = client.patch(
        f"{path}/{created['draft_id']}",
        json=update_body,
        headers=_headers("model_governance:write"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error_code"] == "MODEL_GOVERNANCE_CONFLICT"
