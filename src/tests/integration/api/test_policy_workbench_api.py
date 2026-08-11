from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeConfidence,
    KnowledgeItem,
    KnowledgeWorkbenchDocument,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    SemanticContractUnavailable,
)
from src.runtime.api.app import create_app


PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


def _add_rule_trace(
    store,
    *,
    rule_id: str,
    version: int = 1,
    status: str = "PASS",
    source_type: str = "DIRECT",
    stage: str = "VALIDATE",
) -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.models import (
        CanonicalRule,
        CompileRun,
        CompileStep,
        PolicyExpression,
        ValidationIssue,
    )

    run_id = f"run_{rule_id}_{version}"
    issue = None if status == "PASS" else ValidationIssue(
        issue_id=f"issue_{run_id}",
        severity=status,
        code="LEGACY_HISTORY_MISSING" if stage == "LEGACY_IMPORT" else "REFERENCE_NOT_FOUND",
        stage=stage,
        rule_id=rule_id,
        message="编译历史不完整",
        recommended_action="人工核验原始政策依据",
    )
    run = CompileRun(
        run_id=run_id,
        document_id="doc_trace",
        unit_id="unit_trace",
        extraction_id=f"ext_{version}",
        raw_input={"source_text": "政策原文快照"},
        llm_output={"facts": [{"fact_id": f"fact_{version}"}]},
    )
    store.create_run(run)
    store.append_step(run_id, CompileStep(
        step_id=f"step_{run_id}_2",
        run_id=run_id,
        sequence_no=2,
        stage=stage,
        status=status,
        issues=[issue] if issue else [],
    ))
    store.append_step(run_id, CompileStep(
        step_id=f"step_{run_id}_1",
        run_id=run_id,
        sequence_no=1,
        stage="INPUT_SNAPSHOT",
        status="PASS",
    ))
    store.finish_run(run_id, status=status, metrics={"rule_count": 1})
    rule = CanonicalRule(
        rule_id=rule_id,
        subject="住院待遇",
        result={"ratio": Decimal("0.8")},
        source_type=source_type,
        evidence=["doc_trace:unit_trace"],
        dependencies=["rule_base"] if source_type == "DERIVED" else [],
        formula=PolicyExpression(
            operator="COMPLEMENT", reference={"rule_id": "rule_base"}
        ) if source_type == "DERIVED" else None,
        rule_version=version,
        status=status,
    )
    store.save_lineage(
        rule=rule,
        run_id=run_id,
        extraction_id=run.extraction_id,
        document_id=run.document_id,
        release_id=f"release_{version}",
    )


def _document() -> KnowledgeWorkbenchDocument:
    return KnowledgeWorkbenchDocument(
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        contract_version="2",
        units=[ApprovedUnit(
            unit_id="unit_1",
            doc_id="doc_1",
            doc_title="职工医保待遇政策",
            path=["第一条", "（一）"],
            source_text="在职职工住院费用",
            order_no=1,
            status="reviewed",
            knowledge_count=1,
            knowledge=[KnowledgeItem(
                knowledge_id="kn_1",
                unit_id="unit_1",
                extraction_id="ext_1",
                relationship_source="persisted",
                business_sentence="在职职工住院时，统筹基金支付比例为80%。",
                source_text="政策原文",
                fields=[],
                standardized_fields=[],
                confidence=KnowledgeConfidence(
                    completeness=1,
                    accuracy=None,
                    source_fidelity=1,
                    model_confidence=0.9,
                    value_domain_compliance=1,
                    overall=0.9667,
                    uncertainties=["准确性待经典用例验证"],
                ),
                citations=[],
            )],
        )],
    )


