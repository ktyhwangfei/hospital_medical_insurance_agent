import json

from scripts.generate_outpatient_reconciliation import build_reconciliation_report


def _row(index: int, *, anomaly: bool = False):
    return {
        "T_TradeNo": f"trade-{index}",
        "data_batch_id": "batch-1",
        "trade_date": f"2026-08-{index % 5 + 1:02d}",
        "section": f"section-{index % 4}",
        "cure_type": f"cure-{index % 3}",
        "fund_type": f"fund-{index % 2}",
        "settlement_lifecycle": f"life-{index % 3}",
        "quality_status": "warning" if anomaly else "complete",
        "rule_codes": [f"anomaly-{index}"] if anomaly else [],
        "fee_all": "100.00",
        "fee_item_total": "99.00" if anomaly else "100.00",
    }


def test_report_is_stable_prioritizes_anomalies_and_never_leaks_row_identity() -> None:
    rows = [_row(index, anomaly=index in {31, 33, 37}) for index in range(40)]

    first = build_reconciliation_report("batch-1", rows)
    second = build_reconciliation_report("batch-1", list(reversed(rows)))

    assert first.cases == second.cases
    assert len(first.cases) == 30
    assert all(case.rule_codes for case in first.cases[:3])
    assert {case.case_id for case in first.cases} == {
        f"case-{index:02d}" for index in range(1, 31)
    }
    rendered = json.dumps(first.model_dump(mode="json"), ensure_ascii=False)
    assert "trade-" not in rendered
    assert "T_TradeNo" not in rendered
    assert "payload" not in rendered


def test_report_marks_short_batch_and_complementarily_suppresses_small_buckets() -> None:
    rows = [_row(index) for index in range(12)]
    for index, row in enumerate(rows):
        row["fund_type"] = "small" if index < 2 else "large"

    report = build_reconciliation_report("batch-1", rows)

    assert report.sample_count == 12
    assert report.sample_insufficient is True
    assert report.public_distributions["fund_type"] == {
        "large": "<10",
        "small": "<10",
    }
