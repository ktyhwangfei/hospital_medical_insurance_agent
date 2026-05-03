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
