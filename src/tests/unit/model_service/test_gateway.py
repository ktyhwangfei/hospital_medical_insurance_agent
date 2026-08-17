from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from src.model_service.exceptions import (
    ModelAuthError,
    ModelExhaustedError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.gateway import ModelGateway
from src.model_service.governance_runtime import RuntimeModelProfile, RuntimeModelRoute
from src.model_service.models import Message, ModelResponse, StreamChunk, TokenUsage


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setattr(
        "src.model_service.gateway.resolve_governed_route",
        lambda scene, model_type: None,
    )
    instance = ModelGateway()
    instance._config.base_url = "https://static.example.test/v1"
    return instance


def _make_response(content="ok", model="gpt-4o-mini"):
    return ModelResponse(
        content=content,
        model_name=model,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        finish_reason="stop",
    )


def test_generate_success(gateway):
    messages = [Message(role="user", content="Hello")]
    with patch.object(gateway, "_call_provider", return_value=_make_response("Hi")):
        result = gateway.generate(messages, "llm", "test")
    assert result.content == "Hi"


def test_generate_retries_on_timeout(gateway):
    messages = [Message(role="user", content="Hello")]
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ModelTimeoutError("timeout", model_name="gpt-4o-mini")
        return _make_response()

    with patch.object(gateway, "_call_provider", side_effect=side_effect):
        result = gateway.generate(messages, "llm", "test")

    assert result.content == "ok"
    assert call_count == 3


def test_generate_fallback_on_exhausted(gateway):
    messages = [Message(role="user", content="Hello")]
    call_count = 0

    def side_effect(request, model_name):
        nonlocal call_count
        call_count += 1
        if model_name == "gpt-4o-mini":
            raise ModelServerError("server error", model_name="gpt-4o-mini")
        return _make_response(model="gpt-3.5-turbo")

    with patch.object(gateway, "_call_provider", side_effect=side_effect):
        result = gateway.generate(messages, "llm", "settlement_exception_guidance")

    assert result.model_name == "gpt-3.5-turbo"


def test_generate_auth_error_no_fallback(gateway):
    messages = [Message(role="user", content="Hello")]

    with patch.object(gateway, "_call_provider", side_effect=ModelAuthError("auth", model_name="gpt-4o-mini")):
        with pytest.raises(ModelAuthError):
            gateway.generate(messages, "llm", "test")


def test_generate_exhausted_error(gateway):
    messages = [Message(role="user", content="Hello")]

    with patch.object(gateway, "_call_provider", side_effect=ModelServerError("error", model_name="gpt-4o-mini")):
        with pytest.raises(ModelExhaustedError):
            gateway.generate(messages, "llm", "settlement_exception_guidance")


def test_generate_stream_reraises_provider_error(gateway):
    messages = [Message(role="user", content="Hello")]

    with patch.object(gateway, "_get_provider") as mock_get_provider:
        provider = MagicMock()
        provider.invoke_stream.side_effect = ModelServerError("stream failed", model_name="test-model")
        mock_get_provider.return_value = provider

        with pytest.raises(ModelServerError):
            list(gateway.generate_stream(messages, "llm", "default"))


def test_generate_max_tokens_override(gateway):
    """调用方可传 max_tokens 覆盖 router 默认（长文档提取 JSON 需更大输出空间）。"""
    messages = [Message(role="user", content="Hello")]
    captured = {}

    def fake_call(request, model_name):
        captured["max_tokens"] = request.max_tokens
        return _make_response()

    with patch.object(gateway, "_call_provider", side_effect=fake_call):
        gateway.generate(messages, "llm", "test", max_tokens=8192)

    assert captured["max_tokens"] == 8192


def test_generate_default_max_tokens_unchanged(gateway):
    """不传 max_tokens 时沿用 router 默认（向后兼容，行为与改动前一致）。"""
    messages = [Message(role="user", content="Hello")]
    # 取 router 默认值，断言 generate 用它（不依赖具体数字）
    model_name, _ = gateway._router.resolve("test", "llm")
    expected = gateway._router.get_model_params(model_name)["max_tokens"]
    captured = {}

    def fake_call(request, model_name):
        captured["max_tokens"] = request.max_tokens
        return _make_response()

    with patch.object(gateway, "_call_provider", side_effect=fake_call):
        gateway.generate(messages, "llm", "test")

    assert captured["max_tokens"] == expected


def test_generate_and_stream_share_governed_route_resolution(monkeypatch, gateway):
    from src.model_service import gateway as gateway_module

    profile = RuntimeModelProfile(
        asset_id="model.governed",
        model_name="governed-model",
        base_url="https://governed.example.test/v1",
        api_key=SecretStr("sk-governed"),
        timeout_seconds=19,
        temperature=0.15,
        max_tokens=333,
    )
    route = RuntimeModelRoute(primary=profile)
    resolved = []
    monkeypatch.setattr(
        gateway_module,
        "resolve_governed_route",
        lambda scene, model_type: resolved.append((scene, model_type)) or route,
    )
    calls = []

    class Provider:
        def invoke(self, request):
            calls.append(("generate", request))
            return _make_response(model=request.model_type)

        def invoke_stream(self, request):
            calls.append(("stream", request))
            yield StreamChunk(content="ok", finish_reason="stop")

    monkeypatch.setattr(
        gateway,
        "_get_provider",
        lambda model_name, runtime_profile=None: Provider(),
    )

    gateway.generate([Message(role="user", content="Q")], "llm", "policy_qa")
    list(gateway.generate_stream([Message(role="user", content="Q")], "llm", "policy_qa"))

    assert resolved == [("policy_qa", "llm"), ("policy_qa", "llm")]
    assert [request.model_type for _, request in calls] == [
        "governed-model",
        "governed-model",
    ]
    assert all(request.temperature == 0.15 for _, request in calls)
    assert all(request.max_tokens == 333 for _, request in calls)


def test_generate_stream_uses_governed_fallback_before_any_chunk(monkeypatch, gateway):
    from src.model_service import gateway as gateway_module

    def profile(asset_id, model_name):
        return RuntimeModelProfile(
            asset_id=asset_id,
            model_name=model_name,
            base_url=f"https://{asset_id}.example.test/v1",
            api_key=SecretStr(f"sk-{asset_id}"),
            timeout_seconds=9,
            temperature=0.1,
            max_tokens=100,
        )

    route = RuntimeModelRoute(
        primary=profile("model.primary", "primary"),
        fallbacks=[profile("model.backup", "backup")],
    )
    monkeypatch.setattr(gateway_module, "resolve_governed_route", lambda *_: route)
    requested = []

    class Provider:
        def __init__(self, model_name):
            self.model_name = model_name

        def invoke_stream(self, request):
            requested.append(request.model_type)
            if self.model_name == "primary":
                raise ModelServerError("primary failed", model_name="primary")
            yield StreamChunk(content="backup", finish_reason="stop")

    monkeypatch.setattr(
        gateway,
        "_get_provider",
        lambda model_name, runtime_profile=None: Provider(model_name),
    )

    chunks = list(
        gateway.generate_stream([Message(role="user", content="Q")], "llm", "policy_qa")
    )

    assert [chunk.content for chunk in chunks] == ["backup"]
    assert requested == ["primary", "backup"]


def test_generate_stream_does_not_fallback_after_first_chunk(monkeypatch, gateway):
    from src.model_service import gateway as gateway_module

    primary = RuntimeModelProfile(
        asset_id="model.primary",
        model_name="primary",
        base_url="https://primary.example.test/v1",
        api_key=SecretStr("sk-primary"),
        timeout_seconds=9,
        temperature=0.1,
        max_tokens=100,
    )
    backup = primary.model_copy(
        update={"asset_id": "model.backup", "model_name": "backup"}
    )
    monkeypatch.setattr(
        gateway_module,
        "resolve_governed_route",
        lambda *_: RuntimeModelRoute(primary=primary, fallbacks=[backup]),
    )
    requested = []

    class Provider:
        def __init__(self, model_name):
            self.model_name = model_name

        def invoke_stream(self, request):
            requested.append(request.model_type)
            yield StreamChunk(content="partial")
            raise ModelTimeoutError("interrupted", model_name=request.model_type)

    monkeypatch.setattr(
        gateway,
        "_get_provider",
        lambda model_name, runtime_profile=None: Provider(model_name),
    )
    stream = gateway.generate_stream(
        [Message(role="user", content="Q")], "llm", "policy_qa"
    )

    assert next(stream).content == "partial"
    with pytest.raises(ModelTimeoutError):
        next(stream)
    assert requested == ["primary"]
