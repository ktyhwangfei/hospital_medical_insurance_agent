from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.published_snapshot_store import (
    InMemoryPublishedSnapshotStore,
)
from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease, QualityRun
from src.knowledge_extension.rule_explanation.quality_service import PolicyQualityService
from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore
from src.runtime.api.app import create_app


PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"
QUALITY_CONFIG_HASH = "197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22"


class Searcher:
    def search(self, release, case) -> list[str]:
        return ["kn_expected"] if release.release_id == "candidate" else []


def _client(
    monkeypatch,
    *,
    allow_legacy: bool = True,
) -> tuple[
    TestClient,
    InMemoryPolicyQualityStore,
    InMemoryPublishedSnapshotStore,
]:
    from src.config import production as production_config
    from src.runtime.api import policy_workbench_routes

    monkeypatch.setattr(
        production_config,
        "ALLOW_LEGACY_POLICY_RELEASES",
        allow_legacy,
        raising=False,
    )

    store = InMemoryPolicyQualityStore()
    service = PolicyQualityService(store, Searcher())
    snapshot_store = InMemoryPublishedSnapshotStore()
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: store)
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_service", lambda: service)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_snapshot_store",
        lambda: snapshot_store,
    )

    return TestClient(create_app()), store, snapshot_store


def test_test_case_create_and_list(monkeypatch) -> None:
    client, _, _snapshots = _client(monkeypatch)

    created = client.post(f"{PREFIX}/test-cases", json={
        "case_id": "case_1",
        "name": "职工住院比例",
        "query": "职工住院支付比例",
        "mode": "semantic",
        "expected_knowledge_ids": ["kn_expected"],
        "required": True,
    })
    listed = client.get(f"{PREFIX}/test-cases")

    assert created.status_code == 201
    assert created.json()["case_set_version"] == 1
    assert listed.status_code == 200
    assert listed.json()[0]["case_id"] == "case_1"


def test_candidate_release_uses_one_versioned_collection_pair(monkeypatch) -> None:
    client, _, _snapshots = _client(monkeypatch)
    _install_approved_gate_source(monkeypatch, "CS_collection_pair")

    response = client.post(f"{PREFIX}/releases", json={
        "release_id": "rel_20260803_01",
        "contract_version": "2",
        "config_hash": "cfg_1",
        "source_change_set_id": "CS_collection_pair",
    })

    assert response.status_code == 201
    assert response.json()["status"] == "building"
    assert response.json()["source_change_set_id"] == "CS_collection_pair"
    assert response.json()["facts_collection"] == "policy_facts_rel_20260803_01"
    assert response.json()["rules_collection"] == "policy_rules_rel_20260803_01"
    listed = client.get(f"{PREFIX}/releases")
    assert listed.status_code == 200
    assert listed.json()[0]["release_id"] == "rel_20260803_01"
    duplicate = client.post(f"{PREFIX}/releases", json={
        "release_id": "rel_20260803_01",
        "contract_version": "3",
        "config_hash": "forged",
    })
    assert duplicate.status_code == 409
    assert client.get(f"{PREFIX}/releases").json()[0]["contract_version"] == "2"


def test_candidate_release_rejects_missing_and_unapproved_source(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.change_set_models import (
        KnowledgeChangeSet,
    )
    from src.runtime.api import policy_workbench_routes

    client, store, _snapshots = _client(monkeypatch)
    change_sets = {
        "CS_pending": KnowledgeChangeSet(
            change_set_id="CS_pending",
            source_document_version_id="doc_1",
            doc_id="doc_1",
            doc_title="职工医保待遇政策",
            status="PENDING_REVIEW",
        ),
    }

    class ChangeSetService:
        def get_change_set(self, change_set_id: str) -> KnowledgeChangeSet | None:
            return change_sets.get(change_set_id)

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: ChangeSetService(),
    )

    missing = client.post(f"{PREFIX}/releases", json={
        "release_id": "rel_missing",
        "contract_version": "2",
        "config_hash": "cfg_1",
        "source_change_set_id": "CS_missing",
    })
    pending = client.post(f"{PREFIX}/releases", json={
        "release_id": "rel_pending",
        "contract_version": "2",
        "config_hash": "cfg_1",
        "source_change_set_id": "CS_pending",
    })
    assert missing.status_code == 409
    assert missing.json()["detail"]["error_code"] == "POLICY_RELEASE_LINEAGE_INVALID"
    assert pending.status_code == 409
    assert pending.json()["detail"]["error_code"] == "POLICY_RELEASE_LINEAGE_INVALID"
    assert store.get_release("rel_missing") is None
    assert store.get_release("rel_pending") is None


