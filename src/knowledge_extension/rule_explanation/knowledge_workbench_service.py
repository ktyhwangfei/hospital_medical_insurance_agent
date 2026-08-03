"""审核通过 Unit 与结构化 Knowledge 的只读组合服务。"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Protocol

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeCitation,
    KnowledgeConfidence,
    KnowledgeField,
    KnowledgeItem,
    KnowledgeWorkbenchDocument,
)
from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    match_leaves,
    parse_kept_leaves,
)


class PipelineReadPort(Protocol):
    """工作台所需的最小政策管线读取端口。"""

    def get_document(self, doc_id: str) -> dict[str, Any] | None: ...

    def list_extractions(
        self,
        page: int = 1,
        page_size: int = 1000,
        doc_id: str = "",
        status: str = "",
    ) -> dict[str, Any]: ...


_FIELD_NAMES = {
    "rule_type": "知识类型",
    "insu_type": "险种",
    "med_type": "医疗类别",
    "hosp_lv": "医疗机构等级",
    "psn_type": "人员类别",
    "setl_type": "结算方式",
    "payment_ratio": "支付比例",
    "deductible_amount": "起付标准",
    "cap_amount": "最高支付限额",
    "rule_value": "规则值",
    "amount_band": "金额区间",
}

_NON_BUSINESS_FIELDS = {
    "rule_id",
    "knowledge_id",
    "fact_id",
    "policy_id",
    "clause_id",
    "source_text",
    "confidence",
}

_APPLICABLE_FIELDS = {
    "payment_ratio": ("psn_type", "med_type", "payment_ratio"),
    "deductible": ("psn_type", "med_type", "deductible_amount"),
    "deductible_line": ("psn_type", "med_type", "deductible_amount"),
    "cap": ("psn_type", "med_type", "cap_amount"),
    "cap_amount": ("psn_type", "med_type", "cap_amount"),
    "eligibility": ("psn_type", "med_type"),
    "eligibility_rule": ("psn_type", "med_type"),
}


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _knowledge_id(extraction_id: str, rule: dict[str, Any]) -> str:
    persisted = str(rule.get("knowledge_id") or rule.get("rule_id") or "").strip()
    if persisted:
        return persisted
    identity = {
        key: value
        for key, value in rule.items()
        if key not in {"knowledge_id", "rule_id", "confidence"}
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{extraction_id}|{canonical}".encode("utf-8")).hexdigest()[:16]
    return f"kn_{digest}"


def _sentence(rule: dict[str, Any]) -> str:
    """按知识类型将字段组织成可连读的业务句。"""
    rule_type = str(rule.get("rule_type") or "")
    person = str(rule.get("psn_type") or "参保人员")
    medical = str(rule.get("med_type") or "就医")
    if rule_type == "payment_ratio" and _present(rule.get("payment_ratio")):
        return f"{person}{medical}时，统筹基金支付比例为{rule['payment_ratio']}。"
    if rule_type in {"deductible", "deductible_line"} and _present(rule.get("deductible_amount")):
        return f"{person}{medical}时，起付标准为{rule['deductible_amount']}。"
    if rule_type in {"cap", "cap_amount"} and _present(rule.get("cap_amount")):
        return f"{person}{medical}时，最高支付限额为{rule['cap_amount']}。"
    if rule_type in {"eligibility", "eligibility_rule"}:
        return f"{person}适用于{medical}待遇。"
    parts = [
        f"{_FIELD_NAMES.get(key, key)}为{value}"
        for key, value in rule.items()
        if key not in _NON_BUSINESS_FIELDS and key != "rule_type" and _present(value)
    ]
    return "，".join(parts) + "。" if parts else "该政策知识尚无可连读的结构化字段。"


def _confidence(rule: dict[str, Any], extraction: dict[str, Any]) -> KnowledgeConfidence:
    rule_type = str(rule.get("rule_type") or "")
    applicable = _APPLICABLE_FIELDS.get(
        rule_type,
        tuple(key for key in rule if key not in _NON_BUSINESS_FIELDS and key != "rule_type"),
    )
    completeness = (
        sum(1 for key in applicable if _present(rule.get(key))) / len(applicable)
        if applicable
        else 0.0
    )
    source_text = str(rule.get("source_text") or extraction.get("source_text") or "").strip()
    fact_text = str((extraction.get("extracted_fields") or {}).get("fact_text") or "").strip()
    source_fidelity = 1.0 if source_text and (source_text in fact_text or fact_text in source_text) else 0.0
    model_confidence = _clamp(rule.get("confidence", extraction.get("confidence", 0.0)))
    known = (completeness, source_fidelity, model_confidence)
    return KnowledgeConfidence(
        completeness=round(completeness, 4),
        accuracy=None,
        source_fidelity=source_fidelity,
        model_confidence=model_confidence,
        value_domain_compliance=None,
        overall=round(sum(known) / len(known), 4),
        uncertainties=["准确性待经典用例验证", "值域合规性待标准化契约验证"],
    )


def _unit_status(extractions: list[dict[str, Any]], audit: dict[str, Any] | None) -> str:
    if not extractions:
        if audit and audit.get("action") == "approve":
            return "reviewed"
        if audit and audit.get("action") == "reject":
            return "rejected"
        return "pending"
    statuses = [str(item.get("status") or "draft") for item in extractions]
    if "rejected" in statuses:
        return "rejected"
    if all(status == "published" for status in statuses):
        return "published"
    if all(status in {"reviewed", "published"} for status in statuses):
        return "reviewed"
    return "draft"


class KnowledgeWorkbenchService:
    """组合政策结构与提取记录，不产生任何写操作。"""

    def __init__(self, pipeline_store: PipelineReadPort) -> None:
        self._pipeline_store = pipeline_store

    def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
        document = self._pipeline_store.get_document(doc_id)
        if document is None:
            raise ValueError(f"政策文档不存在: {doc_id}")

        _root, _by_id, _all_leaves, kept = parse_kept_leaves(
            str(document.get("content_text") or ""),
            str(document.get("title") or ""),
        )
        by_unit = {leaf.node_id: leaf for leaf in kept}
        linked: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
        extraction_result = self._pipeline_store.list_extractions(
            page=1,
            page_size=1000,
            doc_id=doc_id,
        )
        for extraction in extraction_result.get("items", []):
            persisted_unit_id = str(extraction.get("unit_id") or "")
            if persisted_unit_id in by_unit:
                linked[persisted_unit_id].append((extraction, "persisted"))
                continue
            fields = extraction.get("extracted_fields") or {}
            source = str(fields.get("fact_text") or extraction.get("source_text") or "")
            for matched_unit_id in match_leaves(source, kept):
                linked[matched_unit_id].append((extraction, "legacy_match"))

        dup_state = document.get("dup_state") or {}
        merged = set((dup_state.get("merged") or {}).keys())
        unit_audit = dup_state.get("unit_audit") or {}
        units: list[ApprovedUnit] = []
        for leaf in kept:
            if leaf.node_id in merged:
                continue
            relations = linked.get(leaf.node_id, [])
            extractions = [item[0] for item in relations]
            status = _unit_status(extractions, unit_audit.get(leaf.node_id))
            if status not in {"reviewed", "published"}:
                continue
            knowledge: list[KnowledgeItem] = []
            for extraction, relationship_source in relations:
                fields = extraction.get("extracted_fields") or {}
                for rule in fields.get("rules") or []:
                    knowledge.append(
                        self._knowledge_item(
                            document=document,
                            unit_id=leaf.node_id,
                            extraction=extraction,
                            relationship_source=relationship_source,
                            rule=rule,
                        )
                    )
            units.append(
                ApprovedUnit(
                    unit_id=leaf.node_id,
                    doc_id=doc_id,
                    doc_title=str(document.get("title") or ""),
                    path=list(getattr(leaf, "path", []) or []),
                    source_text=str(getattr(leaf, "text", "") or ""),
                    order_no=int(getattr(leaf, "order_no", 0) or 0),
                    status=status,
                    knowledge_count=len(knowledge),
                    knowledge=knowledge,
                )
            )
        return KnowledgeWorkbenchDocument(
            doc_id=doc_id,
            doc_title=str(document.get("title") or ""),
            units=units,
        )

    @staticmethod
    def _knowledge_item(
        *,
        document: dict[str, Any],
        unit_id: str,
        extraction: dict[str, Any],
        relationship_source: str,
        rule: dict[str, Any],
    ) -> KnowledgeItem:
        extraction_id = str(extraction.get("extraction_id") or "")
        source_text = str(rule.get("source_text") or extraction.get("source_text") or "")
        structured_fields = [
            KnowledgeField(
                field_code=key,
                field_name=_FIELD_NAMES.get(key, key),
                raw_value=value,
            )
            for key, value in rule.items()
            if key not in _NON_BUSINESS_FIELDS and _present(value)
        ]
        return KnowledgeItem(
            knowledge_id=_knowledge_id(extraction_id, rule),
            unit_id=unit_id,
            extraction_id=extraction_id,
            relationship_source=relationship_source,
            business_sentence=_sentence(rule),
            source_text=source_text,
            fields=structured_fields,
            confidence=_confidence(rule, extraction),
            citations=[
                KnowledgeCitation(
                    source_id=str(document.get("doc_id") or ""),
                    title=str(document.get("title") or ""),
                    unit_id=unit_id,
                    extraction_id=extraction_id,
                    evidence=source_text,
                )
            ],
        )