def test_get_typed_workbench_document(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class Service:
        def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
            assert doc_id == "doc_1"
            return _document()

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/documents/doc_1")

    assert response.status_code == 200
    assert response.json()["contract_version"] == "2"
    assert response.json()["units"][0]["knowledge_count"] == 1


def test_semantic_contract_failure_returns_503_not_empty_200(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class Service:
        def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
            raise SemanticContractUnavailable("semantic registry unavailable")

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/documents/doc_1")

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "SEMANTIC_CONTRACT_UNAVAILABLE"


def test_missing_document_returns_404(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class Service:
        def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
            raise ValueError(f"政策文档不存在: {doc_id}")

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/documents/missing")

    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "POLICY_DOCUMENT_NOT_FOUND"


def test_review_knowledge_persists_status(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes
    from src.knowledge_extension.rule_explanation.knowledge_review_store import (
        InMemoryKnowledgeReviewStore,
    )

    store = InMemoryKnowledgeReviewStore()
    monkeypatch.setattr(policy_workbench_routes, "_review_store", store)
    client = TestClient(create_app())

    response = client.post(
        f"{PREFIX}/knowledge/kn_1/review",
        json={
            "doc_id": "doc_1",
            "unit_id": "unit_1",
            "knowledge_id": "kn_1",
            "extraction_id": "ext_1",
            "status": "approved",
            "reviewed_by": "alice",
            "note": "通过",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == "alice"
    assert body["review_id"].startswith("kr_")
    # 落库可追溯
    assert store.get("doc_1", "kn_1").status == "approved"

    # 状态非法被拦
    bad = client.post(
        f"{PREFIX}/knowledge/kn_1/review",
        json={"doc_id": "doc_1", "unit_id": "unit_1", "knowledge_id": "kn_1",
              "status": "pending", "reviewed_by": "alice"},
    )
    assert bad.status_code == 400

    # 路径与请求体 id 不一致被拦
    mismatch = client.post(
        f"{PREFIX}/knowledge/other/review",
        json={"doc_id": "doc_1", "unit_id": "unit_1", "knowledge_id": "kn_1",
              "status": "rejected", "reviewed_by": "alice"},
    )
    assert mismatch.status_code == 400



def test_promote_release_registers_published_snapshot(monkeypatch) -> None:
    """V4.1 S3：release 通过门禁发布后，登记不可变快照；/published 可查询。"""
    from src.config import production as production_config
    from src.runtime.api import policy_workbench_routes
    from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease, utc_now
    from src.knowledge_extension.rule_explanation.published_snapshot_store import (
        InMemoryPublishedSnapshotStore,
    )

    store = InMemoryPublishedSnapshotStore()
    monkeypatch.setattr(
        production_config,
        "ALLOW_LEGACY_POLICY_RELEASES",
        True,
        raising=False,
    )
    monkeypatch.setattr(policy_workbench_routes, "_snapshot_store", store)

    class QualityStore:
        def get_release(self, release_id: str) -> KnowledgeRelease:
            return KnowledgeRelease(
                release_id=release_id,
                status="passed",
                facts_collection=f"policy_facts_{release_id}",
                rules_collection=f"policy_rules_{release_id}",
                contract_version="2",
                case_set_version=1,
                config_hash="h",
                quality_score=0.95,
                consistency_score=0.96,
            )

        def promote_release(self, release_id: str, reviewed_by: str) -> KnowledgeRelease:
            return self.get_release(release_id).model_copy(
                update={
                    "status": "active",
                    "promoted_by": reviewed_by,
                    "promoted_at": utc_now(),
                }
            )

    monkeypatch.setattr(policy_workbench_routes, "_get_quality_store", lambda: QualityStore())
    client = TestClient(create_app())

    governed = client.post(
        f"{PREFIX}/releases/r_1/promote",
        json={"reviewed_by": "alice"},
    )
    response = client.post(
        f"{PREFIX}/releases/r_1/promote-legacy",
        json={"reviewed_by": "alice"},
    )
    assert governed.status_code == 409
    assert governed.json()["detail"]["error_code"] == (
        "POLICY_RELEASE_LINEAGE_INVALID"
    )
    assert response.status_code == 200

    # 快照已登记
    snapshot = store.get("r_1")
    assert snapshot is not None
    assert snapshot.snapshot_id == "r_1"
    assert snapshot.rules_collection == "policy_rules_r_1"
    assert snapshot.published_by == "alice"
    assert snapshot.immutable is True

    # /published 接口返回
    listed = client.get(f"{PREFIX}/published")
    assert listed.status_code == 200
    assert [item["snapshot_id"] for item in listed.json()] == ["r_1"]


def test_change_sets_api(monkeypatch) -> None:
    """V4.1 S4：change-sets 列表/详情/构建接口。"""
    from src.runtime.api import policy_workbench_routes
    from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet
    from src.knowledge_extension.rule_explanation.change_set_store import InMemoryChangeSetStore

    store = InMemoryChangeSetStore()
    store.save(KnowledgeChangeSet(
        change_set_id="CS_test", source_document_version_id="doc_1",
        doc_id="doc_1", doc_title="测试政策", summary={"additions": 1},
    ))
    monkeypatch.setattr(policy_workbench_routes, "_change_set_service", None)

    class Service:
        def list_change_sets(self, doc_id: str = "") -> list[KnowledgeChangeSet]:
            return store.list(doc_id)
        def get_change_set(self, change_set_id: str) -> KnowledgeChangeSet | None:
            return store.get(change_set_id)
        def build_for_document(self, doc_id: str) -> KnowledgeChangeSet:
            return store.get(f"CS_{doc_id}") or KnowledgeChangeSet(
                change_set_id=f"CS_{doc_id}", source_document_version_id=doc_id,
                doc_id=doc_id, doc_title="t", summary={"additions": 0},
            )

    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: Service())
    client = TestClient(create_app())

    listed = client.get(f"{PREFIX}/change-sets")
    assert listed.status_code == 200
    assert listed.json()[0]["change_set_id"] == "CS_test"

    detail = client.get(f"{PREFIX}/change-sets/CS_test")
    assert detail.status_code == 200
    assert detail.json()["doc_title"] == "测试政策"

    missing = client.get(f"{PREFIX}/change-sets/CS_nope")
    assert missing.status_code == 404


def test_rules_detail_and_dashboard(monkeypatch) -> None:
    """V4.1 S8b/S8d：规则详情定位 + 驾驶舱聚合。"""
    from src.runtime.api import policy_workbench_routes

    class Service:
        def list_documents(self):
            from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
                WorkbenchDocumentList, WorkbenchDocumentSummary,
            )
            return WorkbenchDocumentList(items=[WorkbenchDocumentSummary(
                doc_id="doc_1", doc_title="t", approved_unit_count=1, knowledge_count=1,
            )], total=1)

        def get_document(self, doc_id: str):
            return _document()

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())

    from src.knowledge_extension.rule_explanation.change_set_models import (
        ChangeSetItem, KnowledgeChangeSet,
    )
    from src.knowledge_extension.rule_explanation.decision_task_service import DecisionTaskService
    from src.knowledge_extension.rule_explanation.decision_task_store import InMemoryDecisionTaskStore

    class ChangeSetService:
        def list_change_sets(self, doc_id: str = ""):
            return [KnowledgeChangeSet(
                change_set_id="CS_1", source_document_version_id="doc_1",
                doc_id="doc_1", doc_title="t", status="PENDING_REVIEW",
                summary={"additions": 1},
                items=[ChangeSetItem(
                    item_id="ci_kn_1", change_type="ADD", rule_id="kn_1",
                    unit_id="unit_1", doc_id="doc_1",
                    after={"review_status": "pending", "confidence": {"overall": 0.9, "source_fidelity": 0.8, "completeness": 0.7}},
                    risk_level="LOW",
                )],
                risk_summary={"LOW": 1},
            )]
        def get_change_set(self, change_set_id: str):
            return None

    monkeypatch.setattr(policy_workbench_routes, "_get_change_set_service", lambda: ChangeSetService())
    monkeypatch.setattr(
        policy_workbench_routes, "_get_decision_task_service",
        lambda: DecisionTaskService(InMemoryDecisionTaskStore()),
    )
    client = TestClient(create_app())

    detail = client.get(f"{PREFIX}/rules/kn_1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["rule"]["knowledge_id"] == "kn_1"
    assert body["unit"]["source_text"] == "在职职工住院费用"
    assert body["document"]["doc_id"] == "doc_1"

    missing = client.get(f"{PREFIX}/rules/kn_missing")
    assert missing.status_code == 404

    dashboard = client.get(f"{PREFIX}/governance/dashboard")
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["documents_total"] == 1
    assert body["rules_total"] == 1
    assert body["tasks_pending"] == 0
    assert body["risk_summary"]["LOW"] == 1


def _build_api_client(monkeypatch, documents):
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_service import (
        KnowledgeBuildService,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
        WorkbenchDocumentList,
        WorkbenchDocumentSummary,
    )
    from src.runtime.api import policy_workbench_routes

    class WorkbenchService:
        def list_documents(self) -> WorkbenchDocumentList:
            return WorkbenchDocumentList(
                items=[
                    WorkbenchDocumentSummary(
                        doc_id=document.doc_id,
                        doc_title=document.doc_title,
                        approved_unit_count=len(document.units),
                        knowledge_count=sum(
                            unit.knowledge_count for unit in document.units
                        ),
                    )
                    for document in documents
                ],
                total=len(documents),
            )

        def get_document(
            self, doc_id: str, *, include_knowledge: bool = True
        ) -> KnowledgeWorkbenchDocument:
            return next(document for document in documents if document.doc_id == doc_id)

        def list_document_ids(self) -> list[str]:
            return [document.doc_id for document in documents]

    workbench = WorkbenchService()
    store = InMemoryKnowledgeBuildStore()
    service = KnowledgeBuildService(
        workbench,
        ChangeSetService(workbench, InMemoryChangeSetStore()),
        store,
    )
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_store", store)
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_service", service)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: service._change_set_service,
    )
    return TestClient(create_app()), store, service, workbench


def _build_request(unit: dict, **updates) -> dict:
    request = {
        "name": "门诊待遇知识构建",
        "created_by": "policy-editor",
        "build_mode": "INITIAL",
        "unit_revisions": [{
            "doc_id": unit["doc_id"],
            "unit_id": unit["unit_id"],
            "unit_revision_id": unit["unit_revision_id"],
        }],
    }
    request.update(updates)
    return request


def _create_build_task(client: TestClient) -> dict:
    unit = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()[0]
    response = client.post(
        f"{PREFIX}/knowledge-build/tasks",
        json=_build_request(unit),
    )
    assert response.status_code == 201
    return response.json()


def test_approve_task_backed_change_set_keeps_claim_and_is_idempotent(
    monkeypatch,
) -> None:
    client, store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    task = _create_build_task(client)
    change_set_id = task["result_change_set_id"]

    approved = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/approve",
        json={"reviewer": "alice", "note": "通过"},
    )
    retried = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/approve",
        json={"reviewer": "alice", "note": "通过"},
    )

    assert approved.status_code == 200
    assert retried.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert store.get(task["task_id"]).status == "APPROVED_PENDING_RELEASE"
    assert store.get_claim("doc_1", "unit_1") is not None


def test_return_task_backed_change_set_releases_claim_from_pending_review(
    monkeypatch,
) -> None:
    client, store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    task = _create_build_task(client)
    change_set_id = task["result_change_set_id"]

    returned = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/return",
        json={"reviewer": "bob", "note": "补充证据"},
    )
    retried = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/return",
        json={"reviewer": "bob", "note": "补充证据"},
    )

    assert returned.status_code == 200
    assert retried.status_code == 200
    assert returned.json()["status"] == "RETURNED"
    assert store.get(task["task_id"]).status == "RETURNED"
    assert store.get_claim("doc_1", "unit_1") is None


