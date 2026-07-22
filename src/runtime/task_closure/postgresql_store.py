import json
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.postgresql.client import PostgreSQLClient


def _now() -> datetime:
    return datetime.now(UTC)


def _row_to_task(row: dict[str, Any]) -> dict[str, Any]:
    task: dict[str, Any] = {
        "task_id": row["task_id"],
        "task_type": row["task_type"],
        "status": row["status"],
    }
    if row.get("description") is not None:
        task["description"] = row["description"]
    if row.get("responsible_role") is not None:
        task["responsible_role"] = row["responsible_role"]
    if row.get("workflow_id") is not None:
        task["workflow_id"] = row["workflow_id"]
    if row.get("confirmed_by") is not None:
        task["confirmed_by"] = row["confirmed_by"]
    if row.get("confirmed_at") is not None:
        task["confirmed_at"] = row["confirmed_at"].isoformat() if hasattr(row["confirmed_at"], "isoformat") else row["confirmed_at"]
    if row.get("reason") is not None:
        task["reason"] = row["reason"]
    if row.get("executor_type") is not None:
        task["executor_type"] = row["executor_type"]
    if row.get("input_data") is not None:
        task["input_data"] = row["input_data"]
    if row.get("output_data") is not None:
        task["output_data"] = row["output_data"]
    if row.get("step_id") is not None:
        task["step_id"] = row["step_id"]
    if row.get("error_message") is not None:
        task["error_message"] = row["error_message"]
    if row.get("duration_ms") is not None:
        task["duration_ms"] = row["duration_ms"]
    if row.get("updated_at") is not None:
        task["updated_at"] = row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"]
    else:
        task["updated_at"] = _now()
    return task


class PostgreSQLTaskStore:
    """PostgreSQL-backed task store matching task_closure/service.py function interface.

    Methods: save_task, get_task, create_task, update_task_confirmation, build_pending_task.
    Uses PostgreSQLClient from src.data_platform.storage.postgresql.
    Gracefully handles connection errors (returns None / does nothing on failure).
    """

    def __init__(self, client: PostgreSQLClient):
        self._client = client

    def _serialize(self, value: Any) -> Any:
        """Convert dict values to JSON strings for PostgreSQL JSONB columns.

        Returns '{}' for None to satisfy NOT NULL constraints on JSONB columns.
        """
        if value is None:
            return '{}'
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, default=str)
        return value

    def save_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Insert or update a task record."""
        now = _now()
        sql = """insert into tasks (task_id, task_type, status, description, responsible_role, workflow_id, confirmed_by, confirmed_at, reason, executor_type, input_data, output_data, step_id, error_message, duration_ms, created_at, updated_at)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (task_id) do update set
    task_type = excluded.task_type,
    status = excluded.status,
    description = excluded.description,
    responsible_role = excluded.responsible_role,
    workflow_id = excluded.workflow_id,
    confirmed_by = excluded.confirmed_by,
    confirmed_at = excluded.confirmed_at,
    reason = excluded.reason,
    executor_type = excluded.executor_type,
    input_data = excluded.input_data,
    output_data = excluded.output_data,
    step_id = excluded.step_id,
    error_message = excluded.error_message,
    duration_ms = excluded.duration_ms,
    updated_at = excluded.updated_at"""
        try:
            self._client.execute(
                sql,
                (
                    task["task_id"],
                    task.get("task_type", ""),
                    task.get("status", "pending"),
                    task.get("description"),
                    task.get("responsible_role"),
                    task.get("workflow_id"),
                    task.get("confirmed_by"),
                    task.get("confirmed_at"),
                    task.get("reason"),
                    task.get("executor_type"),
                    self._serialize(task.get("input_data")),
                    self._serialize(task.get("output_data")),
                    task.get("step_id"),
                    task.get("error_message"),
                    task.get("duration_ms"),
                    now,
                    now,
                ),
            )
        except RuntimeError:
            pass
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a task by ID."""
        try:
            rows = self._client.execute("select * from tasks where task_id = %s", (task_id,))
            if not rows:
                return None
            return _row_to_task(rows[0])
        except RuntimeError:
            return None

    def create_task(
        self,
        task_id: str,
        task_type: str,
        description: str,
        responsible_role: str,
        workflow_id: str | None = None,
        executor_type: str | None = None,
        input_data: dict | None = None,
        output_data: dict | None = None,
        step_id: str | None = None,
        error_message: str | None = None,
        duration_ms: float | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        """Create a new pending task."""
        task: dict[str, Any] = {
            "task_id": task_id,
            "task_type": task_type,
            "status": status,
            "description": description,
            "responsible_role": responsible_role,
            "workflow_id": workflow_id,
            "updated_at": _now(),
        }
        if executor_type is not None:
            task["executor_type"] = executor_type
        if input_data is not None:
            task["input_data"] = input_data
        if output_data is not None:
            task["output_data"] = output_data
        if step_id is not None:
            task["step_id"] = step_id
        if error_message is not None:
            task["error_message"] = error_message
        if duration_ms is not None:
            task["duration_ms"] = duration_ms
        return self.save_task(task)

    def update_task_confirmation(
        self,
        task: dict[str, Any],
        action: str,
        user_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Update task with confirmation or rejection."""
        updated = dict(task)
        updated["status"] = "confirmed" if action == "confirm" else "rejected"
        updated["confirmed_by"] = user_id
        updated["confirmed_at"] = _now()
        updated["reason"] = reason
        updated["updated_at"] = updated["confirmed_at"]
        return self.save_task(updated)

    def build_pending_task(
        self,
        task_id: str,
        task_type: str,
        description: str,
        responsible_role: str,
    ) -> dict[str, Any]:
        """Create a pending task (convenience wrapper)."""
        return self.create_task(task_id, task_type, description, responsible_role)

    def list_tasks_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        """List all tasks for a given workflow."""
        try:
            rows = self._client.execute(
                "SELECT * FROM tasks WHERE workflow_id = %s ORDER BY created_at ASC",
                (workflow_id,),
            )
            return [_row_to_task(r) for r in rows]
        except RuntimeError:
            return []
