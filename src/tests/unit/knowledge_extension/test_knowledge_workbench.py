from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
    parse_kept_leaves,
)


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
    assert "准确性待经典用例验证" in knowledge.confidence.uncertainties
    assert knowledge.citations[0].source_id == "doc_1"


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


def test_extract_single_persists_explicit_unit_id() -> None:
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

    assert result["success"] is True
    assert store.created[0]["unit_id"] == "unit_1"


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