def test_reject_task_backed_change_set_releases_claim_and_is_idempotent(
    monkeypatch,
) -> None:
    client, store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    task = _create_build_task(client)
    change_set_id = task["result_change_set_id"]

    rejected = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/reject",
        json={"reviewer": "alice", "note": "证据不足"},
    )
    retried = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/reject",
        json={"reviewer": "alice", "note": "证据不足"},
    )

    assert rejected.status_code == 200
    assert retried.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert store.get(task["task_id"]).status == "REJECTED"
    assert store.get_claim("doc_1", "unit_1") is None


@pytest.mark.parametrize(
    ("action", "change_set_status", "task_status", "claim_retained"),
    [
        ("approve", "APPROVED", "APPROVED_PENDING_RELEASE", True),
        ("return", "RETURNED", "RETURNED", False),
        ("reject", "REJECTED", "REJECTED", False),
    ],
)
def test_change_set_action_retry_finishes_task_sync_after_transient_failure(
    monkeypatch,
    action: str,
    change_set_status: str,
    task_status: str,
    claim_retained: bool,
) -> None:
    _client, store, service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    client = TestClient(create_app(), raise_server_exceptions=False)
    task = _create_build_task(client)
    change_set_id = task["result_change_set_id"]
    original_save = store.save
    failed = False

    def fail_once(candidate):
        nonlocal failed
        if candidate.status == task_status and not failed:
            failed = True
            raise RuntimeError("transient task store failure")
        return original_save(candidate)

    monkeypatch.setattr(store, "save", fail_once)

    first = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/{action}",
        json={"reviewer": "alice", "note": "审核动作"},
    )

    assert first.status_code == 503
    assert first.json()["detail"] == {
        "error_code": "CHANGE_SET_LIFECYCLE_SYNC_PENDING",
        "message": "知识变更集动作已生效，构建任务状态尚待重试收口",
        "audit_event": {
            "change_set_id": change_set_id,
            "target_status": change_set_status,
        },
    }
    changed = service._change_set_service.get_change_set(change_set_id)
    assert changed.status == change_set_status
    assert store.get(task["task_id"]).status == "WAITING_REVIEW"
    assert store.get_claim("doc_1", "unit_1") is not None

    retried = client.post(
        f"{PREFIX}/change-sets/{change_set_id}/{action}",
        json={"reviewer": "alice", "note": "审核动作"},
    )

    assert retried.status_code == 200
    assert store.get(task["task_id"]).status == task_status
    assert (store.get_claim("doc_1", "unit_1") is not None) is claim_retained


