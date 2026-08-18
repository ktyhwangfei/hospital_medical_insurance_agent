from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    parse_kept_leaves,
)
from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


POLICY_TEXT = """第一条 参保人员待遇
（一）在职职工住院费用，统筹基金支付百分之八十。
（二）退休人员住院起付标准为一千元。
"""


class FakePipelineStore:
    def __init__(
        self,
        extractions: list[dict[str, Any]],
        *,
        unit_audit: dict[str, dict[str, str]] | None = None,
        merged: dict[str, str] | None = None,
    ) -> None:
        self.extractions = extractions
        self.document = {
            "doc_id": "doc_1",
            "title": "职工医保待遇政策",
            "content_text": POLICY_TEXT,
            "dup_state": {
                "unit_audit": unit_audit or {},
                "merged": merged or {},
            },
        }

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        return self.document if doc_id == "doc_1" else None

    def list_extractions(
        self,
        page: int = 1,
        page_size: int = 1000,
        doc_id: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        items = [e for e in self.extractions if not doc_id or e["doc_id"] == doc_id]
        if status:
            items = [e for e in items if e["status"] == status]
        return {"items": items, "total": len(items), "page": page, "page_size": page_size}

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 100,
        status: str = "",
        keyword: str = "",
    ) -> dict[str, Any]:
        return {"items": [self.document], "total": 1, "page": page, "page_size": page_size}

    def list_document_ids(self) -> list[str]:
        return [self.document["doc_id"]] if self.document else []


def _leaf_ids() -> list[str]:
    _root, _by_id, _all_leaves, kept = parse_kept_leaves(
        POLICY_TEXT,
        "职工医保待遇政策",
    )
    return [leaf.node_id for leaf in kept]


def _extraction(unit_id: str, rules: list[dict[str, Any]], status: str = "reviewed") -> dict[str, Any]:
    return {
        "extraction_id": "ext_1",
        "doc_id": "doc_1",
        "doc_title": "职工医保待遇政策",
        "unit_id": unit_id,
        "source_text": "（一）在职职工住院费用，统筹基金支付百分之八十。",
        "extracted_fields": {
            "fact_text": "在职职工住院费用，统筹基金支付百分之八十。",
            "rules": rules,
        },
        "confidence": 0.86,
        "status": status,
        "reviewed_by": "reviewer_1",
        "reviewed_at": "2026-08-03T09:00:00+08:00",
    }


def _rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_type": "payment_ratio",
            "psn_type": "在职职工",
            "med_type": "住院",
            "payment_ratio": "80%",
            "source_text": "在职职工住院费用，统筹基金支付百分之八十。",
            "confidence": 0.9,
        },
        {
            "rule_type": "eligibility",
            "psn_type": "在职职工",
            "med_type": "住院",
            "source_text": "在职职工住院费用",
            "confidence": 0.82,
        },
    ]


def test_workbench_only_returns_approved_non_merged_units() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first, second = _leaf_ids()
    store = FakePipelineStore(
        [_extraction(first, _rules(), status="reviewed")],
        unit_audit={second: {"action": "approve", "reason": ""}},
        merged={second: first},
    )

    result = KnowledgeWorkbenchService(store).get_document("doc_1")

    assert [unit.unit_id for unit in result.units] == [first]
    assert result.units[0].status == "reviewed"
    assert result.units[0].knowledge_count == 2
    assert len(result.units[0].knowledge) == 2


