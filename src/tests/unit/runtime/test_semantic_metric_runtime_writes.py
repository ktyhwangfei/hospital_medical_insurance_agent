from __future__ import annotations

from types import SimpleNamespace

from src.runtime.api import semantic_routes
from src.runtime.scenario_executor import _track_skill_metrics
from src.semantic_layer.models import Metric


class _TrackingStore:
    def __init__(self) -> None:
        self.metric = Metric(
            metric_code="zcgz.payment_amount",
            object_code="zcgz",
            name="支付金额",
            source_field="payment_amount",
            source_object="policy_rules",
        )
        self.incremented: list[str] = []
        self.quality_updates: list[tuple[str, float]] = []

    def get_metric(self, metric_code: str):
        return self.metric if metric_code == self.metric.metric_code else None

    def list_metrics(self):
        return [self.metric]

    def increment_metric_usage(self, metric_code: str, delta: int = 1) -> int:
        self.incremented.append(metric_code)
        self.metric.usage_count += delta
        return self.metric.usage_count

    def update_metric_quality(self, metric_code: str, score: float) -> None:
        self.quality_updates.append((metric_code, score))
        self.metric.quality_score = score

    def save_metric(self, _metric) -> None:
        raise AssertionError("runtime writers must use targeted updates")


def test_usage_and_quality_routes_use_targeted_store_methods(monkeypatch) -> None:
    store = _TrackingStore()
    registry = SimpleNamespace(_store=store)
    monkeypatch.setattr(semantic_routes, "get_registry", lambda: registry)

    usage = semantic_routes.track_metric_usage("zcgz.payment_amount")
    updated = semantic_routes._refresh_quality_scores_from_scan([{
        "field_name": "payment_amount",
        "table_name": "policy_rules",
        "non_null_rate": 1.0,
        "description": "支付金额",
        "sample_value": "100",
    }])

    assert usage.usage_count == 1
    assert store.incremented == ["zcgz.payment_amount"]
    assert updated == 1
    assert store.quality_updates == [("zcgz.payment_amount", 70.0)]


def test_scenario_metric_tracking_uses_atomic_increment(monkeypatch, tmp_path) -> None:
    skill_dir = tmp_path / "demo_skill"
    skill_dir.mkdir()
    (skill_dir / "skill_manifest.yaml").write_text(
        "needed_objects:\n  - object_code: zcgz\n    metrics:\n      - payment_amount\n",
        encoding="utf-8",
    )
    store = _TrackingStore()
    monkeypatch.setattr("src.config.production.SKILLS_DIR", tmp_path)
    monkeypatch.setattr(
        semantic_routes, "get_registry", lambda: SimpleNamespace(_store=store),
    )

    _track_skill_metrics("demo_skill")

    assert store.incremented == ["zcgz.payment_amount"]
