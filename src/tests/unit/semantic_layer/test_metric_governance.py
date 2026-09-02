from src.semantic_layer.models import Metric


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
