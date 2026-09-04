from __future__ import annotations

from decimal import Decimal

import pytest

from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    KnowledgeChangeSet,
)
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)
from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore


class FakeIndexBackend:
    def __init__(self, healthy: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.healthy = healthy
        self.records: dict[tuple[str, str], list[dict]] = {}
        self.inserted: dict[tuple[str, str], list[dict]] = {}

    def read_all(self, kind: str, collection_name: str) -> list[dict]:
        self.calls.append((f"read_{kind}", collection_name))
        return [dict(item) for item in self.records.get((kind, collection_name), [])]

    def create(self, kind: str, collection_name: str) -> None:
        self.calls.append((f"create_{kind}", collection_name))

    def insert(self, kind: str, collection_name: str, records: list[dict]) -> None:
        self.calls.append((f"insert_{kind}", collection_name))
        self.inserted[(kind, collection_name)] = records

    def load(self, collection_name: str) -> None:
        self.calls.append(("load", collection_name))

    def is_healthy(self, collection_name: str) -> bool:
        self.calls.append(("health", collection_name))
        return self.healthy


def _building_release(source_change_set_id: str | None = None) -> KnowledgeRelease:
    return KnowledgeRelease(
        release_id="rel_20260803_01",
        status="building",
        facts_collection="policy_facts_rel_20260803_01",
        rules_collection="policy_rules_rel_20260803_01",
        contract_version="2",
        case_set_version=1,
        config_hash="cfg_1",
        source_change_set_id=source_change_set_id,
    )


def _change_set(*, status: str = "PASS", canonical: bool = True) -> KnowledgeChangeSet:
    rule = CanonicalRule(
        rule_id="rule_stable",
        subject="payment_ratio",
        population="employee",
        conditions={"med_type": "inpatient"},
        result={"ratio": "0.8"},
        evidence=["evidence_1"],
    )
    return KnowledgeChangeSet(
        change_set_id="CS_compiled",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="政策",
        status="APPROVED",
        items=[ChangeSetItem(
            item_id="ci_rule_stable",
            change_type="ADD",
            rule_id="rule_stable",
            unit_id="unit_1",
            doc_id="doc_1",
            after={
                "business_sentence": "在职职工住院支付比例为80%。",
                "extraction_id": "ext_1",
            },
            compile_run_id="run_1",
            compilation_status=status,
            canonical_rule=rule if canonical else None,
        )],
    )


class Provider:
    dim = 2

    def encode(self, texts: list[str]):
        return [[0.1, 0.2] for _ in texts]


def _traces() -> InMemoryCompilationTraceStore:
    traces = InMemoryCompilationTraceStore()
    traces.create_run(CompileRun(
        run_id="run_1",
        document_id="doc_1",
        unit_id="unit_1",
        extraction_id="ext_1",
        raw_input={"source_text": "政策原文"},
        llm_output={"rules": []},
    ))
    traces.finish_run("run_1", status="PASS", metrics={})
    return traces


def test_build_loads_and_checks_one_collection_pair_before_ready() -> None:
    from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder

    store = InMemoryPolicyQualityStore()
    release = _building_release()
    store.save_release(release)
    backend = FakeIndexBackend()

    ready = ReleaseIndexBuilder(store, backend).build(
        release.release_id,
        facts=[{"fact_id": "fact_1"}],
        rules=[{"rule_id": "rule_1"}],
    )

    assert ready.status == "ready"
    assert backend.calls == [
        ("create_facts", release.facts_collection),
        ("create_rules", release.rules_collection),
        ("insert_facts", release.facts_collection),
        ("insert_rules", release.rules_collection),
        ("load", release.facts_collection),
        ("load", release.rules_collection),
        ("health", release.facts_collection),
        ("health", release.rules_collection),
    ]


def test_build_merges_global_and_active_baselines_before_candidate_delta() -> None:
    from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder

    store = InMemoryPolicyQualityStore()
    active = KnowledgeRelease(
        release_id="active",
        status="active",
        facts_collection="policy_facts_active",
        rules_collection="policy_rules_active",
        contract_version="1",
        case_set_version=1,
        config_hash="cfg_1",
    )
    store.save_release(active)
    store.active_release_id = active.release_id
    candidate = _building_release()
    store.save_release(candidate)
    backend = FakeIndexBackend()
    backend.records = {
        ("facts", "policy_facts"): [{"fact_id": "fact_global"}],
        ("rules", "policy_rules_v2"): [{"rule_id": "rule_global"}],
        ("facts", active.facts_collection): [{"fact_id": "fact_active"}],
        ("rules", active.rules_collection): [{"rule_id": "rule_active"}],
    }

    ReleaseIndexBuilder(store, backend).build(
        candidate.release_id,
        facts=[{"fact_id": "fact_delta"}],
        rules=[{"rule_id": "rule_delta"}],
    )

    assert {
        item["fact_id"]
        for item in backend.inserted[("facts", candidate.facts_collection)]
    } == {"fact_global", "fact_active", "fact_delta"}
    assert {
        item["rule_id"]
        for item in backend.inserted[("rules", candidate.rules_collection)]
    } == {"rule_global", "rule_active", "rule_delta"}


def test_build_records_publish_step_and_lineage_only_after_health() -> None:
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
        ReleaseIndexBuilder,
    )

    store = InMemoryPolicyQualityStore()
    release = _building_release("CS_compiled")
    store.save_release(release)
    traces = _traces()
    facts, rules, publications = KnowledgeWorkbenchReleaseSource(
        object(), Provider()
    ).records(_change_set())

    ready = ReleaseIndexBuilder(store, FakeIndexBackend(), traces).build(
        release.release_id,
        facts=facts,
        rules=rules,
        publications=publications,
    )

    assert ready.status == "ready"
    assert rules[0]["rule_id"] == "rule_stable"
    trace = traces.get_rule_trace("rule_stable")
    assert trace is not None
    assert trace.steps[-1].stage == "PUBLISH"
    assert trace.publication.release_id == release.release_id


