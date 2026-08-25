from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import Message, ModelRequest, TokenUsage
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider


@pytest.fixture
def provider():
    return OpenAICompatibleProvider(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        timeout=10,
    )


@pytest.fixture
def sample_request():
    return ModelRequest(
        messages=[Message(role="user", content="Hello")],
        model_type="llm",
        scene="test",
        temperature=0.7,
        max_tokens=100,
    )


def test_invoke_success(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hi there"}, "finish_reason": "stop"}],
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    with patch("httpx.Client.post", return_value=mock_response):
        result = provider.invoke(sample_request)

    assert result.content == "Hi there"
    assert result.model_name == "gpt-4o-mini"
    assert result.finish_reason == "stop"
    assert result.usage == TokenUsage(prompt_tokens=10, completion_tokens=5)


def test_invoke_auth_error(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelAuthError):
            provider.invoke(sample_request)


def test_invoke_rate_limit_error(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "Rate limited"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelRateLimitError):
            provider.invoke(sample_request)


def test_invoke_server_error(provider, sample_request):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal error"

    with patch("httpx.Client.post", return_value=mock_response):
        with pytest.raises(ModelServerError):
            provider.invoke(sample_request)


def test_invoke_non_2xx_does_not_expose_upstream_body(provider, sample_request):
    secret = "sk-live-sync-secret"
    body = f"api_key={secret}; Authorization: Bearer {secret}"
    response = httpx.Response(502, text=body)

    with patch("httpx.Client.post", return_value=response):
        with pytest.raises(ModelServerError) as exc_info:
            provider.invoke(sample_request)

    assert "502" in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert body not in str(exc_info.value)


def test_invoke_stream_non_2xx_does_not_expose_upstream_body(
    monkeypatch, provider, sample_request
):
    secret = "sk-live-stream-secret"
    body = f"api_key={secret}; Authorization: Bearer {secret}"
    response = httpx.Response(503, text=body)

    class StreamContext:
        def __enter__(self):
            return response

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        httpx.Client, "stream", lambda self, *args, **kwargs: StreamContext()
    )

    with pytest.raises(ModelServerError) as exc_info:
        list(provider.invoke_stream(sample_request))

    assert "503" in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert body not in str(exc_info.value)


def test_invoke_converts_read_timeout_to_model_timeout(monkeypatch):
    def fake_post(self, url, json, headers):
        raise httpx.ReadTimeout("read timeout")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key", timeout=1)
    request = ModelRequest(
        messages=[Message(role="user", content="你好")],
        model_type="gpt-test",
        scene="default",
        temperature=0.3,
        max_tokens=128,
    )

    with pytest.raises(ModelTimeoutError) as exc_info:
        provider.invoke(request)

    assert str(exc_info.value) == "Model provider request timed out"


def test_invoke_converts_network_error_to_model_server_error(monkeypatch):
    def fake_post(self, url, json, headers):
        raise httpx.ConnectError("connect failed")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key", timeout=1)
    request = ModelRequest(
        messages=[Message(role="user", content="你好")],
        model_type="gpt-test",
        scene="default",
        temperature=0.3,
        max_tokens=128,
    )

    with pytest.raises(ModelServerError) as exc_info:
        provider.invoke(request)

    assert str(exc_info.value) == "Model provider network error"


def test_invoke_embedding_converts_timeout_to_model_timeout(monkeypatch):
    def fake_post(self, url, json, headers):
        raise httpx.ReadTimeout("embedding timeout")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key", timeout=1)

    with pytest.raises(ModelTimeoutError) as exc_info:
        provider.invoke_embedding("医保政策", "embedding-test")

    assert str(exc_info.value) == "Model provider request timed out"


def test_list_models_sorts_unique_ids(provider):
    response = httpx.Response(200, json={
        "data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-b"}]
    })

    class Context:
        def __enter__(self):
            return response

        def __exit__(self, *_):
            return False

    with patch("httpx.Client.stream", return_value=Context()):
        assert provider.list_models() == ["model-a", "model-b"]


def test_list_models_connects_to_pinned_ip_with_original_https_host(monkeypatch, provider):
    response = httpx.Response(200, json={"data": [{"id": "model-pinned"}]})

    class Context:
        def __enter__(self):
            return response

        def __exit__(self, *_):
            return False

    with patch("httpx.Client.stream", return_value=Context()) as stream:
        assert provider.list_models(connect_ip="8.8.8.8") == ["model-pinned"]
    stream.assert_called_once_with(
        "GET",
        "https://8.8.8.8/v1/models",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer test-key",
            "Host": "api.example.com",
        },
        extensions={"sni_hostname": "api.example.com"},
    )


def test_list_models_rejects_unbounded_model_count(provider):
    response = httpx.Response(200, json={
        "data": [{"id": f"model-{index}"} for index in range(1001)]
    })

    class Context:
        def __enter__(self):
            return response

        def __exit__(self, *_):
            return False

    with patch("httpx.Client.stream", return_value=Context()):
        with pytest.raises(ModelServerError, match="too many models"):
            provider.list_models()


def test_list_models_rejects_oversized_response(provider):
    response = httpx.Response(200, content=b"x" * (1024 * 1024 + 1))

    class Context:
        def __enter__(self):
            return response

        def __exit__(self, *_):
            return False

    with patch("httpx.Client.stream", return_value=Context()):
        with pytest.raises(ModelServerError, match="response too large"):
            provider.list_models()
