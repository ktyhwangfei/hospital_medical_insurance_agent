import pytest

from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE, ModelType
from src.model_service.router import ModelRouter


@pytest.fixture
def router():
    return ModelRouter()


def test_resolve_known_scene(router):
    model_name, fallbacks = router.resolve("settlement_exception_guidance", ModelType.LLM)
    assert model_name == "deepseek-ai/DeepSeek-V3.2"
    assert "deepseek-ai/DeepSeek-V4-Flash" in fallbacks


def test_resolve_unknown_scene_defaults(router):
    model_name, fallbacks = router.resolve("unknown_scene", ModelType.LLM)
    assert model_name == "deepseek-ai/DeepSeek-V3.2"


def test_resolve_embedding(router):
    model_name, fallbacks = router.resolve("any_scene", ModelType.EMBEDDING)
    assert model_name == "text-embedding-3-small"
    assert fallbacks == []


def test_get_model_params(router):
    params = router.get_model_params("deepseek-ai/DeepSeek-V3.2")
    assert params["temperature"] == 0.1
    assert params["max_tokens"] == 512


def test_get_model_params_defaults(router):
    params = router.get_model_params("unknown-model")
    assert params["temperature"] == 0.7
    assert params["max_tokens"] == 2048