def test_specific_ratio_subject_reuses_base_payment_ratio_field() -> None:
    """规则主体可以细化，但发布结构不得为每个主体新增指标字段。"""
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
    )

    rule = CanonicalRule(
        rule_id="rule_fund_ratio",
        subject="large_medical_mutual_aid_payment_ratio",
        population="退休人员",
        result={"ratio": "0.8"},
        evidence=["evidence_1"],
    )

    payload = KnowledgeWorkbenchReleaseSource._runtime_rule(rule, "原文")

    assert payload["rule_type"] == "支付比例"
    assert str(payload["payment_ratio"]) == "0.8"
    assert "large_medical_mutual_aid_payment_ratio" not in payload


def test_amount_subjects_publish_with_skill_rule_types() -> None:
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
    )

    deductible = KnowledgeWorkbenchReleaseSource._runtime_rule(CanonicalRule(
        rule_id="rule_deductible",
        subject="deductible",
        result={"amount": "1800"},
        evidence=["evidence_1"],
    ), "原文")
    cap = KnowledgeWorkbenchReleaseSource._runtime_rule(CanonicalRule(
        rule_id="rule_cap",
        subject="cap",
        result={"amount": "20000"},
        evidence=["evidence_1"],
    ), "原文")

    assert deductible["rule_type"] == "起付线"
    assert deductible["deductible_amount"] == "1800"
    assert cap["rule_type"] == "封顶线"
    assert cap["cap_amount"] == "20000"


def test_rule_entity_serializes_decimal_detail_for_milvus_dynamic_json() -> None:
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        rule_to_entity,
    )

    entity = rule_to_entity(
        {"rule_id": "rule_decimal", "payment_ratio": Decimal("0.8")},
        [0.1, 0.2],
    )

    assert entity["payment_ratio"]["value"] == "0.8"


