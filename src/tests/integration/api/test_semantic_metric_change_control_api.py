from __future__ import annotations

import base64
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.semantic_layer.models import BusinessObject, Metric
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


BASE = "/api/v1/medical-insurance-ai-agent/semantic"
JWT_SECRET = "semantic-change-control-test-secret"


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


class _FakeMetaStore:
    def __init__(self) -> None:
        self.tasks: list[dict] = []
        self.fail = False

    def create_task(
        self,
        metric_code: str,
        change_type: str,
        strategy: str,
        golden_score=None,
        schema_version: int = 1,
    ) -> dict:
        if self.fail:
            raise RuntimeError("task store unavailable")
        task = {
            "task_id": f"task_{len(self.tasks) + 1}",
            "metric_code": metric_code,
            "change_type": change_type,
            "strategy": strategy,
            "schema_version": schema_version,
            "status": "pending",
        }
        self.tasks.append(task)
        return task


@pytest.fixture
def api(monkeypatch):
    from src.runtime.api import semantic_routes

    store = InMemoryRegistryStore()
    store.save_object(BusinessObject(
        object_code="zcgz", domain_code="policy", name="政策规则",
    ))
    store.save_metric(Metric(
        metric_code="zcgz.payment_amount",
        object_code="zcgz",
        name="支付金额",
        semantic_type="Amount",
        indexed=False,
        schema_version=4,
        status="published",
    ))
    registry = SemanticRegistry(store)
    meta_store = _FakeMetaStore()
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: registry)
    monkeypatch.setattr(semantic_routes, "_get_meta_store", lambda: meta_store)
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    client = TestClient(create_app(), raise_server_exceptions=False)
    return client, store, meta_store


def test_semantic_type_change_bumps_schema_and_creates_full_task(api) -> None:
    client, store, meta_store = api

    response = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Ratio", "expected_schema_version": 4},
        headers=_review_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "metric_code": "zcgz.payment_amount",
        "schema_version": 5,
        "requires_reextract": True,
        "task_id": "task_1",
        "task_status": "pending",
    }
    assert store.get_metric("zcgz.payment_amount").schema_version == 5
    assert meta_store.tasks == [{
        "task_id": "task_1",
        "metric_code": "zcgz.payment_amount",
        "change_type": "modify",
        "strategy": "full",
        "schema_version": 5,
        "status": "pending",
    }]


def test_indexed_change_bumps_schema_and_extraction_contract(api) -> None:
    client, store, meta_store = api

    response = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"indexed": True, "expected_schema_version": 4},
        headers=_review_headers(),
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == 5
    assert response.json()["requires_reextract"] is True
    assert store.get_metric("zcgz.payment_amount").indexed is True
    assert len(meta_store.tasks) == 1
    schema = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert schema.status_code == 200
    assert schema.json()["schema_version"] == 5

    detail = client.get(f"{BASE}/metrics/zcgz.payment_amount")
    assert detail.status_code == 200
    assert detail.json()["indexed"] is True
    assert detail.json()["schema_version"] == 5


@pytest.mark.parametrize(
    ("payload", "expected_name"),
    [
        ({"name": "统筹支付金额"}, "统筹支付金额"),
        ({"semantic_type": "Amount", "indexed": False}, "支付金额"),
    ],
)
def test_non_breaking_or_unchanged_update_does_not_create_task(
    api, payload: dict, expected_name: str,
) -> None:
    client, store, meta_store = api

    response = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json=payload,
        headers=_review_headers(),
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == 4
    assert response.json()["requires_reextract"] is False
    assert response.json()["task_id"] is None
    assert store.get_metric("zcgz.payment_amount").name == expected_name
    assert meta_store.tasks == []


