from __future__ import annotations

from src.observability.metrics import definitions
from src.observability import metrics


EXPECTED_METRICS = {
    "skill_ai_generation_total",
    "skill_ai_generation_success_total",
    "skill_ai_generation_rejected_total",
    "skill_ai_output_parse_failure_total",
    "skill_ai_unsafe_code_total",
    "skill_ai_manual_accept_total",
}


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def labels(self, **labels: str) -> "_FakeCounter":
        assert set(labels).issubset({"scene", "status", "reason_code"})
        self.calls.append(labels)
        return self

    def inc(self) -> None:
        return None


def test_skill_ai_metric_definitions_use_only_low_cardinality_labels(
    monkeypatch,
) -> None:
    assert EXPECTED_METRICS.issubset(definitions.METRICS)
    counters = {}
    for name in EXPECTED_METRICS:
        counter = _FakeCounter()
        counters[name] = counter
        monkeypatch.setattr(metrics, name, counter)

    metrics.record_skill_ai_generation_started()
    metrics.record_skill_ai_generation_success()
    metrics.record_skill_ai_generation_rejected("output_parse_failure")
    metrics.record_skill_ai_generation_rejected("unsafe_code")
    metrics.record_skill_ai_manual_accept()

    assert counters["skill_ai_generation_total"].calls == [
        {"scene": "skill_authoring", "status": "started"}
    ]
    assert counters["skill_ai_generation_success_total"].calls == [
        {"scene": "skill_authoring", "status": "success"}
    ]
    assert counters["skill_ai_generation_rejected_total"].calls == [
        {"scene": "skill_authoring", "reason_code": "output_parse_failure"},
        {"scene": "skill_authoring", "reason_code": "unsafe_code"},
    ]
    assert counters["skill_ai_output_parse_failure_total"].calls == [
        {"scene": "skill_authoring", "reason_code": "output_parse_failure"}
    ]
    assert counters["skill_ai_unsafe_code_total"].calls == [
        {"scene": "skill_authoring", "reason_code": "unsafe_code"}
    ]
    assert counters["skill_ai_manual_accept_total"].calls == [
        {"scene": "skill_authoring", "status": "accepted"}
    ]