def test_workbench_dedupes_knowledge_across_extraction_versions() -> None:
    """同一单元多条 extraction 时，knowledge 按 knowledge_id 去重并保留最新版本。

    复现缺陷（用户反馈）：REBUILD 重抽会追加新 extraction 而不清理旧的，
    新旧 extraction 的 rules 带相同 rule_id 时 knowledge_id 重复，
    导致 policy_compiler 同一 run 重复写步骤而 500。
    """
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    old = _extraction(
        first,
        [
            dict(_rules()[0], rule_id="rule_001"),
            dict(_rules()[1], rule_id="rule_002"),
        ],
        status="reviewed",
    )
    old["extraction_id"] = "ext_old"
    old["updated_at"] = "2026-08-01T09:00:00+08:00"
    new = _extraction(first, [dict(_rules()[0], rule_id="rule_001")], status="reviewed")
    new["extraction_id"] = "ext_new"
    new["updated_at"] = "2026-08-10T09:00:00+08:00"

    result = KnowledgeWorkbenchService(
        FakePipelineStore([old, new])
    ).get_document("doc_1")

    unit = result.units[0]
    knowledge_ids = [item.knowledge_id for item in unit.knowledge]
    # 命名空间化后：不同 extraction 的同名 rule_id 是不同 knowledge（不再撞名），
    # 全部保留；去重兑底只防完全相同 id 重复。
    assert len(knowledge_ids) == len(set(knowledge_ids)), "knowledge_id 不得重复（重复会导致编译 500）"
    assert len(knowledge_ids) == 3
    assert any(item.extraction_id == "ext_new" for item in unit.knowledge)


def test_knowledge_id_scopes_persisted_rule_id_to_extraction() -> None:
    """LLM 自报 rule_id 是单元内局部序号（每单元都从 rule_001 编号），
    跨单元必撞名——多单元构建时 compile_units 的 runs 按 knowledge_id
    覆盖，同一 run 重复写步骤 → 500「编译步骤已存在」（2026-08-17 实例）。
    knowledge_id 必须绑定 extraction 命名空间。"""
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        _knowledge_id,
    )

    a1 = _knowledge_id("ext_a", {"rule_id": "rule_001"})
    b1 = _knowledge_id("ext_b", {"rule_id": "rule_001"})
    assert a1 != b1, "跨 extraction 的同名 rule_id 不得生成相同 knowledge_id"
    assert _knowledge_id("ext_a", {"rule_id": "rule_001"}) == a1, "同 extraction 内必须稳定（review 跟随）"
    assert _knowledge_id("ext_a", {"rule_id": "rule_002"}) != a1, "同 extraction 内不同 rule 仍区分"


def test_rule_reordering_does_not_change_knowledge_identity() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    rules = _rules()
    before = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, rules)])).get_document("doc_1")
    reordered = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, list(reversed(deepcopy(rules))))])
    ).get_document("doc_1")

    assert {item.knowledge_id for item in before.units[0].knowledge} == {
        item.knowledge_id for item in reordered.units[0].knowledge
    }


def test_explicit_unit_id_wins_over_legacy_text_match() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first, second = _leaf_ids()
    ext = _extraction(second, _rules())
    ext["source_text"] = "（一）在职职工住院费用，统筹基金支付百分之八十。"

    result = KnowledgeWorkbenchService(FakePipelineStore([ext])).get_document("doc_1")

    assert [unit.unit_id for unit in result.units] == [second]
    assert all(item.relationship_source == "persisted" for item in result.units[0].knowledge)


def test_legacy_extraction_is_labeled_when_text_match_is_used() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    ext = _extraction("", _rules())

    result = KnowledgeWorkbenchService(FakePipelineStore([ext])).get_document("doc_1")

    assert [unit.unit_id for unit in result.units] == [first]
    assert all(item.relationship_source == "legacy_match" for item in result.units[0].knowledge)


def test_persisted_extraction_suppresses_legacy_match_for_same_unit() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    persisted = _extraction(first, [dict(_rules()[0], rule_id="rule_current")])
    legacy = _extraction("", [dict(_rules()[0], rule_id="rule_legacy")])
    legacy["extraction_id"] = "ext_legacy"

    result = KnowledgeWorkbenchService(
        FakePipelineStore([legacy, persisted])
    ).get_document("doc_1")

    assert [item.extraction_id for item in result.units[0].knowledge] == ["ext_1"]


