from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    KnowledgeChangeSet,
    SourceUnitRevision,
)
from src.knowledge_extension.rule_explanation.change_set_service import ChangeSetService
from src.knowledge_extension.rule_explanation.change_set_store import InMemoryChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    KnowledgeBuildTask,
    KnowledgeBuildTaskUnit,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeConfidence,
    KnowledgeItem,
)
from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
    PolicyRuleCompiler,
)
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
)
from src.knowledge_extension.rule_explanation.policy_compiler.service import (
    PolicyCompilationService,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)
from src.knowledge_extension.rule_explanation.published_snapshot_store import (
    InMemoryPublishedSnapshotStore,
)
from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityRun,
)
from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore
from src.knowledge_extension.rule_explanation.release_index import (
    KnowledgeWorkbenchReleaseSource,
    ReleaseIndexBuilder,
)
from src.runtime.api.app import create_app


QUALITY_CONFIG_HASH = "197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22"
PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


class HealthyBackend:
    def create(self, kind: str, collection_name: str) -> None:
        pass

    def insert(self, kind: str, collection_name: str, records: list[dict]) -> None:
        pass

    def load(self, collection_name: str) -> None:
        pass

    def is_healthy(self, collection_name: str) -> bool:
        return True


class InvalidRuleJsonBackend(HealthyBackend):
    def insert(self, kind: str, collection_name: str, records: list[dict]) -> None:
        if kind == "rules":
            raise TypeError("规则索引字段类型不兼容")


class ReleaseSearcher:
    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]:
        return ["kn_expected"] if release.release_id == "candidate" else []


class LifecycleReleaseSearcher:
    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]:
        return [] if release.release_id == "baseline" else ["kn_expected"]


def test_candidate_build_test_and_manual_atomic_promotion_flow() -> None:
    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_required",
        name="经典必测用例",
        query="职工住院支付比例",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))
    store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    store.save_run(QualityRun(
        run_id="run_baseline", release_id="baseline", case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH, status="passed",
    ))
    store.promote_release("baseline", "reviewer_a")
    store.save_release(KnowledgeRelease(
        release_id="candidate",
        status="building",
        facts_collection="policy_facts_candidate",
        rules_collection="policy_rules_candidate",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))

    ready = ReleaseIndexBuilder(store, HealthyBackend()).build(
        "candidate", facts=[{"fact_id": "f1"}], rules=[{"rule_id": "r1"}]
    )
    assert ready.status == "ready"

    run = PolicyQualityService(store, ReleaseSearcher()).run_release(
        "candidate", repeat_count=3
    )
    assert run.status == "passed"
    assert store.get_active_release().release_id == "baseline"  # type: ignore[union-attr]

    promoted = store.promote_release("candidate", "reviewer_b")
    assert promoted.status == "active"
    assert store.get_active_release().release_id == "candidate"  # type: ignore[union-attr]
    assert store.get_release("baseline").status == "retired"  # type: ignore[union-attr]


class FailOncePublishedChangeSetStore(InMemoryChangeSetStore):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure
        self.fail_next_publish = True

    def transition_status_with_task(self, *args, **kwargs):
        if kwargs["target_status"] == "PUBLISHED" and self.fail_next_publish:
            self.fail_next_publish = False
            raise self.failure
        return super().transition_status_with_task(*args, **kwargs)