@pytest.mark.parametrize(
    (
        "change_set_status",
        "task_status",
        "task_result_id",
        "task_contract",
        "change_set_contract",
    ),
    [
        ("PENDING_REVIEW", None, None, None, None),
        ("APPROVED", None, None, None, "2"),
        ("APPROVED", "WAITING_REVIEW", "CS_source", "2", "2"),
        ("APPROVED", "APPROVED_PENDING_RELEASE", "CS_other", "2", "2"),
        ("APPROVED", "APPROVED_PENDING_RELEASE", "CS_source", "3", "2"),
        ("APPROVED", "APPROVED_PENDING_RELEASE", "CS_source", "2", "3"),
    ],
)
def test_promote_validates_source_lineage_before_switching_active_release(
    monkeypatch,
    change_set_status: str,
    task_status: str | None,
    task_result_id: str | None,
    task_contract: str | None,
    change_set_contract: str | None,
) -> None:
    from src.knowledge_extension.rule_explanation.change_set_models import (
        KnowledgeChangeSet,
    )
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_models import (
        KnowledgeBuildTask,
        KnowledgeBuildTaskUnit,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.runtime.api import policy_workbench_routes

    client, quality_store, snapshots = _client(monkeypatch)
    change_sets = InMemoryChangeSetStore()
    build_task_id = "KB_source" if task_status is not None else None
    change_sets.save(KnowledgeChangeSet(
        change_set_id="CS_source",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        build_task_id=build_task_id,
        semantic_contract_version=change_set_contract,
        status=change_set_status,
    ))
    build_tasks = InMemoryKnowledgeBuildStore()
    change_set_service = ChangeSetService(
        object(), change_sets, build_store=build_tasks
    )
    if task_status is not None:
        build_tasks.create_with_claims(KnowledgeBuildTask(
            task_id="KB_source",
            name="职工医保待遇知识构建",
            status=task_status,
            build_mode="INITIAL",
            semantic_contract_version=task_contract or "2",
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
                candidate_result_ids=["CS_source"],
            )],
            processed_units=1,
            result_change_set_id=task_result_id,
        ))
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: change_set_service,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_knowledge_build_store",
        lambda: build_tasks,
    )
    quality_store.save_release(KnowledgeRelease(
        release_id="candidate_invalid",
        status="passed",
        facts_collection="policy_facts_candidate_invalid",
        rules_collection="policy_rules_candidate_invalid",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        source_change_set_id="CS_source",
    ))
    quality_store.save_run(QualityRun(
        run_id="run_candidate_invalid",
        release_id="candidate_invalid",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))

    response = client.post(
        f"{PREFIX}/releases/candidate_invalid/promote",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LINEAGE_INVALID"
    )
    assert quality_store.get_release("candidate_invalid").status == "passed"
    assert quality_store.get_active_release() is None
    assert snapshots.list() == []
    assert change_sets.get("CS_source").status == change_set_status