def test_metric_update_requires_semantic_review_permission(api) -> None:
    client, store, meta_store = api

    missing = client.put(
        f"{BASE}/metrics/zcgz.payment_amount", json={"semantic_type": "Ratio"},
    )
    malformed = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Ratio"},
        headers={"Authorization": "Bearer malformed"},
    )

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert store.get_metric("zcgz.payment_amount").semantic_type == "Amount"
    assert meta_store.tasks == []


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/metrics", {"object_code": "zcgz", "name": "新指标"}),
        ("post", "/metrics/batch", {"items": []}),
        ("delete", "/metrics/zcgz.payment_amount", None),
        ("post", "/metrics/refresh-quality-scores", None),
        ("post", "/value-domains", {"domain_code": "status", "name": "状态"}),
        ("delete", "/value-domains/status", None),
        ("put", "/value-domains/status/standard-values", {"standard_values": ["有效"]}),
        ("post", "/value-domain/mapping", {
            "domain_code": "status", "source_value": "1", "standard_value": "有效",
        }),
        ("delete", "/value-domains/status/mappings/1", None),
    ],
)
def test_direct_semantic_governance_mutations_require_review_token(
    api, method: str, path: str, payload: dict | None,
) -> None:
    client, store, meta_store = api

    response = client.request(method, f"{BASE}{path}", json=payload)

    assert response.status_code == 401
    assert store.get_metric("zcgz.payment_amount") is not None
    assert meta_store.tasks == []


@pytest.mark.parametrize(
    "payload",
    [
        {"metric_code": "zcgz.renamed"},
        {"object_code": "claims"},
    ],
)
def test_rename_and_object_move_are_rejected_without_data_loss(api, payload: dict) -> None:
    client, store, meta_store = api
    store.save_object(BusinessObject(
        object_code="claims", domain_code="policy", name="申诉规则",
    ))

    response = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json=payload,
        headers=_review_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "SEMANTIC_METRIC_MIGRATION_REQUIRED"
    assert store.get_metric("zcgz.payment_amount") is not None
    assert meta_store.tasks == []


def test_breaking_update_requires_matching_expected_schema_version(api) -> None:
    client, store, meta_store = api

    missing = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Ratio"},
        headers=_review_headers(),
    )
    stale = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Ratio", "expected_schema_version": 3},
        headers=_review_headers(),
    )

    assert missing.status_code == 409
    assert stale.status_code == 409
    for response in (missing, stale):
        assert response.json()["detail"]["error_code"] == "SEMANTIC_SCHEMA_VERSION_CONFLICT"
    assert store.get_metric("zcgz.payment_amount").schema_version == 4
    assert meta_store.tasks == []


def test_stale_concurrent_update_creates_only_one_task(api) -> None:
    client, store, meta_store = api
    request = {
        "semantic_type": "Ratio",
        "expected_schema_version": 4,
    }

    first = client.put(
        f"{BASE}/metrics/zcgz.payment_amount", json=request, headers=_review_headers(),
    )
    second = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Date", "expected_schema_version": 4},
        headers=_review_headers(),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "SEMANTIC_SCHEMA_VERSION_CONFLICT"
    assert store.get_metric("zcgz.payment_amount").schema_version == 5
    assert len(meta_store.tasks) == 1


def test_simultaneous_breaking_updates_allow_only_one_schema_bump(api) -> None:
    client, store, meta_store = api

    def update(semantic_type: str):
        return client.put(
            f"{BASE}/metrics/zcgz.payment_amount",
            json={
                "semantic_type": semantic_type,
                "expected_schema_version": 4,
            },
            headers=_review_headers(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(update, ["Ratio", "Date"]))

    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"]["error_code"] == "SEMANTIC_SCHEMA_VERSION_CONFLICT"
    assert store.get_metric("zcgz.payment_amount").schema_version == 5
    assert len(meta_store.tasks) == 1


def test_missing_metric_uses_standard_error_contract(api) -> None:
    client, _store, _meta_store = api

    response = client.put(
        f"{BASE}/metrics/zcgz.missing",
        json={"name": "missing"},
        headers=_review_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "SEMANTIC_METRIC_NOT_FOUND"


def test_metric_save_failure_does_not_create_task(api, monkeypatch) -> None:
    client, store, meta_store = api

    def fail_save(_metric):
        raise RuntimeError("metric save failed")

    monkeypatch.setattr(store, "save_metric", fail_save)
    response = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Ratio", "expected_schema_version": 4},
        headers=_review_headers(),
    )

    assert response.status_code == 500
    assert meta_store.tasks == []


def test_task_creation_failure_does_not_persist_breaking_change(api) -> None:
    client, store, meta_store = api
    meta_store.fail = True

    response = client.put(
        f"{BASE}/metrics/zcgz.payment_amount",
        json={"semantic_type": "Ratio", "expected_schema_version": 4},
        headers=_review_headers(),
    )

    assert response.status_code == 500
    metric = store.get_metric("zcgz.payment_amount")
    assert metric.semantic_type == "Amount"
    assert metric.schema_version == 4
