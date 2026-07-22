import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _create_task_store():
    """创建任务存储（使用PostgreSQL，失败时回退到内存实现）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    
    if not use_memory:
        try:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient
            from src.runtime.task_closure.postgresql_store import PostgreSQLTaskStore
            client = PostgreSQLClient(DATABASE_URL)
            logger.info("Using PostgreSQL task store")
            return PostgreSQLTaskStore(client)
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL task store, falling back to in-memory: {e}")
    
    # 内存实现回退
    class InMemoryTaskStore:
        def __init__(self):
            self._tasks: dict[str, dict[str, Any]] = {}

        def save_task(self, task: dict[str, Any]) -> dict[str, Any]:
            self._tasks[task['task_id']] = task
            return task

        def get_task(self, task_id: str) -> dict[str, Any] | None:
            return self._tasks.get(task_id)

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
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            task: dict[str, Any] = {
                "task_id": task_id,
                "task_type": task_type,
                "status": status,
                "description": description,
                "responsible_role": responsible_role,
                "workflow_id": workflow_id,
                "updated_at": now,
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
            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            updated = dict(task)
            updated["status"] = "confirmed" if action == "confirm" else "rejected"
            updated["confirmed_by"] = user_id
            updated["confirmed_at"] = now
            updated["reason"] = reason
            updated["updated_at"] = now
            return self.save_task(updated)

        def build_pending_task(
            self,
            task_id: str,
            task_type: str,
            description: str,
            responsible_role: str,
        ) -> dict[str, Any]:
            return self.create_task(task_id, task_type, description, responsible_role)

        def list_tasks_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
            return [t for t in self._tasks.values() if t.get("workflow_id") == workflow_id]
    
    logger.info("Using in-memory task store")
    return InMemoryTaskStore()


_task_store = _create_task_store()


def save_task(task: dict[str, Any]) -> dict[str, Any]:
    return _task_store.save_task(task)


def get_task(task_id: str) -> dict[str, Any] | None:
    return _task_store.get_task(task_id)


def create_task(
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
    return _task_store.create_task(
        task_id, task_type, description, responsible_role, workflow_id,
        executor_type=executor_type, input_data=input_data, output_data=output_data,
        step_id=step_id, error_message=error_message, duration_ms=duration_ms,
        status=status,
    )


def update_task_confirmation(
    task: dict[str, Any],
    action: str,
    user_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return _task_store.update_task_confirmation(task, action, user_id, reason)


def build_pending_task(
    task_id: str,
    task_type: str,
    description: str,
    responsible_role: str,
) -> dict[str, Any]:
    return _task_store.build_pending_task(task_id, task_type, description, responsible_role)


def list_tasks_by_workflow(workflow_id: str) -> list[dict[str, Any]]:
    return _task_store.list_tasks_by_workflow(workflow_id)
