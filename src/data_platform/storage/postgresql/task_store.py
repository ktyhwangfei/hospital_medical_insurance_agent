import json
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.postgresql.client import PostgreSQLClient


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
        task["confirmed_at"] = row["confirmed_at"]
    if row.get("reason") is not None:
        task["reason"] = row["reason"]
    if row.get("updated_at") is not None:
        task["updated_at"] = row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"]
    else:
        task["updated_at"] = _now()
    return task


class PostgreSQLTaskStore:
    """PostgreSQL-backed task store matching task_closure/service.py interface."""

    def __init__(self, client: PostgreSQLClient):
        self._client = client

    def ensure_tables(self) -> None:
        """Create the tasks table if it does not exist."""
        self._client.execute("create table if not exists tasks (task_id varchar(128) primary key, task_type varchar(64) not null, status varchar(32) not null default 'pending', description text, responsible_role varchar(64), workflow_id varchar(128), confirmed_by varchar(64), confirmed_at varchar(32), reason text, created_at timestamptz not null default current_timestamp, updated_at timestamptz not null default current_timestamp)")

    def save_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Insert or update a task."""
        now = _now()
        sql = """insert into tasks (task_id, task_type, status, description, responsible_role, workflow_id, confirmed_by, confirmed_at, reason, created_at, updated_at)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (task_id) do update set
    task_type = excluded.task_type,
    status = excluded.status,
    description = excluded.description,
    responsible_role = excluded.responsible_role,
    workflow_id = excluded.workflow_id,
    confirmed_by = excluded.confirmed_by,
    confirmed_at = excluded.confirmed_at,
    reason = excluded.reason,
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
    ) -> dict[str, Any]:
        """Create a new pending task."""
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "status": "pending",
            "description": description,
            "responsible_role": responsible_role,
            "workflow_id": workflow_id,
            "updated_at": _now(),
        }
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
