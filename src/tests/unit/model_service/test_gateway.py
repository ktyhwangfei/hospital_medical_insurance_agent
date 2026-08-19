import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
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


def test_generate_provider_error_never_records_upstream_secret(
    monkeypatch, caplog, gateway
):
    from src.model_service import gateway as gateway_module

    secret = "sk-live-gateway-sync"
    body = f"api_key={secret}; Authorization: Bearer {secret}"
    events = []
    gateway._config.api_key = secret
    gateway._config.max_retries = 1
    monkeypatch.setattr(gateway._router, "resolve", lambda *_: ("primary", []))
    monkeypatch.setattr(
        gateway._router,
        "get_model_params",
        lambda *_: {"temperature": 0.1, "max_tokens": 100},
    )
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *args, **kwargs: httpx.Response(502, text=body),
    )
    monkeypatch.setattr(
        gateway_module, "_record_llm_event", lambda **kwargs: events.append(kwargs)
    )
    caplog.set_level("WARNING", logger="src.model_service.gateway")

    with pytest.raises(ModelExhaustedError) as exc_info:
        gateway.generate([Message(role="user", content="Q")], "llm", "policy_qa")

    recorded = "\n".join(
        [
            str(exc_info.value),
            str(exc_info.value.failures),
            str([record.__dict__ for record in caplog.records]),
            str(events),
        ]
    )
    assert secret not in recorded
    assert body not in recorded


def test_generate_stream_provider_error_never_records_upstream_secret(
    monkeypatch, caplog, gateway
):
    from src.model_service import gateway as gateway_module

    secret = "sk-live-gateway-stream"
    body = f"api_key={secret}; Authorization: Bearer {secret}"
    response = httpx.Response(503, text=body)
    events = []
    gateway._config.api_key = secret
    monkeypatch.setattr(gateway._router, "resolve", lambda *_: ("primary", []))
    monkeypatch.setattr(
        gateway._router,
        "get_model_params",
        lambda *_: {"temperature": 0.1, "max_tokens": 100},
    )

    class StreamContext:
        def __enter__(self):
            return response

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        httpx.Client, "stream", lambda self, *args, **kwargs: StreamContext()
    )
    monkeypatch.setattr(
        gateway_module, "_record_llm_event", lambda **kwargs: events.append(kwargs)
    )
    caplog.set_level("ERROR", logger="src.model_service.gateway")

    with pytest.raises(ModelServerError) as exc_info:
        list(
            gateway.generate_stream(
                [Message(role="user", content="Q")], "llm", "policy_qa"
            )
        )

    recorded = "\n".join(
        [
            str(exc_info.value),
            str([record.__dict__ for record in caplog.records]),
            str(events),
        ]
    )
    assert secret not in recorded
    assert body not in recorded

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


def test_unconfigured_gateway_raises_clear_error(gateway, monkeypatch):
    """Issue #19：dummy 假数据模式已移除——未配置真实模型必须明确报错，
    绝不返回写死的示例响应（曾致假规则入库）。"""
    # 显式固定未配置环境（本机 .env 可能配置了真实模型端点）
    monkeypatch.setattr(gateway._config, "base_url", "dummy")

    from src.model_service.exceptions import ModelConfigError

    messages = [Message(role="user", content="请提取以下政策规则")]

    with pytest.raises(ModelConfigError, match="模型服务未配置"):
        gateway.generate(messages, "llm", "policy_qa")

    with pytest.raises(ModelConfigError, match="MODEL_BASE_URL"):
        gateway.generate(messages, "llm", "policy_fact_extraction")

def _recording_patches():
    return (
        patch(
            "src.runtime.infra_event.context.infra_context",
            return_value=SimpleNamespace(workflow_id=None),
        ),
        patch("src.runtime.infra_event.recorder.record_llm_call"),
    )