def test_trace_failure_keeps_release_building() -> None:
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
        ReleaseIndexBuilder,
    )

    class FailingTraceStore(InMemoryCompilationTraceStore):
        def save_lineage(self, **kwargs):
            raise RuntimeError("trace unavailable")

    traces = FailingTraceStore()
    base = _traces().get_run("run_1")
    traces.create_run(base.model_copy(update={"status": "RUNNING", "finished_at": None}))
    traces.finish_run("run_1", status="PASS", metrics={})
    store = InMemoryPolicyQualityStore()
    release = _building_release("CS_compiled")
    store.save_release(release)
    facts, rules, publications = KnowledgeWorkbenchReleaseSource(
        object(), Provider()
    ).records(_change_set())

    with pytest.raises(RuntimeError, match="trace unavailable"):
        ReleaseIndexBuilder(store, FakeIndexBackend(), traces).build(
            release.release_id,
            facts=facts,
            rules=rules,
            publications=publications,
        )

    assert store.get_release(release.release_id).status == "building"


def test_multi_rule_run_writes_one_publish_step_and_retries_partial_lineage() -> None:
    from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder

    class FailSecondLineageOnce(InMemoryCompilationTraceStore):
        failed = False

        def save_lineage(self, **kwargs):
            if kwargs["rule"].rule_id == "rule_b" and not self.failed:
                self.failed = True
                raise RuntimeError("second lineage unavailable")
            return super().save_lineage(**kwargs)

    traces = FailSecondLineageOnce()
    base_run = CompileRun(
        run_id="run_multi",
        document_id="doc_1",
        unit_id="unit_1",
        extraction_id="ext_1",
        raw_input={},
        llm_output={},
    )
    traces.create_run(base_run)
    traces.finish_run("run_multi", status="PASS", metrics={})
    rules = [
        CanonicalRule(
            rule_id=rule_id,
            subject="payment_ratio",
            result={"ratio": ratio},
            evidence=[f"evidence_{rule_id}"],
        )
        for rule_id, ratio in (("rule_b", "0.7"), ("rule_a", "0.8"))
    ]
    for item in rules:
        traces.save_candidate_lineage(
            rule_id=item.rule_id,
            rule=item,
            run_id="run_multi",
            extraction_id="ext_1",
            document_id="doc_1",
        )
    publications = [
        ("run_multi", "ext_1", "doc_1", item) for item in rules
    ]
    store = InMemoryPolicyQualityStore()
    release = _building_release("CS_compiled")
    store.save_release(release)
    builder = ReleaseIndexBuilder(store, FakeIndexBackend(), traces)

    with pytest.raises(RuntimeError, match="second lineage unavailable"):
        builder.build(
            release.release_id,
            facts=[{"fact_id": "fact_1"}],
            rules=[{"rule_id": "rule_a"}, {"rule_id": "rule_b"}],
            publications=publications,
        )
    ready = builder.build(
        release.release_id,
        facts=[{"fact_id": "fact_1"}],
        rules=[{"rule_id": "rule_a"}, {"rule_id": "rule_b"}],
        publications=publications,
    )

    assert ready.status == "ready"
    for rule_id in ("rule_a", "rule_b"):
        trace = traces.get_rule_trace(rule_id)
        assert trace is not None
        publish_steps = [item for item in trace.steps if item.stage == "PUBLISH"]
        assert len(publish_steps) == 1
        assert publish_steps[0].input_payload["rule_ids"] == ["rule_a", "rule_b"]
        assert len(trace.history) == 1


def test_unhealthy_collection_pair_never_becomes_ready() -> None:
    from src.knowledge_extension.rule_explanation.release_index import ReleaseIndexBuilder

    store = InMemoryPolicyQualityStore()
    release = _building_release()
    store.save_release(release)

    with pytest.raises(RuntimeError, match="collection 对健康检查失败"):
        ReleaseIndexBuilder(store, FakeIndexBackend(healthy=False)).build(
            release.release_id, facts=[], rules=[]
        )

    assert store.get_release(release.release_id).status == "building"  # type: ignore[union-attr]


