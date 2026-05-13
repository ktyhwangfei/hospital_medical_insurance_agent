from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _chat_payload(message: str = '结算失败'):
    return {
        'user_id': 'U001',
        'role': 'cashier',
        'message': message,
        'patient_id': 'P001',
        'encounter_id': 'E001',
    }


def test_chat_uses_parse_intent():
    app = create_app()
    client = TestClient(app)
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json=_chat_payload())
    assert response.status_code == 200
    data = response.json()
    assert data['status'] != 'error'


def test_chat_unknown_intent():
    app = create_app()
    client = TestClient(app)
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json=_chat_payload('今天天气'))
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'not_implemented'


def test_chat_response_contains_citations():
    app = create_app()
    client = TestClient(app)
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json=_chat_payload())
    assert response.status_code == 200
    data = response.json()
    assert 'citations' in data
