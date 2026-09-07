"""可信问题库 API 集成测试（Issue #37 Slice 3）。

通过 create_app() 新建应用并覆盖存储依赖为内存实现，不连接真实外部资源。
覆盖：CRUD、审核流状态机（含非法流转 409）、同义表达运营、/match 三态。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.trusted_question.trusted_question_in_memory import (
    InMemoryTrustedQuestionStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.trusted_question_routes import (
    get_semantic_query_service,
    get_trusted_question_store,
)
from src.semantic_layer.query_planner import (
    QueryEvidence,
    SemanticQueryResult,
    SemanticQueryService,
)

PREFIX = "/api/v1/medical-insurance-ai-agent/trusted-questions"


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    store = InMemoryTrustedQuestionStorage()
    app.dependency_overrides[get_trusted_question_store] = lambda: store
    return TestClient(app)


def _create(client: TestClient, question: str = "门诊报销比例是多少", **extra) -> dict:
    response = client.post(
        PREFIX,
        json={"standard_question": question, "created_by": "tester", **extra},
    )
    assert response.status_code == 201
    return response.json()


def _activate(client: TestClient, question_id: str) -> dict:
    created = client.get(f"{PREFIX}/{question_id}").json()
    submitted = client.post(
        f"{PREFIX}/{question_id}/submit-review",
        json={"expected_version": created["version"]},
    )
    assert submitted.status_code == 200
    approved = client.post(
        f"{PREFIX}/{question_id}/approve",
        json={"expected_version": submitted.json()["version"], "operator": "reviewer-1"},
    )
    assert approved.status_code == 200
    return approved.json()


class TestCrud:
    def test_create_defaults_to_draft(self, client: TestClient) -> None:
        created = _create(client)
        assert created["status"] == "draft"
        assert created["version"] == 1
        assert created["question_id"].startswith("tq_")

    def test_list_and_get(self, client: TestClient) -> None:
        created = _create(client)
        listed = client.get(PREFIX).json()
        assert len(listed["items"]) == 1
        detail = client.get(f"{PREFIX}/{created['question_id']}")
        assert detail.status_code == 200
        assert detail.json()["standard_question"] == "门诊报销比例是多少"

    def test_get_missing_404(self, client: TestClient) -> None:
        response = client.get(f"{PREFIX}/tq_missing")
        assert response.status_code == 404
        assert response.json()["detail"]["error_code"] == "TRUSTED_QUESTION_NOT_FOUND"

    def test_update_with_optimistic_lock(self, client: TestClient) -> None:
        created = _create(client)
        updated = client.put(
            f"{PREFIX}/{created['question_id']}",
            json={
                "standard_question": "门诊统筹支付比例是多少",
                "expected_version": 1,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        # 过期 version → 409
        stale = client.put(
            f"{PREFIX}/{created['question_id']}",
            json={
                "standard_question": "再次修改",
                "expected_version": 1,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["error_code"] == "TRUSTED_QUESTION_CONFLICT"


class TestReviewFlow:
    def test_full_flow(self, client: TestClient) -> None:
        created = _create(client)
        qid = created["question_id"]
        approved = _activate(client, qid)
        assert approved["status"] == "active"
        assert approved["reviewed_by"] == "reviewer-1"
        assert approved["reviewed_at"]
        retired = client.post(
            f"{PREFIX}/{qid}/retire",
            json={"expected_version": approved["version"], "operator": "ops"},
        )
        assert retired.status_code == 200
        assert retired.json()["status"] == "retired"

    def test_reject_requires_note(self, client: TestClient) -> None:
        created = _create(client)
        qid = created["question_id"]
        client.post(f"{PREFIX}/{qid}/submit-review", json={"expected_version": 1})
        rejected = client.post(
            f"{PREFIX}/{qid}/reject",
            json={"expected_version": 2, "operator": "reviewer-1"},
        )
        assert rejected.status_code == 400
        assert rejected.json()["detail"]["error_code"] == "REVIEW_NOTE_REQUIRED"
        ok = client.post(
            f"{PREFIX}/{qid}/reject",
            json={
                "expected_version": 2,
                "operator": "reviewer-1",
                "review_note": "查询计划缺失",
            },
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "draft"
        assert ok.json()["review_note"] == "查询计划缺失"

    def test_approve_requires_operator(self, client: TestClient) -> None:
        created = _create(client)
        qid = created["question_id"]
        client.post(f"{PREFIX}/{qid}/submit-review", json={"expected_version": 1})
        response = client.post(
            f"{PREFIX}/{qid}/approve", json={"expected_version": 2}
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error_code"] == "REVIEWER_REQUIRED"

    def test_illegal_transition_409(self, client: TestClient) -> None:
        created = _create(client)
        # draft 不能直接 approve
        response = client.post(
            f"{PREFIX}/{created['question_id']}/approve",
            json={"expected_version": 1, "operator": "reviewer-1"},
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"]["error_code"]
            == "TRUSTED_QUESTION_INVALID_TRANSITION"
        )


class TestSynonymOperations:
    def test_add_and_remove_synonym(self, client: TestClient) -> None:
        created = _create(client)
        qid = created["question_id"]
        added = client.post(
            f"{PREFIX}/{qid}/synonyms",
            json={
                "expression": "门诊能报多少",
                "added_by": "ops-1",
                "expected_version": 1,
            },
        )
        assert added.status_code == 200
        assert added.json()["synonyms"][0]["expression"] == "门诊能报多少"
        assert added.json()["synonyms"][0]["added_by"] == "ops-1"
        removed = client.delete(
            f"{PREFIX}/{qid}/synonyms/门诊能报多少",
            params={"expected_version": 2},
        )
        assert removed.status_code == 200
        assert removed.json()["synonyms"] == []

    def test_remove_missing_synonym_404(self, client: TestClient) -> None:
        created = _create(client)
        response = client.delete(
            f"{PREFIX}/{created['question_id']}/synonyms/不存在",
            params={"expected_version": 1},
        )
        assert response.status_code == 404


class TestMatch:
    def test_match_active_question(self, client: TestClient) -> None:
        created = _create(client)
        _activate(client, created["question_id"])
        response = client.post(f"{PREFIX}/match", json={"question": "门诊报销比例是多少"})
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "matched"
        assert body["question"]["question_id"] == created["question_id"]

    def test_match_ignores_non_active(self, client: TestClient) -> None:
        _create(client)  # draft 状态不参与匹配
        response = client.post(f"{PREFIX}/match", json={"question": "门诊报销比例是多少"})
        assert response.json()["outcome"] == "no_match"

    def test_match_uncertain_returns_candidates(self, client: TestClient) -> None:
        first = _create(client, "在职职工门诊报销比例是多少")
        second = _create(client, "退休职工门诊报销比例是多少")
        _activate(client, first["question_id"])
        _activate(client, second["question_id"])
        response = client.post(f"{PREFIX}/match", json={"question": "职工门诊报销比例是多少"})
        body = response.json()
        # 不确定时必须澄清，不猜测执行
        assert body["outcome"] == "candidates"
        assert body["question"] is None
        assert len(body["candidates"]) == 2

    def test_match_no_match(self, client: TestClient) -> None:
        created = _create(client)
        _activate(client, created["question_id"])
        response = client.post(f"{PREFIX}/match", json={"question": "食堂今天有什么菜"})
        assert response.json()["outcome"] == "no_match"

    def test_match_role_filter(self, client: TestClient) -> None:
        created = _create(client, applicable_roles=["CASHIER"])
        _activate(client, created["question_id"])
        blocked = client.post(
            f"{PREFIX}/match",
            json={"question": "门诊报销比例是多少", "role": "CLINICIAN"},
        )
        assert blocked.json()["outcome"] == "no_match"
        allowed = client.post(
            f"{PREFIX}/match",
            json={"question": "门诊报销比例是多少", "role": "CASHIER"},
        )
        assert allowed.json()["outcome"] == "matched"


# ── 命中执行闭环（Slice 6）─────────────────────────────────────

_VALID_QUERY_PLAN = {
    "object_code": "outpatient_settlement",
    "scope": {
        "entity_code": "settlement",
        "anchor": {"field_code": "settlement_id", "value": "E001"},
        "query_scope": "whole_settlement",
    },
    "metrics": ["total_cost"],
    "limit": 100,
}


def _stub_service(
    rows: list[dict] | None = None, error: Exception | None = None
) -> SemanticQueryService:
    class _Stub(SemanticQueryService):
        def execute(self, query) -> SemanticQueryResult:  # noqa: ANN001
            if error is not None:
                raise error
            return SemanticQueryResult(
                rows=rows if rows is not None else [{"total_cost": 100.0}],
                model_version="v1",
                result_grain=["settlement"],
                query_scope="whole_settlement",
                quality_status="complete",
                evidence=QueryEvidence(plan_hash="h", datasets_used=["ds"]),
            )

    return _Stub.__new__(_Stub)


@pytest.fixture()
def exec_client() -> TestClient:
    app = create_app()
    store = InMemoryTrustedQuestionStorage()
    app.dependency_overrides[get_trusted_question_store] = lambda: store
    app.dependency_overrides[get_semantic_query_service] = lambda: _stub_service()
    return TestClient(app)


class TestMatchAndExecute:
    def test_matched_with_plan_executes(self, exec_client: TestClient) -> None:
        created = _create(exec_client, query_plan=_VALID_QUERY_PLAN)
        _activate(exec_client, created["question_id"])
        response = exec_client.post(
            f"{PREFIX}/match-and-execute", json={"question": "门诊报销比例是多少"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "matched"
        assert body["answer"]["outcome"] == "executed"
        assert body["answer"]["result"]["rows"] == [{"total_cost": 100.0}]

    def test_matched_without_plan_reports_no_plan(self, exec_client: TestClient) -> None:
        created = _create(exec_client)
        _activate(exec_client, created["question_id"])
        body = exec_client.post(
            f"{PREFIX}/match-and-execute", json={"question": "门诊报销比例是多少"}
        ).json()
        assert body["outcome"] == "matched"
        assert body["answer"]["outcome"] == "no_plan"

    def test_candidates_never_execute(self, exec_client: TestClient) -> None:
        first = _create(exec_client, "在职职工门诊报销比例是多少", query_plan=_VALID_QUERY_PLAN)
        second = _create(exec_client, "退休职工门诊报销比例是多少", query_plan=_VALID_QUERY_PLAN)
        _activate(exec_client, first["question_id"])
        _activate(exec_client, second["question_id"])
        body = exec_client.post(
            f"{PREFIX}/match-and-execute", json={"question": "职工门诊报销比例是多少"}
        ).json()
        # 匹配不确定：只回候选澄清，绝不执行
        assert body["outcome"] == "candidates"
        assert body["answer"] is None
        assert len(body["candidates"]) == 2

    def test_no_match_never_execute(self, exec_client: TestClient) -> None:
        created = _create(exec_client, query_plan=_VALID_QUERY_PLAN)
        _activate(exec_client, created["question_id"])
        body = exec_client.post(
            f"{PREFIX}/match-and-execute", json={"question": "食堂今天有什么菜"}
        ).json()
        assert body["outcome"] == "no_match"
        assert body["answer"] is None

    def test_execution_failure_reported(self, exec_client: TestClient) -> None:
        app = create_app()
        store = InMemoryTrustedQuestionStorage()
        app.dependency_overrides[get_trusted_question_store] = lambda: store
        app.dependency_overrides[get_semantic_query_service] = lambda: _stub_service(
            error=RuntimeError("SQL Server 连接超时")
        )
        client = TestClient(app)
        created = _create(client, query_plan=_VALID_QUERY_PLAN)
        _activate(client, created["question_id"])
        body = client.post(
            f"{PREFIX}/match-and-execute", json={"question": "门诊报销比例是多少"}
        ).json()
        assert body["answer"]["outcome"] == "execution_failed"
        assert "连接超时" in body["answer"]["violations"][0]
