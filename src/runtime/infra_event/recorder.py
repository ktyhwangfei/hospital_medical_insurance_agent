"""基础设施事件记录器

在 ModelGateway、McpTransport、SQLDataFetcher 等层调用，
将 LLM/MCP/SQL 调用事件写入 PostgreSQL tasks 表。
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import time as _time
from datetime import datetime, timezone
from typing import Any

from src.runtime.infra_event.context import infra_context
from src.runtime.task_closure.service import create_task as _create_task

logger = logging.getLogger(__name__)

# 截断阈值
_MAX_STR_LEN = 2000
_MAX_DICT_LEN = 5000


def _generate_id(prefix: str, seed: str) -> str:
    suffix = hashlib.md5(seed.encode()).hexdigest()[:8]
    return f"{prefix}-{suffix}"


def _safe_truncate(val: Any, max_len: int = _MAX_STR_LEN) -> Any:
    """安全截断长文本"""
    if isinstance(val, str) and len(val) > max_len:
        return val[:max_len] + "...(truncated)"
    if isinstance(val, dict):
        s = _json.dumps(val, ensure_ascii=False, default=str)
        if len(s) > _MAX_DICT_LEN:
            return {"_truncated": True, "_original_len": len(s)}
        return val
    if isinstance(val, list) and len(val) > 20:
        return val[:20] + ["...(truncated)"]
    return val


def _safe_json_dumps(obj: Any) -> str:
    """安全 JSON 序列化"""
    try:
        return _json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)[:_MAX_STR_LEN]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_llm_call(
    model_name: str,
    scene: str,
    prompt_summary: str,
    response_summary: str,
    token_usage: dict[str, int] | None = None,
    latency_ms: float = 0,
    status: str = "completed",
    error_message: str | None = None,
) -> str | None:
    """记录一次 LLM 调用事件。

    Args:
        model_name: 模型名称（如 deepseek-v3）
        scene: 调用场景（如 intent_detection, answer_assembly）
        prompt_summary: prompt 摘要
        response_summary: 响应摘要
        token_usage: token 用量（prompt_tokens, completion_tokens, total_tokens）
        latency_ms: 耗时（毫秒）
        status: 状态（completed / failed）
        error_message: 错误信息

    Returns:
        task_id 或 None（失败时）
    """
    ctx = infra_context()
    seed = f"{ctx.session_id}:{scene}:{model_name}:{_time.time()}"
    task_id = _generate_id("llm", seed)

    input_data = {
        "model": model_name,
        "scene": scene,
        "prompt_summary": _safe_truncate(prompt_summary),
        "session_id": ctx.session_id,
        "workflow_id": ctx.workflow_id,
    }
    output_data = {
        "response_summary": _safe_truncate(response_summary),
        "token_usage": token_usage or {},
        "latency_ms": latency_ms,
    }

    try:
        _create_task(
            task_id=task_id,
            task_type="infra_llm_call",
            description=f"[LLM] {scene} → {model_name}",
            responsible_role="system",
            workflow_id=ctx.workflow_id or None,
            executor_type="llm",
            input_data=input_data,
            output_data=output_data,
            error_message=error_message,
            duration_ms=latency_ms,
            status=status if status in ("completed", "failed") else "completed",
        )
        logger.debug(f"Infra LLM event recorded: {task_id} ({model_name}, {scene})")
        return task_id
    except Exception as e:
        logger.warning(f"Failed to record infra LLM event: {e}")
        return None


def record_mcp_call(
    tool_name: str,
    server_id: str,
    arguments: dict[str, Any] | None = None,
    result_summary: str = "",
    duration_ms: float = 0,
    status: str = "completed",
    error_message: str | None = None,
) -> str | None:
    """记录一次 MCP 工具调用事件。

    Args:
        tool_name: 工具名称
        server_id: MCP 服务器 ID
        arguments: 调用参数
        result_summary: 结果摘要
        duration_ms: 耗时（毫秒）
        status: 状态（completed / failed）
        error_message: 错误信息

    Returns:
        task_id 或 None（失败时）
    """
    ctx = infra_context()
    seed = f"{ctx.session_id}:{server_id}:{tool_name}:{_time.time()}"
    task_id = _generate_id("mcp", seed)

    input_data = {
        "tool_name": tool_name,
        "server_id": server_id,
        "arguments": _safe_truncate(arguments or {}),
        "session_id": ctx.session_id,
        "workflow_id": ctx.workflow_id,
    }
    output_data = {
        "result_summary": _safe_truncate(result_summary),
        "duration_ms": duration_ms,
    }

    try:
        _create_task(
            task_id=task_id,
            task_type="infra_mcp_call",
            description=f"[MCP] {tool_name} @ {server_id}",
            responsible_role="system",
            workflow_id=ctx.workflow_id or None,
            executor_type="mcp",
            input_data=input_data,
            output_data=output_data,
            error_message=error_message,
            duration_ms=duration_ms,
            status=status if status in ("completed", "failed") else "completed",
        )
        logger.debug(f"Infra MCP event recorded: {task_id} ({tool_name} @ {server_id})")
        return task_id
    except Exception as e:
        logger.warning(f"Failed to record infra MCP event: {e}")
        return None


def record_sql_query(
    query_name: str,
    settlement_id: str = "",
    sql_summary: str = "",
    sql_text: str = "",
    params: dict[str, Any] | None = None,
    result_fields: list[str] | None = None,
    result_sample: dict[str, Any] | None = None,
    row_count: int = 0,
    duration_ms: float = 0,
    status: str = "completed",
    error_message: str | None = None,
) -> str | None:
    """记录一次 SQL 查询事件。

    Args:
        query_name: 查询名称/描述
        settlement_id: 结算 ID
        sql_summary: SQL 摘要（表名、关键字段）
        sql_text: ★ 实际 SQL 语句
        params: SQL 参数
        result_fields: 返回字段列表
        result_sample: 返回结果样例（前几条）
        row_count: 返回行数
        duration_ms: 耗时（毫秒）
        status: 状态（completed / failed）
        error_message: 错误信息

    Returns:
        task_id 或 None（失败时）
    """
    ctx = infra_context()
    seed = f"{ctx.session_id}:{query_name}:{settlement_id}:{_time.time()}"
    task_id = _generate_id("sql", seed)

    input_data = {
        "查询名称": query_name,
        "结算ID": settlement_id,
        "SQL语句": sql_text if sql_text else sql_summary,
        "SQL参数": _safe_truncate(params or {}),
        "session_id": ctx.session_id,
        "workflow_id": ctx.workflow_id,
    }
    output_data = {
        "返回行数": row_count,
        "返回字段": result_fields or [],
        "返回样例": result_sample or {},
        "耗时ms": duration_ms,
    }

    # 清理空值
    input_data = {k: v for k, v in input_data.items() if v not in ("", None, [], {})}
    output_data = {k: v for k, v in output_data.items() if v not in ("", None, [], {})}

    try:
        _create_task(
            task_id=task_id,
            task_type="infra_sql_query",
            description=f"[SQL] {query_name} (settlement={settlement_id})",
            responsible_role="system",
            workflow_id=ctx.workflow_id or None,
            executor_type="sql",
            input_data=input_data,
            output_data=output_data,
            error_message=error_message,
            duration_ms=duration_ms,
            status=status if status in ("completed", "failed") else "completed",
        )
        logger.debug(f"Infra SQL event recorded: {task_id} ({query_name})")
        return task_id
    except Exception as e:
        logger.warning(f"Failed to record infra SQL event: {e}")
        return None
