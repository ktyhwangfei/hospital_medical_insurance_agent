from __future__ import annotations

from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace

import pytest

from scripts.run_outpatient_cdc_sync import (
    build_parser,
    format_status,
    run_loop,
    run_once,
    validate_args,
)
from src.data_platform.storage.postgresql.outpatient_store import OutpatientSyncStatus


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


class _Service:
    def __init__(self, outcomes, stop_event=None):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.stop_event = stop_event

    def run_once(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if self.stop_event is not None:
            self.stop_event.set()
        return outcome


def _result(mode="incremental"):
    return SimpleNamespace(
        batch_id="batch-1", mode=mode, row_count=2,
        quality_status="complete", semantic_version="4",
        published_at=NOW, to_lsn=b"\x20",
    )


def test_parser_defaults_to_45_seconds_and_loop_only_accepts_30_to_60() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.source_id == "bjybdb"
    assert args.interval == 45
    validate_args(args)

    for interval in (29, 61):
        with pytest.raises(ValueError, match="30.*60"):
            validate_args(parser.parse_args(["--interval", str(interval)]))
        validate_args(parser.parse_args(["--once", "--interval", str(interval)]))


def test_once_executes_exactly_one_batch() -> None:
    service = _Service([_result("snapshot")])
    result = run_once(service)
    assert service.calls == 1
    assert result.mode == "snapshot"


def test_loop_recovers_next_period_after_batch_error() -> None:
    stop_event = Event()
    service = _Service([RuntimeError("temporary_db_error"), _result()])
    waits = []

    def wait(interval):
        waits.append(interval)
        if len(waits) == 2:
            stop_event.set()

    completed, errors = run_loop(service, 45, stop_event, wait=wait)

    assert service.calls == 2
    assert completed == 1
    assert errors == ["temporary_db_error"]
    assert waits == [45, 45]


def test_stop_request_during_batch_exits_before_waiting() -> None:
    stop_event = Event()
    service = _Service([_result()], stop_event=stop_event)
    waits = []

    completed, errors = run_loop(service, 45, stop_event, wait=waits.append)

    assert service.calls == 1
    assert completed == 1
    assert errors == []
    assert waits == []


def test_status_is_freshness_only_and_excludes_sensitive_details() -> None:
    status = OutpatientSyncStatus(
        source_id="bjybdb", last_batch_id="batch-9", last_mode="heartbeat",
        checkpoint_kind="lsn", checkpoint_value="20", last_published_at=NOW,
        last_non_empty_latency_seconds=72.5,
        non_empty_sample_count=100, p95_latency_seconds=240.0,
        quality_status="warning", semantic_version="4",
    )

    output = format_status(status)

    assert "batch-9" in output
    assert "checkpoint_kind=lsn" in output
    assert "checkpoint_value" not in output
    assert "last_non_empty_latency_seconds=72.5" in output
    assert "p95_latency_seconds=240.0" in output
    assert "sample_count=100" in output
    for forbidden in ("DATABASE_URL", "password", "T_TradeNo", "payload"):
        assert forbidden not in output
