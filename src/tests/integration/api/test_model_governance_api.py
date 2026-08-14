from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_model_governance_snapshot_is_read_only_and_redacted(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "temporary-secret-key")
    monkeypatch.setenv(
        "MODEL_BASE_URL", "https://user:password@example.test:8443/v1?q=1"
    )

    response = TestClient(create_app()).get(
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
    assert TestClient(create_app()).post(
        "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"
    ).status_code == 405
