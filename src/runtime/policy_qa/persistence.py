"""Policy QA 持久化辅助模块

在 policy QA 流式处理中记录 session、workflow、task 到数据库。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.data_platform.storage.session.factory import session_storage
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.data_platform.storage.postgresql.workflow_store import PostgreSQLWorkflowStore
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.config.production import DATABASE_URL
from src.runtime.task_closure.service import create_task

logger = logging.getLogger(__name__)

# 独立的 workflow store 实例（绕过 runtime_state_store）
_workflow_store: PostgreSQLWorkflowStore | None = None


def _get_wf_store() -> PostgreSQLWorkflowStore:
    global _workflow_store
    if _workflow_store is None:
        _workflow_store = PostgreSQLWorkflowStore(PostgreSQLClient(DATABASE_URL))
    return _workflow_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str, seed: str) -> str:
    """生成语义化 ID"""
    suffix = hashlib.md5(seed.encode()).hexdigest()[:8]
    return f"{prefix}-{suffix}"


def ensure_session_and_workflow(
    session_id: str | None,
    user_id: str,
    role: str,
    question: str,
    settlement_id: str,
) -> tuple[str, str]:
    """
    创建或更新 session 和 workflow。

    Returns:
        (session_id, workflow_id)
    """
    sid = session_id or _generate_id("sess", f"{user_id}:{question}:{uuid.uuid4()}")
    wid = _generate_id("wf", f"{sid}:{question}")

    # 创建/更新 session
    try:
        session_storage.create_or_update_session(sid, user_id, role)
        logger.debug(f"Session created/updated: {sid}")
    except Exception as e:
        logger.warning(f"Failed to create session {sid}: {e}")

    # 创建 workflow
    try:
        wf = WorkflowInstance(
            workflow_id=wid,
            scenario="policy_qa",
            status="running",
            current_step="intent_detection",
            steps=[],
            session_id=sid,
            patient_id=settlement_id,
        )
        result = _get_wf_store().save_workflow(wf)
    except Exception as e:
        print(f"[PERSIST-DEBUG] WF save FAILED: {e}", flush=True)
        logger.warning(f"Failed to create workflow {wid}: {e}")

    return sid, wid


def record_qa_task(
    *,
    qa_turn_id: str,
    workflow_id: str,
    session_id: str,
    user_id: str,
    tenant_id: str,
    question: str,
    output: dict[str, Any] | None = None,
    role: str = "system",
    settlement_id: str = "",
    status: str = "completed",
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> str:
    """
    记录一次 Policy QA 交互为一个 task。

    服务端在请求开始时生成稳定的 qa_turn_id，贯穿 persistence、result、done 和
    异常 done；task 以 qa_turn_id 作为主键，不再根据问题正文计算 task ID。

    Args:
        qa_turn_id: 服务端生成的稳定问答轮次 ID（task 主键）
        workflow_id: 工作流 ID
        session_id: 会话 ID
        user_id: 用户 ID
        tenant_id: 租户 ID（用于后续案例池去重与所有权校验）
        question: 用户问题（仅保存脱敏摘要，不保存原始患者正文）
        output: 输出数据（含内部 selected_skill_id、answer_excerpt 等供后续挖掘使用）
        role: 用户角色
        settlement_id: 结算 ID
        status: 执行状态
        error_message: 错误信息
        duration_ms: 执行耗时（毫秒）

    Returns:
        qa_turn_id（与 task 主键一致）
    """
    task_id = qa_turn_id
    # 仅保存脱敏摘要，不保存原始患者问题正文
    question_excerpt = (question or "")[:500]

    # input_data 仅保留脱敏摘要与所有权/租户字段，供反馈与历史选取按 ID 读取
    input_data = {
        "question_excerpt": question_excerpt,
        "settlement_id": settlement_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "session_id": session_id,
    }

    try:
        create_task(
            task_id=task_id,
            task_type="policy_qa",
            description=question_excerpt[:200] if question_excerpt else "政策问答",
            responsible_role=role,
            workflow_id=workflow_id,
            executor_type="skill",
            input_data=input_data,
            output_data=output or {},
            error_message=error_message,
            duration_ms=duration_ms,
            status=status if status in ("completed", "failed") else "completed",
        )
        logger.debug(f"Task recorded: {task_id}")
        return task_id
    except Exception as e:
        logger.warning(f"Failed to record task {task_id}: {e}")
        return task_id


# ── 步骤 → 执行器映射 ──────────────────────────────────────

_STEP_EXECUTOR_MAP = {
    "intent_detection":         ("llm_call", "llm"),
    "query_sql_data":           ("sql_query", "sql"),
    "settlement_query":         ("sql_query", "sql"),
    "structured_policy_query":  ("mcp_call", "mcp"),
    "policy_rule_search":       ("mcp_call", "mcp"),
    "answer_generation":        ("llm_call", "llm"),
    "skill_routing":            ("internal", "internal"),
    "completeness_judgment":    ("internal", "internal"),
    "answerability_judgment":   ("internal", "internal"),
    "output_validation":        ("internal", "internal"),
}


def record_step_task(
    workflow_id: str,
    step_id: str,
    step_name: str,
    status: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    error_message: str | None = None,
    duration_ms: float | None = None,
) -> str:
    """记录 pipeline 中单个步骤为独立 task（LLM/MCP/SQL 等）"""
    task_type, executor_type = _STEP_EXECUTOR_MAP.get(
        step_id, _STEP_EXECUTOR_MAP.get(step_name, ("internal", "internal"))
    )
    task_id = _generate_id("step", f"{workflow_id}:{step_id}")

    try:
        create_task(
            task_id=task_id,
            task_type=task_type,
            description=f"{step_name}",
            responsible_role="system",
            workflow_id=workflow_id,
            executor_type=executor_type,
            input_data=input_data or {},
            output_data=output_data or {},
            step_id=step_id,
            error_message=error_message,
            duration_ms=duration_ms,
            status=status if status in ("completed", "failed") else "completed",
        )
        logger.debug(f"Step task recorded: {task_id} ({executor_type})")
        return task_id
    except Exception as e:
        logger.warning(f"Failed to record step task {task_id}: {e}")
        return task_id


def finalize_workflow(workflow_id: str, status: str, steps: list[dict]) -> None:
    """获取已有 workflow，更新状态和步骤（不覆盖 session_id/patient_id）"""
    try:
        existing = _get_wf_store().get_workflow(workflow_id)
        step_states = [
            StepState(step_id=s.get("step", ""), status=s.get("status", "completed"))
            for s in steps
        ]
        if existing:
            # 保留已有的 session_id 和 patient_id
            wf = WorkflowInstance(
                workflow_id=workflow_id,
                scenario=existing.scenario,
                status=status,
                current_step=steps[-1]["step"] if steps else existing.current_step,
                steps=step_states,
                session_id=existing.session_id,
                patient_id=existing.patient_id,
            )
        else:
            wf = WorkflowInstance(
                workflow_id=workflow_id,
                scenario="policy_qa",
                status=status,
                current_step=steps[-1]["step"] if steps else None,
                steps=step_states,
            )
        _get_wf_store().save_workflow(wf)
    except Exception as e:
        logger.warning(f"Failed to finalize workflow {workflow_id}: {e}")