@pytest.mark.parametrize("unavailable_store", ["change_set", "build_task"])
def test_promote_returns_503_before_switching_active_when_source_store_unavailable(
    monkeypatch,
    unavailable_store: str,
) -> None:
    from src.knowledge_extension.rule_explanation.change_set_models import (
        KnowledgeChangeSet,
    )
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_models import (
        KnowledgeBuildTask,
        KnowledgeBuildTaskUnit,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.runtime.api import policy_workbench_routes

    class FailingChangeSetStore(InMemoryChangeSetStore):
        def get(self, change_set_id: str) -> KnowledgeChangeSet | None:
            if unavailable_store == "change_set":
                raise RuntimeError("change-set store unavailable")
            return super().get(change_set_id)

    class FailingBuildTaskStore(InMemoryKnowledgeBuildStore):
        def get(self, task_id: str) -> KnowledgeBuildTask | None:
            if unavailable_store == "build_task":
                raise RuntimeError("build-task store unavailable")
            return super().get(task_id)

    _unused_client, quality_store, snapshots = _client(monkeypatch)
    change_sets = FailingChangeSetStore()
    change_sets.save(KnowledgeChangeSet(
        change_set_id="CS_source",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        build_task_id="KB_source",
        semantic_contract_version="2",
        status="APPROVED",
    ))
    build_tasks = FailingBuildTaskStore()
    build_tasks.create_with_claims(KnowledgeBuildTask(
        task_id="KB_source",
        name="职工医保待遇知识构建",
        status="APPROVED_PENDING_RELEASE",
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
            candidate_result_ids=["CS_source"],
        )],
        processed_units=1,
        result_change_set_id="CS_source",
    ))
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: ChangeSetService(object(), change_sets),
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_knowledge_build_store",
        lambda: build_tasks,
    )
    quality_store.save_release(KnowledgeRelease(
        release_id="candidate_unavailable",
        status="passed",
        facts_collection="policy_facts_candidate_unavailable",
        rules_collection="policy_rules_candidate_unavailable",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        source_change_set_id="CS_source",
    ))
    quality_store.save_run(QualityRun(
        run_id="run_candidate_unavailable",
        release_id="candidate_unavailable",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post(
        f"{PREFIX}/releases/candidate_unavailable/promote",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error_code"] == "POLICY_RELEASE_SOURCE_UNAVAILABLE"
    assert detail["audit_event"] == {
        "release_id": "candidate_unavailable",
        "source_change_set_id": "CS_source",
    }
    assert quality_store.get_release("candidate_unavailable").status == "passed"
    assert quality_store.get_active_release() is None
    assert snapshots.list() == []


def test_run_detail_and_legacy_manual_promotion(monkeypatch) -> None:
    client, store, _snapshots = _client(monkeypatch)
    case_response = client.post(f"{PREFIX}/test-cases", json={
        "case_id": "case_1",
        "name": "职工住院比例",
        "query": "职工住院支付比例",
        "mode": "semantic",
        "expected_knowledge_ids": ["kn_expected"],
    })
    assert case_response.status_code == 201
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
        status="ready",
        facts_collection="policy_facts_candidate",
        rules_collection="policy_rules_candidate",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))

    run_response = client.post(
        f"{PREFIX}/releases/candidate/test", json={"repeat_count": 3}
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "passed"
    detail = client.get(f"{PREFIX}/quality-runs/{run['run_id']}")
    assert detail.status_code == 200
    case_results = client.get(f"{PREFIX}/quality-runs/{run['run_id']}/case-results")
    assert case_results.status_code == 200
    assert len(case_results.json()) == 6
    assert {item["target"] for item in case_results.json()} == {"candidate", "baseline"}
    latest = client.get(f"{PREFIX}/releases/candidate/quality/latest")
    assert latest.status_code == 200
    assert latest.json()["run"]["run_id"] == run["run_id"]
    assert len(latest.json()["case_results"]) == 6
    assert client.get(f"{PREFIX}/releases/active").json()["release_id"] == "baseline"

    governed = client.post(
        f"{PREFIX}/releases/candidate/promote", json={"reviewed_by": "reviewer_b"}
    )
    promoted = client.post(
        f"{PREFIX}/releases/candidate/promote-legacy",
        json={"reviewed_by": "reviewer_b"},
    )

    assert governed.status_code == 409
    assert governed.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LINEAGE_INVALID"
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "active"


def test_blocked_promotion_returns_409_and_preserves_active_release(monkeypatch) -> None:
    client, store, _snapshots = _client(monkeypatch)
    store.save_release(KnowledgeRelease(
        release_id="baseline",
        status="passed",
        facts_collection="policy_facts_baseline",
        rules_collection="policy_rules_baseline",
        contract_version="1",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    store.save_run(QualityRun(
        run_id="run_baseline", release_id="baseline", case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH, status="passed",
    ))
    store.promote_release("baseline", "reviewer_a")
    store.save_release(KnowledgeRelease(
        release_id="failed",
        status="failed",
        facts_collection="policy_facts_failed",
        rules_collection="policy_rules_failed",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
    ))

    response = client.post(
        f"{PREFIX}/releases/failed/promote-legacy",
        json={"reviewed_by": "reviewer_b"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "POLICY_RELEASE_GATE_BLOCKED"
    assert store.get_active_release().release_id == "baseline"  # type: ignore[union-attr]


def test_failed_release_can_be_retested_through_api(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.quality_models import PolicyQATestCase
    from src.runtime.api import policy_workbench_routes

    class MutableSearcher:
        passes = False

        def search(self, release, case) -> list[str]:
            return ["kn_expected"] if self.passes else ["kn_wrong"]

    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_retry",
        name="失败候选重跑",
        query="职工住院支付比例",
        mode="semantic",
        expected_knowledge_ids=["kn_expected"],
    ))
    store.save_release(KnowledgeRelease(
        release_id="candidate_retry",
        status="ready",
        facts_collection="policy_facts_candidate_retry",
        rules_collection="policy_rules_candidate_retry",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    searcher = MutableSearcher()
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: store)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_quality_service",
        lambda: PolicyQualityService(store, searcher),
    )
    client = TestClient(create_app())

    failed = client.post(
        f"{PREFIX}/releases/candidate_retry/test",
        json={"repeat_count": 3},
    )
    searcher.passes = True
    passed = client.post(
        f"{PREFIX}/releases/candidate_retry/test",
        json={"repeat_count": 3},
    )

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert passed.status_code == 200
    assert passed.json()["status"] == "passed"
    assert store.get_latest_run("candidate_retry").run_id == passed.json()["run_id"]  # type: ignore[union-attr]


def _install_approved_gate_source(monkeypatch, change_set_id: str):
    from src.knowledge_extension.rule_explanation.change_set_models import (
        KnowledgeChangeSet,
    )
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_models import (
        KnowledgeBuildTask,
        KnowledgeBuildTaskUnit,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.runtime.api import policy_workbench_routes

    task_id = f"KB_{change_set_id}"
    source_store = InMemoryChangeSetStore()
    source_store.save(KnowledgeChangeSet(
        change_set_id=change_set_id,
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        build_task_id=task_id,
        semantic_contract_version="2",
        status="APPROVED",
    ))
    build_store = InMemoryKnowledgeBuildStore()
    service = ChangeSetService(object(), source_store, build_store=build_store)
    build_store.create_with_claims(KnowledgeBuildTask(
        task_id=task_id,
        name="职工医保待遇知识构建",
        status="APPROVED_PENDING_RELEASE",
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
            candidate_result_ids=[change_set_id],
        )],
        processed_units=1,
        result_change_set_id=change_set_id,
    ))

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: service,
    )
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_knowledge_build_store",
        lambda: build_store,
    )
    return service, build_store


def _install_taskless_source(monkeypatch, change_set_id: str):
    from src.knowledge_extension.rule_explanation.change_set_models import (
        KnowledgeChangeSet,
    )
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.runtime.api import policy_workbench_routes

    source_store = InMemoryChangeSetStore()
    source_store.save(KnowledgeChangeSet(
        change_set_id=change_set_id,
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        semantic_contract_version="2",
        status="APPROVED",
    ))
    service = ChangeSetService(object(), source_store)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: service,
    )
    return service


def test_taskless_governed_create_is_blocked_without_persisting(monkeypatch) -> None:
    client, store, _snapshots = _client(monkeypatch, allow_legacy=False)
    _install_taskless_source(monkeypatch, "CS_taskless_create")

    response = client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_taskless_create",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_taskless_create",
    })

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LINEAGE_INVALID"
    )
    assert store.get_release("candidate_taskless_create") is None


