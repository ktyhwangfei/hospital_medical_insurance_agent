"""Policy QA 历史查询服务

聚合 sessions、workflows、tasks 三张表的数据，
返回完整的问答历史：用户问题 + 执行步骤 + MCP/LLM/Skill 调用详情。
"""

from __future__ import annotations

import logging
from typing import Any

from src.data_platform.storage.session.factory import session_storage
from src.data_platform.storage.postgresql.workflow_store import PostgreSQLWorkflowStore
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.config.production import DATABASE_URL
from src.runtime.task_closure.service import list_tasks_by_workflow

logger = logging.getLogger(__name__)

_workflow_store: PostgreSQLWorkflowStore | None = None


def _get_wf_store() -> PostgreSQLWorkflowStore:
    global _workflow_store
    if _workflow_store is None:
        try:
            client = PostgreSQLClient(DATABASE_URL)
            _workflow_store = PostgreSQLWorkflowStore(client)
        except Exception as e:
            logger.warning(f"Failed to init workflow store: {e}")
            _workflow_store = PostgreSQLWorkflowStore(PostgreSQLClient(DATABASE_URL))
    return _workflow_store


def _sanitize_task(task: dict[str, Any]) -> dict[str, Any]:
    """清洗 task 数据，转换 JSON 字段，去掉过大的 output"""
    import json as _json
    result = {
        "task_id": task.get("task_id", ""),
        "task_type": task.get("task_type", ""),
        "status": task.get("status", ""),
        "description": task.get("description", ""),
        "executor_type": task.get("executor_type", ""),
        "step_id": task.get("step_id"),
        "duration_ms": task.get("duration_ms"),
        "error_message": task.get("error_message"),
        "created_at": _to_str(task.get("created_at")),
    }

    # 需要完整保留的字段（不截断）
    _FULL_FIELDS = {"SQL语句", "SQL参数", "返回样例", "返回字段", "patient_view", "office_view"}

    def _smart_truncate(k: str, v: Any) -> Any:
        if k in _FULL_FIELDS:
            return v  # 完整保留
        return _truncate(v)

    # 解析 input_data
    inp = task.get("input_data")
    if isinstance(inp, str):
        try: inp = _json.loads(inp)
        except: pass
    if isinstance(inp, dict):
        result["input_data"] = {k: _smart_truncate(k, v) for k, v in inp.items()}
    else:
        result["input_data"] = {}

    # 解析 output_data（截断长文本）
    out = task.get("output_data")
    if isinstance(out, str):
        try: out = _json.loads(out)
        except: pass
    if isinstance(out, dict):
        result["output_data"] = {k: _smart_truncate(k, v) for k, v in out.items()}
    else:
        result["output_data"] = {}

    return result


def _to_str(val: Any) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _truncate(val: Any, max_len: int = 500) -> Any:
    """截断长文本"""
    if isinstance(val, str) and len(val) > max_len:
        return val[:max_len] + "..."
    if isinstance(val, dict):
        return {k: _truncate(v, max_len) for k, v in val.items()}
    if isinstance(val, list) and len(val) > 10:
        return [_truncate(v, max_len) for v in val[:10]] + ["..."]
    return val


def get_qa_history(
    user_id: str | None = None,
    scenario: str = "policy_qa",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """获取 QA 历史，含 sessions + workflows + tasks 全量数据"""
    try:
        if user_id:
            sessions = session_storage.list_sessions_by_user(user_id, limit=200, offset=0)
        else:
            sessions = session_storage.list_sessions(limit=200, offset=0)
    except Exception as e:
        logger.warning(f"Failed to list sessions: {e}")
        sessions = []

    try:
        all_workflows = _get_wf_store().list_workflows()
    except Exception as e:
        logger.warning(f"Failed to list workflows: {e}")
        all_workflows = []

    # 按 session_id 索引
    workflows_by_session: dict[str, list[Any]] = {}
    for wf in all_workflows:
        sid = getattr(wf, "session_id", None)
        if sid is None:
            continue
        if wf.scenario == scenario or scenario == "*":
            workflows_by_session.setdefault(sid, []).append(wf)

    items: list[dict[str, Any]] = []
    for session in sessions:
        sid = session.session_id
        session_workflows = workflows_by_session.get(sid, [])
        if scenario != "*" and not session_workflows:
            continue

        workflows_data: list[dict[str, Any]] = []
        for wf in session_workflows:
            wf_dict = wf.model_dump() if hasattr(wf, "model_dump") else {}
            # 获取该 workflow 的所有 tasks
            tasks_raw = []
            try:
                tasks_raw = list_tasks_by_workflow(wf.workflow_id)
            except Exception as e:
                logger.warning(f"Failed to list tasks for {wf.workflow_id}: {e}")

            tasks_data = [_sanitize_task(t) for t in tasks_raw]

            workflows_data.append({
                "workflow_id": wf.workflow_id,
                "scenario": wf.scenario,
                "status": wf.status,
                "current_step": wf.current_step,
                "steps": wf_dict.get("steps", []),
                "tasks": tasks_data,
            })

        items.append({
            "session_id": sid,
            "user_id": session.user_id,
            "role": session.role,
            "created_at": session.created_at,
            "last_active": session.last_active,
            "workflows": workflows_data,
        })

    items.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    total = len(items)
    paged = items[offset:offset + limit]

    return {"total": total, "limit": limit, "offset": offset, "items": paged}


def get_qa_history_simple(
    user_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return get_qa_history(user_id=user_id, scenario="policy_qa", limit=limit, offset=offset)
