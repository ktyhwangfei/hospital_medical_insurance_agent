"""人工决策任务服务（V4.1 §10 / §17.2）。

阶段一：从变更集启发式生成决策任务——
- 证据不足（evidences 为空）→ INSUFFICIENT_EVIDENCE；
- 值域未映射（semantic_bindings UNMAPPED/INVALID）→ NEW_STANDARD_VALUE / REVIEW_CONFIRM；
- 低置信（confidence.overall < 0.8）→ REVIEW_CONFIRM。
人工决策后记录 decision；批量解决仅限同类型同推荐的 LOW 风险任务（V4.0 §7.3 边界）。
"""
from __future__ import annotations

import hashlib
from typing import Any

from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet
from src.knowledge_extension.rule_explanation.decision_task_models import DecisionTask
from src.knowledge_extension.rule_explanation.decision_task_store import DecisionTaskStore


def task_id_for(scope: str, kind: str, rule_id: str) -> str:
    raw = f"{scope}|{kind}|{rule_id}"
    return f"dt_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _rule_evidence_count(item) -> int:
    after = item.after or {}
    evidences = after.get("evidences") or []
    return len(evidences)


def _rule_unmapped_fields(item) -> list[dict[str, Any]]:
    after = item.after or {}
    bindings = after.get("semantic_bindings") or []
    # 排除描述型字段（entities/relations/priority 等 AI 辅助信息，无值域映射价值）
    descriptive = {"entities", "relations", "priority", "rule_value"}
    return [
        b for b in bindings
        if b.get("status") in ("UNMAPPED", "INVALID") and b.get("policy_field") not in descriptive
    ]


def _rule_confidence(item) -> float:
    after = item.after or {}
    confidence = after.get("confidence") or {}
    return float(confidence.get("overall") or 0)


class DecisionTaskService:
    def __init__(self, store: DecisionTaskStore) -> None:
        self._store = store

    def generate_for_change_set(self, change_set: KnowledgeChangeSet) -> list[DecisionTask]:
        """扫描变更集 items，为证据不足/值域未映射/低置信的规则生成决策任务。"""
        generated: list[DecisionTask] = []
        for item in change_set.items:
            rule_id = item.rule_id
            # 1. 证据不足 → 高
            if _rule_evidence_count(item) == 0:
                generated.append(DecisionTask(
                    task_id=task_id_for(change_set.change_set_id, "EVIDENCE", rule_id),
                    task_type="INSUFFICIENT_EVIDENCE",
                    question=f"规则 {rule_id} 缺少原文证据：该规则没有任何字段级证据锚点，无法支撑发布。",
                    recommended_option={"action": "补充证据", "detail": "回到规则详情，从原文定位并关联证据片段"},
                    alternatives=[{"action": "标记为候选", "detail": "允许进入候选，但阻断发布"}],
                    evidence={"rule_id": rule_id, "doc_title": change_set.doc_title},
                    risk_level="HIGH",
                    affected_items={"rules": [rule_id]},
                    blocking_scope=change_set.change_set_id,
                ))
            # 2. 值域未映射 → 中
            unmapped = _rule_unmapped_fields(item)
            for binding in unmapped:
                field = binding.get("policy_field")
                generated.append(DecisionTask(
                    task_id=task_id_for(change_set.change_set_id, f"DOMAIN_{field}", rule_id),
                    task_type="NEW_STANDARD_VALUE",
                    question=f"字段 {field}（规则 {rule_id}）尚未映射到标准值域，需要确认或新建标准值。",
                    recommended_option={"action": "确认现有值域", "detail": "在语义映射抽屉中绑定已有标准值域"},
                    alternatives=[{"action": "新建标准值", "detail": "提交新标准值候选，待语义管理员审核"}],
                    evidence={"rule_id": rule_id, "field": field, "doc_title": change_set.doc_title},
                    risk_level="MEDIUM",
                    affected_items={"rules": [rule_id], "fields": [field]},
                    blocking_scope=change_set.change_set_id,
                ))
            # 3. 低置信 → 中（复核）
            if _rule_confidence(item) < 0.8:
                generated.append(DecisionTask(
                    task_id=task_id_for(change_set.change_set_id, "CONFIDENCE", rule_id),
                    task_type="REVIEW_CONFIRM",
                    question=f"规则 {rule_id} 置信度较低（{round(_rule_confidence(item) * 100)}%），需要人工复核结构化是否准确。",
                    recommended_option={"action": "复核通过", "detail": "对照原文人工确认条件/结果/证据一致"},
                    alternatives=[{"action": "退回重抽取", "detail": "重新执行 AI 抽取"}],
                    evidence={"rule_id": rule_id, "confidence": _rule_confidence(item), "doc_title": change_set.doc_title},
                    risk_level="MEDIUM",
                    affected_items={"rules": [rule_id]},
                    blocking_scope=change_set.change_set_id,
                ))
        # 幂等：同 scope 先清空再落库
        for existing in self._store.list(scope=change_set.change_set_id):
            self._store.save(existing.model_copy(update={"status": "SKIPPED"}))
        for task in generated:
            self._store.save(task)
        return generated

    def resolve(self, task_id: str, decision: dict[str, Any]) -> DecisionTask:
        from datetime import datetime, timezone
        task = self._store.get(task_id)
        if task is None:
            raise ValueError(f"决策任务不存在: {task_id}")
        if task.status != "PENDING":
            raise ValueError(f"决策任务 {task_id} 已处理（{task.status}）")
        resolved = task.model_copy(update={
            "status": "RESOLVED",
            "decision": decision,
            "resolved_at": datetime.now(timezone.utc),
        })
        return self._store.save(resolved)

    def list_tasks(self, status: str = "", task_type: str = "", scope: str = "") -> list[DecisionTask]:
        return self._store.list(status=status, task_type=task_type, scope=scope)

    def pending_count(self, scope: str = "") -> int:
        return len(self._store.list(status="PENDING", scope=scope))