def test_existing_taskless_release_is_blocked_by_gate_and_both_promote_paths(
    monkeypatch,
) -> None:
    client, store, snapshots = _client(monkeypatch)
    _install_taskless_source(monkeypatch, "CS_taskless_existing")
    _save_gate_candidate(
        store,
        release_id="candidate_taskless_existing",
        source_change_set_id="CS_taskless_existing",
    )

    gate = client.get(
        f"{PREFIX}/releases/candidate_taskless_existing/gate-status"
    )
    governed = client.post(
        f"{PREFIX}/releases/candidate_taskless_existing/promote",
        json={"reviewed_by": "publisher"},
    )
    legacy = client.post(
        f"{PREFIX}/releases/candidate_taskless_existing/promote-legacy",
        json={"reviewed_by": "legacy-publisher"},
    )

    assert gate.status_code == 200
    assert gate.json()["can_promote"] is False
    assert any("构建任务" in reason for reason in gate.json()["blocked_reasons"])
    assert governed.status_code == 409
    assert governed.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LINEAGE_INVALID"
    )
    assert legacy.status_code == 409
    assert legacy.json()["detail"]["error_code"] == "POLICY_RELEASE_LEGACY_BLOCKED"
    assert store.get_active_release() is None
    assert snapshots.list() == []


