import base64
import json

from fastapi.testclient import TestClient


SNAPSHOT_PATH = "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"


def _token(*, permissions: list[str]) -> str:
    payload = {
        "sub": "governance-reader",
        "roles": ["information_department"],
        "permissions": permissions,
        "exp": 4102444800,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"test.{encoded}.signature"


def test_model_governance_snapshot_requires_permission_and_returns_typed_envelope(
    monkeypatch,
):
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
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
    assert routes[("intent_recognition", "llm")]["explicit"] is False
    assert routes[("fee_explanation", "llm")]["explicit"] is True
    serialized = response.text
    assert "temporary-secret-key" not in serialized
    assert "user:password" not in serialized
    assert "/v1" not in serialized
    assert "q=1" not in serialized
    assert client.post(SNAPSHOT_PATH, headers=authorization).status_code == 405
