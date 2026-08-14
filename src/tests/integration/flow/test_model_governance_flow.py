import base64
import json

from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.model_service.gateway import ModelGateway
from src.model_service.models import ModelResponse, TokenUsage
from src.semantic_layer.extraction_contract import ExtractionSchema, FieldContract


SNAPSHOT_PATH = "/api/v1/medical-insurance-ai-agent/model-governance/snapshot"


def _authorization() -> dict[str, str]:
    payload = {
        "sub": "governance-flow-reader",
        "roles": ["information_department"],
        "permissions": ["model_governance:read"],
        "exp": 4102444800,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer test.{encoded}.signature"}


def test_model_governance_snapshot_drives_gateway_route(monkeypatch):
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
    monkeypatch.setattr("src.model_service.gateway._record_llm_event", lambda **kwargs: None)
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.setenv("MODEL_GOVERNANCE_DEV_MODE", "1")
    monkeypatch.setenv("MODEL_API_KEY", "governance-test-key")
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.test/v1")

    from src.runtime.api.app import create_app

    client = TestClient(create_app())
    response = client.get(SNAPSHOT_PATH, headers=_authorization())
    assert response.status_code == 200
    snapshot = response.json()["result"]

    prompt = next(
        prompt
        for prompt in snapshot["prompts"]
        if prompt["prompt_id"] == "policy.extract.schema"
    )
    extraction_route = next(
        route
        for route in snapshot["routes"]
        if route["scene"] == prompt["scene"] and route["model_type"] == prompt["model_type"]
    )
    model_profile = next(
        model
        for model in snapshot["models"]
        if model["model_name"] == extraction_route["effective_model"]
    )

    captured = {}

    def fake_call_provider(self, request, model_name):
        captured["request"] = request
        captured["model_name"] = model_name
        return ModelResponse(
            content='[{"fact_text":"测试政策事实","rules":[]}]',
            model_name=model_name,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            finish_reason="stop",
        )

    monkeypatch.setattr(ModelGateway, "_call_provider", fake_call_provider)
    monkeypatch.setattr(
        "src.semantic_layer.extraction_contract.build_extraction_schema",
        lambda *_args, **_kwargs: ExtractionSchema(
            fields=[FieldContract(code="rule_type", name="规则类型")]
        ),
    )

    facts = PipelineOrchestrator()._extract_policy_facts(
        "参保人员符合条件时享受医保待遇。",
        document_title="测试医保政策",
    )

    assert facts == [{"fact_text": "测试政策事实", "rules": []}]
    assert extraction_route["model_type"] == prompt["model_type"] == "llm"
    assert captured["model_name"] == extraction_route["effective_model"]
    assert captured["request"].model_type == extraction_route["effective_model"]
    assert captured["request"].scene == prompt["scene"] == "policy_fact_extraction"
    assert captured["request"].temperature == model_profile["temperature"]
    assert captured["request"].temperature == prompt["effective_parameters"]["temperature"]
    assert (
        captured["request"].max_tokens
        == prompt["call_overrides"]["max_tokens"]
        == prompt["effective_parameters"]["max_tokens"]
    )
