from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.semantic_layer.query_planner import SemanticQueryPlanner
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


BASE = "/api/v1/medical-insurance-ai-agent/semantic"
JWT_SECRET = "semantic-query-model-test-secret"


def _review_headers() -> dict[str, str]:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "semantic-reviewer",
        "roles": ["information_department"],
        "permissions": ["semantic:review"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer {signing_input}.{signature}"}


@pytest.fixture
def api(monkeypatch):
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    registry.publish_object("inpatient_settlement")
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: registry)
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    return TestClient(create_app(), raise_server_exceptions=False), registry


def test_query_model_can_be_read_validated_and_replaced(api) -> None:
    client, registry = api

    current = client.get(f"{BASE}/objects/inpatient_settlement/query-model")
    assert current.status_code == 200
    body = current.json()
    assert body["queryable"] is True
    assert len(body["datasets"]) == 4
    assert body["validation_issues"] == []

    document = {key: body[key] for key in (
        "datasets", "keys", "fields", "relations", "quality_rules",
    )}
    document["datasets"][0]["name"] = "住院登记主数据"
    saved = client.put(
        f"{BASE}/objects/inpatient_settlement/query-model",
        json=document,
        headers=_review_headers(),
    )

    assert saved.status_code == 200
    assert saved.json()["datasets"][0]["name"] == "住院登记主数据"
    assert registry.validate_query_model("inpatient_settlement") == []


def test_invalid_query_model_is_rejected_without_deleting_current_model(api) -> None:
    client, registry = api
    body = client.get(f"{BASE}/objects/inpatient_settlement/query-model").json()
    document = {key: body[key] for key in (
        "datasets", "keys", "fields", "relations", "quality_rules",
    )}
    document["relations"][0]["from_key"] = "missing_key"

    response = client.put(
        f"{BASE}/objects/inpatient_settlement/query-model",
        json=document,
        headers=_review_headers(),
    )

    assert response.status_code == 400
    assert registry.list_dataset_relations("inpatient_settlement")[0].from_key != "missing_key"


def test_query_test_returns_plan_result_and_parameterized_sql(api, monkeypatch) -> None:
    from src.runtime.api import semantic_routes

    client, registry = api
    planner = SemanticQueryPlanner(registry)

    class FakeService:
        def execute(self, query):
            return planner.result_from_row(
                query,
                planner.plan(query),
                {
                    "total_amount": 189085.85,
                    "_anchor_count": 1,
                    "_segment_count": 2,
                    "_matched_segment_count": 2,
                    "_extra_segment_count": 0,
                    "_benefit_duplicate_count": 0,
                    "_payment_duplicate_count": 0,
                },
                duration_ms=3,
            )

    monkeypatch.setattr(
        semantic_routes,
        "_get_semantic_query_runtime",
        lambda: (planner, FakeService()),
    )
    response = client.post(
        f"{BASE}/query/test",
        json={
            "object_code": "inpatient_settlement",
            "scope": {
                "entity_code": "inpatient_admission",
                "anchor": {
                    "field_code": "inpatient_registration.registration_id",
                    "value": "1671213",
                },
                "query_scope": "whole_admission",
            },
            "metrics": ["total_amount"],
        },
        headers=_review_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan"]["query_scope"] == "whole_admission"
    assert payload["result"]["quality_status"] == "complete"
    assert payload["result"]["evidence"]["segment_count"] == 2
    assert "1671213" not in payload["parameterized_sql"]


def test_query_model_mutation_and_query_test_require_review_permission(api) -> None:
    client, _registry = api
    body = client.get(f"{BASE}/objects/inpatient_settlement/query-model").json()
    document = {key: body[key] for key in (
        "datasets", "keys", "fields", "relations", "quality_rules",
    )}

    assert client.put(
        f"{BASE}/objects/inpatient_settlement/query-model", json=document,
    ).status_code == 401
    assert client.post(f"{BASE}/query/test", json={}).status_code == 401
    assert client.post(f"{BASE}/query/anchor-sample", json={}).status_code == 401


def test_published_query_model_read_ignores_unpublished_edits(api) -> None:
    client, _registry = api
    current = client.get(f"{BASE}/objects/inpatient_settlement/query-model").json()
    original_name = current["datasets"][0]["name"]
    document = {key: current[key] for key in (
        "datasets", "keys", "fields", "relations", "quality_rules",
    )}
    document["datasets"][0]["name"] = "尚未发布的名称"
    assert client.put(
        f"{BASE}/objects/inpatient_settlement/query-model",
        json=document,
        headers=_review_headers(),
    ).status_code == 200

    published = client.get(
        f"{BASE}/objects/inpatient_settlement/query-model?published=true",
    )

    assert published.status_code == 200
    assert published.json()["datasets"][0]["name"] == original_name
    assert any(item["metric_code"].endswith(".total_amount") for item in published.json()["metrics"])


def test_anchor_sample_uses_review_permission_and_runtime_service(api, monkeypatch) -> None:
    from src.runtime.api import semantic_routes

    client, registry = api
    planner = SemanticQueryPlanner(registry)

    class FakeService:
        def sample_anchor(self, object_code, entity_code, field_code):
            assert object_code == "inpatient_settlement"
            assert entity_code == "inpatient_admission"
            assert field_code == "inpatient_registration.registration_id"
            return "1671213"

    monkeypatch.setattr(
        semantic_routes,
        "_get_semantic_query_runtime",
        lambda: (planner, FakeService()),
    )
    response = client.post(
        f"{BASE}/query/anchor-sample",
        json={
            "object_code": "inpatient_settlement",
            "entity_code": "inpatient_admission",
            "field_code": "inpatient_registration.registration_id",
        },
        headers=_review_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"value": "1671213"}


def test_batch_metric_creation_preserves_query_metadata(api) -> None:
    client, registry = api

    response = client.post(
        f"{BASE}/metrics/batch",
        json={"items": [{
            "object_code": "inpatient_settlement",
            "metric_code": "inpatient_settlement.batch_total",
            "name": "批量登记总费用",
            "semantic_type": "Amount",
            "source_table": "yb_zyfdxx",
            "source_field": "bdfyzje",
            "fact_field_code": "payment_segments.total_amount",
            "aggregation": "sum",
        }]},
        headers=_review_headers(),
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "created"
    metric = registry.get_metric("inpatient_settlement.batch_total")
    assert metric.fact_field_code == "payment_segments.total_amount"
    query_model = client.get(
        f"{BASE}/objects/inpatient_settlement/query-model",
    ).json()
    assert any(
        item["metric_code"] == "inpatient_settlement.batch_total"
        and item["aggregation"] == "sum"
        for item in query_model["metrics"]
    )
