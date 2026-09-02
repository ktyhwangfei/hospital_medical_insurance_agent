import pytest

from src.semantic_layer.models import Metric
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


def test_metric_has_backward_compatible_governance_defaults():
    metric = Metric(metric_code="mzjyxx.total_fee", object_code="mzjyxx", name="门诊总费用")

    assert metric.synonyms == []
    assert metric.compatible_dimensions == []
    assert metric.default_time_role is None
    assert metric.refresh_frequency is None
    assert metric.permission_level is None
    assert metric.owner is None
    assert metric.reviewer is None
    assert metric.precision is None


def test_published_metric_reports_missing_governance_fields():
    metric = Metric(
        metric_code="mzjyxx.total_fee",
        object_code="mzjyxx",
        name="门诊总费用",
        status="published",
    )

    assert set(metric.governance_missing_fields()) == {
        "synonyms",
        "definition",
        "aggregation",
        "unit",
        "precision",
        "compatible_dimensions",
        "default_time_role",
        "source_object",
        "refresh_frequency",
        "permission_level",
        "owner",
        "reviewer",
    }


def test_seed_publishes_four_metrics_and_defers_encounter_dependent_metrics():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)

    assert {
        metric.metric_code
        for metric in store.list_metrics("mzjyxx")
        if metric.status == "published"
    } == {
        "mzjyxx.T_State",
        "mzjyxx.T_FeeAll",
        "mzjyxx.T_FundPay",
        "mzjyxx.T_SelfPayAll",
    }
    average_fee = store.get_metric("mzjyxx.average_fee")
    assert average_fee.status == "draft"
    assert average_fee.fact_field_code is None
    assert average_fee.aggregation is None
    assert average_fee.dependencies == [
        "mzjyxx.T_FeeAll",
        "mzjyxx.insured_encounter_count",
    ]
    assert store.get_metric("mzjyxx.insured_encounter_count").status == "draft"

    version = registry.publish_object("mzjyxx")

    deferred_codes = {
        "mzjyxx.average_fee",
        "mzjyxx.insured_encounter_count",
    }
    assert deferred_codes.isdisjoint(metric.metric_code for metric in version.metrics)
    assert registry.get_metric_mapping("mzjyxx", list(deferred_codes)) == []
    assert all(store.get_metric(code).status == "draft" for code in deferred_codes)


@pytest.mark.parametrize(
    "metric_code",
    ["mzjyxx.average_fee", "mzjyxx.insured_encounter_count"],
)
def test_encounter_dependent_metric_publication_is_rejected(metric_code):
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    metric = store.get_metric(metric_code).model_copy(update={"status": "published"})

    with pytest.raises(ValueError, match="就诊人次口径未定"):
        registry.save_published_metric(metric)