class FailOnceSnapshotStore(InMemoryPublishedSnapshotStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_save = True

    def save(self, snapshot):
        if self.fail_next_save:
            self.fail_next_save = False
            raise OSError("transient snapshot storage failure")
        return super().save(snapshot)


class FailingSourceChangeSetStore(InMemoryChangeSetStore):
    fail_source_reads = False

    def get(self, change_set_id: str) -> KnowledgeChangeSet | None:
        if self.fail_source_reads:
            raise RuntimeError("change-set store unavailable")
        return super().get(change_set_id)


class FailingSourceBuildTaskStore(InMemoryKnowledgeBuildStore):
    fail_source_reads = False

    def get(self, task_id: str) -> KnowledgeBuildTask | None:
        if self.fail_source_reads:
            raise RuntimeError("build-task store unavailable")
        return super().get(task_id)


def _lifecycle_client(
    monkeypatch,
    *,
    change_set_store: InMemoryChangeSetStore | None = None,
    build_store: InMemoryKnowledgeBuildStore | None = None,
    snapshot_store: InMemoryPublishedSnapshotStore | None = None,
) -> tuple[
    TestClient,
    InMemoryPolicyQualityStore,
    InMemoryChangeSetStore,
    InMemoryKnowledgeBuildStore,
    InMemoryPublishedSnapshotStore,
]:
    from src.runtime.api import policy_workbench_routes

    trace_store = InMemoryCompilationTraceStore()
    compile_run = CompileRun(
        run_id="run_task_1",
        document_id="doc_1",
        unit_id="unit_1",
        extraction_id="ext_task_1",
        raw_input={"source_text": "candidate source"},
        llm_output={"facts": []},
    )
    trace_store.create_run(compile_run)
    trace_store.finish_run(compile_run.run_id, status="PASS", metrics={"rules": 1})
    canonical_rule = CanonicalRule(
        rule_id="rule_task_1",
        subject="benefit_rule",
        result={"value": "candidate"},
        evidence=["evidence_task_1"],
    )
    selected_change_set_store = change_set_store or InMemoryChangeSetStore()
    selected_change_set_store.save(KnowledgeChangeSet(
        change_set_id="CS_task_1",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        build_task_id="KB_task_1",
        semantic_contract_version="2",
        status="PENDING_REVIEW",
        items=[ChangeSetItem(
            item_id="ITEM_task_1",
            change_type="ADD",
            rule_id=canonical_rule.rule_id,
            unit_id="unit_1",
            doc_id="doc_1",
            after={
                "extraction_id": compile_run.extraction_id,
                "business_sentence": "candidate",
            },
            compile_run_id=compile_run.run_id,
            compilation_status="PASS",
            canonical_rule=canonical_rule,
        )],
    ))
    selected_build_store = build_store or InMemoryKnowledgeBuildStore()
    change_set_service = ChangeSetService(
        object(), selected_change_set_store, build_store=selected_build_store
    )
    selected_build_store.create_with_claims(KnowledgeBuildTask(
        task_id="KB_task_1",
        name="职工医保待遇知识构建",
        status="WAITING_REVIEW",
        build_mode="INITIAL",
        semantic_contract_version="2",
        pipeline_version="pipeline-v1",
        model_scene="policy-knowledge-build",
        config_hash="cfg_1",
        created_by="policy-editor",
        units=[KnowledgeBuildTaskUnit(
            doc_id="doc_1",
            doc_title="职工医保待遇政策",
            unit_id="unit_1",
            unit_revision_id="UR_1",
            status="BUILT",
            candidate_result_ids=["CS_task_1"],
        )],
        processed_units=1,
        result_change_set_id="CS_task_1",
    ))
    quality_store = InMemoryPolicyQualityStore()
    quality_service = PolicyQualityService(
        quality_store,
        LifecycleReleaseSearcher(),
    )
    selected_snapshot_store = snapshot_store or InMemoryPublishedSnapshotStore()
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: change_set_service,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_knowledge_build_store",
        lambda: selected_build_store,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_quality_store",
        lambda: quality_store,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_quality_service",
        lambda: quality_service,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_snapshot_store",
        lambda: selected_snapshot_store,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_compilation_trace_store",
        lambda: trace_store,
    )
    return (
        TestClient(create_app(), raise_server_exceptions=False),
        quality_store,
        selected_change_set_store,
        selected_build_store,
        selected_snapshot_store,
    )