def test_skill_authoring_success_event_hashes_prompt_and_response(gateway):
    messages = [Message(role="user", content="PRIVATE AUTHORING DESCRIPTION")]
    context_patch, recorder_patch = _recording_patches()

    with (
        context_patch,
        recorder_patch as recorder,
        patch.object(
            gateway,
            "_call_provider",
            return_value=_make_response("PRIVATE GENERATED SCRIPT"),
        ),
    ):
        gateway.generate(messages, "reasoning", "skill_authoring")

    event = recorder.call_args.kwargs
    assert event["prompt_summary"].startswith("sha256:")
    assert event["response_summary"].startswith("sha256:")
    assert "PRIVATE" not in event["prompt_summary"]
    assert "PRIVATE" not in event["response_summary"]


def test_skill_authoring_all_failure_events_hash_prompt_and_response(gateway):
    messages = [Message(role="user", content="PRIVATE AUTHORING DESCRIPTION")]
    gateway._config.max_retries = 1
    context_patch, recorder_patch = _recording_patches()

    with (
        context_patch,
        recorder_patch as recorder,
        patch.object(
            gateway,
            "_call_provider",
            side_effect=ModelServerError("provider failed"),
        ),
        pytest.raises(ModelExhaustedError),
    ):
        gateway.generate(messages, "reasoning", "skill_authoring")

    assert recorder.call_count == 2
    for call in recorder.call_args_list:
        event = call.kwargs
        assert event["prompt_summary"].startswith("sha256:")
        assert event["response_summary"].startswith("sha256:")
        assert "PRIVATE" not in event["prompt_summary"]


def test_skill_authoring_retry_log_redacts_provider_error(gateway, caplog):
    prompt_secret = "PRIVATE AUTHORING PROMPT"
    provider_secret = "provider echoed PRIVATE SCRIPT response body"
    error = ModelServerError(provider_secret, model_name="provider-model")
    gateway._config.max_retries = 1

    with (
        caplog.at_level(logging.WARNING, logger="src.model_service.gateway"),
        patch.object(gateway, "_call_provider", side_effect=error),
        pytest.raises(ModelExhaustedError) as captured,
    ):
        gateway.generate(
            [Message(role="user", content=prompt_secret)],
            "reasoning",
            "skill_authoring",
        )

    retry_record = next(
        record for record in caplog.records if record.getMessage() == "model_retry"
    )
    assert retry_record.error.startswith("ModelServerError:sha256:")
    assert prompt_secret not in str(retry_record.__dict__)
    assert provider_secret not in str(retry_record.__dict__)
    failure_summary = captured.value.failures[0]["error_message"]
    assert failure_summary.startswith("ModelServerError:sha256:")
    assert provider_secret not in failure_summary


def test_non_authoring_retry_log_keeps_existing_error_text(gateway, caplog):
    provider_error = "ordinary provider failure body"
    gateway._config.max_retries = 1

    with (
        caplog.at_level(logging.WARNING, logger="src.model_service.gateway"),
        patch.object(
            gateway,
            "_call_provider",
            side_effect=ModelServerError(provider_error),
        ),
        pytest.raises(ModelExhaustedError) as captured,
    ):
        gateway.generate(
            [Message(role="user", content="ordinary prompt")], "llm", "test"
        )

    retry_record = next(
        record for record in caplog.records if record.getMessage() == "model_retry"
    )
    assert retry_record.error == provider_error
    assert captured.value.failures[0]["error_message"] == provider_error


