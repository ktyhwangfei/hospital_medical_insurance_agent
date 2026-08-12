"""政策抽取未知概念进入语义提议队列。"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import TriggerSource


def _fact(concept: str = "大额互助起付标准") -> dict:
    return {
        "fact_text": "大额互助起付标准为650元。",
        "rules": [{"confidence": 0.9}],
        "unknown_concepts": [{
            "concept": concept,
            "concept_type": "new_metric",
            "metric_code": "zcgz.dazhu_deductible",
            "metric_name": "大额互助起付标准",
            "definition": "大额医疗互助的年度起付金额",
            "semantic_type": "Amount",
            "unit": "元",
            "excerpt": "大额互助起付标准为650元。",
            "confidence": 0.86,
        }],
    }


class _Alignment:
    def __init__(self, fail: bool = False):
        self.signals = []
        self.fail = fail

    def intake_signal(self, signal):
        self.signals.append(signal)
        if self.fail:
            raise RuntimeError("proposal store unavailable")


class _Store:
    def __init__(self):
        self.doc = {
            "doc_id": "doc_1",
            "title": "医保政策",
            "content_text": "第一条 大额互助起付标准为650元。",
        }
        self.extractions: dict[str, dict] = {}
        self._lock = threading.RLock()

    def get_document(self, doc_id):
        return self.doc if doc_id == "doc_1" else None

    def update_document(self, doc_id, data):
        with self._lock:
            self.doc.update(data)
            return self.doc

    def claim_extraction_run(self, doc_id, run_token):
        with self._lock:
            self.doc.update({
                "status": "processing",
                "extraction_run_token": run_token,
            })
            return True

    @contextmanager
    def commit_extraction_run(self, doc_id, run_token):
        with self._lock:
            yield self.doc.get("extraction_run_token") == run_token

    def is_extraction_run_current(self, doc_id, run_token):
        with self._lock:
            return self.doc.get("extraction_run_token") == run_token

    def finish_extraction_run(self, doc_id, run_token, data):
        with self._lock:
            if self.doc.get("extraction_run_token") != run_token:
                return False
            self.doc.update(data)
            return True

    def delete_extractions_by_doc(self, doc_id):
        self.extractions.clear()
        return 0

    def list_extractions(self, page=1, page_size=20, doc_id="", status=""):
        items = [
            item for item in self.extractions.values()
            if (not doc_id or item["doc_id"] == doc_id)
            and (item["status"] == status if status else item["status"] != "archived")
        ]
        return {"items": items, "total": len(items), "page": page, "page_size": page_size}

    def batch_create_extractions(self, items):
        for item in items:
            self.extractions[item["extraction_id"]] = {**item, "status": "draft"}
        return len(items)

    def reconcile_extractions(self, doc_id, items, run_token=None):
        with self._lock:
            if run_token and self.doc.get("extraction_run_token") != run_token:
                return None
            self.batch_create_extractions(items)
            current_ids = {item["extraction_id"] for item in items}
            for extraction in self.extractions.values():
                if (
                    extraction["doc_id"] == doc_id
                    and extraction["extraction_id"] not in current_ids
                    and extraction["status"] != "archived"
                ):
                    extraction["status"] = "archived"
            return len(items)

    def get_extraction(self, extraction_id):
        return self.extractions.get(extraction_id)

    def update_extraction(self, extraction_id, data):
        self.extractions[extraction_id].update(data)
        return self.extractions[extraction_id]


def _assert_signal(signal, extraction: dict) -> None:
    assert signal.trigger_source == TriggerSource.EXTRACTION_UNKNOWN
    assert signal.concept == "大额互助起付标准"
    assert signal.metric_code == "zcgz.dazhu_deductible"
    assert signal.evidence.doc_id == "doc_1"
    assert signal.evidence.unit_id == "unit_1"
    assert signal.evidence.extraction_id == extraction["extraction_id"]
    assert signal.concept in signal.evidence.excerpt
    assert signal.evidence.occurrence_count == 1


def test_extract_single_intakes_unknown_after_extraction_is_persisted(monkeypatch) -> None:
    store = _Store()
    alignment = _Alignment()
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [_fact()])

    result = orch.extract_single("doc_1", "大额互助起付标准为650元。", unit_id="unit_1")

    assert result["success"] is True
    extraction = store.extractions[result["extraction_ids"][0]]
    assert "unknown_concepts" not in extraction["extracted_fields"]
    _assert_signal(alignment.signals[0], extraction)


def test_extract_single_passes_enum_alias_routing_fields(monkeypatch) -> None:
    store = _Store()
    alignment = _Alignment()
    fact = _fact()
    fact["unknown_concepts"] = [{
        "concept": "灵活就业",
        "concept_type": "enum_alias",
        "axis_metric_code": "zcgz.psn_type",
        "domain_code": "psn_type",
        "alias_target": "灵活就业人员",
        "excerpt": "灵活就业人员参照职工医保执行。",
        "confidence": 0.8,
    }]
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [fact])

    result = orch.extract_single(
        "doc_1", "灵活就业人员参照职工医保执行。", unit_id="unit_1"
    )

    assert result["success"] is True
    signal = alignment.signals[0]
    assert signal.axis_metric_code == "zcgz.psn_type"
    assert signal.domain_code == "psn_type"
    assert signal.alias_target == "灵活就业人员"


def test_occurrence_count_is_computed_from_source_not_llm_claim(monkeypatch) -> None:
    store = _Store()
    alignment = _Alignment()
    fact = _fact()
    fact["unknown_concepts"][0]["occurrence_count"] = 999
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [fact])

    result = orch.extract_single(
        "doc_1",
        "大额互助起付标准为650元；次年大额互助起付标准调整。",
        unit_id="unit_1",
    )

    assert result["success"] is True
    assert alignment.signals[0].evidence.occurrence_count == 2


def test_hallucinated_unknown_evidence_is_skipped_without_logging_raw_value(
    monkeypatch, caplog
) -> None:
    store = _Store()
    alignment = _Alignment()
    hallucinated = _fact("患者身份证号110101199001011234")
    # excerpt 虽来自原文，但不含 concept，不能替幻觉概念背书。
    hallucinated["unknown_concepts"][0]["excerpt"] = "普通政策事实。"
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(
        orch, "_extract_policy_facts", lambda *args, **kwargs: [hallucinated]
    )

    result = orch.extract_single("doc_1", "普通政策事实。", unit_id="unit_1")

    assert result["success"] is True
    assert alignment.signals == []
    assert "未知概念证据未在输入原文定位，已跳过" in caplog.text
    assert "110101199001011234" not in caplog.text
    assert "普通政策事实" not in caplog.text


def test_new_enum_value_reaches_value_proposal_with_standard_value(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        ProposalType,
        SemanticAlignmentService,
    )
    from src.semantic_layer.models import BusinessObject, Metric, ValueDomain
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则"
    ))
    registry_store.save_value_domain(ValueDomain(
        domain_code="psn_type", name="人员类别", standard_values=["在职职工", "退休人员"]
    ))
    registry_store.save_metric(Metric(
        metric_code="zcgz.psn_type",
        object_code="zcgz",
        name="人员类别",
        semantic_type="Enum",
        value_domain="psn_type",
        status="published",
    ))
    service = SemanticAlignmentService(
        SemanticRegistry(registry_store), InMemorySemanticAlignmentStore()
    )
    store = _Store()
    fact = _fact()
    fact["unknown_concepts"] = [{
        "concept": "灵活就业人员",
        "concept_type": "new_enum_value",
        "axis_metric_code": "zcgz.psn_type",
        "domain_code": "psn_type",
        "excerpt": "灵活就业人员参照职工医保执行。",
        "confidence": 0.8,
    }]
    orch = PipelineOrchestrator(store=store, alignment_service=service)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [fact])

    result = orch.extract_single(
        "doc_1", "灵活就业人员参照职工医保执行。", unit_id="unit_1"
    )

    assert result["success"] is True
    proposal = service.list_proposals()[0]
    assert proposal.proposal_type == ProposalType.VALUE
    assert proposal.axis_metric_code == "zcgz.psn_type"
    assert proposal.value_draft is not None
    assert proposal.value_draft.domain_code == "psn_type"
    assert proposal.value_draft.standard_value == "灵活就业人员"


def test_run_extraction_intakes_unknown_with_matched_unit(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match

    store = _Store()
    alignment = _Alignment()
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [_fact()])
    monkeypatch.setattr(orch, "_calculate_coverage", lambda *args: {"ratio": 1})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(leaf_match, "match_leaves", lambda *args: ["unit_1"])

    result = orch.run_extraction("doc_1")

    assert result["success"] is True
    extraction = next(iter(store.extractions.values()))
    _assert_signal(alignment.signals[0], extraction)


def test_run_extraction_rerun_replaces_evidence_and_keeps_current_extraction_link(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )
    from src.semantic_layer.models import BusinessObject
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则"
    ))
    service = SemanticAlignmentService(
        SemanticRegistry(registry_store), InMemorySemanticAlignmentStore()
    )
    store = _Store()
    orch = PipelineOrchestrator(store=store, alignment_service=service)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [_fact()])
    monkeypatch.setattr(orch, "_calculate_coverage", lambda *args: {"ratio": 1})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(leaf_match, "match_leaves", lambda *args: ["unit_1"])

    assert orch.run_extraction("doc_1")["success"] is True
    first = service.list_proposals()[0]
    first_extraction_id = first.evidence[0].extraction_id
    assert orch.run_extraction("doc_1")["success"] is True
    rerun = service.list_proposals()[0]

    assert rerun.occurrence_count == 1
    assert rerun.confidence == first.confidence
    assert len(rerun.evidence) == 1
    assert rerun.evidence[0].extraction_id == first_extraction_id
    assert store.get_extraction(rerun.evidence[0].extraction_id) is not None


def test_run_extraction_counts_same_concept_per_fact_unit_with_distinct_evidence(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )
    from src.semantic_layer.models import BusinessObject
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则"
    ))
    service = SemanticAlignmentService(
        SemanticRegistry(registry_store), InMemorySemanticAlignmentStore()
    )
    store = _Store()
    store.doc["content_text"] = (
        "第一条 大额互助起付标准为650元。\n第二条 大额互助起付标准调整为700元。"
    )
    facts = [_fact(), _fact()]
    facts[0]["fact_text"] = "第一条 大额互助起付标准为650元。"
    facts[1]["fact_text"] = "第二条 大额互助起付标准调整为700元。"
    orch = PipelineOrchestrator(store=store, alignment_service=service)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: facts)
    monkeypatch.setattr(orch, "_calculate_coverage", lambda *args: {"ratio": 1})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(
        leaf_match,
        "match_leaves",
        lambda text, _leaves: ["unit_1"] if text.startswith("第一条") else ["unit_2"],
    )

    assert orch.run_extraction("doc_1")["success"] is True
    proposal = service.list_proposals()[0]

    assert proposal.occurrence_count == 2
    assert {item.unit_id for item in proposal.evidence} == {"unit_1", "unit_2"}
    assert {item.excerpt for item in proposal.evidence} == {
        facts[0]["fact_text"], facts[1]["fact_text"],
    }


def test_run_extraction_archives_disappeared_fact_without_breaking_old_evidence(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )
    from src.semantic_layer.models import BusinessObject
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则"
    ))
    service = SemanticAlignmentService(
        SemanticRegistry(registry_store), InMemorySemanticAlignmentStore()
    )
    store = _Store()
    responses = [
        [_fact()],
        [{"fact_text": "普通政策事实。", "rules": [{"confidence": 0.8}], "unknown_concepts": []}],
    ]
    orch = PipelineOrchestrator(store=store, alignment_service=service)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(orch, "_calculate_coverage", lambda *args: {"ratio": 1})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(leaf_match, "match_leaves", lambda *args: ["unit_1"])

    assert orch.run_extraction("doc_1")["success"] is True
    evidence_id = service.list_proposals()[0].evidence[0].extraction_id
    assert orch.run_extraction("doc_1")["success"] is True

    historical = store.get_extraction(evidence_id)
    assert historical is not None
    assert historical["status"] == "archived"
    active = store.list_extractions(doc_id="doc_1")["items"]
    assert {item["source_text"] for item in active} == {"普通政策事实。"}


def test_run_extraction_rejects_hallucinated_fact_context_from_model(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match

    store = _Store()
    store.doc["content_text"] = "普通政策原文。"
    alignment = _Alignment()
    hallucinated = _fact()
    hallucinated["_source_context"] = "大额互助起付标准为650元。"
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(
        orch, "_extract_policy_facts", lambda *args, **kwargs: [hallucinated]
    )
    monkeypatch.setattr(orch, "_calculate_coverage", lambda *args: {"ratio": 1})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(leaf_match, "match_leaves", lambda *args: ["unit_1"])

    result = orch.run_extraction("doc_1")

    assert result["success"] is True
    assert alignment.signals == []


def test_run_extraction_model_json_failure_preserves_old_active_extractions(
    monkeypatch,
) -> None:
    from src.model_service.gateway import ModelGateway
    from src.model_service.models import ModelResponse, TokenUsage

    store = _Store()
    store.extractions["ext_old"] = {
        "extraction_id": "ext_old",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "旧事实",
        "extracted_fields": {"fact_text": "旧事实", "rules": []},
        "confidence": 0.8,
        "status": "reviewed",
    }
    store.doc["content_text"] = "甲" * 600 + "\n" + "乙" * 600
    orch = PipelineOrchestrator(store=store, alignment_service=_Alignment())
    monkeypatch.setattr(orch, "_build_fact_extraction_prompt", lambda *args: "prompt")
    responses = iter(("[]", "not-json"))
    monkeypatch.setattr(
        ModelGateway,
        "generate",
        lambda *args, **kwargs: ModelResponse(
            content=next(responses),
            model_name="fake",
            usage=TokenUsage(0, 0),
            finish_reason="stop",
        ),
    )

    result = orch.run_extraction("doc_1")

    assert result["success"] is False
    assert store.get_extraction("ext_old")["status"] == "reviewed"


def test_run_extraction_legal_empty_facts_archives_previous_active_rows(
    monkeypatch,
) -> None:
    store = _Store()
    store.extractions["ext_old"] = {
        "extraction_id": "ext_old",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "旧事实",
        "extracted_fields": {"fact_text": "旧事实", "rules": []},
        "confidence": 0.8,
        "status": "reviewed",
    }
    orch = PipelineOrchestrator(store=store, alignment_service=_Alignment())
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [])

    result = orch.run_extraction("doc_1")

    assert result["success"] is True
    assert result["total_facts"] == 0
    assert store.get_extraction("ext_old")["status"] == "archived"


def test_stale_concurrent_run_cannot_reconcile_intake_or_overwrite_status(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        InMemorySemanticAlignmentStore,
        SemanticAlignmentService,
    )
    from src.semantic_layer.models import BusinessObject
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

    registry_store = InMemoryRegistryStore()
    registry_store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则"
    ))
    service = SemanticAlignmentService(
        SemanticRegistry(registry_store), InMemorySemanticAlignmentStore()
    )
    store = _Store()
    store.doc["content_text"] = "大额互助起付标准为650元。普通政策事实。"
    a_waiting = threading.Event()
    release_a = threading.Event()
    orch_a = PipelineOrchestrator(store=store, alignment_service=service)
    orch_b = PipelineOrchestrator(store=store, alignment_service=service)

    def extract_a(*_args, **_kwargs):
        a_waiting.set()
        assert release_a.wait(timeout=2)
        return [_fact()]

    monkeypatch.setattr(orch_a, "_extract_policy_facts", extract_a)
    monkeypatch.setattr(
        orch_b,
        "_extract_policy_facts",
        lambda *_args, **_kwargs: [{
            "fact_text": "普通政策事实。",
            "rules": [{"confidence": 0.8}],
            "unknown_concepts": [],
        }],
    )
    monkeypatch.setattr(orch_a, "_calculate_coverage", lambda *args: {"ratio": 0.9})
    monkeypatch.setattr(orch_b, "_calculate_coverage", lambda *args: {"ratio": 0.2})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(leaf_match, "match_leaves", lambda *args: ["unit_1"])
    result_a = {}

    thread_a = threading.Thread(
        target=lambda: result_a.update(orch_a.run_extraction("doc_1"))
    )
    thread_a.start()
    assert a_waiting.wait(timeout=2)
    result_b = orch_b.run_extraction("doc_1")
    release_a.set()
    thread_a.join(timeout=2)

    assert result_b["success"] is True
    assert result_a["success"] is False
    assert "已被更新运行取代" in result_a["error"]
    assert service.list_proposals() == []
    assert store.doc["status"] == "extracted"
    assert store.doc["coverage_ratio"] == 0.2
    active = store.list_extractions(doc_id="doc_1")["items"]
    assert {item["source_text"] for item in active} == {"普通政策事实。"}


def test_claim_waits_while_current_run_intakes_and_finishes(monkeypatch) -> None:
    """token 校验后到 intake/finish 结束前，更新运行不能穿透提交窗口。"""
    from src.knowledge_extension.rule_explanation.policy_struct import leaf_match

    intake_started = threading.Event()
    release_intake = threading.Event()
    b_run_started = threading.Event()
    b_extraction_started = threading.Event()

    class _BlockingAlignment(_Alignment):
        def intake_signal(self, signal):
            intake_started.set()
            assert release_intake.wait(timeout=2)
            super().intake_signal(signal)

    store = _Store()
    store.doc["content_text"] = "大额互助起付标准为650元。普通政策事实。"
    alignment = _BlockingAlignment()
    orch_a = PipelineOrchestrator(store=store, alignment_service=alignment)
    orch_b = PipelineOrchestrator(store=store, alignment_service=alignment)
    monkeypatch.setattr(orch_a, "_extract_policy_facts", lambda *_a, **_k: [_fact()])

    def extract_b(*_args, **_kwargs):
        b_extraction_started.set()
        return [{
            "fact_text": "普通政策事实。",
            "rules": [{"confidence": 0.8}],
            "unknown_concepts": [],
        }]

    monkeypatch.setattr(orch_b, "_extract_policy_facts", extract_b)
    monkeypatch.setattr(orch_a, "_calculate_coverage", lambda *args: {"ratio": 0.9})
    monkeypatch.setattr(orch_b, "_calculate_coverage", lambda *args: {"ratio": 0.2})
    monkeypatch.setattr(leaf_match, "parse_kept_leaves", lambda *args: (None, {}, [], []))
    monkeypatch.setattr(leaf_match, "match_leaves", lambda *args: ["unit_1"])
    result_a: dict = {}
    result_b: dict = {}

    def run_b():
        b_run_started.set()
        result_b.update(orch_b.run_extraction("doc_1"))

    thread_a = threading.Thread(
        target=lambda: result_a.update(orch_a.run_extraction("doc_1"))
    )
    thread_b = threading.Thread(target=run_b)

    thread_a.start()
    assert intake_started.wait(timeout=2)
    thread_b.start()
    try:
        assert b_run_started.wait(timeout=2)
        assert not b_extraction_started.wait(timeout=0.1)
    finally:
        release_intake.set()
    thread_a.join(timeout=2)
    thread_b.join(timeout=2)

    assert result_a["success"] is True
    assert result_b["success"] is True
    assert len(alignment.signals) == 1
    assert store.doc["coverage_ratio"] == 0.2
    active = store.list_extractions(doc_id="doc_1")["items"]
    assert {item["source_text"] for item in active} == {"普通政策事实。"}


def test_reextract_unit_intakes_unknown_after_existing_id_is_updated(monkeypatch) -> None:
    store = _Store()
    store.extractions["ext_existing"] = {
        "extraction_id": "ext_existing",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "大额互助起付标准为650元。补充未知概念。",
        "extracted_fields": {"fact_text": "旧事实", "rules": [], "unknown_concepts": ["旧数据"]},
        "status": "reviewed",
    }
    alignment = _Alignment()
    orch = PipelineOrchestrator(store=store, alignment_service=alignment)
    second_fact = _fact("补充未知概念")
    second_fact["unknown_concepts"][0]["metric_code"] = "zcgz.extra_unknown"
    monkeypatch.setattr(
        orch, "_extract_policy_facts", lambda *args, **kwargs: [_fact(), second_fact]
    )

    result = orch.reextract_unit("ext_existing")

    assert result["success"] is True
    extraction = store.extractions["ext_existing"]
    assert "unknown_concepts" not in extraction["extracted_fields"]
    _assert_signal(alignment.signals[0], extraction)
    assert [signal.concept for signal in alignment.signals] == [
        "大额互助起付标准",
        "补充未知概念",
    ]


def test_proposal_failure_is_logged_without_failing_extraction(monkeypatch, caplog) -> None:
    store = _Store()
    orch = PipelineOrchestrator(store=store, alignment_service=_Alignment(fail=True))
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [_fact()])

    result = orch.extract_single("doc_1", "大额互助起付标准为650元。", unit_id="unit_1")

    assert result["success"] is True
    assert "未知概念提议入队失败" in caplog.text


def test_alignment_service_is_lazy_when_no_unknown_concepts(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation import semantic_alignment

    store = _Store()
    orch = PipelineOrchestrator(store=store)
    monkeypatch.setattr(
        orch,
        "_extract_policy_facts",
        lambda *args, **kwargs: [{"fact_text": "普通事实", "rules": [{"confidence": 0.8}]}],
    )
    monkeypatch.setattr(
        semantic_alignment,
        "get_semantic_alignment_service",
        lambda: (_ for _ in ()).throw(AssertionError("不应初始化语义服务")),
    )

    result = orch.extract_single("doc_1", "普通事实", unit_id="unit_1")

    assert result["success"] is True


def test_default_alignment_provider_is_not_cached_on_orchestrator(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation import semantic_alignment

    store = _Store()
    alignment = _Alignment()
    orch = PipelineOrchestrator(store=store)
    monkeypatch.setattr(orch, "_extract_policy_facts", lambda *args, **kwargs: [_fact()])
    monkeypatch.setattr(
        semantic_alignment, "get_semantic_alignment_service", lambda: alignment
    )

    result = orch.extract_single(
        "doc_1", "大额互助起付标准为650元。", unit_id="unit_1"
    )

    assert result["success"] is True
    assert len(alignment.signals) == 1
    assert orch._alignment_service is None


def test_pipeline_store_hides_archived_by_default_and_allows_explicit_history() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    calls = []

    class _Client:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            return [{"cnt": 0}] if "COUNT(*)" in sql else []

    store = PipelineStore("postgresql://test")
    store._client = _Client()
    store.list_extractions(doc_id="doc_1")
    default_calls = list(calls)
    calls.clear()
    store.list_extractions(doc_id="doc_1", status="archived")

    assert all("e.status <> 'archived'" in sql for sql, _ in default_calls)
    assert all("e.status = %s" in sql for sql, _ in calls)
    assert all("e.status <> 'archived'" not in sql for sql, _ in calls)


def test_pipeline_store_upsert_reuses_existing_extraction_id() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    calls = []

    class _Client:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            if sql.lstrip().startswith("SELECT extraction_id"):
                return [{"extraction_id": "ext_legacy"}]
            return []

    store = PipelineStore("postgresql://test")
    store._client = _Client()
    item = {
        "extraction_id": "ext_deterministic",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "事实",
        "extracted_fields": {"rules": []},
        "confidence": 0.8,
    }

    assert store.batch_create_extractions([item]) == 0
    assert item["extraction_id"] == "ext_legacy"
    assert "status='draft'" in calls[-1][0]


def test_pipeline_store_reconcile_is_one_document_transaction() -> None:
    from contextlib import contextmanager
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    calls = []
    transactions = 0

    class _Client:
        @contextmanager
        def transaction(self):
            nonlocal transactions
            transactions += 1
            yield

        def execute(self, sql, params=()):
            calls.append((sql, params))
            return []

    store = PipelineStore("postgresql://test")
    store._client = _Client()
    items = [{
        "extraction_id": "ext_current",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "事实",
        "extracted_fields": {"rules": []},
        "confidence": 0.8,
    }]

    assert store.reconcile_extractions("doc_1", items) == 1
    assert transactions == 1
    assert "pg_advisory_xact_lock" in calls[0][0]
    assert any("ON CONFLICT (extraction_id) DO UPDATE" in sql for sql, _ in calls)
    assert "status='archived'" in calls[-1][0]
    assert calls[-1][1][-1] == ["ext_current"]


def test_pipeline_store_claim_and_commit_share_document_advisory_lock() -> None:
    from contextlib import contextmanager
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    calls = []
    transactions = 0

    class _Client:
        @contextmanager
        def transaction(self):
            nonlocal transactions
            transactions += 1
            yield

        def execute(self, sql, params=()):
            calls.append((sql, params))
            if "RETURNING doc_id" in sql or "extraction_run_token=%s FOR UPDATE" in sql:
                return [{"doc_id": "doc_1"}]
            return []

    store = PipelineStore("postgresql://test")
    store._client = _Client()

    assert store.claim_extraction_run("doc_1", "token_1") is True
    with store.commit_extraction_run("doc_1", "token_1") as current:
        assert current is True

    lock_calls = [call for call in calls if "pg_advisory_xact_lock" in call[0]]
    assert transactions == 2
    assert len(lock_calls) == 2
    assert lock_calls[0][1] == lock_calls[1][1]
