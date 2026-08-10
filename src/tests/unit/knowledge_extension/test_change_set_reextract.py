"""ChangeSetService.reextract 单元测试（迭代 18 S2，Option A 原地刷新）。

验证：
- 状态校验（仅 PENDING_REVIEW/NEEDS_DECISION 可重提）
- item_ids → extraction_id 映射与去重（多 item 共享 extraction 只重提一次）
- 透传 override + reset_status="reviewed"（保持单元在工作台可见）
- 部分失败逐条上报
- 原地刷新后变更集保持 PENDING_REVIEW 并记录 reextracted 决策
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    KnowledgeChangeSet,
)
from src.knowledge_extension.rule_explanation.change_set_service import ChangeSetService
from src.knowledge_extension.rule_explanation.change_set_store import InMemoryChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
    ReextractReport,
)


def _change_set(status: str = "PENDING_REVIEW", items=None) -> KnowledgeChangeSet:
    return KnowledgeChangeSet(
        change_set_id="cs_1",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="政策文档",
        status=status,
        items=items or [],
    )


def _item(item_id: str, extraction_id: str) -> ChangeSetItem:
    return ChangeSetItem(
        item_id=item_id,
        change_type="ADD",
        rule_id=item_id,
        unit_id="u1",
        doc_id="doc_1",
        after={"extraction_id": extraction_id, "knowledge_id": item_id},
    )


def _service(store, orchestrator=None) -> ChangeSetService:
    return ChangeSetService(MagicMock(), store, orchestrator=orchestrator)


def test_reextract_rejects_non_reviewable_status():
    store = InMemoryChangeSetStore()
    store.save(_change_set(status="APPROVED", items=[_item("ci_1", "ext_1")]))
    svc = _service(store, MagicMock())
    with pytest.raises(ValueError):
        svc.reextract("cs_1")


def test_reextract_allows_needs_decision():
    store = InMemoryChangeSetStore()
    store.save(_change_set(status="NEEDS_DECISION", items=[_item("ci_1", "ext_1")]))
    orch = MagicMock()
    orch.reextract_unit.return_value = {
        "success": True, "extraction": {"extracted_fields": {"total_rules": 1, "rules": [{}]}}
    }
    svc = _service(store, orch)
    svc._rebuild_in_place = MagicMock(return_value=_change_set())
    report = svc.reextract("cs_1")
    assert report.succeeded == 1


def test_reextract_single_item_delegates_to_orchestrator_with_reviewed_status():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1")]))
    orch = MagicMock()
    orch.reextract_unit.return_value = {
        "success": True,
        "extraction_id": "ext_1",
        "extraction": {"extracted_fields": {"total_rules": 2, "rules": [{}, {}]}},
    }
    svc = _service(store, orch)
    svc._rebuild_in_place = MagicMock(return_value=_change_set(items=[_item("ci_1", "ext_1")]))

    ov = ExtractionOverride(model_name="my-model", operator="rev1")
    report = svc.reextract("cs_1", item_ids=["ci_1"], override=ov)

    # 透传 extraction_id + override + reset_status=reviewed（保持单元可见）
    orch.reextract_unit.assert_called_once_with("ext_1", ov, reset_status="reviewed")
    assert isinstance(report, ReextractReport)
    assert report.total == 1
    assert report.succeeded == 1
    assert report.failed == 0
    assert report.items[0].extraction_id == "ext_1"
    assert report.items[0].item_ids == ["ci_1"]
    assert report.items[0].success
    assert report.items[0].model_used == "my-model"
    assert report.items[0].new_knowledge_count == 2
    assert report.override_applied == ov.model_dump()


def test_reextract_all_items_when_item_ids_none():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1"), _item("ci_2", "ext_2")]))
    orch = MagicMock()
    orch.reextract_unit.return_value = {
        "success": True, "extraction": {"extracted_fields": {"total_rules": 1, "rules": [{}]}}
    }
    svc = _service(store, orch)
    svc._rebuild_in_place = MagicMock(return_value=_change_set())

    report = svc.reextract("cs_1")

    called = {c.args[0] for c in orch.reextract_unit.call_args_list}
    assert called == {"ext_1", "ext_2"}
    assert report.total == 2


def test_reextract_groups_items_sharing_extraction():
    """两个 item 共享同一 extraction → 只重提取一次，item_ids 合并。"""
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1"), _item("ci_2", "ext_1")]))
    orch = MagicMock()
    orch.reextract_unit.return_value = {
        "success": True, "extraction": {"extracted_fields": {"total_rules": 1, "rules": [{}]}}
    }
    svc = _service(store, orch)
    svc._rebuild_in_place = MagicMock(return_value=_change_set())

    report = svc.reextract("cs_1")

    assert orch.reextract_unit.call_count == 1
    assert report.total == 1  # 按 extraction 计
    assert set(report.items[0].item_ids) == {"ci_1", "ci_2"}


def test_reextract_partial_failure_reported_per_extraction():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1"), _item("ci_2", "ext_2")]))
    orch = MagicMock()
    orch.reextract_unit.side_effect = [
        {"success": True, "extraction": {"extracted_fields": {"total_rules": 1, "rules": [{}]}}},
        {"success": False, "error": "LLM 未返回结果"},
    ]
    svc = _service(store, orch)
    svc._rebuild_in_place = MagicMock(return_value=_change_set())

    report = svc.reextract("cs_1")
    assert report.succeeded == 1
    assert report.failed == 1
    failed = next(r for r in report.items if not r.success)
    assert failed.error == "LLM 未返回结果"
    assert failed.model_used is None  # 失败项不回显模型


def test_reextract_missing_item_ids_raises():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1")]))
    svc = _service(store, MagicMock())
    with pytest.raises(ValueError):
        svc.reextract("cs_1", item_ids=["ci_unknown"])


def test_reextract_records_decision_and_keeps_pending_review():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1")]))
    orch = MagicMock()
    orch.reextract_unit.return_value = {
        "success": True, "extraction": {"extracted_fields": {"total_rules": 1, "rules": [{}]}}
    }
    svc = _service(store, orch)
    svc._rebuild_in_place = MagicMock(return_value=_change_set(items=[_item("ci_1", "ext_1")]))

    svc.reextract("cs_1", override=ExtractionOverride(operator="rev1"))

    cs = store.get("cs_1")
    assert cs.status == "PENDING_REVIEW"
    assert cs.review_decision["action"] == "reextracted"
    assert cs.review_decision["reviewed_by"] == "rev1"


def test_reextract_no_extraction_id_raises():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[ChangeSetItem(
        item_id="ci_1", change_type="ADD", rule_id="ci_1",
        unit_id="u1", doc_id="doc_1", after={},
    )]))
    svc = _service(store, MagicMock())
    with pytest.raises(ValueError):
        svc.reextract("cs_1")


# ── 迭代 19 修改2：test_extract（不落库预览）────────────────────


def _orch_with_extraction(extraction):
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )

    class _Store:
        def get_extraction(self, extraction_id):
            return extraction if extraction["extraction_id"] == extraction_id else None

        def get_document(self, doc_id):
            return {"title": "政策标题"} if extraction["doc_id"] == doc_id else None

    return PipelineOrchestrator(store=_Store())


def test_test_extract_returns_preview_without_persisting(monkeypatch):
    """test_extract 用单元原文+override 跑提取，返回 facts，不写存储。"""
    from src.model_service.gateway import ModelGateway
    from src.model_service.models import ModelResponse, TokenUsage

    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1")]))
    extraction = {
        "extraction_id": "ext_1",
        "doc_id": "doc_1",
        "source_text": "（四）退休人员个人支付比例为职工支付比例的60%。",
        "extracted_fields": {"fact_text": "旧", "rules": []},
    }
    orch = _orch_with_extraction(extraction)
    svc = _service(store, orch)
    written = {}
    orch.store.update_extraction = lambda eid, data: written.update({eid: data}) or {}

    monkeypatch.setattr(
        ModelGateway,
        "generate",
        lambda self, messages, model_type, scene, max_tokens=None, model_override=None: ModelResponse(
            content='[{"fact_text": "退休人员支付60%", "rules": [{"payment_ratio": "60%", "psn_type": "退休人员", "confidence": 0.9}]}]',
            model_name=model_override or "default",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        ),
    )

    ov = ExtractionOverride(prompt_mode="schema", operator="rev1")
    result = svc.test_extract("cs_1", "ci_1", override=ov)

    assert result["item_id"] == "ci_1"
    assert result["fact_count"] == 1
    assert result["rule_count"] == 1
    assert "payment_ratio" in result["fields_extracted"]
    assert "psn_type" in result["fields_extracted"]
    assert result["facts"][0]["rules"][0]["payment_ratio"] == "60%"
    # 关键：不落库（update_extraction 未被调用）
    assert written == {}


def test_test_extract_missing_item_raises():
    store = InMemoryChangeSetStore()
    store.save(_change_set(items=[_item("ci_1", "ext_1")]))
    svc = _service(store, _orch_with_extraction({
        "extraction_id": "ext_1", "doc_id": "doc_1", "source_text": "x",
    }))
    with pytest.raises(ValueError):
        svc.test_extract("cs_1", "ci_missing")
