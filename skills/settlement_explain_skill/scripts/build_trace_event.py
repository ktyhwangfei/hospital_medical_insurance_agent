"""
build_trace_event.py — 执行链路事件构建器

skill 执行过程中的每个步骤生成一个 trace_event。
14 个步骤对应 14 个 trace_event，按顺序生成。

用法：
    builder = TraceEventBuilder()
    builder.start("intent_detection", "意图识别")
    # ... 执行意图识别 ...
    builder.done(detail="识别为统筹自付", duration_ms=45)
    builder.start("query_sql_data", "查询结算数据")
    ...
    events = builder.to_list()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from typing import Any


@dataclass
class TraceEvent:
    """单条执行链路事件。"""
    step_id: str
    step_name: str
    step_number: int
    status: str                      # running / done / error / skipped
    duration_ms: float = 0.0
    detail: str = ""
    data: dict[str, Any] | None = None


_STEP_DEFINITIONS = [
    (1, "intent_detection", "意图识别"),
    (2, "fee_item_identification", "费用字段识别"),
    (3, "query_sql_data", "真实结算数据查询"),
    (4, "context_normalization", "结算上下文标准化"),
    (5, "policy_query_planning", "政策查询计划生成"),
    (6, "structured_policy_query", "结构化政策规则查询"),
    (7, "vector_fallback", "向量检索兜底"),
    (8, "policy_evidence_assembly", "政策证据组装"),
    (9, "completeness_judgment", "政策完整性判断"),
    (10, "answerability_judgment", "可回答性判断"),
    (11, "patient_view_generation", "患者视角生成"),
    (12, "office_view_generation", "医保办视角生成"),
    (13, "output_validation", "输出校验"),
    (14, "return_result", "返回结果"),
]


class TraceEventBuilder:
    """执行链路事件构建器。"""

    def __init__(self):
        self._events: list[TraceEvent] = []
        self._current: TraceEvent | None = None
        self._start_time: float = 0.0

    def start(self, step_id: str, step_name: str) -> TraceEvent:
        """开始一个步骤，返回 running 状态事件。"""
        if self._current:
            self._finish_current("skipped")
        step_def = next(
            (s for s in _STEP_DEFINITIONS if s[1] == step_id),
            (len(self._events) + 1, step_id, step_name),
        )
        self._current = TraceEvent(
            step_id=step_def[1],
            step_name=step_def[2],
            step_number=step_def[0],
            status="running",
        )
        self._start_time = time.time()
        return self._current

    def done(self, detail: str = "", data: dict[str, Any] | None = None) -> TraceEvent:
        """完成当前步骤，标记 done。"""
        return self._finish_current("done", detail, data)

    def error(self, detail: str = "") -> TraceEvent:
        """当前步骤出错。"""
        return self._finish_current("error", detail)

    def skip(self, step_id: str, step_name: str, reason: str = "") -> TraceEvent:
        """跳过一个步骤。"""
        event = TraceEvent(
            step_id=step_id,
            step_name=step_name,
            step_number=len(self._events) + 1,
            status="skipped",
            detail=reason,
        )
        self._events.append(event)
        self._current = None
        return event

    def _finish_current(
        self, status: str, detail: str = "", data: dict[str, Any] | None = None
    ) -> TraceEvent:
        if self._current is None:
            raise ValueError("No current event")
        self._current.status = status
        self._current.duration_ms = (time.time() - self._start_time) * 1000
        self._current.detail = detail
        if data:
            self._current.data = data
        self._events.append(self._current)
        self._current = None
        return self._events[-1]

    def to_list(self) -> list[dict[str, Any]]:
        """导出所有事件为 dict 列表。"""
        if self._current:
            self._finish_current("skipped")
        return [
            {
                "step_id": e.step_id,
                "step_name": e.step_name,
                "step_number": e.step_number,
                "status": e.status,
                "duration_ms": e.duration_ms,
                "detail": e.detail,
            }
            for e in self._events
        ]


# ── 命令行测试 ──────────────────────────────────────────────────

if __name__ == "__main__":
    builder = TraceEventBuilder()
    builder.start("intent_detection", "意图识别")
    builder.done(detail="识别为目标费用项: pooling_self_pay")
    builder.start("query_sql_data", "真实结算数据查询")
    builder.done(detail="seq=1671213, 查询 5 张表")
    builder.skip("vector_fallback", "向量检索兜底", reason="结构化查询已有结果")
    events = builder.to_list()
    for e in events:
        print(f"  {e['step_number']:2d}. {e['step_name']}: {e['status']} ({e['duration_ms']:.0f}ms) — {e['detail']}")
    print("OK")