def test_task_backed_create_gate_promote_and_published_active_retry_succeed(
    monkeypatch,
) -> None:
    client, store, snapshots = _client(monkeypatch, allow_legacy=False)
    change_sets, build_tasks = _install_approved_gate_source(
        monkeypatch, "CS_task_backed"
    )

    created = client.post(f"{PREFIX}/releases", json={
        "release_id": "candidate_task_backed",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
        "source_change_set_id": "CS_task_backed",
    })
    release = store.get_release("candidate_task_backed")
    assert release is not None
    store.save_release(release.model_copy(update={"status": "passed"}))
    store.save_run(QualityRun(
        run_id="run_candidate_task_backed",
        release_id="candidate_task_backed",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))

    gate = client.get(
        f"{PREFIX}/releases/candidate_task_backed/gate-status"
    )
    promoted = client.post(
        f"{PREFIX}/releases/candidate_task_backed/promote",
        json={"reviewed_by": "publisher"},
    )
    retried = client.post(
        f"{PREFIX}/releases/candidate_task_backed/promote",
        json={"reviewed_by": "publisher"},
    )

    assert created.status_code == 201
    assert gate.status_code == 200
    assert gate.json()["can_promote"] is True
    assert promoted.status_code == 200
    assert retried.status_code == 200
    assert change_sets.get_change_set("CS_task_backed").status == "PUBLISHED"
    assert build_tasks.get("KB_CS_task_backed").status == "PUBLISHED"
    assert snapshots.get("candidate_task_backed") is not None


def _save_gate_candidate(
    store: InMemoryPolicyQualityStore,
    *,
    release_id: str,
    source_change_set_id: str | None,
    status: str = "passed",
) -> None:
    store.save_release(KnowledgeRelease(
        release_id=release_id,
        status=status,
        facts_collection=f"policy_facts_{release_id}",
        rules_collection=f"policy_rules_{release_id}",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        source_change_set_id=source_change_set_id,
    ))
    store.save_run(QualityRun(
        run_id=f"run_{release_id}",
        release_id=release_id,
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))