def test_legacy_change_set_actions_do_not_access_build_task_store(monkeypatch) -> None:
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

    change_sets = InMemoryChangeSetStore()
    for change_set_id in ("CS_approve", "CS_return", "CS_reject"):
        change_sets.save(KnowledgeChangeSet(
            change_set_id=change_set_id,
            source_document_version_id="doc_legacy",
            doc_id="doc_legacy",
            doc_title="历史政策",
            status="PENDING_REVIEW",
        ))
    service = ChangeSetService(object(), change_sets)
    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_change_set_service",
        lambda: service,
    )

    def unexpected_build_store_access():
        raise AssertionError("legacy change set must not access build task store")

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_knowledge_build_store",
        unexpected_build_store_access,
    )
    client = TestClient(create_app())

    responses = {
        action: client.post(
            f"{PREFIX}/change-sets/CS_{action}/{action}",
            json={"reviewer": "alice", "note": "兼容旧候选"},
        )
        for action in ("approve", "return", "reject")
    }

    assert {action: response.status_code for action, response in responses.items()} == {
        "approve": 200,
        "return": 200,
        "reject": 200,
    }
    assert responses["approve"].json()["status"] == "APPROVED"
    assert responses["return"].json()["status"] == "RETURNED"
    assert responses["reject"].json()["status"] == "REJECTED"


def test_concurrent_approve_and_reject_keep_change_set_and_task_consistent(
    monkeypatch,
) -> None:
    client, store, service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    task = _create_build_task(client)
    change_set_id = task["result_change_set_id"]
    barrier = Barrier(2)

    def act(action: str):
        barrier.wait()
        return TestClient(create_app()).post(
            f"{PREFIX}/change-sets/{change_set_id}/{action}",
            json={"reviewer": action, "note": "并发审核"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(act, ("approve", "reject")))

    assert sorted(response.status_code for response in responses) == [200, 409]
    change_set = service._change_set_service.get_change_set(change_set_id)
    saved_task = store.get(task["task_id"])
    if change_set.status == "APPROVED":
        assert saved_task.status == "APPROVED_PENDING_RELEASE"
        assert store.get_claim("doc_1", "unit_1") is not None
    else:
        assert change_set.status == "REJECTED"
        assert saved_task.status == "REJECTED"
        assert store.get_claim("doc_1", "unit_1") is None


def test_knowledge_build_api_preflight_create_list_and_detail(monkeypatch) -> None:
    client, _store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )

    eligible = client.get(f"{PREFIX}/knowledge-build/eligible-units")
    assert eligible.status_code == 200
    unit = eligible.json()[0]
    assert unit["availability"] == "AVAILABLE"

    payload = _build_request(unit)
    preflight = client.post(f"{PREFIX}/knowledge-build/preflight", json=payload)
    assert preflight.status_code == 200
    assert preflight.json()["can_submit"] is True

    created = client.post(f"{PREFIX}/knowledge-build/tasks", json=payload)
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "WAITING_REVIEW"
    assert [item["unit_id"] for item in task["units"]] == ["unit_1"]

    listed = client.get(f"{PREFIX}/knowledge-build/tasks")
    assert listed.status_code == 200
    assert [item["task_id"] for item in listed.json()] == [task["task_id"]]

    detail = client.get(f"{PREFIX}/knowledge-build/tasks/{task['task_id']}")
    assert detail.status_code == 200
    assert detail.json() == task


def _semantic_contract_unavailable_client(monkeypatch) -> TestClient:
    from src.runtime.api import policy_workbench_routes

    class UnavailableBuildService:
        def list_eligible_units(self):
            raise SemanticContractUnavailable("semantic registry unavailable")

        def preflight(self, request):
            raise SemanticContractUnavailable("semantic registry unavailable")

        def create_task(self, request):
            raise SemanticContractUnavailable("semantic registry unavailable")

    monkeypatch.setattr(
        policy_workbench_routes,
        "_knowledge_build_service",
        UnavailableBuildService(),
    )
    return TestClient(create_app())


