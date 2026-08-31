from types import SimpleNamespace

import pytest

from scripts.publish_outpatient_postgres_query_model import (
    CHANGELOG,
    publish_outpatient_postgres_query_model,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


class _OutpatientStore:
    def __init__(self, columns, *, schema_ok=True, batch_id="batch-1") -> None:
        self.columns = columns
        self.schema_ok = schema_ok
        self.batch_id = batch_id

    def check_schema(self):
        return self.schema_ok

    def get_sync_status(self, _source_id):
        return SimpleNamespace(last_batch_id=self.batch_id)

    def get_view_columns(self):
        return self.columns


def _previous_registry():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    for code, table in (("mz_trade", "o_Trade"), ("mz_fee_item", "o_FeeItem")):
        dataset = store.get_dataset(code)
        store.save_dataset(dataset.model_copy(update={
            "datasource_id": "bjybdb", "schema_name": "dbo", "table_name": table,
        }))
    registry = SemanticRegistry(store)
    previous = registry.publish_object("mzjyxx", changelog="previous SQL Server model")
    columns = {
        code: {field.column_name for field in registry.list_fields(dataset_code=code)}
        for code in ("mz_trade", "mz_fee_item")
    }
    return store, registry, previous, columns


def test_publish_switches_binding_and_keeps_previous_version_readable() -> None:
    store, registry, previous, columns = _previous_registry()

    published = publish_outpatient_postgres_query_model(store, _OutpatientStore(columns))

    assert published.version == "2"
    assert published.changelog == CHANGELOG
    assert {(item.datasource_id, item.schema_name, item.table_name) for item in published.datasets} == {
        ("outpatient_postgres", "public", "mz_trade"),
        ("outpatient_postgres", "public", "mz_fee_item"),
    }
    restored = registry.get_object_version("mzjyxx", previous.version)
    assert restored is not None
    assert {item.datasource_id for item in restored.datasets} == {"bjybdb"}


@pytest.mark.parametrize("gate", ["schema", "batch", "columns", "validation"])
def test_publish_fails_closed_before_creating_a_version(gate: str) -> None:
    store, registry, _previous, columns = _previous_registry()
    outpatient = _OutpatientStore(columns)
    if gate == "schema":
        outpatient.schema_ok = False
    elif gate == "batch":
        outpatient.batch_id = None
    elif gate == "columns":
        outpatient.columns["mz_trade"].remove("T_TradeNo")
    else:
        store.delete_quality_rule("mz_fee_item_coverage")

    with pytest.raises(RuntimeError):
        publish_outpatient_postgres_query_model(store, outpatient)

    assert len(registry.list_object_versions("mzjyxx")) == 1
