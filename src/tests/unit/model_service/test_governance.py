import json
from pathlib import Path

from src.config.model_service import ModelServiceConfig
from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE
from src.model_service.governance import build_governance_snapshot
from src.model_service.router import ModelRouter


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
    for prompt in snapshot.prompts:
        assert Path(prompt.source_path).is_file()
        for related_source_path in prompt.related_source_paths:
            assert Path(related_source_path).is_file()


def test_active_routes_are_explicit_without_direct_fabrication():
    snapshot = build_governance_snapshot()
    routes = {(route.scene, route.model_type): route for route in snapshot.routes}
    for scene in {
        "intent_recognition",
        "skill_routing",
        "policy_qa",
        "fee_explanation",
        "policy_fact_extraction",
    }:
        route = routes[(scene, "llm")]
        assert route.explicit is True
        assert route.effective_model == "deepseek-chat"
        assert not any("default" in warning for warning in route.warnings)

    prompts = {prompt.prompt_id: prompt for prompt in snapshot.prompts}
    assert prompts["policy.extract.schema"].scene == "policy_fact_extraction"
    assert prompts["policy.extract.legacy"].scene == "policy_fact_extraction"
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
    assert any(
        "生产认证未接入" in uncertainty and "默认关闭" in uncertainty
        for uncertainty in snapshot.uncertainties
    )


def test_fallback_only_models_are_projected_with_router_defaults(monkeypatch):
    monkeypatch.setitem(FALLBACK_CHAINS, "deepseek-chat", ["fallback-only-model"])
    snapshot = build_governance_snapshot()
    profile = next(model for model in snapshot.models if model.model_name == "fallback-only-model")
    expected = ModelRouter().get_model_params("fallback-only-model")
    assert profile.temperature == expected["temperature"]
    assert profile.max_tokens == expected["max_tokens"]


def test_exact_empty_route_is_not_replaced_by_default(monkeypatch):
    monkeypatch.setitem(ROUTING_TABLE, ("empty_scene", "llm"), "")
    route = next(route for route in build_governance_snapshot().routes if route.scene == "empty_scene")
    assert route.explicit is True
    assert route.effective_model == ""


def test_endpoint_preserves_port_zero_and_rejects_invalid_port():
    assert build_governance_snapshot(ModelServiceConfig(base_url="http://unit.invalid:0/path")).providers[0].endpoint == "http://unit.invalid:0"
    assert build_governance_snapshot(ModelServiceConfig(base_url="http://unit.invalid:99999")).providers[0].endpoint == "invalid"


def test_dummy_provider_is_typed_as_development_fixture_without_credentials():
    provider = build_governance_snapshot(
        ModelServiceConfig(base_url="dummy", api_key="ignored-secret")
    ).providers[0]

    assert provider.provider_id == "dummy"
    assert provider.type == "development_fixture"
    assert provider.credential_status == "not_applicable"


def test_prompt_parameters_distinguish_declared_route_override_and_effective_values():
    snapshot = build_governance_snapshot()
    prompts = {prompt.prompt_id: prompt for prompt in snapshot.prompts}

    for prompt_id in ("policy.extract.schema", "policy.extract.legacy"):
        prompt = prompts[prompt_id]
        assert prompt.route_defaults.temperature == 0.1
        assert prompt.route_defaults.max_tokens == 4096
        assert prompt.call_overrides.temperature is None
        assert prompt.call_overrides.max_tokens == 8192
        assert prompt.effective_parameters.temperature == 0.1
        assert prompt.effective_parameters.max_tokens == 8192

    skill = prompts["skill.settlement_explain"]
    assert skill.declared_parameters.temperature == 0.3
    assert skill.declared_parameters.max_tokens == 1024
    assert skill.route_defaults.temperature == 0.1
    assert skill.route_defaults.max_tokens == 4096
    assert skill.effective_parameters.temperature == 0.1
    assert skill.effective_parameters.max_tokens == 4096
    assert any("声明参数" in warning and "实际生效" in warning for warning in skill.warnings)


def test_policy_fact_extract_lists_client_side_system_constraint_source():
    prompt = next(
        prompt
        for prompt in build_governance_snapshot().prompts
        if prompt.prompt_id == "policy.fact_extract"
    )

    assert (
        "src/knowledge_extension/rule_explanation/policy_fact/deepseek_llm_client.py"
        in prompt.related_source_paths
    )