def _assert_semantic_contract_unavailable(response) -> None:
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error_code"] == "SEMANTIC_CONTRACT_UNAVAILABLE"
    assert detail["audit_event"] == {}


def test_eligible_units_maps_semantic_contract_unavailable_to_503(
    monkeypatch,
) -> None:
    client = _semantic_contract_unavailable_client(monkeypatch)

    response = client.get(f"{PREFIX}/knowledge-build/eligible-units")

    _assert_semantic_contract_unavailable(response)


def test_build_preflight_maps_semantic_contract_unavailable_to_503(
    monkeypatch,
) -> None:
    client = _semantic_contract_unavailable_client(monkeypatch)

    response = client.post(
        f"{PREFIX}/knowledge-build/preflight",
        json=_build_request({
            "doc_id": "doc_1",
            "unit_id": "unit_1",
            "unit_revision_id": "UR_1",
        }),
    )

    _assert_semantic_contract_unavailable(response)


def test_create_build_task_maps_semantic_contract_unavailable_to_503(
    monkeypatch,
) -> None:
    client = _semantic_contract_unavailable_client(monkeypatch)

    response = client.post(
        f"{PREFIX}/knowledge-build/tasks",
        json=_build_request({
            "doc_id": "doc_1",
            "unit_id": "unit_1",
            "unit_revision_id": "UR_1",
        }),
    )

    _assert_semantic_contract_unavailable(response)


def test_knowledge_build_api_maps_input_blockers_to_422(monkeypatch) -> None:
    published = _document().model_copy(
        update={
            "units": [
                _document().units[0].model_copy(update={"status": "published"})
            ]
        },
        deep=True,
    )
    client, _store, _service, _workbench = _build_api_client(
        monkeypatch, [published]
    )
    published_unit = client.get(
        f"{PREFIX}/knowledge-build/eligible-units"
    ).json()[0]

    not_approved_payload = _build_request({
        "doc_id": "doc_missing",
        "unit_id": "unit_missing",
        "unit_revision_id": "UR_missing",
    })
    not_approved_preflight = client.post(
        f"{PREFIX}/knowledge-build/preflight",
        json=not_approved_payload,
    )
    assert not_approved_preflight.status_code == 200
    not_approved_result = not_approved_preflight.json()
    assert not_approved_result["can_submit"] is False
    assert not_approved_result["blockers"][0]["code"] == "UNIT_NOT_APPROVED"

    not_approved = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=not_approved_payload
    )
    assert not_approved.status_code == 422
    assert not_approved.json()["detail"]["error_code"] == "UNIT_NOT_APPROVED"

    no_reason_payload = _build_request(published_unit, build_mode="REBUILD")
    no_reason_preflight = client.post(
        f"{PREFIX}/knowledge-build/preflight", json=no_reason_payload
    )
    assert no_reason_preflight.status_code == 200
    no_reason_result = no_reason_preflight.json()
    assert no_reason_result["can_submit"] is False
    assert no_reason_result["blockers"][0]["code"] == "REBUILD_REASON_REQUIRED"

    no_reason = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=no_reason_payload
    )
    assert no_reason.status_code == 422
    assert no_reason.json()["detail"]["error_code"] == "REBUILD_REASON_REQUIRED"


def test_knowledge_build_api_maps_revision_and_claim_conflicts_to_409(
    monkeypatch,
) -> None:
    client, _store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    unit = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()[0]

    stale_payload = _build_request(unit)
    stale_payload["unit_revisions"][0]["unit_revision_id"] = "UR_stale"
    stale_preflight = client.post(
        f"{PREFIX}/knowledge-build/preflight", json=stale_payload
    )
    assert stale_preflight.status_code == 200
    stale_result = stale_preflight.json()
    assert stale_result["can_submit"] is False
    assert stale_result["blockers"][0]["code"] == "UNIT_REVISION_CHANGED"
    assert stale_result["blockers"][0]["unit_revision_id"] == unit[
        "unit_revision_id"
    ]

    stale = client.post(f"{PREFIX}/knowledge-build/tasks", json=stale_payload)
    assert stale.status_code == 409
    stale_detail = stale.json()["detail"]
    assert stale_detail["error_code"] == "UNIT_REVISION_CHANGED"
    assert stale_detail["audit_event"]["unit_revision_id"] == unit[
        "unit_revision_id"
    ]

    created = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=_build_request(unit)
    ).json()
    claimed_preflight = client.post(
        f"{PREFIX}/knowledge-build/preflight", json=_build_request(unit)
    )
    assert claimed_preflight.status_code == 200
    claimed_result = claimed_preflight.json()
    assert claimed_result["can_submit"] is False
    assert claimed_result["blockers"][0]["code"] == "UNIT_ALREADY_CLAIMED"
    assert claimed_result["blockers"][0]["task_id"] == created["task_id"]
    assert claimed_result["blockers"][0]["target_href"] == (
        f"/policy-knowledge/knowledge/review/{created['result_change_set_id']}"
    )

    claimed = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=_build_request(unit)
    )
    assert claimed.status_code == 409
    claimed_detail = claimed.json()["detail"]
    assert claimed_detail["error_code"] == "UNIT_ALREADY_CLAIMED"
    assert claimed_detail["audit_event"]["task_id"] == created["task_id"]
    assert claimed_detail["audit_event"]["target_href"] == (
        f"/policy-knowledge/knowledge/review/{created['result_change_set_id']}"
    )


