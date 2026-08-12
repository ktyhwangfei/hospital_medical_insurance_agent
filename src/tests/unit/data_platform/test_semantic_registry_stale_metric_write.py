from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from src.data_platform.storage.postgresql.semantic_registry_store import (
    PostgresRegistryStore,
)
from src.semantic_layer.models import Metric
from src.semantic_layer.registry import InMemoryRegistryStore


def _metric(**overrides) -> Metric:
    data = {
        "metric_code": "zcgz.payment_amount",
        "object_code": "zcgz",
        "name": "支付金额",
        "semantic_type": "Amount",
        "indexed": False,
        "schema_version": 4,
        "status": "published",
        "usage_count": 1,
        "quality_score": 10.0,
    }
    data.update(overrides)
    return Metric(**data)


def test_in_memory_stale_writer_preserves_contract_but_updates_runtime_scores() -> None:
    store = InMemoryRegistryStore()
    store.save_metric(_metric(
        semantic_type="Ratio", indexed=True, schema_version=5,
    ))

    store.save_metric(_metric(
        semantic_type="Amount",
        indexed=False,
        schema_version=4,
        usage_count=9,
        quality_score=88.0,
    ))

    saved = store.get_metric("zcgz.payment_amount")
    assert saved is not None
    assert (saved.semantic_type, saved.indexed, saved.schema_version) == (
        "Ratio", True, 5,
    )
    assert (saved.usage_count, saved.quality_score) == (9, 88.0)


def test_in_memory_same_version_contract_write_remains_supported() -> None:
    store = InMemoryRegistryStore()
    store.save_metric(_metric(schema_version=5))

    store.save_metric(_metric(
        name="统筹支付金额", semantic_type="Ratio", schema_version=5,
    ))

    saved = store.get_metric("zcgz.payment_amount")
    assert saved is not None
    assert saved.name == "统筹支付金额"
    assert saved.semantic_type == "Ratio"
    assert saved.schema_version == 5


def test_postgres_upsert_guards_contract_columns_by_schema_version() -> None:
    calls: list[tuple[str, tuple]] = []

    class _FakeClient:
        def execute(self, sql: str, params: tuple = ()) -> list[dict]:
            calls.append((sql, params))
            return []

    store = PostgresRegistryStore.__new__(PostgresRegistryStore)
    store._client = _FakeClient()
    store.save_metric(_metric())

    sql = calls[0][0]
    guard = "EXCLUDED.schema_version >= semantic_metrics.schema_version"
    assert f"semantic_type = CASE WHEN {guard}" in sql
    assert f"indexed = CASE WHEN {guard}" in sql
    assert f"metric_kind = CASE WHEN {guard}" in sql
    assert "schema_version = GREATEST(semantic_metrics.schema_version, EXCLUDED.schema_version)" in sql
    assert "usage_count = EXCLUDED.usage_count" in sql
    assert "quality_score = EXCLUDED.quality_score" in sql


def test_in_memory_usage_increment_is_atomic() -> None:
    store = InMemoryRegistryStore()
    store.save_metric(_metric(usage_count=0))

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _index: store.increment_metric_usage(
            "zcgz.payment_amount"
        ), range(100)))

    assert store.get_metric("zcgz.payment_amount").usage_count == 100


def test_in_memory_quality_update_does_not_change_usage_or_contract() -> None:
    store = InMemoryRegistryStore()
    store.save_metric(_metric(
        semantic_type="Ratio", indexed=True, schema_version=5, usage_count=7,
    ))

    store.update_metric_quality("zcgz.payment_amount", 91.0)

    saved = store.get_metric("zcgz.payment_amount")
    assert saved is not None
    assert saved.quality_score == 91.0
    assert saved.usage_count == 7
    assert (saved.semantic_type, saved.indexed, saved.schema_version) == (
        "Ratio", True, 5,
    )


def test_postgres_runtime_updates_are_targeted_sql() -> None:
    calls: list[tuple[str, tuple]] = []

    class _FakeClient:
        def execute(self, sql: str, params: tuple = ()) -> list[dict]:
            calls.append((sql, params))
            return [{"usage_count": 4}] if "RETURNING usage_count" in sql else []

    store = PostgresRegistryStore.__new__(PostgresRegistryStore)
    store._client = _FakeClient()

    assert store.increment_metric_usage("zcgz.payment_amount", 2) == 4
    store.update_metric_quality("zcgz.payment_amount", 88.0)

    assert "SET usage_count = usage_count + %s" in calls[0][0]
    assert calls[0][1] == (2, "zcgz.payment_amount")
    assert "SET quality_score = %s" in calls[1][0]
    assert calls[1][1] == (88.0, "zcgz.payment_amount")
    assert all("semantic_type" not in sql for sql, _params in calls)
