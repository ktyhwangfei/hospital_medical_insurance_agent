"""可信问题库 /question-library API 测试 — issue #37（鉴权 + 试问命中/澄清 +
审核生命周期 + 同义运营 + 冷启动）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.question_library.question_in_memory import (
    InMemoryTrustedQuestionStorage,
)
from src.runtime.api.app import create_app
from src.runtime.api.question_library_routes import get_question_library_service
from src.runtime.question_library.service import QuestionLibraryService

BASE = "/api/v1/medical-insurance-ai-agent/question-library"
JWT_SECRET = "question-library-test-secret"
NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)


def _token(permissions):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "qlib-admin-1",
        "roles": ["information_department"],
        "permissions": permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()).decode().rstrip("=")
    return f"Bearer {signing_input}.{signature}"


READ_HEADERS = {"Authorization": _token(["question_library:read"])}
WRITE_HEADERS = {"Authorization": _token(["question_library:read", "question_library:write"])}
WRONG_HEADERS = {"Authorization": _token(["ops:read"])}

PLAN = {
    "object_code": "mzjyxx",
    "scope": {"query_scope": "whole_settlement"},
    "metrics": ["fund_pay_total"],
    "group_by": [],
    "filters": [],
    "order_by": [],
    "limit": 100,
}

DRAFT_BODY = {
    "standard_question": "本年度医保基金支付总额是多少",
    "synonyms": ["今年基金支付总额是多少"],
    "roles": ["information_department"],
    "object_code": "mzjyxx",
    "metrics": ["fund_pay_total"],
    "dimensions": [],
    "time_scope": "本年度",
    "filters": [],
    "query_plan": PLAN,
    "allow_drilldown": False,
    "expected_result": {"grain": ["全院"], "metrics": ["fund_pay_total"]},
}


class _FakeExecutor:
    def __init__(self):
        self.plans: list[dict] = []

    def __call__(self, plan: dict) -> dict:
        self.plans.append(plan)
        return {"rows": [{"fund_pay_total": 88.0}], "quality_status": "complete"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    storage = InMemoryTrustedQuestionStorage()
    executor = _FakeExecutor()
    service = QuestionLibraryService(
        storage,
        plan_validator=lambda plan: None,
        query_executor=executor,
        history_source=lambda: [("个人自付总额怎么查", "2026-09-02")] * 3,
        now=lambda: NOW,
    )
    app = create_app()
    app.dependency_overrides[get_question_library_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client, service, executor


def _create_and_publish(test_client, body=None) -> str:
    response = test_client.post(f"{BASE}/questions", json=body or DRAFT_BODY, headers=WRITE_HEADERS)
    assert response.status_code == 201, response.text
    question_id = response.json()["question_id"]
    review = test_client.post(
        f"{BASE}/questions/{question_id}/review",
        json={"approve": True, "reviewer": "reviewer-1", "expected_revision": 1},
        headers=WRITE_HEADERS,
    )
    assert review.status_code == 200, review.text
    return question_id


class TestMatch:
    def test_match_hit_open_without_auth(self, client):
        test_client, _, _ = client
        _create_and_publish(test_client)
        response = test_client.post(f"{BASE}/match", json={"question": "本年度医保基金支付总额是多少？"})
        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "hit"
        assert body["question"]["standard_question"] == "本年度医保基金支付总额是多少"

    def test_match_synonym_hit(self, client):
        test_client, _, _ = client
        _create_and_publish(test_client)
        response = test_client.post(f"{BASE}/match", json={"question": "今年基金支付总额是多少"})
        assert response.json()["kind"] == "hit"

    def test_match_uncertain_clarifies_with_candidates(self, client):
        test_client, service, _ = client
        _create_and_publish(test_client)
        response = test_client.post(f"{BASE}/match", json={"question": "医保基金支付总额"})
        assert response.status_code == 200
        body = response.json()
        # 验收：不确定必须澄清——kind=clarify 且绝不返回 question
        assert body["kind"] == "clarify"
        assert body["question"] is None
        assert len(body["candidates"]) >= 1

    def test_match_empty_question_rejected(self, client):
        test_client, _, _ = client
        response = test_client.post(f"{BASE}/match", json={"question": ""})
        assert response.status_code == 422


class TestDraftLifecycle:
    def test_create_draft_requires_write_permission(self, client):
        test_client, _, _ = client
        assert test_client.post(f"{BASE}/questions", json=DRAFT_BODY).status_code == 401
        assert test_client.post(f"{BASE}/questions", json=DRAFT_BODY, headers=READ_HEADERS).status_code == 403
        assert test_client.post(f"{BASE}/questions", json=DRAFT_BODY, headers=WRITE_HEADERS).status_code == 201

    def test_create_draft_invalid_plan_returns_422(self, client):
        test_client, _, _ = client
        # 元数据与绑定计划不一致 → Pydantic 请求体验证直接 422
        body = {**DRAFT_BODY, "query_plan": {**PLAN, "object_code": "mismatch"}}
        response = test_client.post(f"{BASE}/questions", json=body, headers=WRITE_HEADERS)
        assert response.status_code == 422

    def test_list_questions_with_status_filter(self, client):
        test_client, _, _ = client
        _create_and_publish(test_client)
        response = test_client.get(f"{BASE}/questions?status=draft", headers=READ_HEADERS)
        assert response.status_code == 200
        assert response.json()["total"] == 0
        response = test_client.get(f"{BASE}/questions?status=published", headers=READ_HEADERS)
        assert response.json()["total"] == 1

    def test_get_question_detail(self, client):
        test_client, _, _ = client
        question_id = _create_and_publish(test_client)
        response = test_client.get(f"{BASE}/questions/{question_id}", headers=READ_HEADERS)
        assert response.status_code == 200
        assert response.json()["query_plan"] == PLAN

    def test_get_question_not_found(self, client):
        test_client, _, _ = client
        response = test_client.get(f"{BASE}/questions/tq_missing", headers=READ_HEADERS)
        assert response.status_code == 404
        assert response.json()["detail"]["error_code"] == "QUESTION_NOT_FOUND"

    def test_review_conflict_returns_409(self, client):
        test_client, _, _ = client
        response = test_client.post(f"{BASE}/questions", json=DRAFT_BODY, headers=WRITE_HEADERS)
        question_id = response.json()["question_id"]
        review = test_client.post(
            f"{BASE}/questions/{question_id}/review",
            json={"approve": True, "reviewer": "reviewer-1", "expected_revision": 99},
            headers=WRITE_HEADERS,
        )
        assert review.status_code == 409
        assert review.json()["detail"]["error_code"] == "QUESTION_REVISION_CONFLICT"

    def test_review_published_again_returns_409_transition(self, client):
        test_client, _, _ = client
        question_id = _create_and_publish(test_client)
        review = test_client.post(
            f"{BASE}/questions/{question_id}/review",
            json={"approve": True, "reviewer": "reviewer-1", "expected_revision": 2},
            headers=WRITE_HEADERS,
        )
        assert review.status_code == 409
        assert review.json()["detail"]["error_code"] == "QUESTION_TRANSITION_INVALID"

    def test_archive_published(self, client):
        test_client, _, _ = client
        question_id = _create_and_publish(test_client)
        response = test_client.post(
            f"{BASE}/questions/{question_id}/archive?expected_revision=2", headers=WRITE_HEADERS
        )
        assert response.status_code == 200
        assert response.json()["status"] == "archived"


class TestExecute:
    def test_execute_published_question_open(self, client):
        test_client, _, executor = client
        question_id = _create_and_publish(test_client)
        response = test_client.post(f"{BASE}/questions/{question_id}/execute")
        assert response.status_code == 200
        assert response.json()["rows"][0]["fund_pay_total"] == 88.0
        assert executor.plans == [PLAN]

    def test_execute_draft_rejected(self, client):
        test_client, _, _ = client
        response = test_client.post(f"{BASE}/questions", json=DRAFT_BODY, headers=WRITE_HEADERS)
        question_id = response.json()["question_id"]
        assert (
            test_client.post(f"{BASE}/questions/{question_id}/execute").status_code == 409
        )

    def test_execute_missing_question_404(self, client):
        test_client, _, _ = client
        response = test_client.post(f"{BASE}/questions/tq_missing/execute")
        assert response.status_code == 404


class TestSynonymOperationsAndEvents:
    def test_add_synonym_then_match_hits(self, client):
        test_client, _, _ = client
        question_id = _create_and_publish(test_client)
        response = test_client.post(
            f"{BASE}/questions/{question_id}/synonyms",
            json={"synonym": "医保基金支付总额年度合计", "expected_revision": 2},
            headers=WRITE_HEADERS,
        )
        assert response.status_code == 200
        match = test_client.post(f"{BASE}/match", json={"question": "医保基金支付总额年度合计？"})
        assert match.json()["kind"] == "hit"

    def test_add_synonym_conflict_409(self, client):
        test_client, _, _ = client
        _create_and_publish(test_client)
        other = {
            **DRAFT_BODY,
            "standard_question": "个人自付总额是多少",
            "synonyms": [],
        }
        response = test_client.post(f"{BASE}/questions", json=other, headers=WRITE_HEADERS)
        other_id = response.json()["question_id"]
        test_client.post(
            f"{BASE}/questions/{other_id}/review",
            json={"approve": True, "reviewer": "reviewer-1", "expected_revision": 1},
            headers=WRITE_HEADERS,
        )
        conflict = test_client.post(
            f"{BASE}/questions/{other_id}/synonyms",
            json={"synonym": "本年度医保基金支付总额是多少", "expected_revision": 2},
            headers=WRITE_HEADERS,
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["error_code"] == "QUESTION_SYNONYM_CONFLICT"

    def test_match_events_recorded_and_listed(self, client):
        test_client, _, _ = client
        _create_and_publish(test_client)
        test_client.post(f"{BASE}/match", json={"question": "本年度医保基金支付总额是多少"})
        test_client.post(f"{BASE}/match", json={"question": "完全无关的问题"})
        response = test_client.get(f"{BASE}/match-events?outcome=clarify", headers=READ_HEADERS)
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["asked_text"] == "完全无关的问题"

    def test_match_events_require_read_permission(self, client):
        test_client, _, _ = client
        assert test_client.get(f"{BASE}/match-events").status_code == 401


class TestStatsAndColdStart:
    def test_stats(self, client):
        test_client, _, _ = client
        _create_and_publish(test_client)
        response = test_client.get(f"{BASE}/stats", headers=READ_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["question_counts"]["published"] == 1

    def test_cold_start_returns_frequency_candidates(self, client):
        test_client, _, _ = client
        response = test_client.get(f"{BASE}/cold-start", headers=READ_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body == [{"question_text": "个人自付总额怎么查", "frequency": 3}]

    def test_cold_start_requires_read_permission(self, client):
        test_client, _, _ = client
        assert test_client.get(f"{BASE}/cold-start").status_code == 401
        assert test_client.get(f"{BASE}/cold-start", headers=WRONG_HEADERS).status_code == 403