def _approve_and_prepare_release(
    client: TestClient,
    quality_store: InMemoryPolicyQualityStore,
) -> None:
    from src.runtime.api import policy_workbench_routes

    approved = client.post(
        f"{PREFIX}/change-sets/CS_task_1/approve",
        json={"reviewer": "reviewer_a", "note": "通过"},
    )
    assert approved.status_code == 200
    test_case = client.post(f"{PREFIX}/test-cases", json={
        "case_id": "case_lifecycle",
        "name": "发布生命周期经典用例",
        "query": "职工住院支付比例",
        "mode": "semantic",
        "expected_knowledge_ids": ["kn_expected"],
    })
    assert test_case.status_code == 201
    created = client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_task_1",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_task_1",
    })
    assert created.status_code == 201
    change_set = policy_workbench_routes._get_change_set_service().get_change_set(
        "CS_task_1"
    )
    assert change_set is not None
    item = change_set.items[0]
    assert item.canonical_rule is not None
    assert item.compile_run_id is not None
    policy_workbench_routes._get_compilation_trace_store().save_lineage(
        rule=item.canonical_rule,
        run_id=item.compile_run_id,
        extraction_id=str((item.after or {}).get("extraction_id")),
        document_id=item.doc_id,
        release_id="candidate_task_1",
    )
    release = quality_store.get_release("candidate_task_1")
    assert release is not None
    quality_store.save_release(release.model_copy(update={"status": "ready"}))
    tested = client.post(
        f"{PREFIX}/releases/candidate_task_1/test",
        json={"repeat_count": 3},
    )
    assert tested.status_code == 200
    assert tested.json()["status"] == "passed"


def test_task_backed_release_promotion_publishes_lineage_and_releases_claim(
    monkeypatch,
) -> None:
    client, quality_store, change_sets, build_tasks, snapshots = _lifecycle_client(
        monkeypatch
    )
    _approve_and_prepare_release(client, quality_store)

    promoted = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert promoted.status_code == 200
    snapshot = snapshots.get("candidate_task_1")
    assert snapshot is not None
    assert snapshot.source_change_set_id == "CS_task_1"
    assert change_sets.get("CS_task_1").status == "PUBLISHED"
    assert build_tasks.get("KB_task_1").status == "PUBLISHED"
    assert build_tasks.get_claim("doc_1", "unit_1") is None


def test_task_backed_approved_change_set_can_return_for_rebuild(monkeypatch) -> None:
    client, quality_store, change_sets, build_tasks, _snapshots = _lifecycle_client(
        monkeypatch
    )
    _approve_and_prepare_release(client, quality_store)

    returned = client.post(
        f"{PREFIX}/change-sets/CS_task_1/return",
        json={"reviewer": "reviewer_b", "note": "经典用例集已更新"},
    )

    assert returned.status_code == 200
    assert change_sets.get("CS_task_1").status == "RETURNED"
    assert build_tasks.get("KB_task_1").status == "RETURNED"
    assert build_tasks.get_claim("doc_1", "unit_1") is None


def test_promotion_retry_finishes_lineage_after_task_sync_failure(
    monkeypatch,
) -> None:
    failing_store = FailOncePublishedChangeSetStore(
        RuntimeError("transient lineage transaction failure")
    )
    client, quality_store, change_sets, build_tasks, snapshots = _lifecycle_client(
        monkeypatch,
        change_set_store=failing_store,
    )
    _approve_and_prepare_release(client, quality_store)

    first = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert first.status_code == 503
    assert first.json()["detail"]["error_code"] == "POLICY_RELEASE_SYNC_PENDING"
    assert quality_store.get_release("candidate_task_1").status == "active"
    assert snapshots.get("candidate_task_1").source_change_set_id == "CS_task_1"
    assert change_sets.get("CS_task_1").status == "APPROVED"
    assert build_tasks.get("KB_task_1").status == "APPROVED_PENDING_RELEASE"
    assert build_tasks.get_claim("doc_1", "unit_1") is not None
    pending_gate = client.get(
        f"{PREFIX}/releases/candidate_task_1/gate-status"
    )
    assert pending_gate.status_code == 200
    assert pending_gate.json()["sync_pending"] is True
    assert any(
        "知识变更集" in reason
        for reason in pending_gate.json()["sync_pending_reasons"]
    )
    active_fallback = client.get(f"{PREFIX}/published/active")
    assert active_fallback.status_code == 200
    assert active_fallback.json()["source_change_set_id"] == "CS_task_1"

    retried = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert retried.status_code == 200
    assert build_tasks.get("KB_task_1").status == "PUBLISHED"
    assert build_tasks.get_claim("doc_1", "unit_1") is None
    completed_gate = client.get(
        f"{PREFIX}/releases/candidate_task_1/gate-status"
    )
    assert completed_gate.json()["sync_pending"] is False
    assert completed_gate.json()["sync_pending_reasons"] == []


