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


# ── model_override（迭代 18：审核时换大模型）──────────────────────

def _nondummy(gateway):
    """把 base_url 从 dummy 改为非 dummy，让真实 chain 循环执行（不被 dummy 分支短路）。"""
    gateway._config.base_url = "https://example.com/v1"
    return gateway


def test_generate_model_override_bypasses_router(gateway):
    """model_override 非空时绕过 router，直接用指定模型。"""
    _nondummy(gateway)
    messages = [Message(role="user", content="Hello")]
    captured = {}

    def fake_call(request, model_name):
        captured["model_name"] = model_name
        return _make_response(model=model_name)

    with patch.object(gateway, "_call_provider", side_effect=fake_call):
        result = gateway.generate(
            messages, "llm", "policy_qa", model_override="my-custom-model"
        )

    assert captured["model_name"] == "my-custom-model"
    assert result.model_name == "my-custom-model"


def test_generate_model_override_no_fallback(gateway):
    """model_override 指定的模型失败时关闭 fallback：只重试该模型，绝不偷换为其他模型。"""
    _nondummy(gateway)
    messages = [Message(role="user", content="Hello")]
    called_models: list[str] = []

    def fake_call(request, model_name):
        called_models.append(model_name)
        raise ModelServerError("boom", model_name=model_name)

    with patch.object(gateway, "_call_provider", side_effect=fake_call):
        with pytest.raises(ModelExhaustedError):
            gateway.generate(
                messages, "llm", "policy_qa", model_override="my-custom-model"
            )

    # 重试若干次（max_retries），但全部落在 override 模型上，绝不出现 fallback 模型
    assert called_models
    assert all(m == "my-custom-model" for m in called_models)


def test_generate_model_override_max_tokens_propagates(gateway):
    """model_override 与 max_tokens 可同时生效（长输出 + 指定模型）。"""
    _nondummy(gateway)
    messages = [Message(role="user", content="Hello")]
    captured = {}

    def fake_call(request, model_name):
        captured["model_name"] = model_name
        captured["max_tokens"] = request.max_tokens
        return _make_response(model=model_name)

    with patch.object(gateway, "_call_provider", side_effect=fake_call):
        gateway.generate(
            messages,
            "llm",
            "policy_qa",
            max_tokens=4096,
            model_override="my-custom-model",
        )

    assert captured["model_name"] == "my-custom-model"
    assert captured["max_tokens"] == 4096


def test_dummy_generate_policy_qa_returns_extraction_json(gateway, monkeypatch):
    """迭代19 修改2：dummy 分支对 policy_qa（提取）场景必须返回合法 JSON 数组，
    否则重提取在调试/未配置模型环境下必然为空（'LLM 未返回结果'）。"""
    import json as jsonlib

    # 显式固定 dummy 环境（本机 .env 可能配置了真实模型端点）
    monkeypatch.setattr(gateway._config, "base_url", "dummy")

    messages = [Message(role="user", content="请提取以下政策规则")]

    result = gateway.generate(messages, "llm", "policy_qa")

    # dummy 分支不应返回结算解释文本（===PATIENT===），应返回提取 JSON
    assert result.model_name == "dummy_llm"
    content = result.content.strip()
    assert "===PATIENT===" not in content
    parsed = jsonlib.loads(content)
    assert isinstance(parsed, list), "dummy policy_qa 应返回 JSON 数组（facts）"
    if parsed:
        first = parsed[0]
        assert "fact_text" in first
        assert isinstance(first.get("rules"), list)
