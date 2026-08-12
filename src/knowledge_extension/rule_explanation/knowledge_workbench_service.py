"""审核通过 Unit 与结构化 Knowledge 的只读组合服务。"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Protocol

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeCitation,
    KnowledgeConfidence,
    KnowledgeEvidence,
    KnowledgeField,
    KnowledgeItem,
    KnowledgeWorkbenchDocument,
    SemanticBinding,
    StandardizedField,
    WorkbenchDocumentList,
    WorkbenchDocumentSummary,
)
from src.knowledge_extension.rule_explanation.knowledge_review_store import (
    KnowledgeReviewStore,
)
from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    match_leaves,
    parse_kept_leaves,
)

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        SemanticAlignmentService,
    )
    from src.semantic_layer.models import Metric
    from src.semantic_layer.registry import SemanticRegistry


class SemanticContractUnavailable(RuntimeError):
    """已发布语义契约无法读取，工作台不得伪装为空结果。"""


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

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 100,
        status: str = "",
        keyword: str = "",
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
    "approved_case_accuracy",
    "source_span",
    # 迭代 19 反思：LLM 提取的结构化字段，不是可连读的业务句子成分
    "entities",
    "relations",
    "priority",
    "time_period",
    "admission_order",
    "setl_type",
    "insu_type",
}

# V4.1 S1：rule_type → 业务主题概念 / 规则类型枚举 / 中文标签（阶段一映射，抽取枚举扩展后置）
_RULE_TYPE_META: dict[str, tuple[str, str, str]] = {
    "payment_ratio": ("PAYMENT_RATIO", "FIXED_STANDARD", "固定标准（支付比例）"),
    "deductible": ("DEDUCTIBLE", "FIXED_STANDARD", "固定标准（起付）"),
    "deductible_line": ("DEDUCTIBLE", "FIXED_STANDARD", "固定标准（起付线）"),
    "cap": ("CAP", "FIXED_STANDARD", "固定标准（封顶）"),
    "cap_amount": ("CAP", "FIXED_STANDARD", "固定标准（封顶额）"),
    "eligibility": ("ELIGIBILITY", "ELIGIBILITY", "资格条件"),
    "eligibility_rule": ("ELIGIBILITY", "ELIGIBILITY", "资格条件"),
    # 模型实际输出的中文 rule_type 别名（数据驱动：见 policy_compile_runs.llm_output
    # 的 rule_type 分布）。补全中文别名是修复 rule_id 塌缩的最小入口，
    # 见 docs/superpowers/specs/2026-08-11-policy-rule-compiler-trace-design.md 成功标准。
    # ponytail: “通用规则”/“排除规则”语义模糊不映射，保持 UNCLASSIFIED 交 fail-closed。
    "支付比例": ("PAYMENT_RATIO", "FIXED_STANDARD", "固定标准（支付比例）"),
    "起付线": ("DEDUCTIBLE", "FIXED_STANDARD", "固定标准（起付线）"),
    "封顶线": ("CAP", "FIXED_STANDARD", "固定标准（封顶）"),
    "适用范围": ("ELIGIBILITY", "ELIGIBILITY", "资格条件"),
}


def _short_hash(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

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


def _compact_clause_path(path: list[str]) -> str:
    """精简条款路径：只保留每级条款标识，不存整段条款原文（迭代 19 反思）。

    原实现把完整 path（含整段条款文本）拼进 clause_path，每条 knowledge 重复
    存储长文本，冗余浪费。此处每级取条款号/子项号：
      「第三十六条 在一个结算期内职工和退休人员…」→「第三十六条」
      「（四） 退休人员个人支付比例为职工支付比例的60%」→「（四）」
    匹配规则：开头的「第X条」「第X章」「第X节」「（X）」「X.」「X、」等。
    """
    import re

    labels: list[str] = []
    for part in path:
        text = (part or "").strip()
        m = re.match(r"^(第[一二三四五六七八九十百千0-9]+[章节条款]|（[一二三四五六七八九十0-9]+）|\d+[.、])", text)
        labels.append(m.group(1) if m else text[:20])
    return "/".join(labels)


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
    # 兜底：优先 rule_value（LLM 生成的自然业务描述）
    rule_value = rule.get("rule_value")
    if isinstance(rule_value, str) and rule_value.strip():
        return rule_value.strip().rstrip("。") + "。"
    # 否则拼业务标量字段（排除数组/对象等结构化字段）
    parts = [
        f"{_FIELD_NAMES.get(key, key)}为{value}"
        for key, value in rule.items()
        if key not in _NON_BUSINESS_FIELDS
        and key != "rule_type"
        and isinstance(value, (str, int, float))
        and _present(value)
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
    normalized_source = "".join(source_text.lower().split())
    field_values = [
        "".join(str(rule.get(key)).lower().split())
        for key in applicable
        if _present(rule.get(key))
    ]
    source_fidelity = (
        sum(value in normalized_source for value in field_values) / len(field_values)
        if normalized_source and field_values
        else 0.0
    )
    model_confidence = _clamp(rule.get("confidence", extraction.get("confidence", 0.0)))
    accuracy = None
    known = (completeness, source_fidelity, model_confidence)
    uncertainties = [
        "准确性待已批准经典用例验证",
        "值域合规性待标准化契约验证",
    ]
    return KnowledgeConfidence(
        completeness=round(completeness, 4),
        accuracy=accuracy,
        source_fidelity=source_fidelity,
        model_confidence=model_confidence,
        value_domain_compliance=None,
        overall=round(sum(known) / len(known), 4),
        uncertainties=uncertainties,
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

    def __init__(
        self,
        pipeline_store: PipelineReadPort,
        registry: "SemanticRegistry | None" = None,
        alignment_service: "SemanticAlignmentService | None" = None,
        review_store: KnowledgeReviewStore | None = None,
    ) -> None:
        self._pipeline_store = pipeline_store
        self._registry = registry
        self._alignment_service = alignment_service
        self._review_store = review_store

    def list_documents(self) -> WorkbenchDocumentList:
        """只列出至少含一个审核通过 Unit 的政策文档。"""
        source = self._pipeline_store.list_documents(page=1, page_size=1000)
        items: list[WorkbenchDocumentSummary] = []
        for document in source.get("items", []):
            workbench = self.get_document(str(document.get("doc_id") or ""))
            if not workbench.units:
                continue
            items.append(WorkbenchDocumentSummary(
                doc_id=workbench.doc_id,
                doc_title=workbench.doc_title,
                approved_unit_count=len(workbench.units),
                knowledge_count=sum(unit.knowledge_count for unit in workbench.units),
            ))
        return WorkbenchDocumentList(items=items, total=len(items))

    def list_document_ids(self) -> list[str]:
        """廉价枚举全部文档 id（不构建工作台详情），供只读批次扫描使用。"""
        return self._pipeline_store.list_document_ids()

    def get_document(
        self,
        doc_id: str,
        *,
        include_knowledge: bool = True,
    ) -> KnowledgeWorkbenchDocument:
        document = self._pipeline_store.get_document(doc_id)
        if document is None:
            raise ValueError(f"政策文档不存在: {doc_id}")

        contract_version, published_metrics = self._load_contract()

        review_map = self._load_review_map(doc_id)

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
            clause_path = _compact_clause_path(getattr(leaf, "path", []) or [])
            knowledge_count = 0
            if include_knowledge:
                for extraction, relationship_source in relations:
                    fields = extraction.get("extracted_fields") or {}
                    extraction_id = str(extraction.get("extraction_id") or "")
                    for rule in fields.get("rules") or []:
                        knowledge_id = _knowledge_id(extraction_id, rule)
                        review = review_map.get(knowledge_id)
                        knowledge.append(
                            self._knowledge_item(
                                document=document,
                                unit_id=leaf.node_id,
                                extraction=extraction,
                                relationship_source=relationship_source,
                                rule=rule,
                                contract_version=contract_version,
                                published_metrics=published_metrics,
                                review_status=review.status if review else "pending",
                                review_note=review.note if review else None,
                                clause_path=clause_path,
                            )
                        )
                knowledge_count = len(knowledge)
            else:
                # 只读批次扫描：跳过 KnowledgeItem 构建，仅统计规则数。
                for extraction, _relationship_source in relations:
                    fields = extraction.get("extracted_fields") or {}
                    knowledge_count += len(fields.get("rules") or [])
            units.append(
                ApprovedUnit(
                    unit_id=leaf.node_id,
                    doc_id=doc_id,
                    doc_title=str(document.get("title") or ""),
                    path=list(getattr(leaf, "path", []) or []),
                    source_text=str(getattr(leaf, "text", "") or ""),
                    order_no=int(getattr(leaf, "order_no", 0) or 0),
                    status=status,
                    knowledge_count=knowledge_count,
                    knowledge=knowledge,
                )
            )
        return KnowledgeWorkbenchDocument(
            doc_id=doc_id,
            doc_title=str(document.get("title") or ""),
            contract_version=contract_version,
            units=units,
        )

    def _load_contract(self) -> tuple[str | None, dict[str, "Metric"]]:
        if self._registry is None:
            return None, {}
        try:
            obj = self._registry.get_object("zcgz")
            if obj is None:
                raise SemanticContractUnavailable("语义对象 zcgz 不存在")
            metrics = {
                metric.metric_code.split(".", 1)[-1]: metric
                for metric in self._registry.list_metrics("zcgz")
                if metric.status == "published"
            }
            return obj.current_version or obj.version, metrics
        except SemanticContractUnavailable:
            raise
        except Exception as exc:
            raise SemanticContractUnavailable(str(exc)) from exc

    def _knowledge_item(
        self,
        *,
        document: dict[str, Any],
        unit_id: str,
        extraction: dict[str, Any],
        relationship_source: str,
        rule: dict[str, Any],
        contract_version: str | None,
        published_metrics: dict[str, "Metric"],
        review_status: str = "pending",
        review_note: str | None = None,
        clause_path: str = "",
    ) -> KnowledgeItem:
        extraction_id = str(extraction.get("extraction_id") or "")
        knowledge_id = _knowledge_id(extraction_id, rule)
        doc_id = str(document.get("doc_id") or "")
        source_text = str(rule.get("source_text") or extraction.get("source_text") or "")
        rule_type = str(rule.get("rule_type") or "")
        _topic, _enum, _label = _RULE_TYPE_META.get(
            rule_type, ("UNCLASSIFIED", "UNCLASSIFIED", "未分类")
        )
        structured_fields = [
            KnowledgeField(
                field_code=key,
                field_name=_FIELD_NAMES.get(key, key),
                raw_value=value,
            )
            for key, value in rule.items()
            if key not in _NON_BUSINESS_FIELDS and _present(value)
        ]
        standardized_fields = self._standardize_fields(
            doc_id=str(document.get("doc_id") or ""),
            unit_id=unit_id,
            knowledge_id=knowledge_id,
            contract_version=contract_version,
            fields=structured_fields,
            published_metrics=published_metrics,
        )
        confidence = _confidence(rule, extraction)
        domain_results = [
            item for item in standardized_fields if item.value_domain is not None
        ]
        if domain_results:
            compliance = sum(item.status == "mapped" for item in domain_results) / len(domain_results)
            known_scores = (
                confidence.completeness,
                confidence.source_fidelity,
                confidence.model_confidence,
                compliance,
            )
            confidence = confidence.model_copy(update={
                "value_domain_compliance": round(compliance, 4),
                "overall": round(sum(known_scores) / len(known_scores), 4),
                "uncertainties": [
                    item for item in confidence.uncertainties
                    if item != "值域合规性待标准化契约验证"
                ],
            })
        return KnowledgeItem(
            knowledge_id=knowledge_id,
            unit_id=unit_id,
            extraction_id=extraction_id,
            relationship_source=relationship_source,
            business_sentence=_sentence(rule),
            source_text=source_text,
            fields=structured_fields,
            standardized_fields=standardized_fields,
            confidence=confidence,
            citations=[
                KnowledgeCitation(
                    source_id=str(document.get("doc_id") or ""),
                    title=str(document.get("title") or ""),
                    unit_id=unit_id,
                    extraction_id=extraction_id,
                    evidence=source_text,
                )
            ],
            review_status=review_status,
            review_note=review_note,
            # —— V4.1 S1 政策规则单元契约字段 ——
            rule_group_id=f"KG_{_short_hash(unit_id, extraction_id)}",
            topic_concept=_topic,
            rule_type_enum=_enum,
            rule_type_label=_label,
            validity=None,
            variants=[],
            evidences=[
                KnowledgeEvidence(
                    evidence_id=f"ev_{_short_hash(doc_id, unit_id, source_text)}",
                    document_version_id=doc_id,
                    unit_id=unit_id,
                    clause_path=clause_path or None,
                    exact_quote=source_text,
                    evidence_role="主结论证据",
                )
            ] if source_text else [],
            semantic_bindings=[
                SemanticBinding(
                    policy_field=sf.source_field,
                    value_domain=sf.value_domain,
                    status={
                        "mapped": "CONFIRMED",
                        "unmapped": "UNMAPPED",
                        "invalid": "INVALID",
                        "not_applicable": "NOT_APPLICABLE",
                    }.get(sf.status, "UNMAPPED"),
                )
                for sf in standardized_fields
            ],
        )

    def _load_review_map(self, doc_id: str) -> dict[str, "object"]:
        """加载文档下所有知识的最新评审状态，映射 knowledge_id → KnowledgeReview。"""
        if self._review_store is None:
            return {}
        return {item.knowledge_id: item for item in self._review_store.list_for_document(doc_id)}

    def _standardize_fields(
        self,
        *,
        doc_id: str,
        unit_id: str,
        knowledge_id: str,
        contract_version: str | None,
        fields: list[KnowledgeField],
        published_metrics: dict[str, "Metric"],
    ) -> list[StandardizedField]:
        if self._registry is None:
            return []
        source_ref = f"{doc_id}/{unit_id}/{knowledge_id}"
        results: list[StandardizedField] = []
        for field in fields:
            metric = published_metrics.get(field.field_code)
            binding = None
            if self._alignment_service is not None:
                for candidate in published_metrics.values():
                    bindings = self._alignment_service.list_metric_bindings(candidate.metric_code)
                    binding = next((item for item in bindings if (
                        item.status == "published"
                        and item.source_type == "policy_knowledge"
                        and item.source_ref == source_ref
                        and item.source_field == field.field_code
                        and item.source_version == (contract_version or item.source_version)
                    )), None)
                    if binding is not None:
                        metric = candidate
                        break
            if metric is None:
                results.append(StandardizedField(
                    source_field=field.field_code,
                    source_value=field.raw_value,
                    status="unmapped",
                ))
                continue
            standard_value = field.raw_value
            status = "mapped"
            if metric.value_domain:
                domain = self._registry.get_value_domain(metric.value_domain)
                if domain is None:
                    status = "invalid"
                    standard_value = None
                elif field.raw_value in domain.standard_values:
                    standard_value = field.raw_value
                elif binding is not None and self._alignment_service is not None:
                    resolved = self._alignment_service.resolve_source_value(
                        binding.binding_id,
                        str(field.raw_value),
                    )
                    if resolved == str(field.raw_value):
                        status = "invalid"
                        standard_value = None
                    else:
                        standard_value = resolved
                else:
                    status = "invalid"
                    standard_value = None
            results.append(StandardizedField(
                source_field=field.field_code,
                source_value=field.raw_value,
                status=status,
                metric_code=metric.metric_code,
                metric_name=metric.name,
                value_domain=metric.value_domain,
                standard_value=standard_value,
                binding_id=binding.binding_id if binding else None,
            ))
        return results
