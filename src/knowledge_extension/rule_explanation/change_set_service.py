"""知识变更集聚合服务（V4.1 §6.1 步骤 12 / §27.2）。

阶段一（最小可信闭环）：按"文档批次"聚合现有 pipeline 产物——读取审核通过的单元
及其知识，全量生成 additions 变更项；无独立差异分析（差异/替代/失效放阶段二）。
风险分级用启发式（低置信/证据缺失/不确定项），为阶段二批量审核做准备。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.service import (
        PolicyCompilationService,
    )

from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    ChangeSetQualityReport,
    KnowledgeChangeSet,
    SourceUnitRevision,
)
from src.knowledge_extension.rule_explanation.change_set_store import ChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
    ReextractItemResult,
    ReextractReport,
)
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
        orchestrator: "PipelineOrchestrator | None" = None,
        compilation_service: "PolicyCompilationService | None" = None,
    ) -> None:
        self._workbench = workbench_service
        self._store = store
        self._orchestrator = orchestrator
        self._compilation_service = compilation_service

    def _get_orchestrator(self) -> "PipelineOrchestrator":
        """获取提取编排器（未注入时懒创建默认实例）。"""
        if self._orchestrator is None:
            from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
                PipelineOrchestrator,
            )
            self._orchestrator = PipelineOrchestrator()
        return self._orchestrator

    def build_for_document(self, doc_id: str) -> KnowledgeChangeSet:
        """基于当前文档审核通过的单元/知识，构建（或重建）该文档的变更集。"""
        document = self._workbench.get_document(doc_id)
        items, quality_report, risk_counts = _aggregate_units(document.units)
        items, blockers, compilation_blocked = self._compile_items(document.units, items)

        change_set = KnowledgeChangeSet(
            change_set_id=change_set_id_for(doc_id),
            source_document_version_id=f"{doc_id}",
            doc_id=doc_id,
            doc_title=document.doc_title,
            status="NEEDS_DECISION" if compilation_blocked else "PENDING_REVIEW",
            summary={"additions": len(items), "modifications": 0, "replacements": 0,
                     "expirations": 0, "unchanged": 0},
            items=items,
            quality_report=quality_report,
            risk_summary=risk_counts,
            blockers=blockers,
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
        if not items:
            raise ValueError("构建结果未生成候选知识")
        items, blockers, compilation_blocked = self._compile_items(selected_units, items)
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
            status="NEEDS_DECISION" if compilation_blocked else "PENDING_REVIEW",
            summary={"additions": len(items), "modifications": 0, "replacements": 0,
                     "expirations": 0, "unchanged": 0},
            items=items,
            quality_report=quality_report,
            risk_summary=risk_counts,
            blockers=blockers,
        )
        return self._store.save(change_set)

    def list_change_sets(self, doc_id: str = "") -> list[KnowledgeChangeSet]:
        return self._store.list(doc_id)

    def _compile_items(
        self,
        units: list[ApprovedUnit],
        items: list[ChangeSetItem],
    ) -> tuple[list[ChangeSetItem], list[dict[str, Any]], bool]:
        if self._compilation_service is None:
            return items, [], False
        compiled = self._compilation_service.compile_units(units)
        output: list[ChangeSetItem] = []
        blockers: dict[str, dict[str, Any]] = {}
        blocked = False
        for item in items:
            candidate = compiled[item.rule_id]
            blocked = blocked or candidate.status in {"REVIEW", "FAIL"}
            for issue in candidate.issues:
                blockers[issue.issue_id] = issue.model_dump(mode="json")
            if candidate.canonical_rules:
                for rule in candidate.canonical_rules:
                    output.append(item.model_copy(update={
                        "item_id": f"ci_{rule.rule_id}",
                        "rule_id": rule.rule_id,
                        "compile_run_id": candidate.compile_run_id,
                        "compilation_status": candidate.status,
                        "canonical_rule": rule,
                        "needs_human": item.needs_human or blocked,
                    }))
            else:
                output.append(item.model_copy(update={
                    "compile_run_id": candidate.compile_run_id,
                    "compilation_status": candidate.status,
                    "canonical_rule": None,
                    "needs_human": True,
                }))
        return output, list(blockers.values()), blocked

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
            allowed_statuses={"PENDING_REVIEW", "NEEDS_DECISION"},
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
            allowed_statuses={"PENDING_REVIEW", "NEEDS_DECISION"},
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

    # ── 迭代 18：变更集重新提取（Option A 原地刷新）──────────────

    _REEXTRACT_ALLOWED_STATUSES = {"PENDING_REVIEW", "NEEDS_DECISION"}

    def reextract(
        self,
        change_set_id: str,
        item_ids: list[str] | None = None,
        override: ExtractionOverride | None = None,
    ) -> ReextractReport:
        """对变更集中指定变更项（或全部）重新 LLM 提取并原地刷新候选快照。

        Option A（原地刷新）：
        1. 仅 PENDING_REVIEW / NEEDS_DECISION 状态可重提；其他报错。
        2. ``item_ids`` 为空 → 对该变更集全部 item 重提；非空 → 仅这些。
        3. 通过 ``item.after`` 快照取 ``extraction_id`` 定位体系 A 记录（去重）。
        4. 逐条调 ``orchestrator.reextract_unit(ext_id, override, reset_status="reviewed")``；
           保持 extraction 为 reviewed 使单元在工作台可见，新内容进入本变更集接受审核。
        5. 原地重新聚合（同变更集 ID），刷新 items 后保持 PENDING_REVIEW。
        """
        cs = self._require(change_set_id)
        if cs.status not in self._REEXTRACT_ALLOWED_STATUSES:
            raise ValueError(
                f"变更集 {change_set_id} 状态为 {cs.status}，"
                "仅 PENDING_REVIEW/NEEDS_DECISION 可重新提取"
            )

        # 1. 选定目标 item（按 item_id 过滤；空=全部）
        if item_ids:
            wanted = set(item_ids)
            targets = [it for it in cs.items if it.item_id in wanted]
            missing = wanted - {it.item_id for it in targets}
            if missing:
                raise ValueError(
                    f"变更集 {change_set_id} 不含变更项: {sorted(missing)}"
                )
        else:
            targets = list(cs.items)
        if not targets:
            raise ValueError(f"变更集 {change_set_id} 无可重新提取的变更项")

        # 2. item → extraction_id（去重；多个 item 可共享同一 extraction）
        extraction_to_items: dict[str, list[str]] = {}
        for it in targets:
            ext_id = (it.after or {}).get("extraction_id")
            if ext_id:
                extraction_to_items.setdefault(ext_id, []).append(it.item_id)
        if not extraction_to_items:
            raise ValueError("未找到可重新提取的单元（变更项缺少 extraction_id）")

        # 3. 逐条重提取（体系 B：reset_status=reviewed 保持单元可见）
        orch = self._get_orchestrator()
        item_results: list[ReextractItemResult] = []
        for ext_id, src_item_ids in extraction_to_items.items():
            result = orch.reextract_unit(ext_id, override, reset_status="reviewed")
            success = bool(result.get("success"))
            fields = ((result.get("extraction") or {}).get("extracted_fields")) or {}
            new_count = int(fields.get("total_rules") or len(fields.get("rules") or []))
            item_results.append(ReextractItemResult(
                extraction_id=ext_id,
                item_ids=src_item_ids,
                success=success,
                error=result.get("error") if not success else None,
                model_used=override.model_name if (override and success) else None,
                prompt_mode_used=(
                    override.prompt_mode if (override and override.prompt_mode and success) else None
                ),
                new_knowledge_count=new_count,
            ))

        # 4. 原地刷新候选（同变更集 ID 重新聚合）
        refreshed = self._rebuild_in_place(cs)

        # 5. 记录重提取决策（保持 PENDING_REVIEW）
        succeeded = sum(1 for r in item_results if r.success)
        self._store.update_status(
            refreshed.change_set_id,
            "PENDING_REVIEW",
            {
                "action": "reextracted",
                "reviewed_by": override.operator if override else None,
                "override": override.model_dump() if override else None,
                "total": len(item_results),
                "succeeded": succeeded,
            },
        )

        return ReextractReport(
            change_set_id=cs.change_set_id,
            total=len(item_results),
            succeeded=succeeded,
            failed=len(item_results) - succeeded,
            items=item_results,
            override_applied=override.model_dump() if override else None,
        )

    # ── 迭代 19 修改2：重提取前测试（不落库纯预览）──────────────

    def test_extract(
        self,
        change_set_id: str,
        item_id: str,
        override: ExtractionOverride | None = None,
    ) -> dict[str, Any]:
        """对单个变更项用当前配置（提示词/模型）跑一次提取，**不写任何存储**。

        用于重提取前预览：基于当前单元原文 + 动态加载指标 + 所选提示词/模型
        返回提取结果（facts / 规则 / 字段覆盖），满意后再正式提交重提取。
        """
        cs = self._require(change_set_id)
        item = next((it for it in cs.items if it.item_id == item_id), None)
        if item is None:
            raise ValueError(f"变更集 {change_set_id} 不含变更项: {item_id}")
        ext_id = (item.after or {}).get("extraction_id")
        if not ext_id:
            raise ValueError(f"变更项 {item_id} 缺少 extraction_id，无法测试提取")

        orch = self._get_orchestrator()
        ext = orch.store.get_extraction(ext_id)
        if not ext:
            raise ValueError(f"提取记录不存在: {ext_id}")
        doc = orch.store.get_document(ext["doc_id"])
        title = doc.get("title", "") if doc else ""
        source = ext.get("source_text") or ext.get("extracted_fields", {}).get("fact_text", "")
        if not source.strip():
            raise ValueError(f"单元 {item_id} 无源文本，无法测试提取")

        facts = orch._extract_policy_facts(source, title, override=override)
        rules = [r for f in facts for r in (f.get("rules") or [])]
        fields_seen = {
            key for rule in rules for key in rule if rule[key] not in (None, "")
        }
        return {
            "change_set_id": change_set_id,
            "item_id": item_id,
            "extraction_id": ext_id,
            "fact_count": len(facts),
            "rule_count": len(rules),
            "fields_extracted": sorted(fields_seen),
            "facts": facts,
            "override_applied": override.model_dump() if override else None,
        }

    def _rebuild_in_place(self, cs: KnowledgeChangeSet) -> KnowledgeChangeSet:
        """原地刷新变更集 items：按原构建路径重新聚合（同变更集 ID）。"""
        if cs.build_task_id:
            # 任务型：用原任务上下文重新聚合（change_set_id_for_task(task_id) = 同 ID）
            units = self._resolve_selected_units(cs)
            return self.build_for_units(
                task_id=cs.build_task_id,
                task_name=cs.doc_title,
                units=units,
                semantic_contract_version=cs.semantic_contract_version or "",
                supersedes_candidate_id=cs.supersedes_candidate_id,
            )
        # 文档型：按文档重新聚合（change_set_id_for(doc_id) = 同 ID）
        return self.build_for_document(cs.doc_id)

    def _resolve_selected_units(
        self, cs: KnowledgeChangeSet
    ) -> list[SelectedKnowledgeUnit]:
        """从工作台重建任务型变更集所选单元（原地刷新用）。"""
        units_by_key: dict[tuple[str, str], ApprovedUnit] = {}
        for doc_id in {su.doc_id for su in cs.source_units}:
            document = self._workbench.get_document(doc_id)
            for unit in document.units:
                units_by_key[(doc_id, unit.unit_id)] = unit
        selected: list[SelectedKnowledgeUnit] = []
        for su in cs.source_units:
            unit = units_by_key.get((su.doc_id, su.unit_id))
            if unit is not None:
                selected.append(SelectedKnowledgeUnit(unit=unit, source_revision=su))
        if not selected:
            raise ValueError("无法原地刷新：来源单元在当前工作台中不可见")
        return selected

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
