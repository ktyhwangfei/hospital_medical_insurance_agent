"""知识变更集聚合服务（V4.1 §6.1 步骤 12 / §27.2）。

阶段一（最小可信闭环）：按"文档批次"聚合现有 pipeline 产物——读取审核通过的单元
及其知识，全量生成 additions 变更项；无独立差异分析（差异/替代/失效放阶段二）。
风险分级用启发式（低置信/证据缺失/不确定项），为阶段二批量审核做准备。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    ChangeSetQualityReport,
    KnowledgeChangeSet,
    SourceUnitRevision,
)
from src.knowledge_extension.rule_explanation.change_set_store import ChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import ApprovedUnit
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)


def change_set_id_for(doc_id: str) -> str:
    digest = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:16]
    return f"CS_{digest}"


def change_set_id_for_task(task_id: str) -> str:
    """使用任务命名空间派生候选 ID，避免与旧文档 ID 碰撞。"""
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]
    return f"CS_TASK_{digest}"


def _risk_level(knowledge) -> str:
    """启发式风险分级：证据缺失→HIGH；低置信或不确定→MEDIUM；否则 LOW。"""
    overall = (knowledge.confidence.overall or 0) if knowledge.confidence else 0
    has_evidence = bool(knowledge.citations and knowledge.citations[0].evidence)
    if not has_evidence:
        return "HIGH"
    if overall < 0.8 or getattr(knowledge.confidence, "uncertainties", None):
        return "MEDIUM"
    return "LOW"


@dataclass(frozen=True)
class SelectedKnowledgeUnit:
    """一个显式选中的知识单元及其来源修订。"""

    unit: ApprovedUnit
    source_revision: SourceUnitRevision


def _aggregate_units(
    units: list[ApprovedUnit],
) -> tuple[list[ChangeSetItem], ChangeSetQualityReport, dict[str, int]]:
    items: list[ChangeSetItem] = []
    fidelity: list[float] = []
    completeness: list[float] = []
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for unit in units:
        for knowledge in unit.knowledge:
            risk = _risk_level(knowledge)
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
            confidence = knowledge.confidence
            fidelity.append(confidence.source_fidelity)
            completeness.append(confidence.completeness)
            items.append(ChangeSetItem(
                item_id=f"ci_{knowledge.knowledge_id}",
                change_type="ADD",
                rule_id=knowledge.knowledge_id,
                unit_id=unit.unit_id,
                doc_id=unit.doc_id,
                after=knowledge.model_dump(),
                ai_recommendation="自动通过候选（阶段一全量人工审核）",
                reason="初始批次：由文档→单元→提取产物聚合",
                evidence_ids=[e.evidence_id for e in knowledge.evidences],
                quality_checks=["source_fidelity", "structural_completeness"],
                risk_level=risk,
                impact_scope={
                    "topic_concept": knowledge.topic_concept,
                    "rule_type_label": knowledge.rule_type_label,
                },
                needs_human=risk != "LOW",
            ))
    quality_report = ChangeSetQualityReport(
        source_fidelity=round(sum(fidelity) / len(fidelity), 4) if fidelity else None,
        structural_completeness=(
            round(sum(completeness) / len(completeness), 4) if completeness else None
        ),
    )
    return items, quality_report, risk_counts


class ChangeSetService:
    """按文档批次聚合知识变更集。"""

    def __init__(
        self,
        workbench_service: KnowledgeWorkbenchService,
        store: ChangeSetStore,
    ) -> None:
        self._workbench = workbench_service
        self._store = store

    def build_for_document(self, doc_id: str) -> KnowledgeChangeSet:
        """基于当前文档审核通过的单元/知识，构建（或重建）该文档的变更集。"""
        document = self._workbench.get_document(doc_id)
        items, quality_report, risk_counts = _aggregate_units(document.units)

        change_set = KnowledgeChangeSet(
            change_set_id=change_set_id_for(doc_id),
            source_document_version_id=f"{doc_id}",
            doc_id=doc_id,
            doc_title=document.doc_title,
            status="PENDING_REVIEW",
            summary={"additions": len(items), "modifications": 0, "replacements": 0,
                     "expirations": 0, "unchanged": 0},
            items=items,
            quality_report=quality_report,
            risk_summary=risk_counts,
        )
        return self._store.save(change_set)

    def build_for_units(
        self,
        *,
        task_id: str,
        task_name: str,
        units: list[SelectedKnowledgeUnit],
        semantic_contract_version: str,
        supersedes_candidate_id: str | None = None,
    ) -> KnowledgeChangeSet:
        """仅聚合任务显式选中的单元，生成独立候选结果。"""
        if not units:
            raise ValueError("构建任务至少需要一个已审核单元")
        if not task_id.strip():
            raise ValueError("构建任务 ID 不能为空")
        for selection in units:
            if selection.unit.doc_id != selection.source_revision.doc_id:
                raise ValueError("来源修订的文档 ID 与所选单元不一致")
            if selection.unit.unit_id != selection.source_revision.unit_id:
                raise ValueError("来源修订的单元 ID 与所选单元不一致")

        # 以入参选择为唯一聚合边界，不回查或补全整篇文档。
        selected_units = [selection.unit for selection in units]
        items, quality_report, risk_counts = _aggregate_units(selected_units)
        source_units = [selection.source_revision for selection in units]
        source_doc_ids = {source.doc_id for source in source_units}
        doc_id = next(iter(source_doc_ids)) if len(source_doc_ids) == 1 else "MULTI"
        change_set = KnowledgeChangeSet(
            change_set_id=change_set_id_for_task(task_id),
            source_document_version_id="|".join(sorted(source_doc_ids)),
            doc_id=doc_id,
            doc_title=task_name,
            build_task_id=task_id,
            source_units=source_units,
            semantic_contract_version=semantic_contract_version,
            supersedes_candidate_id=supersedes_candidate_id,
            status="PENDING_REVIEW",
            summary={"additions": len(items), "modifications": 0, "replacements": 0,
                     "expirations": 0, "unchanged": 0},
            items=items,
            quality_report=quality_report,
            risk_summary=risk_counts,
        )
        return self._store.save(change_set)

    def list_change_sets(self, doc_id: str = "") -> list[KnowledgeChangeSet]:
        return self._store.list(doc_id)

    def get_change_set(self, change_set_id: str) -> KnowledgeChangeSet | None:
        return self._store.get(change_set_id)

    def fail_candidate(
        self,
        change_set_id: str,
        *,
        reason: str,
    ) -> KnowledgeChangeSet:
        """将构建后无法进入任务审核流的已持久化候选置为不可审核。"""
        self._require(change_set_id)
        failed = self._store.update_status(
            change_set_id,
            "FAILED",
            {"action": "build_failed", "reason": reason},
        )
        if failed is None:
            raise ValueError(f"变更集不存在: {change_set_id}")
        return failed

    def submit_review(self, change_set_id: str, reviewer: str) -> KnowledgeChangeSet:
        change_set = self._require(change_set_id)
        if change_set.status != "DRAFT":
            raise ValueError(f"变更集 {change_set_id} 状态为 {change_set.status}，仅 DRAFT 可提交审核")
        return self._store.update_status(change_set_id, "PENDING_REVIEW")

    def approve(self, change_set_id: str, reviewer: str, note: str = "") -> KnowledgeChangeSet:
        return self._transition_status(
            change_set_id,
            allowed_statuses={"PENDING_REVIEW", "NEEDS_DECISION"},
            target_status="APPROVED",
            invalid_action="通过",
            decision={
                "action": "approved", "reviewed_by": reviewer, "note": note,
            },
        )

    def reject(self, change_set_id: str, reviewer: str, reason: str) -> KnowledgeChangeSet:
        return self._transition_status(
            change_set_id,
            allowed_statuses={"PENDING_REVIEW"},
            target_status="REJECTED",
            invalid_action="驳回",
            decision={
                "action": "rejected", "reviewed_by": reviewer, "reason": reason,
            },
        )

    def return_for_rebuild(
        self,
        change_set_id: str,
        reviewer: str,
        reason: str,
    ) -> KnowledgeChangeSet:
        """将待审或已通过候选退回，等待新的构建任务重新生成。"""
        return self._transition_status(
            change_set_id,
            allowed_statuses={"PENDING_REVIEW"},
            target_status="RETURNED",
            invalid_action="退回",
            decision={
                "action": "returned", "reviewed_by": reviewer, "reason": reason,
            },
        )

    def mark_published(
        self,
        change_set_id: str,
    ) -> KnowledgeChangeSet:
        """记录审核通过候选已进入正式发布快照。"""
        return self._transition_status(
            change_set_id,
            allowed_statuses={"APPROVED"},
            target_status="PUBLISHED",
            invalid_action="发布",
        )

    def reprocess(self, change_set_id: str, doc_id: str | None = None) -> KnowledgeChangeSet:
        """退回 AI 重处理：阶段一按原文档批次重建变更集（差异分析放阶段二）。"""
        change_set = self._require(change_set_id)
        return self.build_for_document(doc_id or change_set.doc_id)

    def _require(self, change_set_id: str) -> KnowledgeChangeSet:
        change_set = self._store.get(change_set_id)
        if change_set is None:
            raise ValueError(f"变更集不存在: {change_set_id}")
        return change_set

    def _transition_status(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        invalid_action: str,
        decision: dict | None = None,
    ) -> KnowledgeChangeSet:
        changed = self._store.transition_status(
            change_set_id,
            allowed_statuses=allowed_statuses,
            target_status=target_status,
            decision=decision,
        )
        if changed is not None:
            return changed
        current = self._require(change_set_id)
        if current.status == target_status:
            return current
        raise ValueError(
            f"变更集 {change_set_id} 状态为 {current.status}，不可{invalid_action}"
        )