def test_business_sentence_and_confidence_are_explainable() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    result = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules()[:1])])).get_document("doc_1")
    knowledge = result.units[0].knowledge[0]

    assert knowledge.business_sentence == "在职职工住院时，统筹基金支付比例为80%。"
    assert knowledge.confidence.completeness == 1.0
    assert knowledge.confidence.model_confidence == 0.9
    assert knowledge.confidence.accuracy is None
    assert "准确性待已批准经典用例验证" in knowledge.confidence.uncertainties
    assert knowledge.citations[0].source_id == "doc_1"


def test_business_sentence_keeps_fund_and_cap_semantics() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import _sentence

    assert _sentence({
        "rule_type": "封顶线",
        "jjgs": "统筹基金",
        "psn_type": "在职职工",
        "cap_amount": "100000",
        "rule_value": "100000",
    }) == "在职职工就医时，统筹基金最高支付限额为100000元。"


def test_accuracy_ignores_untrusted_inline_approved_case_claim() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    rules = _rules()[:1]
    rules[0]["approved_case_accuracy"] = 0.95
    result = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, rules)])).get_document("doc_1")

    confidence = result.units[0].knowledge[0].confidence
    assert confidence.accuracy is None
    assert "准确性待已批准经典用例验证" in confidence.uncertainties


def test_accuracy_ignores_untrusted_source_span_verified_flag() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    rules = _rules()[:1]
    rules[0]["source_span"] = {"verified": True, "accuracy": 0.9}
    result = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, rules)])).get_document("doc_1")

    confidence = result.units[0].knowledge[0].confidence
    assert confidence.accuracy is None
    assert "准确性待已批准经典用例验证" in confidence.uncertainties


def test_source_fidelity_measures_structured_field_token_coverage() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    rules = _rules()[:1]
    rules[0]["source_text"] = "在职职工住院统筹基金支付比例为百分之八十"
    rules[0]["psn_type"] = "在职职工"
    rules[0]["med_type"] = "门诊"
    rules[0]["pay_ratio"] = 0.8
    result = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, rules)])).get_document("doc_1")

    fidelity = result.units[0].knowledge[0].confidence.source_fidelity
    assert 0 < fidelity < 1


def test_pipeline_store_keeps_persisted_unit_id_in_read_model() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    row = {
        "extraction_id": "ext_1",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "extracted_fields": {},
        "confidence": 0.8,
        "status": "reviewed",
    }

    result = PipelineStore._ext_row(PipelineStore(), row)

    assert result["unit_id"] == "unit_1"


def test_extract_single_fails_closed_when_model_returns_no_facts() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    class RecordingStore:
        def __init__(self) -> None:
            self.created: list[dict[str, Any]] = []

        def get_document(self, doc_id: str) -> dict[str, str]:
            return {"doc_id": doc_id, "title": "职工医保待遇政策"}

        def batch_create_extractions(self, items: list[dict[str, Any]]) -> int:
            self.created.extend(items)
            return len(items)

    store = RecordingStore()
    orchestrator = PipelineOrchestrator(store)  # type: ignore[arg-type]
    orchestrator._extract_policy_facts = lambda *_args, **_kwargs: []  # type: ignore[method-assign]

    result = orchestrator.extract_single("doc_1", "政策单元原文", unit_id="unit_1")

    assert result == {
        "success": False,
        "error": "LLM 未返回可构建的政策事实",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
    }
    assert store.created == []


