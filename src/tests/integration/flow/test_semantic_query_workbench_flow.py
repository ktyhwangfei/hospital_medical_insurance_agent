from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.semantic_layer.query_planner import SemanticQueryPlanner
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


BASE = "/api/v1/medical-insurance-ai-agent/semantic"
JWT_SECRET = "semantic-query-workbench-flow-secret"


def _review_headers() -> dict[str, str]:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": "semantic-reviewer",
        "roles": ["information_department"],
        "permissions": ["semantic:review"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }).encode()).decode().rstrip("=")
    signing_input = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer {signing_input}.{signature}"}


def test_object_model_anchor_and_query_validation_flow(monkeypatch) -> None:
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    registry.publish_object("inpatient_settlement")
    planner = SemanticQueryPlanner(registry)

    class FakeService:
        def sample_anchor(self, object_code, entity_code, field_code):
            return "1671213"

        def execute(self, query):
            return planner.result_from_row(query, planner.plan(query), {
                "total_amount": 189085.85,
                "_anchor_count": 1,
                "_segment_count": 2,
                "_matched_segment_count": 2,
                "_extra_segment_count": 0,
                "_benefit_duplicate_count": 0,
                "_payment_duplicate_count": 0,
            }, duration_ms=1)

    monkeypatch.setattr(semantic_routes, "get_registry", lambda: registry)
    monkeypatch.setattr(semantic_routes, "_get_semantic_query_runtime", lambda: (planner, FakeService()))
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    client = TestClient(create_app(), raise_server_exceptions=False)

    objects = client.get(f"{BASE}/objects").json()
    assert next(item for item in objects if item["object_code"] == "inpatient_settlement")["current_version"] == "1"

    model = client.get(f"{BASE}/objects/inpatient_settlement/query-model?published=true").json()
    assert model["queryable"] is True
    anchor_field = next(item for item in model["fields"] if item["field_role"] == "identifier")
    entity_code = next(
        key["entity_code"] for key in model["keys"]
        if key["dataset_code"] == anchor_field["dataset_code"]
        and anchor_field["column_name"] in key["columns"]
    )
    metric_code = next(item["metric_code"] for item in model["metrics"] if item.get("fact_field_code"))

    sample = client.post(f"{BASE}/query/anchor-sample", json={
        "object_code": "inpatient_settlement",
        "entity_code": entity_code,
        "field_code": anchor_field["field_code"],
    }, headers=_review_headers())
    assert sample.status_code == 200

    result = client.post(f"{BASE}/query/test", json={
        "object_code": "inpatient_settlement",
        "scope": {
            "entity_code": entity_code,
            "anchor": {"field_code": anchor_field["field_code"], "value": sample.json()["value"]},
            "query_scope": "whole_admission",
        },
        "metrics": [metric_code],
    }, headers=_review_headers())
    assert result.status_code == 200
    assert result.json()["result"]["quality_status"] == "complete"
    assert result.json()["result"]["evidence"]["matched_segment_count"] == 2