def test_post_active_lineage_value_error_is_sync_pending_and_retryable(
    monkeypatch,
) -> None:
    failing_store = FailOncePublishedChangeSetStore(
        ValueError("lineage compare-and-set conflict")
    )
    client, quality_store, change_sets, build_tasks, _snapshots = _lifecycle_client(
        monkeypatch,
        change_set_store=failing_store,
    )
    _approve_and_prepare_release(client, quality_store)

    first = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert first.status_code == 503
    assert first.json()["detail"]["error_code"] == "POLICY_RELEASE_SYNC_PENDING"
    assert quality_store.get_active_release().release_id == "candidate_task_1"  # type: ignore[union-attr]
    assert change_sets.get("CS_task_1").status == "APPROVED"
    assert build_tasks.get("KB_task_1").status == "APPROVED_PENDING_RELEASE"

    retried = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert retried.status_code == 200
    assert build_tasks.get("KB_task_1").status == "PUBLISHED"
    assert build_tasks.get_claim("doc_1", "unit_1") is None


def test_tampered_source_does_not_replace_existing_active_release(
    monkeypatch,
) -> None:
    client, quality_store, change_sets, _build_tasks, snapshots = _lifecycle_client(
        monkeypatch
    )
    quality_store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    quality_store.save_run(QualityRun(
        run_id="run_baseline",
        release_id="baseline",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))
    quality_store.promote_release("baseline", "publisher")
    _approve_and_prepare_release(client, quality_store)
    change_sets.update_status("CS_task_1", "REJECTED")

    response = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LINEAGE_INVALID"
    )
    assert quality_store.get_active_release().release_id == "baseline"
    assert quality_store.get_release("baseline").status == "active"
    assert quality_store.get_release("candidate_task_1").status == "passed"
    assert snapshots.get("candidate_task_1") is None


@pytest.mark.parametrize("unavailable_store", ["change_set", "build_task"])
def test_source_store_failure_blocks_promotion_before_active_switch(
    monkeypatch,
    unavailable_store: str,
) -> None:
    failing_change_sets = FailingSourceChangeSetStore()
    failing_build_tasks = FailingSourceBuildTaskStore()
    client, quality_store, change_sets, build_tasks, snapshots = _lifecycle_client(
        monkeypatch,
        change_set_store=failing_change_sets,
        build_store=failing_build_tasks,
    )
    _approve_and_prepare_release(client, quality_store)
    failing_change_sets.fail_source_reads = unavailable_store == "change_set"
    failing_build_tasks.fail_source_reads = unavailable_store == "build_task"

    response = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error_code"] == "POLICY_RELEASE_SOURCE_UNAVAILABLE"
    assert detail["audit_event"] == {
        "release_id": "candidate_task_1",
        "source_change_set_id": "CS_task_1",
    }
    assert quality_store.get_release("candidate_task_1").status == "passed"
    assert quality_store.get_active_release() is None
    assert snapshots.get("candidate_task_1") is None
    failing_change_sets.fail_source_reads = False
    failing_build_tasks.fail_source_reads = False
    assert change_sets.get("CS_task_1").status == "APPROVED"
    assert build_tasks.get("KB_task_1").status == "APPROVED_PENDING_RELEASE"
    assert build_tasks.get_claim("doc_1", "unit_1") is not None


def test_promotion_retry_finishes_after_arbitrary_snapshot_store_failure(
    monkeypatch,
) -> None:
    failing_snapshots = FailOnceSnapshotStore()
    client, quality_store, change_sets, build_tasks, snapshots = _lifecycle_client(
        monkeypatch,
        snapshot_store=failing_snapshots,
    )
    _approve_and_prepare_release(client, quality_store)

    first = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert first.status_code == 503
    assert first.json()["detail"]["error_code"] == "POLICY_RELEASE_SYNC_PENDING"
    assert quality_store.get_release("candidate_task_1").status == "active"
    assert snapshots.get("candidate_task_1") is None
    assert change_sets.get("CS_task_1").status == "APPROVED"
    assert build_tasks.get("KB_task_1").status == "APPROVED_PENDING_RELEASE"
    assert build_tasks.get_claim("doc_1", "unit_1") is not None
    pending_gate = client.get(
        f"{PREFIX}/releases/candidate_task_1/gate-status"
    )
    assert pending_gate.status_code == 200
    assert pending_gate.json()["sync_pending"] is True
    assert any(
        "快照" in reason
        for reason in pending_gate.json()["sync_pending_reasons"]
    )
    active_fallback = client.get(f"{PREFIX}/published/active")
    assert active_fallback.status_code == 200
    assert active_fallback.json()["source_change_set_id"] == "CS_task_1"

    retried = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )

    assert retried.status_code == 200
    assert snapshots.get("candidate_task_1").source_change_set_id == "CS_task_1"
    assert change_sets.get("CS_task_1").status == "PUBLISHED"
    assert build_tasks.get("KB_task_1").status == "PUBLISHED"
    assert build_tasks.get_claim("doc_1", "unit_1") is None
    assert client.get(
        f"{PREFIX}/releases/candidate_task_1/gate-status"
    ).json()["sync_pending"] is False


