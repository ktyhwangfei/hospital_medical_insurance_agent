import pytest

from src.semantic_layer.models import (
    BusinessDomain,
    BusinessObject,
    Metric,
    SemanticDataset,
    SemanticField,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


def test_settlement_query_model_is_seeded_and_frozen_on_publish():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)

    datasets = registry.list_datasets("inpatient_settlement")
    assert {dataset.dataset_code for dataset in datasets} == {
        "inpatient_registration",
        "benefit_segments",
        "payment_segments",
        "inpatient_transaction",
    }
    assert any(
        key.dataset_code == "benefit_segments"
        and key.key_type == "primary"
        and key.columns == ["djh", "bcqsrq", "zqxh"]
        for key in registry.list_dataset_keys(object_code="inpatient_settlement")
    )
    assert registry.get_metric("inpatient_settlement.total_amount").aggregation == "sum"

    version = registry.publish_object("inpatient_settlement")

    assert version.snapshot["object_code"] == "inpatient_settlement"
    assert len(version.datasets) == 4
    assert version.datasets[0].status == "published"
    assert version.keys
    assert version.fields
    assert version.relations
    assert version.quality_rules
    assert all(metric.status == "published" for metric in registry.get_metrics_by_object("inpatient_settlement"))


def test_query_object_without_primary_key_cannot_publish():
    store = InMemoryRegistryStore()
    store.save_domain(BusinessDomain(domain_code="test", name="测试"))
    store.save_object(BusinessObject(
        object_code="broken_query",
        domain_code="test",
        name="缺主键模型",
    ))
    store.save_dataset(SemanticDataset(
        dataset_code="broken_rows",
        object_code="broken_query",
        datasource_id="bjybdb",
        table_name="broken_rows",
        name="缺主键数据集",
    ))
    store.save_field(SemanticField(
        field_code="broken_rows.amount",
        dataset_code="broken_rows",
        column_name="amount",
        name="金额",
        field_role="fact",
        semantic_type="Amount",
    ))
    store.save_metric(Metric(
        metric_code="broken_query.amount",
        object_code="broken_query",
        name="金额",
        metric_type="aggregate",
        semantic_type="Amount",
        fact_field_code="broken_rows.amount",
        aggregation="sum",
    ))

    with pytest.raises(ValueError, match="primary key"):
        SemanticRegistry(store).publish_object("broken_query")


def test_query_model_rejects_unregistered_key_column_and_cross_datasource():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    key = next(item for item in store.list_dataset_keys(object_code="inpatient_settlement") if item.key_code == "payment_segment_pk")
    store.save_dataset_key(key.model_copy(update={"columns": [*key.columns, "not_registered"]}))
    payment = next(item for item in store.list_datasets("inpatient_settlement") if item.dataset_code == "payment_segments")
    store.save_dataset(payment.model_copy(update={"datasource_id": "another_database"}))

    issues = SemanticRegistry(store).validate_query_model("inpatient_settlement")

    assert any("unknown columns" in issue for issue in issues)
    assert any("multiple datasources" in issue for issue in issues)
