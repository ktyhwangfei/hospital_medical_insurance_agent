from unittest.mock import MagicMock, patch
from typing import Iterator

import pytest

from src.model_service.exceptions import (
    ModelAuthError,
    ModelExhaustedError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message, ModelResponse, StreamChunk, TokenUsage


@pytest.fixture
def gateway():
    return ModelGateway()


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
