import httpx
import pytest

from src.model_service.exceptions import ModelAuthError, ModelRateLimitError, ModelServerError, ModelTimeoutError
from src.model_service.models import Message, ModelRequest
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider


def _request() -> ModelRequest:
    return ModelRequest(messages=[Message(role="user", content="hello")], model_type="test-model", scene="default")


def test_invoke_stream_converts_timeout(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def stream(self, *args, **kwargs):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(ModelTimeoutError):
        list(provider.invoke_stream(_request()))


def test_invoke_stream_converts_network_error(monkeypatch):
    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def stream(self, *args, **kwargs):
            raise httpx.NetworkError("network")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(ModelServerError):
        list(provider.invoke_stream(_request()))


def test_invoke_stream_converts_malformed_json(respx_mock):
    route = respx_mock.post("https://example.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text="data: {bad-json}\n\ndata: [DONE]\n")
    )
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(ModelServerError):
        list(provider.invoke_stream(_request()))
    assert route.called


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(401, ModelAuthError), (403, ModelAuthError), (429, ModelRateLimitError), (500, ModelServerError)],
)
def test_invoke_stream_converts_status_errors(respx_mock, status_code, error_type):
    respx_mock.post("https://example.test/v1/chat/completions").mock(return_value=httpx.Response(status_code, text="error"))
    provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="key")

    with pytest.raises(error_type):
        list(provider.invoke_stream(_request()))
