from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .streaming import (
    STREAM_EVENT_DELTA,
    STREAM_EVENT_DONE,
    STREAM_EVENT_ERROR,
    STREAM_EVENT_FINAL,
    STREAM_EVENT_INTENT_TRACE,
    STREAM_EVENT_START,
    STREAM_EVENT_STEP,
    STREAM_EVENT_TOOL_CALL,
    STREAM_EVENT_TOOL_RESULT,
    ensure_streaming_fields,
    format_tool_call_event,
    format_tool_result_event,
    generate_request_id,
    sse_event,
)


class StreamingEmitter:
    """流式事件发射器，封装 SSE 事件生成逻辑。

    接收一个同步的 yield 函数，所有 emit_* 方法通过该函数发送格式化后的 SSE 字符串。
    每个事件负载自动附加 request_id 和 event_timestamp 公共字段。
    """

    def __init__(self, yield_fn: Callable[[str], None]) -> None:
        self._yield = yield_fn
        self._request_id = generate_request_id()

    def _build_payload(self, extra: dict | None = None) -> dict:
        """构建包含公共字段的事件负载。"""
        payload: dict = {
            "request_id": self._request_id,
            "event_timestamp": datetime.utcnow().isoformat(),
        }
        if extra:
            payload.update(extra)
        return payload

    def emit_start(self, intent: str, confidence: float) -> None:
        """发射 stream:start 事件，标识流开始并传递识别的意图。"""
        payload = self._build_payload({"intent": intent, "confidence": confidence})
        self._yield(sse_event(STREAM_EVENT_START, payload))

    def emit_step(self, step: str, message: str) -> None:
        """发射 stream:step 事件，标识推理或处理步骤。"""
        payload = self._build_payload({"step": step, "message": message})
        self._yield(sse_event(STREAM_EVENT_STEP, payload))

    def emit_intent_trace(self, trace: dict) -> None:
        """发射 stream:intent_trace 事件，传递意图识别过程的详细追溯信息。"""
        payload = self._build_payload({"trace": trace})
        self._yield(sse_event(STREAM_EVENT_INTENT_TRACE, payload))

    def emit_delta(self, content: str) -> None:
        """发射 stream:delta 事件，推送逐片生成的文本内容。"""
        payload = self._build_payload({"content": content})
        self._yield(sse_event(STREAM_EVENT_DELTA, payload))

    def emit_tool_call(self, call_id: str, tool_name: str, params: dict) -> None:
        """发射 stream:tool_call 事件，通知客户端即将发起工具调用。"""
        payload = self._build_payload(format_tool_call_event(call_id, tool_name, params))
        self._yield(sse_event(STREAM_EVENT_TOOL_CALL, payload))

    def emit_tool_result(self, call_id: str, result: dict, duration_ms: int) -> None:
        """发射 stream:tool_result 事件，传递工具调用的返回结果。"""
        payload = self._build_payload(format_tool_result_event(call_id, result, duration_ms))
        self._yield(sse_event(STREAM_EVENT_TOOL_RESULT, payload))

    def emit_final(self, response: dict) -> None:
        """发射 stream:final 事件，传递最终的完整响应内容。"""
        base = self._build_payload({"response": response})
        payload = ensure_streaming_fields(base)
        self._yield(sse_event(STREAM_EVENT_FINAL, payload))

    def emit_error(self, error: dict) -> None:
        """发射 stream:error 事件，传递流式过程中的错误信息。"""
        payload = self._build_payload({"error": error})
        self._yield(sse_event(STREAM_EVENT_ERROR, payload))

    def emit_done(self) -> None:
        """发射 stream:done 事件，标识流式响应结束。"""
        payload = self._build_payload()
        self._yield(sse_event(STREAM_EVENT_DONE, payload))
