from typing import Any


class InMemoryAuditLog:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def record(self, event_type: str, workflow_id: str | None = None, step_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {'event_type': event_type, 'workflow_id': workflow_id, 'step_id': step_id, 'payload': payload or {}}
        self.records.append(event)
        return event

    def record_event(self, event_type: str, **kwargs: Any) -> dict[str, Any]:
        """PostgreSQLAuditLog.record_event 的内存对齐（#75 治理审计可用内存存储测试）。"""
        event = {'event_type': event_type, **kwargs}
        self.records.append(event)
        return event

    def by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records if record.get('workflow_id') == workflow_id]


audit_log = InMemoryAuditLog()
