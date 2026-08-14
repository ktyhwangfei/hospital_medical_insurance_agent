import os

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_test_environment_defaults_to_memory_storage():
    assert os.environ.get("USE_MEMORY_STORAGE") == "1"


def test_model_governance_snapshot_is_read_only_and_redacted(monkeypatch):
    async def no_op_session(self, *args):
        return None

    async def no_op_audit(self, **kwargs):
        return None

    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_session",
        no_op_session,
    )
    monkeypatch.setattr(
        "src.gateway.api_gateway.audit_middleware.GatewayAuditMiddleware._write_audit",
        no_op_audit,
    )
    monkeypatch.setenv("MODEL_API_KEY", "temporary-secret-key")
    monkeypatch.setenv(
        "MODEL_BASE_URL", "https://user:password@example.test:8443/v1?q=1"
    )

    client = TestClient(create_app())
    response = client.get(
        "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"prompts", "models", "routes", "providers", "citations", "uncertainties"}
    assert {prompt["prompt_id"] for prompt in payload["prompts"]} >= {
        "intent.classify",
        "policy.fact_extract",
    }
    routes = {(route["scene"], route["model_type"]): route for route in payload["routes"]}
    assert routes[("intent_recognition", "llm")]["explicit"] is False
    assert routes[("fee_explanation", "llm")]["explicit"] is True
    serialized = response.text
    assert "temporary-secret-key" not in serialized
    assert "user:password" not in serialized
    assert "/v1" not in serialized
    assert "q=1" not in serialized
    assert client.post(
        "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"
    ).status_code == 405
