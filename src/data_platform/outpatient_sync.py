"""门诊数据批次的确定性加工与原子发布。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.adapters.insurance_interface.outpatient_source import (
    OUTPATIENT_SOURCE_SPECS,
    CheckpointKind,
    OutpatientChange,
    OutpatientCheckpoint,
    OutpatientSourceBatch,
)


_CAPTURES = tuple(OUTPATIENT_SOURCE_SPECS)
_PRIMARY_DIAGNOSIS_TYPES = frozenset({"1", "01", "PRIMARY", "主诊断"})
_SUCCESS_STATES = frozenset({3, 4})
_REVERSED_STATES = frozenset({-4, -3, -2, -1})
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class OutpatientSyncResult:
    batch_id: str
    mode: str
    checkpoint: OutpatientCheckpoint
    row_count: int
    semantic_version: str | None
    quality_status: str
    published_at: datetime


class OutpatientSyncService:
    """单次执行 source → 质量/上下文 → PostgreSQL 原子批次。"""

    def __init__(self, source, store, semantic_registry, source_id: str = "bjybdb") -> None:
        self._source = source
        self._store = store
        self._registry = semantic_registry
        self._source_id = source_id

    def run_once(self) -> OutpatientSyncResult:
        checkpoint = self._store.get_checkpoint(self._source_id)
        batch = self._source.read(checkpoint)
        if batch.snapshot_rows is not None:
            changes = _snapshot_changes(batch)
            mode = "snapshot"
            rows = batch.snapshot_rows
            batch = replace(batch, changes=changes)
        else:
            changes = batch.changes
            mode = "incremental" if changes else "heartbeat"
            affected = set(batch.scope_trade_nos) or _affected_trade_nos(changes)
            rows = self._store.load_projection_rows(affected)

        state, issues = _build_state(rows)
        _apply_changes(state, changes, issues)
        metadata = _analyze_state(state, issues)
        semantic_version = _semantic_version(self._registry)
        if semantic_version is None:
            issues.append(_issue("semantic_model_unavailable", "blocking"))
        quality_summary = _quality_summary(issues)

        published = self._store.publish_batch(
            source_id=self._source_id,
            execution_mode=mode,
            batch=batch,
            semantic_version=semantic_version,
            quality_summary=quality_summary,
            projection_metadata=metadata,
        )
        return OutpatientSyncResult(
            batch_id=published.batch_id,
            mode=mode,
            checkpoint=batch.checkpoint,
            row_count=published.row_count,
            semantic_version=semantic_version,
            quality_status=quality_summary["status"],
            published_at=published.published_at,
        )


def _snapshot_changes(batch: OutpatientSourceBatch) -> tuple[OutpatientChange, ...]:
    changes: list[OutpatientChange] = []
    cursor_prefix = _checkpoint_bytes(batch.checkpoint)
    for capture in _CAPTURES:
        spec = OUTPATIENT_SOURCE_SPECS[capture]
        rows = sorted(
            (batch.snapshot_rows or {}).get(capture, ()),
            key=lambda row: tuple(repr(row.get(column)) for column in spec.key_columns),
        )
        for index, row in enumerate(rows, start=1):
            payload = dict(row)
            changes.append(OutpatientChange(
                capture_instance=capture,
                source_cursor=cursor_prefix + index.to_bytes(10, "big"),
                operation=2,
                commit_time=None,
                source_key=tuple(payload.get(column) for column in spec.key_columns),
                payload=payload,
            ))
    return tuple(changes)


def _affected_trade_nos(changes: tuple[OutpatientChange, ...]) -> set[str]:
    values: set[str] = set()
    for change in changes:
        trade_no = change.payload.get("T_TradeNo")
        original = change.payload.get("T_OraginalTradeNo")
        if trade_no not in (None, ""):
            values.add(str(trade_no))
        if original not in (None, ""):
            values.add(str(original))
    return values


def _checkpoint_bytes(checkpoint: OutpatientCheckpoint) -> bytes:
    if checkpoint.kind is CheckpointKind.LSN:
        return bytes.fromhex(checkpoint.value)
    return checkpoint.value.encode("utf-8")


def _empty_state() -> dict[str, dict[tuple[Any, ...], dict[str, Any]]]:
    return {capture: {} for capture in _CAPTURES}


def _build_state(rows_by_capture):
    state = _empty_state()
    issues: list[dict[str, Any]] = []
    for capture in _CAPTURES:
        spec = OUTPATIENT_SOURCE_SPECS[capture]
        for row in rows_by_capture.get(capture, ()):
            payload = dict(row)
            key = tuple(payload.get(column) for column in spec.key_columns)
            trade_no = _trade_no(payload)
            if any(value in (None, "") for value in key):
                issues.append(_issue("null_source_key", "blocking", trade_no))
                continue
            if key in state[capture]:
                issues.append(_issue("duplicate_source_key", "blocking", trade_no))
            state[capture][key] = payload
    return state, issues


def _apply_changes(state, changes, issues) -> None:
    for change in changes:
        spec = OUTPATIENT_SOURCE_SPECS[change.capture_instance]
        key = tuple(change.payload.get(column) for column in spec.key_columns)
        if any(value in (None, "") for value in key):
            issues.append(_issue("null_source_key", "blocking", _trade_no(change.payload)))
            continue
        if change.operation == 1:
            state[change.capture_instance].pop(key, None)
        else:
            state[change.capture_instance][key] = dict(change.payload)


def _analyze_state(state, issues):
    trades = list(state["dbo_o_Trade"].values())
    trade_by_no = {_trade_no(row): row for row in trades if _trade_no(row)}
    fees_by_trade = _group_by_trade(state["dbo_o_FeeItem"].values())
    diagnoses_by_trade = _group_by_trade(state["dbo_o_Diagnose"].values())

    for trade_no in fees_by_trade:
        if trade_no not in trade_by_no:
            issues.append(_issue("orphan_fee_item", "blocking", trade_no))
    for trade_no in diagnoses_by_trade:
        if trade_no not in trade_by_no:
            issues.append(_issue("orphan_diagnosis", "blocking", trade_no))

    chains: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        trade_no = _trade_no(trade)
        original = _text(trade.get("T_OraginalTradeNo"))
        chain_id = original or trade_no
        if trade_no and chain_id:
            chains.setdefault(chain_id, []).append(trade)

    metadata: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}
    for chain_id, members in chains.items():
        lifecycle = _chain_lifecycle(chain_id, members, trade_by_no, issues)
        for trade in members:
            trade_no = _trade_no(trade)
            _check_amounts(trade, fees_by_trade.get(trade_no, []), issues)
            diagnosis = _select_diagnosis(trade, diagnoses_by_trade.get(trade_no, []))
            if diagnosis["context_quality"] != "source_primary":
                issues.append(_issue(
                    "diagnosis_fallback" if diagnosis["context_quality"] == "deterministic_fallback"
                    else "diagnosis_missing",
                    "warning",
                    trade_no,
                ))
            metadata[("dbo_o_Trade", (trade_no,))] = {
                "settlement_chain_id": chain_id,
                "settlement_lifecycle": lifecycle,
                **diagnosis,
            }

    for key, item in metadata.items():
        trade_no = str(key[1][0])
        relevant = [issue for issue in issues if issue.get("trade_no") in (None, trade_no)]
        item["quality_status"] = _status(relevant)
    return metadata


def _chain_lifecycle(chain_id, members, trade_by_no, issues) -> str:
    refund_rows = [row for row in members if _text(row.get("T_OraginalTradeNo"))]
    unmatched = [
        row for row in refund_rows
        if _text(row.get("T_OraginalTradeNo")) not in trade_by_no
    ]
    if unmatched:
        for row in unmatched:
            issues.append(_issue("unmatched_negative", "blocking", _trade_no(row)))
        return "unmatched_negative"

    net = sum((_amount(row, "T_FeeAll") or Decimal("0") for row in members), Decimal("0"))
    if net < 0:
        for row in members:
            issues.append(_issue("unmatched_negative", "blocking", _trade_no(row)))
        return "unmatched_negative"
    if refund_rows:
        if any(_text(row.get("T_PartialReturnFlag")) == "1" for row in refund_rows) or net > 0:
            return "partially_refunded"
        return "refunded"
    states = {_integer(row.get("T_State")) for row in members}
    if states & _REVERSED_STATES:
        return "reversed"
    if any(_text(row.get("NP_Settle_State")) == "0" for row in members) or not states & _SUCCESS_STATES:
        return "source_failed"
    return "active"


def _check_amounts(trade, fees, issues) -> None:
    trade_no = _trade_no(trade)
    _compare(
        trade_no, "trade_total_split_mismatch", _amount(trade, "T_FeeAll"),
        _sum_present(_amount(trade, "T_FeeIn"), _amount(trade, "T_FeeOut")), issues,
    )
    _compare(
        trade_no, "trade_payment_split_mismatch", _amount(trade, "T_FeeAll"),
        _sum_present(_amount(trade, "T_FundPay"), _amount(trade, "T_SelfPayAll")), issues,
    )
    for trade_field, fee_field, rule_code in (
        ("T_FeeAll", "Fee", "fee_detail_total_mismatch"),
        ("T_FeeIn", "FeeIn", "fee_detail_in_mismatch"),
        ("T_FeeOut", "FeeOut", "fee_detail_out_mismatch"),
    ):
        values = [_amount(row, fee_field) for row in fees]
        detail_total = sum((value for value in values if value is not None), Decimal("0")) if fees else None
        _compare(trade_no, rule_code, _amount(trade, trade_field), detail_total, issues)


def _compare(trade_no, rule_code, expected, actual, issues) -> None:
    if expected is None or actual is None:
        return
    difference = expected - actual
    if abs(difference) > _CENT:
        issues.append(_issue(rule_code, "warning", trade_no, difference))


def _select_diagnosis(trade, diagnoses):
    if not diagnoses:
        return {
            "context_quality": "missing", "diagnosis_codes": [],
            "section_codes": [], "section_names": [],
        }
    primary = [
        row for row in diagnoses
        if _text(row.get("DiagnoseType"), upper=True) in _PRIMARY_DIAGNOSIS_TYPES
    ]
    quality = "source_primary" if primary else "deterministic_fallback"
    candidates = primary or diagnoses
    trade_date = _datetime(trade.get("T_TradeDate"))

    def sort_key(row):
        recipe_date = _datetime(row.get("RecipeDate"))
        distance = abs((recipe_date - trade_date).total_seconds()) if recipe_date and trade_date else float("inf")
        return distance, _text(row.get("DiagnoseNo")) or "", _text(row.get("RecipeNo")) or ""

    selected = min(candidates, key=sort_key)
    names = [
        value for value in (
            _text(selected.get("Sectionname")), _text(selected.get("HISSectionName")),
        ) if value
    ]
    return {
        "context_quality": quality,
        "diagnosis_codes": _unique([_text(selected.get("DiagnoseCode"))]),
        "section_codes": _unique([_text(selected.get("SectionCode"))]),
        "section_names": _unique(names),
    }


def _semantic_version(registry) -> str | None:
    obj = registry.get_object("mzjyxx")
    if obj is None or obj.status != "published" or not obj.current_version:
        return None
    version = registry.get_object_version("mzjyxx", obj.current_version)
    if version is None or not version.snapshot.get("queryable"):
        return None
    return str(obj.current_version)


def _quality_summary(issues):
    ordered = sorted(
        issues,
        key=lambda item: (item["severity"], item["rule_code"], item.get("trade_no") or ""),
    )
    return {
        "status": _status(ordered),
        "blocked_count": sum(item["severity"] == "blocking" for item in ordered),
        "warning_count": sum(item["severity"] == "warning" for item in ordered),
        "issues": ordered,
    }


def _status(issues) -> str:
    if any(item["severity"] == "blocking" for item in issues):
        return "blocked"
    if any(item["severity"] == "warning" for item in issues):
        return "warning"
    return "complete"


def _issue(rule_code, severity, trade_no=None, difference=None):
    value = {"rule_code": rule_code, "severity": severity}
    if trade_no:
        value["trade_no"] = trade_no
    if difference is not None:
        value["difference"] = str(difference)
    return value


def _group_by_trade(rows):
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        trade_no = _trade_no(row)
        if trade_no:
            grouped.setdefault(trade_no, []).append(row)
    return grouped


def _trade_no(payload) -> str | None:
    return _text(payload.get("T_TradeNo"))


def _amount(payload, field) -> Decimal | None:
    value = payload.get(field)
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal field {field}") from exc


def _sum_present(left, right) -> Decimal | None:
    return None if left is None or right is None else left + right


def _integer(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value, *, upper=False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if upper else text


def _datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))
