from fastapi.testclient import TestClient

from src.model_service.exceptions import ModelAuthError, ModelExhaustedError, ModelRateLimitError, ModelServerError
from src.runtime.api.app import create_app
from src.runtime.api import routes


def test_health_version_and_openapi_contract():
    client = TestClient(create_app())

    health = client.get('/health')
    assert health.status_code == 200
    assert health.json() == {'status': 'ok'}

    version = client.get('/api/v1/medical-insurance-ai-agent/version')
    assert version.status_code == 200
    assert version.json()['module'] == 'medical-insurance-ai-agent'
    assert version.json()['mode'] == 'memory-mvp'

    openapi = client.get('/openapi.json').json()
    paths = openapi['paths'].keys()
    assert '/api/v1/medical-insurance-ai-agent/chat' in paths
    assert '/api/v1/medical-insurance-ai-agent/patient-context/{patient_id}/{encounter_id}' in paths
    assert '/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}' in paths
    assert '/api/v1/medical-insurance-ai-agent/tasks/{task_id}' in paths


def test_chat_stream_returns_step_final_and_done_events():
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/chat/stream',
        json={
            'user_id': 'u-demo-001',
            'role': 'medical_office',
            'message': '患者 P001 本次医保结算失败，帮我看一下原因',
            'patient_id': 'P001',
            'encounter_id': 'E001',
        },
    )

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    text = response.text
    assert 'event: step' in text
    assert 'intent_detection' in text
    assert 'risk_control' in text
    assert 'scenario_processing' in text
    assert 'event: final' in text
    assert 'settlement_exception_guidance' in text
    assert 'event: done' in text


def test_model_test_stream_returns_delta_final_and_done_events(monkeypatch):
    from src.model_service.models import StreamChunk, TokenUsage
    from src.runtime.api import routes

    def fake_generate_stream(self, messages, model_type, scene):
        yield StreamChunk(content='你', finish_reason=None, usage=None)
        yield StreamChunk(content='好', finish_reason='stop', usage=TokenUsage(prompt_tokens=1, completion_tokens=2))

    monkeypatch.setattr(routes.ModelGateway, 'generate_stream', fake_generate_stream)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test/stream',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    text = response.text
    assert 'event: start' in text
    assert 'event: delta' in text
    assert '你' in text
    assert '好' in text
    assert 'event: final' in text
    assert 'event: done' in text


def test_model_test_returns_json_error_when_gateway_auth_fails(monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY', '')

    def fake_generate(self, messages, model_type, scene):
        raise ModelAuthError('Auth error: missing api key')

    monkeypatch.setattr(routes.ModelGateway, 'generate', fake_generate)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 503
    assert response.headers['content-type'].startswith('application/json')
    body = response.json()
    assert body['detail']['error_code'] == 'MODEL_CONFIG_ERROR'
    assert 'MODEL_API_KEY' in body['detail']['message']


def test_model_test_returns_rate_limit_error(monkeypatch):
    def fake_generate(self, messages, model_type, scene):
        raise ModelRateLimitError('Rate limited')

    monkeypatch.setattr(routes.ModelGateway, 'generate', fake_generate)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 429
    assert response.json()['detail']['error_code'] == 'MODEL_RATE_LIMITED'


def test_model_test_returns_upstream_error(monkeypatch):
    def fake_generate(self, messages, model_type, scene):
        raise ModelServerError('Server error')

    monkeypatch.setattr(routes.ModelGateway, 'generate', fake_generate)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 502
    assert response.json()['detail']['error_code'] == 'MODEL_UPSTREAM_ERROR'


def test_model_test_returns_exhausted_error(monkeypatch):
    def fake_generate(self, messages, model_type, scene):
        raise ModelExhaustedError(
            'All models in fallback chain failed',
            failures=[{'model_name': 'gpt-test', 'error_type': 'ModelTimeoutError', 'error_message': 'read timeout'}],
        )

    monkeypatch.setattr(routes.ModelGateway, 'generate', fake_generate)
    client = TestClient(create_app())

    response = client.post(
        '/api/v1/medical-insurance-ai-agent/model-test',
        json={'message': '你好', 'scene': 'default'},
    )

    assert response.status_code == 503
    assert response.headers['content-type'].startswith('application/json')
    assert response.json()['detail']['error_code'] == 'MODEL_EXHAUSTED'
