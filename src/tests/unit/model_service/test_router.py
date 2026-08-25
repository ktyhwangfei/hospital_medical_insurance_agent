import pytest

from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE, ModelType
from src.model_service.router import ModelRouter


@pytest.fixture
def router():
    return ModelRouter()


def test_resolve_known_scene(router):
    model_name, fallbacks = router.resolve("policy_qa_fee_decomposition", ModelType.LLM)
    assert model_name == ROUTING_TABLE[("default", "llm")]
    assert fallbacks == []


def test_resolve_unknown_scene_defaults(router):
    model_name, fallbacks = router.resolve("unknown_scene", ModelType.LLM)
    assert model_name == ROUTING_TABLE[("default", "llm")]


def test_active_llm_scenes_have_explicit_routes(router):
    active_scenes = {
        "skill_routing",
        "policy_qa",
        "fee_explanation",
        "policy_fact_extraction",
    }

    for scene in active_scenes:
        assert ROUTING_TABLE[(scene, ModelType.LLM)] == "deepseek-chat"
        assert router.resolve(scene, ModelType.LLM) == ("deepseek-chat", [])


def test_resolve_embedding(router):
    model_name, fallbacks = router.resolve("any_scene", ModelType.EMBEDDING)
    assert model_name == "text-embedding-3-small"
    assert fallbacks == []


def test_get_model_params(router):
    params = router.get_model_params("deepseek-chat")
    assert params["temperature"] == 0.1
    assert params["max_tokens"] == 4096


def test_get_model_params_defaults(router):
    params = router.get_model_params("unknown-model")
    assert params["temperature"] == 0.7
    assert params["max_tokens"] == 2048
