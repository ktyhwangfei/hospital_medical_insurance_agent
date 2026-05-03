from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def create_task(
    task_id: str,
    task_type: str,
    description: str,
    responsible_role: str,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_type": task_type,
        "status": "pending",
        "description": description,
        "responsible_role": responsible_role,
        "workflow_id": workflow_id,
        "updated_at": _now(),
    }


def update_task_confirmation(
    task: dict[str, Any],
    action: str,
    user_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    updated = dict(task)
    updated["status"] = "confirmed" if action == "confirm" else "rejected"
    updated["confirmed_by"] = user_id
    updated["confirmed_at"] = _now()
    updated["reason"] = reason
    updated["updated_at"] = updated["confirmed_at"]
    return updated


def build_pending_task(
    task_id: str,
    task_type: str,
    description: str,
    responsible_role: str,
) -> dict[str, Any]:
    return create_task(task_id, task_type, description, responsible_role)
