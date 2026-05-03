from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.runtime.runtime_state.store import RuntimeStateStore
from src.runtime.task_closure.service import create_task, update_task_confirmation


def test_runtime_state_store_saves_and_returns_workflow():
    store = RuntimeStateStore()
    workflow = WorkflowInstance(
        workflow_id="wf-001",
        scenario="settlement_exception_guidance",
        status="running",
        steps=[StepState(step_id="query_transaction", status="completed")],
    )

    store.save_workflow(workflow)
    saved = store.get_workflow("wf-001")

    assert saved.workflow_id == "wf-001"
    assert saved.steps[0].step_id == "query_transaction"


def test_task_closure_creates_and_confirms_task():
    task = create_task(
        task_id="task-001",
        task_type="human_confirmation",
        description="请人工确认",
        responsible_role="医保办",
        workflow_id="wf-001",
    )
    confirmed = update_task_confirmation(
        task,
        action="confirm",
        user_id="U001",
        reason="已处理",
    )

    assert confirmed["status"] == "confirmed"
    assert confirmed["confirmed_by"] == "U001"
    assert confirmed["confirmed_at"].endswith("Z")


def test_chat_creates_workflow_audit_and_preserves_response_shape():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "医保结算失败", "patient_id": "P001", "encounter_id": "E001"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["scenario"] == "settlement_exception_guidance"
    assert body["status"] == "completed"
    assert body["audit"]["workflow_id"].startswith("wf-")
    assert "steps" in body["audit"]


def test_workflow_status_returns_real_state_after_chat():
    client = TestClient(create_app())
    chat = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "医保结算失败", "patient_id": "P001", "encounter_id": "E001"},
    )
    workflow_id = chat.json()["audit"]["workflow_id"]

    response = client.get(f"/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}")

    assert response.status_code == 200
    assert response.json()["workflow_id"] == workflow_id
    assert response.json()["status"] in ["completed", "degraded", "waiting_human_confirmation"]


def test_audit_view_can_restore_high_risk_workflow():
    client = TestClient(create_app())
    chat = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "请自动退费", "patient_id": "P001", "encounter_id": "E001"},
    )
    workflow_id = chat.json()["audit"]["workflow_id"]

    response = client.get(f"/api/v1/medical-insurance-ai-agent/workflows/{workflow_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == workflow_id
    assert body["status"] == "waiting_human_confirmation"


def test_task_status_returns_real_task_after_high_risk_chat():
    client = TestClient(create_app())
    chat = client.post(
        "/api/v1/medical-insurance-ai-agent/chat",
        json={"user_id": "U001", "role": "medical_office", "message": "请自动退费并冲正", "patient_id": "P001", "encounter_id": "E001"},
    )
    task_id = chat.json()["tasks"][0]["task_id"]

    response = client.get(f"/api/v1/medical-insurance-ai-agent/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id
    assert response.json()["status"] == "pending"


def test_confirm_task_uses_runtime_time_not_hardcoded_value():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/tasks/confirm",
        json={"task_id": "task-manual-001", "action": "confirm", "user_id": "U001", "reason": "已在系统处理"},
    )

    assert response.status_code == 200
    assert response.json()["confirmed_at"] != "2026-05-02T00:00:00Z"
    assert response.json()["confirmed_at"].endswith("Z")