def test_extract_single_fails_closed_when_facts_have_no_rules() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    class RecordingStore:
        def __init__(self) -> None:
            self.created: list[dict[str, Any]] = []

        def get_document(self, doc_id: str) -> dict[str, str]:
            return {"doc_id": doc_id, "title": "职工医保待遇政策"}

        def batch_create_extractions(self, items: list[dict[str, Any]]) -> int:
            self.created.extend(items)
            return len(items)

    store = RecordingStore()
    orchestrator = PipelineOrchestrator(store)  # type: ignore[arg-type]
    orchestrator._extract_policy_facts = lambda *_args, **_kwargs: [  # type: ignore[method-assign]
        {"fact_text": "政策单元原文", "rules": []}
    ]

    result = orchestrator.extract_single("doc_1", "政策单元原文", unit_id="unit_1")

    assert result["success"] is False
    assert result["error"] == "LLM 未返回可构建的政策规则"
    assert store.created == []


def test_extract_single_can_keep_build_candidates_visible_for_change_set_review() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    class RecordingStore:
        def __init__(self) -> None:
            self.created: list[dict[str, Any]] = []
            self.updated: list[tuple[str, dict[str, Any]]] = []

        def get_document(self, doc_id: str) -> dict[str, str]:
            return {"doc_id": doc_id, "title": "职工医保待遇政策"}

        def batch_create_extractions(self, items: list[dict[str, Any]]) -> int:
            self.created.extend(items)
            return len(items)

        def list_extractions(
            self, page: int = 1, page_size: int = 1000, doc_id: str = "", status: str = ""
        ) -> dict[str, Any]:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        def update_extraction(
            self, extraction_id: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            self.updated.append((extraction_id, data))
            return {"extraction_id": extraction_id, **data}

    store = RecordingStore()
    orchestrator = PipelineOrchestrator(store)  # type: ignore[arg-type]
    orchestrator._extract_policy_facts = lambda *_args, **_kwargs: [  # type: ignore[method-assign]
        {"fact_text": "政策单元原文", "rules": _rules()[:1]}
    ]

    result = orchestrator.extract_single(
        "doc_1",
        "政策单元原文",
        unit_id="unit_1",
        reset_status="reviewed",
    )

    assert result["success"] is True
    assert result["total_rules"] == 1
    assert store.created[0]["unit_id"] == "unit_1"
    assert store.updated == [
        (store.created[0]["extraction_id"], {"status": "reviewed"})
    ]


def test_extract_leaf_request_requires_unit_id() -> None:
    from src.runtime.api.policy_pipeline_routes import ExtractLeafRequest

    with pytest.raises(ValidationError):
        ExtractLeafRequest(source_text="政策单元原文")  # type: ignore[call-arg]


def test_extract_leaf_rejects_unit_outside_document(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.runtime.api import policy_pipeline_routes

    class Store:
        def get_document(self, doc_id: str) -> dict[str, str]:
            return {
                "doc_id": doc_id,
                "title": "职工医保待遇政策",
                "content_text": POLICY_TEXT,
            }

    monkeypatch.setattr(policy_pipeline_routes, "_get_store", lambda: Store())
    request = policy_pipeline_routes.ExtractLeafRequest(
        unit_id="unit_outside_document",
        source_text="政策单元原文",
    )

    with pytest.raises(HTTPException) as exc:
        policy_pipeline_routes.extract_single_leaf("doc_1", request)

    assert exc.value.status_code == 400


def test_extract_leaf_passes_validated_unit_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.runtime.api import policy_pipeline_routes

    first = _leaf_ids()[0]
    calls: list[tuple[str, str, str]] = []

    class Store:
        def get_document(self, doc_id: str) -> dict[str, str]:
            return {
                "doc_id": doc_id,
                "title": "职工医保待遇政策",
                "content_text": POLICY_TEXT,
            }

    class Orchestrator:
        def extract_single(self, doc_id: str, source_text: str, unit_id: str = "") -> dict[str, Any]:
            calls.append((doc_id, source_text, unit_id))
            return {"success": True, "extractions_created": 1}

    monkeypatch.setattr(policy_pipeline_routes, "_get_store", lambda: Store())
    monkeypatch.setattr(policy_pipeline_routes, "_get_orchestrator", lambda: Orchestrator())
    request = policy_pipeline_routes.ExtractLeafRequest(
        unit_id=first,
        source_text="政策单元原文",
    )

    result = policy_pipeline_routes.extract_single_leaf("doc_1", request)

    assert result["success"] is True
    assert calls == [("doc_1", "政策单元原文", first)]


def test_full_document_extraction_assigns_matching_unit_id() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    class RecordingStore:
        def __init__(self) -> None:
            self.created: list[dict[str, Any]] = []

        def get_document(self, doc_id: str) -> dict[str, str]:
            return {
                "doc_id": doc_id,
                "title": "职工医保待遇政策",
                "content_text": POLICY_TEXT,
            }

        def update_document(self, doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"doc_id": doc_id, **data}

        def delete_extractions_by_doc(self, doc_id: str) -> int:
            return 0

        def batch_create_extractions(self, items: list[dict[str, Any]]) -> int:
            self.created.extend(items)
            return len(items)

    store = RecordingStore()
    orchestrator = PipelineOrchestrator(store)  # type: ignore[arg-type]
    orchestrator._split_text = lambda *_args, **_kwargs: [POLICY_TEXT]  # type: ignore[method-assign]
    orchestrator._extract_policy_facts = lambda *_args, **_kwargs: [  # type: ignore[method-assign]
        {
            "fact_text": "（一）在职职工住院费用，统筹基金支付百分之八十。",
            "rules": _rules()[:1],
        }
    ]

    result = orchestrator.run_extraction("doc_1")

    assert result["success"] is True
    assert store.created[0]["unit_id"] == _leaf_ids()[0]


def test_policy_field_maps_to_unified_metric_and_source_specific_standard_value() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        MetricSourceBindingDraft,
        SemanticAlignmentService,
        SourceValueMappingDraft,
    )

    first = _leaf_ids()[0]
    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则",
        status="published", current_version="2",
    ))
    registry_store.save_value_domain(ValueDomain(
        domain_code="PERSON_TYPE", name="人员类别", standard_values=["职工医保"],
    ))
    registry_store.save_metric(Metric(
        metric_code="zcgz.psn_type", object_code="zcgz", name="参保人员类别",
        semantic_type="Enum", value_domain="PERSON_TYPE", status="published",
    ))
    registry_store.save_metric(Metric(
        metric_code="zcgz.payment_ratio", object_code="zcgz", name="支付比例",
        semantic_type="Ratio", status="published",
    ))
    registry = SemanticRegistry(registry_store)
    alignment = SemanticAlignmentService(registry, InMemorySemanticAlignmentStore())
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        _knowledge_id,
    )
    # knowledge_id 由 _knowledge_id 派生（persisted id 绑定 extraction 命名空间），
    # binding 的 source_ref 必须用同一派生结果构造才能命中。
    rules = _rules()[:1]
    rules[0]["knowledge_id"] = "kn_policy_person"
    rules[0]["psn_type"] = "城镇职工"
    source_ref = f"doc_1/{first}/{_knowledge_id('ext_1', rules[0])}"
    binding = alignment.bind_existing_metric(MetricSourceBindingDraft(
        metric_code="zcgz.psn_type",
        source_type="policy_knowledge",
        source_ref=source_ref,
        source_field="psn_type",
        source_version="2",
        evidence="政策原文：城镇职工",
    ))
    alignment.approve_binding(binding.binding_id, "semantic_reviewer")
    mapping = alignment.propose_value_mapping(SourceValueMappingDraft(
        metric_code="zcgz.psn_type",
        domain_code="PERSON_TYPE",
        binding_id=binding.binding_id,
        source_value="城镇职工",
        standard_value="职工医保",
    ))
    alignment.approve_value_mapping(mapping.mapping_id, "semantic_reviewer")

    result = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, rules)]),
        registry=registry,
        alignment_service=alignment,
    ).get_document("doc_1")

    knowledge = result.units[0].knowledge[0]
    person = next(item for item in knowledge.standardized_fields if item.source_field == "psn_type")
    ratio = next(item for item in knowledge.standardized_fields if item.source_field == "payment_ratio")
    assert result.contract_version == "2"
    assert person.status == "mapped"
    assert person.metric_code == "zcgz.psn_type"
    assert person.standard_value == "职工医保"
    assert ratio.status == "mapped"
    assert ratio.standard_value == "80%"
    assert knowledge.confidence.value_domain_compliance == 1.0
    assert knowledge.confidence.overall == 0.8083


