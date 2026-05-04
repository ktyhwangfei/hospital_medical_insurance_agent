from src.runtime.runtime_state.models import WorkflowInstance


class RuntimeStateStore:
    def __init__(self):
        self._workflows: dict[str, WorkflowInstance] = {}

    def save_workflow(self, workflow: WorkflowInstance) -> WorkflowInstance:
        self._workflows[workflow.workflow_id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> WorkflowInstance | None:
        return self._workflows.get(workflow_id)


runtime_state_store = RuntimeStateStore()
