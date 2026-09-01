"""门禁通过后发布门诊 PostgreSQL 查询模型新版本。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
from src.data_platform.storage.postgresql.semantic_registry_store import PostgresRegistryStore
from src.semantic_layer.registry import RegistryStore, SemanticRegistry
from src.semantic_layer.seed import (
    OUTPATIENT_P1_TRADE_FIELDS,
    switch_outpatient_query_model_to_postgres,
)


CHANGELOG = "P1 PostgreSQL near-real-time source switch"


def publish_outpatient_postgres_query_model(
    registry_store: RegistryStore,
    outpatient_store: OutpatientPostgresStore,
    *,
    source_id: str = "bjybdb",
):
    registry = SemanticRegistry(registry_store)
    if not outpatient_store.check_schema():
        raise RuntimeError("outpatient_store_schema_unavailable")
    if not outpatient_store.get_sync_status(source_id).last_batch_id:
        raise RuntimeError("outpatient_published_batch_required")

    required = {"mz_trade": set(), "mz_fee_item": set()}
    for field in registry.list_fields(object_code="mzjyxx"):
        required[field.dataset_code].add(field.column_name)
    required["mz_trade"].update(column for column, _type in OUTPATIENT_P1_TRADE_FIELDS)
    available = outpatient_store.get_view_columns()
    missing = {
        dataset: sorted(columns - available.get(dataset, set()))
        for dataset, columns in required.items()
        if columns - available.get(dataset, set())
    }
    if missing:
        raise RuntimeError(f"outpatient_view_columns_missing: {missing}")

    issues = registry.validate_query_model("mzjyxx")
    if issues:
        raise RuntimeError(f"outpatient_query_model_invalid: {'; '.join(issues)}")

    switch_outpatient_query_model_to_postgres(registry_store)
    issues = registry.validate_query_model("mzjyxx")
    if issues:
        raise RuntimeError(f"outpatient_postgres_model_invalid: {'; '.join(issues)}")
    return registry.publish_object("mzjyxx", changelog=CHANGELOG)


def main() -> int:
    version = publish_outpatient_postgres_query_model(
        PostgresRegistryStore(), OutpatientPostgresStore()
    )
    print(f"object_code={version.object_code} version={version.version} changelog={CHANGELOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
