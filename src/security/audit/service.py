from src.runtime.runtime_state.store import runtime_state_store
from src.security.audit.in_memory import audit_log


def record_audit_event(event_type: str, workflow_id: str | None = None, step_id: str | None = None, payload: dict | None = None) -> dict:
    return audit_log.record(event_type, workflow_id, step_id, payload)


def build_workflow_audit_view(workflow_id: str) -> dict | None:
    workflow = runtime_state_store.get_workflow(workflow_id)
    if workflow is None:
        return None
    return {
        'workflow_id': workflow.workflow_id,
        'scenario': workflow.scenario,
        'status': workflow.status,
        'steps': [step.model_dump() for step in workflow.steps],
        'events': audit_log.by_workflow(workflow_id),
    }
