"""政策问答会话生命周期服务（Issue #30 §四）

状态机：active ⇄ suspended；active → escalated →(resolve)→ active；任意非终态 → closed。
- 挂起/恢复由用户显式操作；升级创建医保办人工工单（复用 task_closure）；
- 轨迹读取按 session 所有权校验，非本人一律按不存在处理。

设计依据：docs/steering/政策问答-轨迹持久化与挂起升级恢复-设计-V1.0.md
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.data_platform.storage.policy_qa.trajectory_storage import (
    TrajectoryStorage,
    trajectory_storage as default_trajectory_storage,
)
from src.data_platform.storage.session.factory import session_storage
from src.runtime.task_closure import service as task_service

logger = logging.getLogger(__name__)

ACTIVE = "active"
SUSPENDED = "suspended"
ESCALATED = "escalated"
CLOSED = "closed"

# 合法状态转移表（设计 §四）
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ACTIVE: frozenset({SUSPENDED, ESCALATED, CLOSED}),
    SUSPENDED: frozenset({ACTIVE, CLOSED}),
    ESCALATED: frozenset({ACTIVE, CLOSED}),
    CLOSED: frozenset(),
}

ESCALATION_TASK_TYPE = "policy_qa_escalation"
ESCALATION_ROLE = "insurance_office"


class SessionLifecycleError(Exception):
    """生命周期操作失败（route 层转为 4xx）"""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _get_session(session_id: str):
    session = session_storage.get_session(session_id)
    if session is None:
        raise SessionLifecycleError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
    return session


def _assert_owner(session, user_id: str) -> None:
    """所有权校验：非本人一律按不存在处理（不泄露会话存在性）"""
    if user_id and session.user_id != user_id:
        raise SessionLifecycleError("SESSION_NOT_FOUND", "会话不存在", status_code=404)


def _transition(session_id: str, target: str, reason: str = ""):
    session = _get_session(session_id)
    current = session.status or ACTIVE
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise SessionLifecycleError(
            "INVALID_SESSION_TRANSITION",
            f"会话当前状态为 {current}，不允许转为 {target}",
        )
    updated = session_storage.update_session_status(session_id, target, reason)
    if updated is None:
        raise SessionLifecycleError("SESSION_NOT_FOUND", "会话不存在", status_code=404)
    return updated


# ── 状态机操作 ──────────────────────────────────────────────────

def suspend_session(session_id: str, user_id: str, reason: str = ""):
    session = _get_session(session_id)
    _assert_owner(session, user_id)
    return _transition(session_id, SUSPENDED, reason)


def resume_session(session_id: str, user_id: str):
    _assert_owner(_get_session(session_id), user_id)
    return _transition(session_id, ACTIVE, reason="resume")


def close_session(session_id: str, user_id: str, reason: str = ""):
    _assert_owner(_get_session(session_id), user_id)
    return _transition(session_id, CLOSED, reason)


def get_session_detail(session_id: str, user_id: str) -> dict[str, Any]:
    session = _get_session(session_id)
    _assert_owner(session, user_id)
    detail = {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "role": session.role,
        "status": session.status or ACTIVE,
        "status_reason": session.status_reason or "",
        "status_updated_at": session.status_updated_at or "",
        "created_at": session.created_at,
        "last_active": session.last_active,
        "turn_count": default_trajectory_storage.count_by_session(session_id),
        "escalation": None,
    }
    escalation = _latest_escalation(session_id)
    if escalation:
        detail["escalation"] = _escalation_public(escalation)
    return detail


# ── 升级闭环（设计 §3.3：复用 task_closure 工单）────────────────

def escalate_session(
    session_id: str,
    user_id: str,
    question: str,
    reason: str = "",
    qa_turn_id: str | None = None,
) -> dict[str, Any]:
    """升级问题至医保办：创建人工工单并把会话置为 escalated"""
    session = _get_session(session_id)
    _assert_owner(session, user_id)

    task_id = f"esc_{uuid.uuid4().hex}"
    task_service.create_task(
        task_id=task_id,
        task_type=ESCALATION_TASK_TYPE,
        description=(question or "")[:200] or "政策问答升级",
        responsible_role=ESCALATION_ROLE,
        # workflow_id=session_id：_latest_escalation 按会话反查工单
        workflow_id=session_id,
        input_data={
            "session_id": session_id,
            "question_excerpt": (question or "")[:500],
            "reason": (reason or "")[:500],
            "qa_turn_id": qa_turn_id or "",
            "user_id": session.user_id,
            "tenant_id": "default",
        },
        status="waiting_human_confirmation",
    )
    _transition(session_id, ESCALATED, reason or question[:200])
    return _escalation_public(_require_escalation(task_id))


def resolve_escalation(task_id: str, reply: str, resolved_by: str) -> dict[str, Any]:
    """医保办回复升级工单；回填回复后所属会话恢复 active"""
    task = task_service.get_task(task_id)
    if task is None or task.get("task_type") != ESCALATION_TASK_TYPE:
        raise SessionLifecycleError("ESCALATION_NOT_FOUND", "升级工单不存在", status_code=404)
    if task.get("status") == "completed":
        # 幂等：重复 resolve 返回已回填内容
        return _escalation_public(task)

    updated = dict(task)
    updated["status"] = "completed"
    updated["output_data"] = {**(task.get("output_data") or {}),
                              "escalation_reply": reply,
                              "resolved_by": resolved_by}
    task_service.save_task(updated)

    session_id = str((task.get("input_data") or {}).get("session_id") or "")
    if session_id:
        session = session_storage.get_session(session_id)
        if session is not None and (session.status or ACTIVE) == ESCALATED:
            session_storage.update_session_status(session_id, ACTIVE, "escalation_resolved")
    return _escalation_public(updated)


def _latest_escalation(session_id: str) -> dict[str, Any] | None:
    """会话最近一条升级工单（无按 session 枚举 task 的接口，按最近 ID 反查不可行时降级 None）"""
    # task_closure 目前只提供按 workflow_id 枚举；升级工单直接登记 workflow_id=session_id
    for task in task_service.list_tasks_by_workflow(session_id):
        if task.get("task_type") == ESCALATION_TASK_TYPE:
            return task
    return None


def _require_escalation(task_id: str) -> dict[str, Any]:
    task = task_service.get_task(task_id)
    if task is None:
        raise SessionLifecycleError("ESCALATION_NOT_FOUND", "升级工单不存在", status_code=404)
    return task


def _escalation_public(task: dict[str, Any]) -> dict[str, Any]:
    output = task.get("output_data") or {}
    input_data = task.get("input_data") or {}
    return {
        "task_id": task.get("task_id", ""),
        "status": task.get("status", ""),
        "question_excerpt": str(input_data.get("question_excerpt") or ""),
        "reason": str(input_data.get("reason") or ""),
        "reply": str(output.get("escalation_reply") or ""),
        "resolved_by": str(output.get("resolved_by") or ""),
        "created_at": str(task.get("created_at") or task.get("updated_at") or ""),
    }


# ── 轨迹读取（设计 §五）────────────────────────────────────────

def list_session_trajectory(
    session_id: str,
    user_id: str,
    storage: TrajectoryStorage | None = None,
) -> dict[str, Any]:
    """按会话回放全部轮次快照；校验所有权。"""
    session = _get_session(session_id)
    _assert_owner(session, user_id)
    store = storage or default_trajectory_storage
    turns = store.list_by_session(session_id)
    return {
        "session_id": session_id,
        "status": session.status or ACTIVE,
        "status_reason": session.status_reason or "",
        "turns": turns,
    }


def list_user_sessions(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """用户可恢复会话列表（含状态与轮次摘要）"""
    sessions = session_storage.list_sessions_by_user(user_id, limit=limit)
    items: list[dict[str, Any]] = []
    for s in sessions:
        turns = default_trajectory_storage.list_by_session(s.session_id)
        first_question = turns[0]["question"] if turns else ""
        last_question = turns[-1]["question"] if turns else ""
        items.append({
            "session_id": s.session_id,
            "status": s.status or ACTIVE,
            "status_reason": s.status_reason or "",
            "created_at": s.created_at,
            "last_active": s.last_active,
            "turn_count": len(turns),
            "first_question_excerpt": first_question[:80],
            "last_question_excerpt": last_question[:80],
        })
    return items