def test_create_build_task_keeps_conflict_context_on_primary_blocker(
    monkeypatch,
) -> None:
    client, _store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    unit = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()[0]
    competing = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=_build_request(unit)
    ).json()
    stale_payload = _build_request(unit)
    stale_payload["unit_revisions"][0]["unit_revision_id"] = "UR_stale"

    response = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=stale_payload
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "UNIT_REVISION_CHANGED"
    assert detail["audit_event"]["unit_revision_id"] == unit[
        "unit_revision_id"
    ]
    assert detail["audit_event"]["task_id"] is None
    assert detail["audit_event"]["target_href"] is None
    assert [
        blocker["code"] for blocker in detail["audit_event"]["blockers"]
    ] == ["UNIT_REVISION_CHANGED", "UNIT_ALREADY_CLAIMED"]
    assert detail["audit_event"]["blockers"][1]["task_id"] == competing[
        "task_id"
    ]


def test_knowledge_build_api_maps_semantic_contract_conflict_to_409(
    monkeypatch,
) -> None:
    first = _document()
    second_unit = first.units[0].model_copy(
        update={"doc_id": "doc_2", "doc_title": "居民医保待遇", "unit_id": "unit_2"},
        deep=True,
    )
    second = first.model_copy(
        update={
            "doc_id": "doc_2",
            "doc_title": "居民医保待遇",
            "contract_version": "3",
            "units": [second_unit],
        },
        deep=True,
    )
    client, _store, _service, _workbench = _build_api_client(
        monkeypatch, [first, second]
    )
    units = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()
    payload = _build_request(units[0])
    payload["unit_revisions"].append({
        "doc_id": units[1]["doc_id"],
        "unit_id": units[1]["unit_id"],
        "unit_revision_id": units[1]["unit_revision_id"],
    })

    preflight = client.post(f"{PREFIX}/knowledge-build/preflight", json=payload)

    assert preflight.status_code == 200
    preflight_result = preflight.json()
    assert preflight_result["can_submit"] is False
    assert preflight_result["blockers"][0]["code"] == (
        "SEMANTIC_CONTRACT_MISMATCH"
    )

    response = client.post(f"{PREFIX}/knowledge-build/tasks", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == (
        "SEMANTIC_CONTRACT_MISMATCH"
    )


def test_knowledge_build_api_maps_persisted_atomic_claim_race_to_review(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_service import (
        KnowledgeBuildService,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.runtime.api import policy_workbench_routes

    client, _store, _service, workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    unit = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()[0]

    class RacingStore(InMemoryKnowledgeBuildStore):
        def create_with_claims(self, task):
            competing = super().create_with_claims(
                task.model_copy(
                    update={"task_id": "KB_competing"},
                    deep=True,
                )
            )
            running = super().save(
                competing.model_copy(update={"status": "RUNNING"}, deep=True)
            )
            super().save(
                running.model_copy(
                    update={
                        "status": "WAITING_REVIEW",
                        "result_change_set_id": "CS_competing",
                    },
                    deep=True,
                )
            )
            return super().create_with_claims(task)

    racing_store = RacingStore()
    racing_service = KnowledgeBuildService(
        workbench,
        ChangeSetService(workbench, InMemoryChangeSetStore()),
        racing_store,
    )
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_store", racing_store)
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_service", racing_service)

    response = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=_build_request(unit)
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "UNIT_ALREADY_CLAIMED"
    assert detail["audit_event"] == {
        "unit_revision_id": unit["unit_revision_id"],
        "task_id": "KB_competing",
        "target_href": "/policy-knowledge/knowledge/review/CS_competing",
    }


def test_knowledge_build_atomic_claim_race_falls_back_to_build_task(
    monkeypatch,
) -> None:
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.change_set_store import (
        InMemoryChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_service import (
        KnowledgeBuildService,
    )
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
        UnitRevisionClaimed,
    )
    from src.runtime.api import policy_workbench_routes

    client, _store, _service, workbench = _build_api_client(
        monkeypatch, [_document()]
    )
    unit = client.get(f"{PREFIX}/knowledge-build/eligible-units").json()[0]

    class UnrecordedRacingStore(InMemoryKnowledgeBuildStore):
        def create_with_claims(self, task):
            raise UnitRevisionClaimed(
                doc_id=task.units[0].doc_id,
                unit_id=task.units[0].unit_id,
                unit_revision_id=task.units[0].unit_revision_id,
                task_id="KB_competing",
            )

    racing_store = UnrecordedRacingStore()
    racing_service = KnowledgeBuildService(
        workbench,
        ChangeSetService(workbench, InMemoryChangeSetStore()),
        racing_store,
    )
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_store", racing_store)
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_service", racing_service)

    response = client.post(
        f"{PREFIX}/knowledge-build/tasks", json=_build_request(unit)
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "UNIT_ALREADY_CLAIMED"
    assert detail["audit_event"] == {
        "unit_revision_id": unit["unit_revision_id"],
        "task_id": "KB_competing",
        "target_href": (
            "/policy-knowledge/knowledge/build?task_id=KB_competing"
        ),
    }


def test_claim_race_keeps_409_when_target_lookup_fails(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        UnitRevisionClaimed,
    )
    from src.runtime.api import policy_workbench_routes

    class ClaimRaceService:
        def create_task(self, request):
            raise UnitRevisionClaimed(
                doc_id="doc_1",
                unit_id="unit_1",
                unit_revision_id="UR_race",
                task_id="KB_competing",
            )

        def list_eligible_units(self):
            raise RuntimeError("审计跳转查询失败")

    monkeypatch.setattr(
        policy_workbench_routes,
        "_knowledge_build_service",
        ClaimRaceService(),
    )
    client = TestClient(create_app())

    response = client.post(
        f"{PREFIX}/knowledge-build/tasks",
        json=_build_request({
            "doc_id": "doc_1",
            "unit_id": "unit_1",
            "unit_revision_id": "UR_race",
        }),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error_code"] == "UNIT_ALREADY_CLAIMED"
    assert detail["audit_event"] == {
        "unit_revision_id": "UR_race",
        "task_id": "KB_competing",
        "target_href": (
            "/policy-knowledge/knowledge/build?task_id=KB_competing"
        ),
    }


def test_knowledge_build_task_detail_returns_typed_404(monkeypatch) -> None:
    client, _store, _service, _workbench = _build_api_client(
        monkeypatch, [_document()]
    )

    response = client.get(f"{PREFIX}/knowledge-build/tasks/KB_missing")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "error_code": "KNOWLEDGE_BUILD_TASK_NOT_FOUND",
        "message": "知识构建任务不存在",
        "audit_event": {"task_id": "KB_missing"},
    }


def test_knowledge_build_wiring_uses_one_memory_store(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.knowledge_build_store import (
        InMemoryKnowledgeBuildStore,
    )
    from src.runtime.api import policy_workbench_routes

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_store", None)
    monkeypatch.setattr(policy_workbench_routes, "_knowledge_build_service", None)
    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: object())
    monkeypatch.setattr(
        policy_workbench_routes, "_get_change_set_service", lambda: object()
    )

    store = policy_workbench_routes._get_knowledge_build_store()
    service = policy_workbench_routes._get_knowledge_build_service()

    assert isinstance(store, InMemoryKnowledgeBuildStore)
    assert policy_workbench_routes._get_knowledge_build_store() is store
    assert policy_workbench_routes._get_knowledge_build_service() is service
    assert service._store is store


@pytest.mark.parametrize(
    ("rule_id", "source_type", "status", "stage"),
    [
        ("rule_direct", "DIRECT", "PASS", "VALIDATE"),
        ("rule_derived", "DERIVED", "PASS", "DERIVE"),
        ("rule_review", "DIRECT", "REVIEW", "VALIDATE"),
        ("rule_failed", "DIRECT", "FAIL", "VALIDATE"),
        ("rule_legacy", "DIRECT", "REVIEW", "LEGACY_IMPORT"),
    ],
)
def test_rule_compilation_trace_returns_typed_audit_chain(
    monkeypatch, rule_id, source_type, status, stage
) -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        InMemoryCompilationTraceStore,
    )
    from src.runtime.api import policy_workbench_routes

    store = InMemoryCompilationTraceStore()
    _add_rule_trace(
        store,
        rule_id=rule_id,
        source_type=source_type,
        status=status,
        stage=stage,
    )
    monkeypatch.setattr(
        policy_workbench_routes, "_get_compilation_trace_store", lambda: store
    )

    response = TestClient(create_app()).get(f"{PREFIX}/rules/{rule_id}/trace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rule"]["source_type"] == source_type
    assert payload["raw_input"] == {"source_text": "政策原文快照"}
    assert payload["llm_output"]["facts"][0]["fact_id"] == "fact_1"
    assert [step["sequence_no"] for step in payload["steps"]] == [1, 2]
    assert payload["run"]["status"] == status
    assert payload["publication"]["release_id"] == "release_1"
    assert payload["history"][0]["rule_version"] == 1
    assert bool(payload["issues"]) is (status != "PASS")
    if source_type == "DERIVED":
        assert payload["rule"]["dependencies"] == ["rule_base"]
        assert payload["rule"]["formula"]["operator"] == "COMPLEMENT"


def test_rule_compilation_trace_returns_newest_version_and_history(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        InMemoryCompilationTraceStore,
    )
    from src.runtime.api import policy_workbench_routes

    store = InMemoryCompilationTraceStore()
    _add_rule_trace(store, rule_id="rule_history", version=1)
    _add_rule_trace(store, rule_id="rule_history", version=2)
    monkeypatch.setattr(
        policy_workbench_routes, "_get_compilation_trace_store", lambda: store
    )

    payload = TestClient(create_app()).get(
        f"{PREFIX}/rules/rule_history/trace"
    ).json()

    assert payload["rule"]["rule_version"] == 2
    assert [item["rule_version"] for item in payload["history"]] == [2, 1]


def test_rule_compilation_trace_returns_typed_not_found(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        InMemoryCompilationTraceStore,
    )
    from src.runtime.api import policy_workbench_routes

    monkeypatch.setattr(
        policy_workbench_routes,
        "_get_compilation_trace_store",
        lambda: InMemoryCompilationTraceStore(),
    )

    response = TestClient(create_app()).get(f"{PREFIX}/rules/rule_missing/trace")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "error_code": "RULE_TRACE_NOT_FOUND",
        "message": "规则编译轨迹不存在",
        "audit_event": {"rule_id": "rule_missing"},
    }


@pytest.mark.parametrize(
    ("raw_rule", "expected_status", "expected_issue"),
    [
        (
            {
                "knowledge_id": "kn_1",
                "subject": "payment_ratio",
                "expression": {
                    "operator": "MULTIPLY",
                    "reference": {"population": "employee"},
                    "factor": "0.6",
                },
            },
            "REVIEW",
            "NOT_FOUND",
        ),
        (
            {
                "knowledge_id": "kn_1",
                "subject": "payment_ratio",
                "result": {"ratio": "not-a-ratio"},
            },
            "FAIL",
            "RATIO_INVALID",
        ),
    ],
)
def test_candidate_without_canonical_rule_is_queryable_via_api(
    monkeypatch, raw_rule, expected_status, expected_issue
) -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
        PolicyRuleCompiler,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.service import (
        PolicyCompilationService,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        InMemoryCompilationTraceStore,
    )
    from src.runtime.api import policy_workbench_routes

    extraction = {
        "extraction_id": "ext_1",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "政策原文",
        "extracted_fields": {"rules": [raw_rule]},
    }

    class Pipeline:
        def get_extraction(self, extraction_id):
            return extraction if extraction_id == "ext_1" else None

    traces = InMemoryCompilationTraceStore()
    candidate = PolicyCompilationService(
        Pipeline(), PolicyRuleCompiler(), traces
    ).compile_units(_document().units)["kn_1"]
    monkeypatch.setattr(
        policy_workbench_routes, "_get_compilation_trace_store", lambda: traces
    )

    response = TestClient(create_app()).get(f"{PREFIX}/rules/kn_1/trace")

    assert candidate.status == expected_status
    assert candidate.canonical_rules == []
    assert response.status_code == 200
    payload = response.json()
    assert payload["rule_id"] == "kn_1"
    assert payload["rule"] is None
    assert payload["run"]["status"] == expected_status
    assert expected_issue in {issue["code"] for issue in payload["issues"]}
    assert payload["publication"] is None


def test_rule_trace_backfill_uses_legacy_import_once_when_extraction_is_missing() -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.backfill import (
        backfill_rules,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        InMemoryCompilationTraceStore,
    )

    document = _document()

    class Workbench:
        def list_documents(self):
            return type("Documents", (), {"items": [type("Summary", (), {"doc_id": document.doc_id})()]})()

        def get_document(self, _doc_id):
            return document

    class MissingExtraction:
        def get_extraction(self, _extraction_id):
            return None

    class UnexpectedCompiler:
        def compile_units(self, _units):
            raise AssertionError("missing extraction must use LEGACY_IMPORT")

    traces = InMemoryCompilationTraceStore()

    first = backfill_rules(Workbench(), UnexpectedCompiler(), MissingExtraction(), traces)
    second = backfill_rules(Workbench(), UnexpectedCompiler(), MissingExtraction(), traces)
    trace = traces.get_rule_trace("kn_1")

    assert first.legacy_imported == 1
    assert second.skipped == 1
    assert trace is not None
    assert [step.stage for step in trace.steps] == ["LEGACY_IMPORT"]
    assert trace.issues[0].code == "LEGACY_HISTORY_MISSING"


def test_rule_trace_backfill_repairs_orphan_extraction_run_and_then_skips() -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler.backfill import (
        backfill_rules,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
        PolicyRuleCompiler,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.models import CompileRun
    from src.knowledge_extension.rule_explanation.policy_compiler.service import (
        PolicyCompilationService,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        InMemoryCompilationTraceStore,
    )

    document = _document()
    first_knowledge = document.units[0].knowledge[0]
    second_knowledge = first_knowledge.model_copy(update={
        "knowledge_id": "kn_2",
        "business_sentence": "退休人员住院时执行另一待遇规则。",
    })
    document = document.model_copy(update={
        "units": [document.units[0].model_copy(update={
            "knowledge_count": 2,
            "knowledge": [first_knowledge, second_knowledge],
        })],
    })
    extraction = {
        "extraction_id": "ext_1",
        "doc_id": "doc_1",
        "unit_id": "unit_1",
        "source_text": "政策原文",
        "extracted_fields": {"rules": [
            {"knowledge_id": "kn_1"},
            {"knowledge_id": "kn_2"},
        ]},
    }

    class Workbench:
        def list_documents(self):
            summary = type("Summary", (), {"doc_id": document.doc_id})()
            return type("Documents", (), {"items": [summary]})()

        def get_document(self, _doc_id):
            return document

    class Extractions:
        def get_extraction(self, extraction_id):
            return extraction if extraction_id == "ext_1" else None

    traces = InMemoryCompilationTraceStore()
    traces.create_run(CompileRun(
        run_id="run_orphan",
        document_id="doc_1",
        unit_id="unit_1",
        extraction_id="ext_1",
        raw_input={},
        llm_output={},
    ))
    traces.finish_run("run_orphan", status="PASS", metrics={})
    compiler = PolicyCompilationService(Extractions(), PolicyRuleCompiler(), traces)

    first = backfill_rules(Workbench(), compiler, Extractions(), traces)
    second = backfill_rules(Workbench(), compiler, Extractions(), traces)
    first_trace = traces.get_rule_trace("kn_1")
    second_trace = traces.get_rule_trace("kn_2")

    assert first.compiled == 2
    assert second.skipped == 2
    assert first_trace is not None
    assert second_trace is not None
    assert first_trace.run.run_id != "run_orphan"
    assert second_trace.run.run_id != "run_orphan"
    assert traces.get_run("run_orphan") is not None
    for trace in (first_trace, second_trace):
        assert [step.sequence_no for step in trace.steps] == sorted(
            step.sequence_no for step in trace.steps
        )
