"""生成不含交易号和身份字段的门诊批次核验报告。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient


DIMENSIONS = ("trade_date", "section", "cure_type", "fund_type", "settlement_lifecycle")


class ReconciliationCase(BaseModel):
    case_id: str
    data_batch_id: str
    rule_codes: list[str] = Field(default_factory=list)
    amount_difference: str | None = None
    quality_status: str


class ReconciliationReport(BaseModel):
    data_batch_id: str
    sample_count: int
    sample_insufficient: bool
    cases: list[ReconciliationCase]
    public_distributions: dict[str, dict[str, int | Literal["<10"]]]


def build_reconciliation_report(
    batch_id: str,
    rows: list[dict[str, Any]],
    *,
    sample_size: int = 30,
) -> ReconciliationReport:
    prepared = [_prepare(batch_id, row) for row in rows]
    ordered = sorted(prepared, key=lambda item: item["_hash"])
    anomalies = [item for item in ordered if item["_anomaly"]]
    selected = anomalies[:sample_size]
    remaining = [item for item in ordered if not item["_anomaly"]]
    seen_values = {dimension: {item[dimension] for item in selected} for dimension in DIMENSIONS}
    seen_combinations = {_combination(item) for item in selected}

    while len(selected) < sample_size and remaining:
        best = max(
            remaining,
            key=lambda item: (
                _combination(item) not in seen_combinations,
                sum(item[dimension] not in seen_values[dimension] for dimension in DIMENSIONS),
                _reverse_hash(item["_hash"]),
            ),
        )
        remaining.remove(best)
        selected.append(best)
        seen_combinations.add(_combination(best))
        for dimension in DIMENSIONS:
            seen_values[dimension].add(best[dimension])

    cases = [
        ReconciliationCase(
            case_id=f"case-{index:02d}",
            data_batch_id=batch_id,
            rule_codes=item["rule_codes"],
            amount_difference=item["amount_difference"],
            quality_status=item["quality_status"],
        )
        for index, item in enumerate(selected, start=1)
    ]
    distributions = {
        dimension: _suppress(Counter(item[dimension] for item in selected))
        for dimension in DIMENSIONS
    }
    return ReconciliationReport(
        data_batch_id=batch_id,
        sample_count=len(cases),
        sample_insufficient=len(cases) < sample_size,
        cases=cases,
        public_distributions=distributions,
    )


def load_reconciliation_rows(
    client: PostgreSQLClient, batch_id: str | None
) -> tuple[str, list[dict[str, Any]]]:
    if batch_id is None:
        latest = client.execute(
            """SELECT batch_id FROM outpatient_sync_batches
               WHERE row_count > 0 ORDER BY published_at DESC LIMIT 1"""
        )
        if not latest:
            raise RuntimeError("outpatient_non_empty_batch_required")
        batch_id = latest[0]["batch_id"]
    rows = client.execute(
        """SELECT trade.trade_no AS "T_TradeNo", trade.data_batch_id,
                  trade.trade_date, COALESCE(trade.section_codes ->> 0, 'unknown') AS section,
                  COALESCE(trade.cure_type, 'unknown') AS cure_type,
                  COALESCE(trade.fund_type, 'unknown') AS fund_type,
                  COALESCE(trade.settlement_lifecycle, 'unknown') AS settlement_lifecycle,
                  trade.quality_status, trade.fee_all,
                  COALESCE(SUM(fee.fee) FILTER (WHERE NOT fee.is_deleted), 0) AS fee_item_total
           FROM outpatient_trade_current AS trade
           LEFT JOIN outpatient_fee_item_current AS fee ON fee.trade_no = trade.trade_no
           WHERE trade.data_batch_id = %s AND NOT trade.is_deleted
           GROUP BY trade.trade_no""",
        (batch_id,),
    )
    return batch_id, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id")
    args = parser.parse_args(argv)
    batch_id, rows = load_reconciliation_rows(PostgreSQLClient(DATABASE_URL), args.batch_id)
    report = build_reconciliation_report(batch_id, rows)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def _prepare(batch_id: str, row: dict[str, Any]) -> dict[str, Any]:
    trade_no = str(row.get("T_TradeNo") or "")
    difference = _difference(row.get("fee_all"), row.get("fee_item_total"))
    quality_status = str(row.get("quality_status") or "unknown")
    rules = sorted({str(code) for code in row.get("rule_codes", []) if code})
    if difference is not None and abs(difference) > Decimal("0.01"):
        rules.append("fee_detail_total_mismatch")
    if quality_status not in {"complete", "unknown"} and not rules:
        rules.append(f"quality_status_{quality_status}")
    prepared = {
        dimension: _value(row.get(dimension)) for dimension in DIMENSIONS
    }
    prepared.update({
        "_hash": hashlib.sha256(f"{batch_id}:{trade_no}".encode()).hexdigest(),
        "_anomaly": quality_status != "complete" or bool(rules),
        "rule_codes": sorted(set(rules)),
        "amount_difference": str(difference) if difference is not None else None,
        "quality_status": quality_status,
    })
    return prepared


def _difference(expected: Any, actual: Any) -> Decimal | None:
    if expected is None or actual is None:
        return None
    try:
        return Decimal(str(expected)) - Decimal(str(actual))
    except InvalidOperation:
        return None


def _value(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value not in (None, "") else "unknown"


def _combination(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(item[dimension] for dimension in DIMENSIONS)


def _reverse_hash(value: str) -> int:
    return -int(value, 16)


def _suppress(counts: Counter) -> dict[str, int | Literal["<10"]]:
    suppressed = {label for label, count in counts.items() if 0 < count < 10}
    visible = [(count, label) for label, count in counts.items() if label not in suppressed]
    if len(suppressed) == 1 and visible:
        suppressed.add(min(visible)[1])
    return {
        label: "<10" if label in suppressed else count
        for label, count in sorted(counts.items())
    }


if __name__ == "__main__":
    raise SystemExit(main())