def test_unmapped_policy_field_is_explicit_and_not_auto_created() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则",
        status="published", current_version="1",
    ))
    registry = SemanticRegistry(registry_store)
    rules = [{
        "knowledge_id": "kn_unmapped",
        "rule_type": "general_policy",
        "special_population": "困难人群",
        "source_text": "困难人群享受倾斜待遇",
    }]

    result = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, rules)]),
        registry=registry,
    ).get_document("doc_1")

    mapped = result.units[0].knowledge[0].standardized_fields
    assert [(item.source_field, item.status) for item in mapped] == [
        ("rule_type", "unmapped"),
        ("special_population", "unmapped"),
    ]
    assert registry.get_metric("zcgz.special_population") is None


def test_semantic_registry_failure_is_not_returned_as_empty_success() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
        SemanticContractUnavailable,
    )

    class BrokenRegistry:
        def get_object(self, object_code: str) -> None:
            raise RuntimeError("semantic registry unavailable")

    first = _leaf_ids()[0]

    with pytest.raises(SemanticContractUnavailable, match="semantic registry unavailable"):
        KnowledgeWorkbenchService(
            FakePipelineStore([_extraction(first, _rules()[:1])]),
            registry=BrokenRegistry(),  # type: ignore[arg-type]
        ).get_document("doc_1")