def test_workbench_content_source_preserves_stable_knowledge_id() -> None:
    from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
        ApprovedUnit,
        KnowledgeConfidence,
        KnowledgeItem,
        KnowledgeWorkbenchDocument,
        WorkbenchDocumentList,
        WorkbenchDocumentSummary,
    )
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
    )

    item = KnowledgeItem(
        knowledge_id="kn_stable",
        unit_id="unit_1",
        extraction_id="ext_1",
        relationship_source="persisted",
        business_sentence="在职职工住院支付比例为80%。",
        source_text="政策原文",
        fields=[],
        confidence=KnowledgeConfidence(
            completeness=1, accuracy=None, source_fidelity=1,
            model_confidence=1, value_domain_compliance=None, overall=1,
        ),
        citations=[],
    )

    class Workbench:
        def list_documents(self):
            return WorkbenchDocumentList(items=[WorkbenchDocumentSummary(
                doc_id="doc_1", doc_title="政策", approved_unit_count=1, knowledge_count=1,
            )], total=1)

        def get_document(self, doc_id: str):
            return KnowledgeWorkbenchDocument(
                doc_id=doc_id, doc_title="政策", contract_version="2",
                units=[ApprovedUnit(
                    unit_id="unit_1", doc_id=doc_id, doc_title="政策", path=["第一条"],
                    source_text="政策原文", order_no=1, status="reviewed",
                    knowledge_count=1, knowledge=[item],
                )],
            )

    class Provider:
        dim = 2

        def encode(self, texts: list[str]):
            return [[0.1, 0.2] for _ in texts]

    facts, rules, publications = KnowledgeWorkbenchReleaseSource(
        Workbench(), Provider()
    ).records(_change_set())

    assert len(facts) == 1
    assert rules[0]["rule_id"] == "rule_stable"
    assert publications[0][0] == "run_1"


@pytest.mark.parametrize(
    "change_set",
    [_change_set(status="REVIEW"), _change_set(canonical=False)],
)
def test_release_source_rejects_non_publishable_items(change_set) -> None:
    from src.knowledge_extension.rule_explanation.release_index import (
        KnowledgeWorkbenchReleaseSource,
    )

    with pytest.raises(ValueError, match="规范规则|编译状态"):
        KnowledgeWorkbenchReleaseSource(object(), Provider()).records(change_set)


def test_promote_gate_rejects_missing_release_lineage(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    change_set = _change_set()

    class ChangeSets:
        def get_change_set(self, change_set_id: str):
            return change_set

    monkeypatch.setattr(
        policy_workbench_routes,
        "_validate_release_source_before_promote",
        lambda release, active_retry: None,
    )
    monkeypatch.setattr(
        policy_workbench_routes, "_get_change_set_service", lambda: ChangeSets()
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_compilation_trace_store",
        lambda: InMemoryCompilationTraceStore(),
    )

    with pytest.raises(ValueError, match="编译血缘"):
        policy_workbench_routes._validate_governed_release_source_before_promote(
            _building_release(change_set.change_set_id), active_retry=False
        )


def test_promote_gate_rejects_same_rule_lineage_from_old_run(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    change_set = _change_set()

    class ChangeSets:
        def get_change_set(self, _change_set_id: str):
            return change_set

    traces = InMemoryCompilationTraceStore()
    traces.create_run(CompileRun(
        run_id="run_old",
        document_id="doc_1",
        unit_id="unit_1",
        extraction_id="ext_old",
        raw_input={},
        llm_output={},
    ))
    traces.finish_run("run_old", status="PASS", metrics={})
    traces.save_lineage(
        rule=change_set.items[0].canonical_rule,
        run_id="run_old",
        extraction_id="ext_old",
        document_id="doc_1",
        release_id="rel_20260803_01",
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_validate_release_source_before_promote",
        lambda release, active_retry: None,
    )
    monkeypatch.setattr(
        policy_workbench_routes, "_get_change_set_service", lambda: ChangeSets()
    )
    monkeypatch.setattr(
        policy_workbench_routes, "_get_compilation_trace_store", lambda: traces
    )

    with pytest.raises(ValueError, match="编译血缘"):
        policy_workbench_routes._validate_governed_release_source_before_promote(
            _building_release(change_set.change_set_id), active_retry=False
        )