def test_release_gate_status_returns_authoritative_typed_decision(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    client, store, _snapshots = _client(monkeypatch)
    _install_approved_gate_source(monkeypatch, "CS_gate")
    _save_gate_candidate(
        store,
        release_id="candidate_gate",
        source_change_set_id="CS_gate",
    )

    response = client.get(f"{PREFIX}/releases/candidate_gate/gate-status")

    assert response.status_code == 200
    assert response.json() == {
        "release_id": "candidate_gate",
        "can_promote": True,
        "current_case_set_version": 0,
        "active_release_id": None,
        "latest_run": response.json()["latest_run"],
        "latest_answer_verification_run": None,
        "answer_verification_gate_enabled": False,
        "answer_verification_blocked_reasons": ["skipped: 答案验证门禁未启用"],
        "blocked_reasons": [],
        "sync_pending": False,
        "sync_pending_reasons": [],
    }
    assert response.json()["latest_run"]["run_id"] == "run_candidate_gate"
    assert policy_workbench_routes._get_quality_store() is store


def test_release_gate_status_blocks_legacy_release_without_lineage(monkeypatch) -> None:
    client, store, _snapshots = _client(monkeypatch)
    _save_gate_candidate(
        store,
        release_id="legacy_candidate",
        source_change_set_id=None,
    )

    response = client.get(f"{PREFIX}/releases/legacy_candidate/gate-status")

    assert response.status_code == 200
    assert response.json()["can_promote"] is False
    assert any("来源" in reason for reason in response.json()["blocked_reasons"])


def test_release_gate_status_does_not_offer_normal_promote_for_active_retry(
    monkeypatch,
) -> None:
    client, store, _snapshots = _client(monkeypatch)
    _install_approved_gate_source(monkeypatch, "CS_active")
    _save_gate_candidate(
        store,
        release_id="active_candidate",
        source_change_set_id="CS_active",
        status="active",
    )
    store.active_release_id = "active_candidate"

    response = client.get(f"{PREFIX}/releases/active_candidate/gate-status")

    assert response.status_code == 200
    assert response.json()["can_promote"] is False
    assert any("活动版本" in reason for reason in response.json()["blocked_reasons"])


def test_release_gate_status_maps_quality_store_failure_to_structured_503(
    monkeypatch,
) -> None:
    from src.runtime.api import policy_workbench_routes

    class UnavailableQualityStore:
        def get_release(self, release_id: str):
            raise RuntimeError("quality store unavailable")

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_quality_store",
        lambda: UnavailableQualityStore(),
    )
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.get(f"{PREFIX}/releases/candidate/gate-status")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error_code": "POLICY_RELEASE_GATE_UNAVAILABLE",
        "message": "发布门禁状态暂不可用，请稍后重试",
        "audit_event": {"release_id": "candidate"},
    }


def test_release_gate_status_maps_source_store_failure_to_structured_503(
    monkeypatch,
) -> None:
    from src.runtime.api import policy_workbench_routes

    client, store, _snapshots = _client(monkeypatch)
    _save_gate_candidate(
        store,
        release_id="candidate_source_unavailable",
        source_change_set_id="CS_unavailable",
    )

    class UnavailableChangeSetService:
        def get_change_set(self, change_set_id: str):
            raise RuntimeError("change-set store unavailable")

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: UnavailableChangeSetService(),
    )

    response = client.get(
        f"{PREFIX}/releases/candidate_source_unavailable/gate-status"
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_SOURCE_UNAVAILABLE"
    )


