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
        # v3.0 可选字段
        user_id: str | None = None,
        session_id: str | None = None,
        role: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
        request_summary: dict[str, Any] | None = None,
        response_status: int | None = None,
        response_summary: dict[str, Any] | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Record an audit event.

        Supports both legacy (event_type/workflow_id/step_id/payload) and
        v3.0 gateway fields.
        """
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        request_summary_json = json.dumps(request_summary, ensure_ascii=False, sort_keys=True) if request_summary else None
        response_summary_json = json.dumps(response_summary, ensure_ascii=False, sort_keys=True) if response_summary else None
        sql = """insert into audit_logs
            (event_type, workflow_id, step_id, payload,
             user_id, session_id, role,
             request_path, request_method, request_summary,
             response_status, response_summary,
             client_ip, user_agent, duration_ms)
            values (%s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s)"""
        try:
            self._client.execute(sql, (
                event_type, workflow_id, step_id, payload_json,
                user_id, session_id, role,
                request_path, request_method, request_summary_json,
                response_status, response_summary_json,
                client_ip, user_agent, duration_ms,
            ))
        except RuntimeError:
            pass
        return {
            "event_type": event_type,
            "workflow_id": workflow_id,
            "step_id": step_id,
            "payload": payload or {},
        }

    @staticmethod
    def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        result: dict[str, Any] = {
            "event_type": row["event_type"],
            "workflow_id": row.get("workflow_id"),
            "step_id": row.get("step_id"),
            "payload": payload,
        }
        # v3.0 网关审计字段
        for field in ("user_id", "session_id", "role", "request_path", "request_method",
                      "response_status", "client_ip", "user_agent", "duration_ms"):
            if row.get(field) is not None:
                result[field] = row[field]
        for field in ("request_summary", "response_summary"):
            val = row.get(field)
            if val is not None:
                if isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                result[field] = val
        return result

    def get_events(self, workflow_id: str) -> list[dict[str, Any]]:
        """Retrieve all audit events for a workflow."""
        try:
            rows = self._client.execute(
                "select * from audit_logs where workflow_id = %s order by id asc",
                (workflow_id,),
            )
            return [self._row_to_dict(row) for row in rows]
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
