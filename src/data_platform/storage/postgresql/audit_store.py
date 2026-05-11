import json
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.postgresql.client import PostgreSQLClient


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PostgreSQLAuditStore:
    """PostgreSQL-backed audit log store matching InMemoryAuditLog interface."""

    def __init__(self, client: PostgreSQLClient):
        self._client = client

    def ensure_tables(self) -> None:
        """Create the audit_logs table if it does not exist."""
        self._client.execute("create table if not exists audit_logs (id serial primary key, event_type varchar(64) not null, workflow_id varchar(128), step_id varchar(128), payload json not null default '{}', created_at timestamptz not null default current_timestamp)")

    def record(
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

    def by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
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
