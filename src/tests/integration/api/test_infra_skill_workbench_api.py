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
