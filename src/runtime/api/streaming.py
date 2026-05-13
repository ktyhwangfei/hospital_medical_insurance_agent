from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4


def sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f'event: {event}\ndata: {payload}\n\n'


def ensure_knowledge_fields(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("citations", [])
    payload.setdefault("uncertainties", ["流式响应未获得额外知识依据"] if not payload.get("citations") else [])
    return payload


# ── 流式事件类型常量 ────────────────────────────────────────────
STREAM_EVENT_START = "stream:start"
STREAM_EVENT_STEP = "stream:step"
STREAM_EVENT_INTENT_TRACE = "stream:intent_trace"
STREAM_EVENT_DELTA = "stream:delta"
STREAM_EVENT_TOOL_CALL = "stream:tool_call"
STREAM_EVENT_TOOL_RESULT = "stream:tool_result"
STREAM_EVENT_FINAL = "stream:final"
STREAM_EVENT_ERROR = "stream:error"
STREAM_EVENT_DONE = "stream:done"


# ── 流式事件辅助函数 ────────────────────────────────────────────

def ensure_streaming_fields(payload: dict) -> dict:
    """确保流式事件负载包含 request_id / citations / uncertainties / event_timestamp 字段。

    返回一个新字典，不修改原始传入的 payload。
    """
    result = payload.copy()
    result.setdefault("request_id", "")
    result.setdefault("citations", [])
    result.setdefault("uncertainties", [])
    result.setdefault("event_timestamp", datetime.utcnow().isoformat())
    return result


def format_tool_call_event(call_id: str, tool_name: str, params: dict) -> dict:
    """格式化工具调用事件负载。"""
    return {
        "call_id": call_id,
        "tool_name": tool_name,
        "params": params,
    }


def format_tool_result_event(call_id: str, result: dict, duration_ms: int) -> dict:
    """格式化工具结果事件负载。"""
    return {
        "call_id": call_id,
        "result": result,
        "duration_ms": duration_ms,
    }


def generate_request_id() -> str:
    """生成请求 ID（uuid4 hex 前 12 字符）。"""
    return uuid4().hex[:12]


def generate_call_id() -> str:
    """生成调用 ID（uuid4 hex 前 8 字符）。"""
    return uuid4().hex[:8]
