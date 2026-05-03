from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.security.risk_control.service import build_human_confirmation_response


def test_human_confirmation_api_confirm():
    client = TestClient(create_app())
    confirmation = build_human_confirmation_response(['退费'])
    task_id = confirmation.tasks[0]['task_id']
    response = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
        'task_id': task_id,
        'action': 'confirm',
        'user_id': 'u-medical-office-001',
        'reason': '确认执行退费操作'
    })
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'confirmed'
    assert body['task_id'] == task_id


def test_human_confirmation_api_reject():
    client = TestClient(create_app())
    confirmation = build_human_confirmation_response(['退费'])
    task_id = confirmation.tasks[0]['task_id']
    response = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
        'task_id': task_id,
        'action': 'reject',
        'user_id': 'u-medical-office-001',
        'reason': '风险过高，拒绝执行'
    })
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'rejected'
    assert body['result']['blocked'] is True


def test_human_confirmation_invalid_action():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
        'task_id': 'task-001',
        'action': 'approve',
        'user_id': 'u001'
    })
    assert response.status_code == 400
