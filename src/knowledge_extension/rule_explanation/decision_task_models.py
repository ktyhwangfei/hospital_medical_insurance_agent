"""人工决策任务模型（V4.1 §4.5 / §10）。

AI 不确定的问题不留在普通知识列表中，而是生成明确的决策任务：
问题 / AI 推荐 / 候选 / 证据 / 风险 / 影响范围 / 阻塞范围 / 人工决策。
阶段一：从变更集启发式生成（证据不足 / 值域未映射 / 低置信）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DecisionTaskType = Literal[
    "NEW_CONCEPT", "NEW_STANDARD_VALUE", "LOW_CONFIDENCE_MAPPING", "INSUFFICIENT_EVIDENCE",
    "RULE_SPLIT_MERGE", "COMPLEX_FORMULA", "EXCEPTION_RULE", "REPLACEMENT", "CONFLICT",
    "PUBLISH_IMPACT", "REVIEW_CONFIRM",
]
TaskStatus = Literal["PENDING", "RESOLVED", "SKIPPED"]


class DecisionTask(BaseModel):
    """一个明确的待人工决策问题。"""

    task_id: str
    task_type: DecisionTaskType
    question: str
    recommended_option: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "MEDIUM"  # LOW / MEDIUM / HIGH / CRITICAL
    affected_items: dict[str, Any] = Field(default_factory=dict)
    blocking_scope: str | None = None  # change_set_id / rule_id
    status: TaskStatus = "PENDING"
    decision: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