def test_formal_release_cannot_use_deprecated_legacy_promote(monkeypatch) -> None:
    client, store, _snapshots = _client(monkeypatch)
    _install_approved_gate_source(monkeypatch, "CS_formal")
    _save_gate_candidate(
        store,
        release_id="candidate_formal",
        source_change_set_id="CS_formal",
    )

    response = client.post(
        f"{PREFIX}/releases/candidate_formal/promote-legacy",
        json={"reviewed_by": "legacy-reviewer"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LEGACY_BLOCKED"
    )
    assert store.get_release("candidate_formal").status == "passed"  # type: ignore[union-attr]


def test_legacy_create_promote_and_rollback_are_disabled_by_default(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.quality_models import utc_now

    client, store, _snapshots = _client(monkeypatch, allow_legacy=False)

    created = client.post(f"{PREFIX}/releases", json={
        "release_id": "legacy_create",
        "contract_version": "2",
        "config_hash": QUALITY_CONFIG_HASH,
    })
    store.save_release(KnowledgeRelease(
        release_id="legacy_existing",
        status="passed",
        facts_collection="policy_facts_legacy_existing",
        rules_collection="policy_rules_legacy_existing",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
    ))
    promoted = client.post(
        f"{PREFIX}/releases/legacy_existing/promote-legacy",
        json={"reviewed_by": "legacy-reviewer"},
    )
    store.save_release(KnowledgeRelease(
        release_id="legacy_retired",
        status="retired",
        facts_collection="policy_facts_legacy_retired",
        rules_collection="policy_rules_legacy_retired",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        promoted_at=utc_now(),
    ))
    rolled_back = client.post(
        f"{PREFIX}/releases/legacy_retired/rollback",
        json={"reviewed_by": "legacy-reviewer"},
    )

    assert {created.status_code, promoted.status_code, rolled_back.status_code} == {403}
    assert {
        created.json()["detail"]["error_code"],
        promoted.json()["detail"]["error_code"],
        rolled_back.json()["detail"]["error_code"],
    } == {"POLICY_LEGACY_RELEASE_DISABLED"}


def test_formal_release_rollback_is_not_blocked_by_legacy_switch(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.quality_models import utc_now

    client, store, _snapshots = _client(monkeypatch, allow_legacy=False)
    store.save_release(KnowledgeRelease(
        release_id="formal_retired",
        status="retired",
        facts_collection="policy_facts_formal_retired",
        rules_collection="policy_rules_formal_retired",
        contract_version="2",
        case_set_version=0,
        config_hash=QUALITY_CONFIG_HASH,
        source_change_set_id="CS_formal",
        promoted_at=utc_now(),
    ))

    response = client.post(
        f"{PREFIX}/releases/formal_retired/rollback",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.parametrize(
    ("failure_mode", "expected_code"),
    [
        ("before_commit", "POLICY_RELEASE_PROMOTION_UNAVAILABLE"),
        ("commit_then_raise", "POLICY_RELEASE_SYNC_PENDING"),
        ("state_unknown", "POLICY_RELEASE_STATE_UNKNOWN"),
    ],
)
def test_promotion_runtime_failures_are_classified_by_observed_active_state(
    monkeypatch,
    failure_mode: str,
    expected_code: str,
) -> None:
    from src.runtime.api import policy_workbench_routes

    class FailingPromotionStore(InMemoryPolicyQualityStore):
        mode = ""
        promote_failed = False

        def get_release(self, release_id: str):
            if self.mode == "initial_read":
                raise RuntimeError("initial release read unavailable")
            if self.mode == "state_unknown" and self.promote_failed:
                raise RuntimeError("promotion state unreadable")
            return super().get_release(release_id)

        def promote_release(self, release_id: str, promoted_by: str):
            self.promote_failed = True
            if self.mode == "commit_then_raise":
                super().promote_release(release_id, promoted_by)
            raise RuntimeError("promotion store failed")

    _client(monkeypatch, allow_legacy=False)
    store = FailingPromotionStore()
    _save_gate_candidate(
        store,
        release_id="candidate_failure",
        source_change_set_id="CS_failure",
    )
    _install_approved_gate_source(monkeypatch, "CS_failure")
    store.mode = failure_mode
    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: store)
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post(
        f"{PREFIX}/releases/candidate_failure/promote",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == expected_code
    if failure_mode == "commit_then_raise":
        assert store.get_active_release().release_id == "candidate_failure"  # type: ignore[union-attr]
    elif failure_mode == "before_commit":
        assert store.get_release("candidate_failure").status == "passed"  # type: ignore[union-attr]


def test_initial_release_read_failure_is_structured_503(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class InitialReadUnavailable:
        def get_release(self, release_id: str):
            raise RuntimeError("quality store unavailable")

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_quality_store",
        lambda: InitialReadUnavailable(),
    )
    client = TestClient(create_app(), raise_server_exceptions=False)

    response = client.post(
        f"{PREFIX}/releases/candidate/promote",
        json={"reviewed_by": "publisher"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_PROMOTION_UNAVAILABLE"
    )