def test_document_selector_only_lists_documents_with_approved_units() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    service = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, _rules()[:1], status="reviewed")])
    )

    result = service.list_documents()

    assert result.total == 1
    assert result.items[0].doc_id == "doc_1"
    assert result.items[0].approved_unit_count == 1
    assert result.items[0].knowledge_count == 1


def test_review_status_is_joined_into_knowledge_from_store() -> None:
    """评审结论落库后，工作台读取应把 review_status 合并进每条知识（需求4）。"""
    from src.knowledge_extension.rule_explanation.knowledge_review_store import (
        InMemoryKnowledgeReviewStore,
        KnowledgeReview,
        stable_review_id,
    )
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    review_store = InMemoryKnowledgeReviewStore()
    service = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, _rules())]),
        review_store=review_store,
    )

    # 默认全部待评审
    first_doc = service.get_document("doc_1")
    knowledge_id = first_doc.units[0].knowledge[0].knowledge_id
    assert all(item.review_status == "pending" for item in first_doc.units[0].knowledge)

    # 写入一条「通过」评审并落库
    review_store.save(KnowledgeReview(
        review_id=stable_review_id("doc_1", knowledge_id),
        doc_id="doc_1",
        unit_id=first,
        knowledge_id=knowledge_id,
        status="approved",
        reviewed_by="alice",
    ))

    second_doc = service.get_document("doc_1")
    by_id = {item.knowledge_id: item.review_status for item in second_doc.units[0].knowledge}
    assert by_id[knowledge_id] == "approved"
    # 未评审的其它知识仍为 pending
    pending = [kid for kid, status in by_id.items() if kid != knowledge_id]
    assert pending and all(by_id[kid] == "pending" for kid in pending)


