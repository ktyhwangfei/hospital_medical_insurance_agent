"""Portal Skill 管理工作台的兼容 API 测试。"""

import os
from unittest.mock import patch

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


PREFIX = "/api/v1/medical-insurance-ai-agent"


def test_skill_overview_returns_loaded_skill_summary():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).get(f"{PREFIX}/infra-skills/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["skill_count"] >= 1
    assert body["skills"]
    assert {"skill_id", "loaded", "manifest_valid", "metric_count"}.issubset(body["skills"][0])


def test_skill_workbench_static_route_returns_actionable_summary():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).get(f"{PREFIX}/infra-skills/workbench")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] >= 1
    assert {
        "healthy",
        "needs_evaluation",
        "pending_approval",
        "test_active",
        "updated_at",
    }.issubset(body["summary"])
    assert {
        "governance_status",
        "latest_eval_status",
        "test_release_status",
        "attention_reason",
    }.issubset(body["items"][0])
    assert "question_template" not in response.text
    assert "approval_reason" not in response.text


def test_route_test_response_keeps_legacy_fields_and_adds_explanation():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).post(
            f"{PREFIX}/infra-skills/route-test",
            json={"question": "统筹自付怎么算？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "统筹自付怎么算？"
    assert "matched_skill_id" in body
    assert isinstance(body["confidence"], float)
    assert isinstance(body["candidates"], list)


def test_route_test_rejects_empty_question():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).post(
            f"{PREFIX}/infra-skills/route-test",
            json={"question": ""},
        )

    assert response.status_code == 200
    assert response.json()["matched_skill_id"] is None
    assert response.json()["match_method"] == "none"
