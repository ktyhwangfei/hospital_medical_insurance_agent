"""已发布知识快照模型（V4.1 §4.6 / §27.4）。

Agent 运行时不读取草稿/候选/审核过程表，只读取经发布生成的不可变快照。
新发布产生新快照，不原地覆盖旧快照；支持回滚与替代血缘、审计。
阶段一：由现有 KnowledgeRelease promote（active）登记为快照。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PublishedSnapshot(BaseModel):
    """一份不可变已发布知识快照。"""

    snapshot_id: str
    doc_id: str | None = None
    policy_scope: dict[str, Any] = Field(default_factory=dict)
    semantic_contract_version: str | None = None
    rules_collection: str
    facts_collection: str
    source_change_set_id: str | None = None
    immutable: bool = True
    published_at: datetime = Field(default_factory=utc_now)
    published_by: str
    rollback_of: str | None = None
    replaced_by: str | None = None