def test_formal_release_gate_is_true_before_promotion_and_false_after_activation(
    monkeypatch,
) -> None:
    client, quality_store, _change_sets, _build_tasks, _snapshots = (
        _lifecycle_client(monkeypatch)
    )
    _approve_and_prepare_release(client, quality_store)

    before = client.get(
        f"{PREFIX}/releases/candidate_task_1/gate-status"
    )
    promoted = client.post(
        f"{PREFIX}/releases/candidate_task_1/promote",
        json={"reviewed_by": "publisher"},
    )
    after = client.get(
        f"{PREFIX}/releases/candidate_task_1/gate-status"
    )

    assert before.status_code == 200
    assert before.json()["can_promote"] is True
    assert before.json()["blocked_reasons"] == []
    assert promoted.status_code == 200
    assert after.status_code == 200
    assert after.json()["can_promote"] is False
    assert after.json()["active_release_id"] == "candidate_task_1"
    assert any("活动版本" in reason for reason in after.json()["blocked_reasons"])
    assert after.json()["sync_pending"] is False
    assert after.json()["sync_pending_reasons"] == []


class TraceFlowPipeline:
    def get_extraction(self, extraction_id: str):
        if extraction_id != "ext_trace":
            return None
        return {
            "extraction_id": extraction_id,
            "doc_id": "doc_trace",
            "unit_id": "unit_trace",
            "source_text": "在职职工住院报销比例为80%",
            "extracted_fields": {
                "schema_version": "1",
                "rules": [{
                    "knowledge_id": "kn_trace",
                    "subject": "payment_ratio",
                    "population": "employee",
                    "result": {"ratio": "0.8"},
                }],
            },
        }


class TraceFlowEmbedding:
    dim = 2

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class FailPublishTraceStore(InMemoryCompilationTraceStore):
    def append_step(self, run_id, step):
        if step.stage == "PUBLISH":
            raise RuntimeError("trace persistence unavailable")
        return super().append_step(run_id, step)