def test_rule_unit_contract_fields_are_assembled() -> None:
    """V4.1 S1：知识项应携带政策规则单元契约字段（rule_group/topic/type/evidences/bindings）。"""
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    result = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, _rules())])
    ).get_document("doc_1")

    unit = result.units[0]
    by_type = {item.rule_type_enum: item for item in unit.knowledge}
    # 规则组：同一 extraction 的规则共享 rule_group_id
    groups = {item.rule_group_id for item in unit.knowledge}
    assert len(groups) == 1
    assert groups.pop().startswith("KG_")
    # 类型映射：payment_ratio → 固定标准（支付比例）；eligibility → 资格条件
    assert by_type["FIXED_STANDARD"].topic_concept == "PAYMENT_RATIO"
    assert by_type["FIXED_STANDARD"].rule_type_label == "固定标准（支付比例）"
    assert by_type["ELIGIBILITY"].topic_concept == "ELIGIBILITY"
    assert by_type["ELIGIBILITY"].rule_type_label == "资格条件"
    # 多证据锚点派生
    item = by_type["FIXED_STANDARD"]
    assert len(item.evidences) == 1
    evidence = item.evidences[0]
    assert evidence.evidence_id.startswith("ev_")
    assert evidence.document_version_id == "doc_1"
    assert evidence.clause_path == "第一条/（一）"  # 迭代19反思：精简为条款级标识
    assert evidence.exact_quote == item.source_text
    assert evidence.evidence_role == "主结论证据"
    # 语义绑定派生：payment_ratio 无值域（registry 未注入）→ 空列表；validity 未识别
    assert item.validity is None
    assert item.variants == []


@pytest.mark.parametrize(
    ("rule_type", "topic", "enum"),
    [
        ("支付比例", "PAYMENT_RATIO", "FIXED_STANDARD"),
        ("起付线", "DEDUCTIBLE", "FIXED_STANDARD"),
        ("封顶线", "CAP", "FIXED_STANDARD"),
        ("适用范围", "ELIGIBILITY", "ELIGIBILITY"),
    ],
)
def test_chinese_rule_type_resolves_to_canonical_topic_concept(
    rule_type: str, topic: str, enum: str
) -> None:
    """模型实际输出中文 rule_type（如“支付比例”），必须映射到标准 topic_concept。

    复现 rule_8f94f240d5da7fb6：_RULE_TYPE_META 仅有英文 key，中文 rule_type
    全部落 UNCLASSIFIED → subject 塌缩 → rule_id 碰撞（影响全部 361 条 REAL 提取）。
    """
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )

    first = _leaf_ids()[0]
    rules = [{
        "rule_type": rule_type,
        "psn_type": "退休人员",
        "payment_ratio": "60%",
        "source_text": "退休人员个人支付比例为职工的60%",
        "confidence": 0.9,
    }]
    result = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, rules)])
    ).get_document("doc_1")

    knowledge = result.units[0].knowledge[0]
    assert knowledge.topic_concept == topic
    assert knowledge.rule_type_enum == enum


@pytest.mark.parametrize("rule_type", ["通用规则", "排除规则"])
def test_ambiguous_rule_type_stays_unclassified(rule_type: str) -> None:
    """语义模糊的 rule_type 不强行映射，保持 UNCLASSIFIED，交 fail-closed 拦截。

    强行映射会让数百条异质规则（“通用规则”338 条）塌缩进同一 subject，制造新碰撞。
    """
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        _RULE_TYPE_META,
    )

    assert rule_type not in _RULE_TYPE_META



def test_field_label_prefers_semantic_metric_name() -> None:
    """字段中文名：语义层 published 指标名优先（如新维度 jjgs→基金归属），硬编码字典兜底。"""
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        _field_label,
    )

    published = {
        "jjgs": Metric(
            metric_code="jjgs", object_code="zcgz", name="基金归属",
            semantic_type="Enum", status="published",
        ),
    }
    # 语义层指标名优先
    assert _field_label("jjgs", published) == "基金归属"
    # 无指标时回退硬编码字典
    assert _field_label("med_type", {}) == "医疗类别"
    # 两者都无 → 原样返回
    assert _field_label("custom_field", {}) == "custom_field"
