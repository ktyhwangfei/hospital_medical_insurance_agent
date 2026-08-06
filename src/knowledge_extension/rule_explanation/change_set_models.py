"""知识变更集模型（V4.1 §4.4 / §27.2）。

变更集 = AI 一次处理任务提交给人的完整成果（类似代码 PR）：
按"文档批次"聚合新增/修改/替代/失效/映射变化 + 质量报告 + 风险摘要。
阶段一（最小可信闭环）：按现有"文档→单元→提取"批次全量生成 additions，
无独立差异分析（差异放阶段二）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


ChangeItemType = Literal["ADD", "MODIFY", "REPLACE", "EXPIRE", "SEMANTIC_CHANGE"]
ChangeSetStatus = Literal[
    "DRAFT", "NEEDS_DECISION", "PENDING_REVIEW", "APPROVED", "REJECTED", "RETURNED",
    "PUBLISHED", "FAILED"
]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class ChangeSetItem(BaseModel):
    """单个变更项：变化前/后 + AI 推荐 + 证据 + 校验 + 风险 + 影响。"""

    item_id: str
    change_type: ChangeItemType
    rule_id: str
    unit_id: str
    doc_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ai_recommendation: str = "自动通过候选"
    reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    quality_checks: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "LOW"
    impact_scope: dict[str, Any] = Field(default_factory=dict)
    needs_human: bool = True


class ChangeSetQualityReport(BaseModel):
    source_fidelity: float | None = None
    structural_completeness: float | None = None
    semantic_consistency: float | None = None
    rule_consistency: float | None = None


class SourceUnitRevision(BaseModel):
    """候选结果所引用的精确政策单元修订。"""

    doc_id: str
    doc_title: str
    unit_id: str
    unit_revision_id: str
    path: list[str] = Field(default_factory=list)


class KnowledgeChangeSet(BaseModel):
    """知识变更集：一次文档批次处理提交给人的完整成果。"""

    change_set_id: str
    source_document_version_id: str
    doc_id: str
    doc_title: str
    build_task_id: str | None = None
    source_units: list[SourceUnitRevision] = Field(default_factory=list)
    semantic_contract_version: str | None = None
    supersedes_candidate_id: str | None = None
    status: ChangeSetStatus = "PENDING_REVIEW"
    summary: dict[str, int] = Field(default_factory=dict)
    items: list[ChangeSetItem] = Field(default_factory=list)
    quality_report: ChangeSetQualityReport = Field(default_factory=ChangeSetQualityReport)
    risk_summary: dict[str, int] = Field(default_factory=dict)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    review_decision: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
