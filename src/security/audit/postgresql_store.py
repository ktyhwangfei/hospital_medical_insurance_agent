import json
from typing import Any

from src.data_platform.storage.postgresql.client import PostgreSQLClient


class PostgreSQLAuditLog:
    """PostgreSQL-backed audit log matching InMemoryAuditLog interface.

    Uses PostgreSQLClient from src.data_platform.storage.postgresql.
    Gracefully handles connection errors (returns empty results / does nothing on failure).

    Methods: record_event, get_events (aliased as record, by_workflow for compatibility).
    """

    def __init__(self, client: PostgreSQLClient):
        self._client = client

    def record_event(
        self,
        event_type: str,
        workflow_id: str | None = None,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an audit event."""
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        sql = "insert into audit_logs (event_type, workflow_id, step_id, payload) values (%s, %s, %s, %s)"
        try:
            self._client.execute(sql, (event_type, workflow_id, step_id, payload_json))
        except RuntimeError:
            pass
        return {
            "event_type": event_type,
            "workflow_id": workflow_id,
            "step_id": step_id,
            "payload": payload or {},
        }

    def get_events(self, workflow_id: str) -> list[dict[str, Any]]:
        """Retrieve all audit events for a workflow."""
        try:
            rows = self._client.execute(
                "select * from audit_logs where workflow_id = %s order by id asc",
                (workflow_id,),
            )
            results: list[dict[str, Any]] = []
            for row in rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                results.append({
                    "event_type": row["event_type"],
                    "workflow_id": row.get("workflow_id"),
                    "step_id": row.get("step_id"),
                    "payload": payload,
                })
            return results
        except RuntimeError:
            return []

    # -- aliases for InMemoryAuditLog interface compatibility --

    def record(
        self,
        event_type: str,
        workflow_id: str | None = None,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Alias for record_event, matches InMemoryAuditLog.record signature."""
        return self.record_event(event_type, workflow_id, step_id, payload)

    def by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        """Alias for get_events, matches InMemoryAuditLog.by_workflow signature."""
        return self.get_events(workflow_id)