def test_skill_authoring_stream_redacts_error_but_reraises_same_object(
    gateway, caplog
):
    prompt_secret = "PRIVATE AUTHORING PROMPT"
    provider_secret = "provider echoed PRIVATE SCRIPT response body"
    error = ModelServerError(provider_secret, model_name="provider-model")
    provider = MagicMock()
    provider.invoke_stream.side_effect = error
    context_patch, recorder_patch = _recording_patches()

    with (
        caplog.at_level(logging.ERROR, logger="src.model_service.gateway"),
        context_patch,
        recorder_patch as recorder,
        patch.object(gateway, "_get_provider", return_value=provider),
        pytest.raises(ModelServerError) as captured,
    ):
        list(
            gateway.generate_stream(
                [Message(role="user", content=prompt_secret)],
                "reasoning",
                "skill_authoring",
            )
        )

    assert captured.value is error
    log_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "model_stream_interrupted"
    )
    assert log_record.error.startswith("ModelServerError:sha256:")
    assert prompt_secret not in str(log_record.__dict__)
    assert provider_secret not in str(log_record.__dict__)
    event = recorder.call_args.kwargs
    assert event["error_message"].startswith("ModelServerError:sha256:")
    assert provider_secret not in event["error_message"]


def test_non_authoring_stream_keeps_existing_error_text(gateway, caplog):
    provider_error = "ordinary stream provider failure body"
    error = ModelServerError(provider_error, model_name="provider-model")
    provider = MagicMock()
    provider.invoke_stream.side_effect = error
    context_patch, recorder_patch = _recording_patches()

    with (
        caplog.at_level(logging.ERROR, logger="src.model_service.gateway"),
        context_patch,
        recorder_patch as recorder,
        patch.object(gateway, "_get_provider", return_value=provider),
        pytest.raises(ModelServerError) as captured,
    ):
        list(
            gateway.generate_stream(
                [Message(role="user", content="ordinary prompt")],
                "llm",
                "default",
            )
        )

    assert captured.value is error
    log_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "model_stream_interrupted"
    )
    assert log_record.error == provider_error
    assert recorder.call_args.kwargs["error_message"] == provider_error


def test_non_authoring_event_keeps_existing_plaintext_summary(gateway):
    messages = [Message(role="user", content="ordinary prompt")]
    context_patch, recorder_patch = _recording_patches()

    with (
        context_patch,
        recorder_patch as recorder,
        patch.object(
            gateway,
            "_call_provider",
            return_value=_make_response("ordinary response"),
        ),
    ):
        gateway.generate(messages, "llm", "test")

    event = recorder.call_args.kwargs
    assert event["prompt_summary"] == "ordinary prompt"
    assert event["response_summary"] == "ordinary response"


def test_generate_fills_empty_provider_model_name_from_route(gateway):
    messages = [Message(role="user", content="Hello")]
    routed_model, _ = gateway._router.resolve("skill_authoring", "reasoning")

    with patch.object(
        gateway, "_call_provider", return_value=_make_response(model="")
    ):
        result = gateway.generate(messages, "reasoning", "skill_authoring")

    assert result.model_name == routed_model


def test_skill_authoring_records_hash_only_success_event(gateway):
    _nondummy(gateway)
    prompt_secret = "PRIVATE DUMMY AUTHORING DESCRIPTION"
    context_patch, recorder_patch = _recording_patches()

    with context_patch, recorder_patch as recorder, patch.object(
        gateway,
        "_call_provider",
        return_value=_make_response(content="AUTHORED RESPONSE BODY", model="authored"),
    ):
        result = gateway.generate(
            [Message(role="user", content=prompt_secret)],
            "reasoning",
            "skill_authoring",
        )

    event = recorder.call_args.kwargs
    assert event["prompt_summary"].startswith("sha256:")
    assert event["response_summary"].startswith("sha256:")
    assert prompt_secret not in str(event)
    assert result.content not in str(event)


def test_non_authoring_records_existing_plaintext_summary(gateway):
    _nondummy(gateway)
    prompt = "ordinary dummy prompt"
    context_patch, recorder_patch = _recording_patches()

    with context_patch, recorder_patch as recorder, patch.object(
        gateway, "_call_provider", return_value=_make_response(model="plain")
    ):
        result = gateway.generate(
            [Message(role="user", content=prompt)], "llm", "test"
        )

    event = recorder.call_args.kwargs
    assert event["prompt_summary"] == prompt
    assert event["response_summary"] == result.content
