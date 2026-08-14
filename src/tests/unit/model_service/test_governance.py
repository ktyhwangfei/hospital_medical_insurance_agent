import json

from src.config.model_service import ModelServiceConfig
from src.config.model_routing import MODEL_PARAMS, ROUTING_TABLE
from src.model_service.governance import build_governance_snapshot


def test_snapshot_has_complete_prompt_assets_and_stable_config_projection():
    snapshot = build_governance_snapshot(ModelServiceConfig(base_url="https://user:secret@example.test:8443/v1/path?q=1", api_key="top-secret"))
    assert {item.prompt_id for item in snapshot.prompts} == {
        "intent.classify", "intent.discriminate", "skill.route",
        "policy_qa.intent_detect", "policy_qa.patient_explain",
        "policy.extract.schema", "policy.extract.legacy", "policy.fact_extract",
        "policy.synonym_discovery", "policy.domain_discovery", "skill.settlement_explain",
    }
    assert snapshot.providers[0].endpoint == "https://example.test:8443"
    dumped = json.dumps(snapshot.model_dump(), ensure_ascii=False)
    assert "top-secret" not in dumped and "secret" not in dumped
    projected = {model.model_name: model for model in snapshot.models}
    assert set(projected) >= set(MODEL_PARAMS)
    for model_name, params in MODEL_PARAMS.items():
        assert projected[model_name].temperature == params["temperature"]
        assert projected[model_name].max_tokens == params["max_tokens"]


def test_implicit_and_explicit_routes_are_distinguished_without_direct_fabrication():
    snapshot = build_governance_snapshot()
    intent = next(route for route in snapshot.routes if route.scene == "intent_recognition")
    assert intent.explicit is False
    assert any("default" in warning for warning in intent.warnings)
    fee = next(route for route in snapshot.routes if route.scene == "fee_explanation")
    assert fee.explicit is True
    assert fee.effective_model == "deepseek-chat"
    direct = next(prompt for prompt in snapshot.prompts if prompt.prompt_id == "policy.fact_extract")
    assert direct.gateway_status == "direct"
    assert direct.scene is None
    expected_route_keys = set(ROUTING_TABLE)
    expected_route_keys.update(
        (prompt.scene, prompt.model_type)
        for prompt in snapshot.prompts
        if prompt.gateway_status == "routed" and prompt.scene
    )
    assert {(route.scene, route.model_type) for route in snapshot.routes} == expected_route_keys
    assert any("遗留" in uncertainty for uncertainty in snapshot.uncertainties)