class FailFirstLineageTraceStore(InMemoryCompilationTraceStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def save_lineage(self, **kwargs):
        if not self.failed_once:
            self.failed_once = True
            raise RuntimeError("lineage persistence unavailable")
        return super().save_lineage(**kwargs)


def _compile_trace_flow_client(monkeypatch, traces=None, backend=None):
    from src.runtime.api import policy_workbench_routes

    trace_store = traces or InMemoryCompilationTraceStore()
    unit = ApprovedUnit(
        unit_id="unit_trace",
        doc_id="doc_trace",
        doc_title="测试政策",
        path=["测试条款"],
        source_text="在职职工住院报销比例为80%",
        order_no=1,
        status="reviewed",
        knowledge_count=1,
        knowledge=[KnowledgeItem(
            knowledge_id="kn_trace",
            unit_id="unit_trace",
            extraction_id="ext_trace",
            relationship_source="persisted",
            business_sentence="在职职工住院报销比例为80%",
            source_text="在职职工住院报销比例为80%",
            fields=[],
            confidence=KnowledgeConfidence(
                completeness=1,
                accuracy=1,
                source_fidelity=1,
                model_confidence=1,
                value_domain_compliance=1,
                overall=1,
            ),
            citations=[],
        )],
    )
    compiled = PolicyCompilationService(
        TraceFlowPipeline(), PolicyRuleCompiler(), trace_store
    ).compile_units([unit])["unit_trace::kn_trace"]
    canonical = compiled.canonical_rules[0]

    change_sets = InMemoryChangeSetStore()
    change_sets.save(KnowledgeChangeSet(
        change_set_id="CS_compile_trace",
        source_document_version_id="doc_trace_v1",
        doc_id="doc_trace",
        doc_title="测试政策",
        build_task_id="KB_compile_trace",
        source_units=[SourceUnitRevision(
            doc_id="doc_trace",
            doc_title="测试政策",
            unit_id="unit_trace",
            unit_revision_id="unit_trace_v1",
            path=["测试条款"],
        )],
        semantic_contract_version="2",
        status="PENDING_REVIEW",
        items=[ChangeSetItem(
            item_id="ITEM_compile_trace",
            change_type="ADD",
            rule_id=canonical.rule_id,
            unit_id="unit_trace",
            doc_id="doc_trace",
            after={
                "knowledge_id": "kn_trace",
                "extraction_id": "ext_trace",
                "business_sentence": "在职职工住院报销比例为80%",
            },
            evidence_ids=list(canonical.evidence),
            risk_level="LOW",
            needs_human=False,
            compile_run_id=compiled.compile_run_id,
            compilation_status=compiled.status,
            canonical_rule=canonical,
        )],
    ))
    build_tasks = InMemoryKnowledgeBuildStore()
    change_set_service = ChangeSetService(
        object(), change_sets, build_store=build_tasks
    )
    build_tasks.create_with_claims(KnowledgeBuildTask(
        task_id="KB_compile_trace",
        name="规则编译治理流",
        status="WAITING_REVIEW",
        build_mode="INITIAL",
        semantic_contract_version="2",
        pipeline_version="pipeline-v1",
        model_scene="policy-knowledge-build",
        config_hash="cfg_trace",
        created_by="policy-editor",
        units=[KnowledgeBuildTaskUnit(
            doc_id="doc_trace",
            doc_title="测试政策",
            unit_id="unit_trace",
            unit_revision_id="unit_trace_v1",
            status="BUILT",
            candidate_result_ids=["CS_compile_trace"],
        )],
        processed_units=1,
        result_change_set_id="CS_compile_trace",
    ))

    quality = InMemoryPolicyQualityStore()
    quality.save_test_case(PolicyQATestCase(
        case_id="case_compile_trace",
        name="规则编译治理流用例",
        query="待遇规则",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))
    quality.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    quality.save_run(QualityRun(
        run_id="run_baseline_trace",
        release_id="baseline",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))
    quality.promote_release("baseline", "publisher")
    snapshots = InMemoryPublishedSnapshotStore()

    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: change_set_service)
    monkeypatch.setattr(policy_workbench_routes, "_get_knowledge_build_store", lambda: build_tasks)
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: quality)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_quality_service",
        lambda: PolicyQualityService(quality, LifecycleReleaseSearcher()),
    )
    monkeypatch.setattr(policy_workbench_routes, "_get_snapshot_store", lambda: snapshots)
    monkeypatch.setattr(policy_workbench_routes, "_get_compilation_trace_store", lambda: trace_store)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_release_content_source",
        lambda: KnowledgeWorkbenchReleaseSource(object(), TraceFlowEmbedding()),
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_release_index_builder",
        lambda: ReleaseIndexBuilder(quality, backend or HealthyBackend(), trace_store),
    )
    return (
        TestClient(create_app(), raise_server_exceptions=False),
        quality,
        trace_store,
        compiled.compile_run_id,
        canonical.rule_id,
    )


