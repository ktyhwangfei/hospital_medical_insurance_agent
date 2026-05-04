from typing import Any


class InMemoryAuditLog:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def record(self, event_type: str, workflow_id: str | None = None, step_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {'event_type': event_type, 'workflow_id': workflow_id, 'step_id': step_id, 'payload': payload or {}}
        self.records.append(event)
        return event

    def by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records if record.get('workflow_id') == workflow_id]


audit_log = InMemoryAuditLog()
