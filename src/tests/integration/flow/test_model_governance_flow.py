from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


SNAPSHOT_PATH = "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"


def test_model_governance_read_only_flow(monkeypatch):
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
    monkeypatch.setenv("MODEL_API_KEY", "temporary-governance-secret")
    monkeypatch.setenv(
        "MODEL_BASE_URL", "https://user:password@example.test:8443/v1/path?q=1"
    )

    client = TestClient(create_app())
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    first = client.get(SNAPSHOT_PATH)
    second = client.get(SNAPSHOT_PATH)
    assert first.status_code == second.status_code == 200
    snapshot = first.json()
    assert snapshot == second.json()

    routes = {(route["scene"], route["model_type"]): route for route in snapshot["routes"]}
    model_names = {model["model_name"] for model in snapshot["models"]}
    for prompt in snapshot["prompts"]:
        if prompt["gateway_status"] == "routed" and prompt["scene"]:
            assert (prompt["scene"], prompt["model_type"]) in routes

    for route in snapshot["routes"]:
        if route["effective_model"]:
            assert route["effective_model"] in model_names

    direct_prompts = [
        prompt for prompt in snapshot["prompts"] if prompt["gateway_status"] == "direct"
    ]
    assert direct_prompts
    for prompt in direct_prompts:
        assert any("绕过统一网关" in warning for warning in prompt["warnings"])
        assert prompt["scene"] is None
        assert not any(route["scene"] == prompt["scene"] for route in snapshot["routes"])

    serialized = first.text
    assert "temporary-governance-secret" not in serialized
    for provider in snapshot["providers"]:
        endpoint = urlsplit(provider["endpoint"])
        assert endpoint.username is None
        assert endpoint.password is None
        assert endpoint.path == ""
        assert endpoint.query == ""

    assert snapshot["citations"]
    assert snapshot["uncertainties"]