def test_compile_trace_governed_release_flow_is_queryable_after_activation(
    monkeypatch,
) -> None:
    client, quality, traces, run_id, rule_id = _compile_trace_flow_client(monkeypatch)

    candidate_trace = client.get(f"{PREFIX}/rules/{rule_id}/trace")

    assert candidate_trace.status_code == 200
    assert candidate_trace.json()["rule_id"] == rule_id
    assert candidate_trace.json()["run"]["run_id"] == run_id
    assert candidate_trace.json()["publication"] is None

    assert client.post(
        f"{PREFIX}/change-sets/CS_compile_trace/approve",
        json={"reviewer": "reviewer", "note": "核验通过"},
    ).status_code == 200
    assert client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_compile_trace",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_compile_trace",
    }).status_code == 201
    assert client.post(
        f"{PREFIX}/releases/candidate_compile_trace/build"
    ).status_code == 200
    tested = client.post(
        f"{PREFIX}/releases/candidate_compile_trace/test",
        json={"repeat_count": 3},
    )
    assert tested.status_code == 200
    assert tested.json()["status"] == "passed"
    promoted = client.post(
        f"{PREFIX}/releases/candidate_compile_trace/promote",
        json={"reviewed_by": "publisher"},
    )
    trace = client.get(f"{PREFIX}/rules/{rule_id}/trace")

    assert promoted.status_code == 200
    assert quality.get_active_release().release_id == "candidate_compile_trace"  # type: ignore[union-attr]
    assert trace.status_code == 200
    assert trace.json()["run"]["run_id"] == run_id
    assert [step["stage"] for step in trace.json()["steps"]] == [
        "INPUT_SNAPSHOT", "LLM_EXTRACTION", "CANONICALIZE", "COMPOSE",
        "RESOLVE", "DERIVE", "VALIDATE", "PUBLISH",
    ]
    assert traces.has_release_lineage(
        "candidate_compile_trace", [(rule_id, run_id)]
    )


def test_compile_trace_persistence_failure_keeps_active_release_and_run(
    monkeypatch,
) -> None:
    traces = FailPublishTraceStore()
    client, quality, _traces, run_id, _rule_id = _compile_trace_flow_client(
        monkeypatch, traces
    )
    assert client.post(
        f"{PREFIX}/change-sets/CS_compile_trace/approve",
        json={"reviewer": "reviewer", "note": "核验通过"},
    ).status_code == 200
    assert client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_compile_trace",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_compile_trace",
    }).status_code == 201

    failed = client.post(f"{PREFIX}/releases/candidate_compile_trace/build")

    assert failed.status_code == 503
    assert failed.json()["detail"]["message"] == "trace persistence unavailable"
    assert quality.get_active_release().release_id == "baseline"  # type: ignore[union-attr]
    assert quality.get_release("candidate_compile_trace").status == "building"  # type: ignore[union-attr]
    assert quality.get_release("candidate_compile_trace").build_error == "trace persistence unavailable"  # type: ignore[union-attr]
    assert traces.get_run(run_id).status == "PASS"  # type: ignore[union-attr]


def test_unexpected_index_failure_is_structured_and_persisted(monkeypatch) -> None:
    client, quality, _traces, _run_id, _rule_id = _compile_trace_flow_client(
        monkeypatch, backend=InvalidRuleJsonBackend()
    )
    assert client.post(
        f"{PREFIX}/change-sets/CS_compile_trace/approve",
        json={"reviewer": "reviewer", "note": "核验通过"},
    ).status_code == 200
    assert client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_compile_trace",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_compile_trace",
    }).status_code == 201

    failed = client.post(f"{PREFIX}/releases/candidate_compile_trace/build")

    assert failed.status_code == 503
    assert failed.json()["detail"]["message"] == "规则索引字段类型不兼容"
    assert quality.get_release("candidate_compile_trace").build_error == "规则索引字段类型不兼容"  # type: ignore[union-attr]


def test_release_build_retry_after_lineage_failure_is_idempotent(monkeypatch) -> None:
    traces = FailFirstLineageTraceStore()
    client, quality, _traces, _run_id, rule_id = _compile_trace_flow_client(
        monkeypatch, traces
    )
    assert client.post(
        f"{PREFIX}/change-sets/CS_compile_trace/approve",
        json={"reviewer": "reviewer", "note": "核验通过"},
    ).status_code == 200
    assert client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_compile_trace",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_compile_trace",
    }).status_code == 201

    first = client.post(f"{PREFIX}/releases/candidate_compile_trace/build")
    retried = client.post(f"{PREFIX}/releases/candidate_compile_trace/build")
    trace = traces.get_rule_trace(rule_id)

    assert first.status_code == 503
    assert retried.status_code == 200
    assert retried.json()["status"] == "ready"
    assert quality.get_release("candidate_compile_trace").status == "ready"  # type: ignore[union-attr]
    assert quality.get_release("candidate_compile_trace").build_error is None  # type: ignore[union-attr]
    assert trace is not None
    assert [step.stage for step in trace.steps].count("PUBLISH") == 1
    assert len(trace.history) == 1
