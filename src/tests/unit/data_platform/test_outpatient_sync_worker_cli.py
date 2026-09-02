from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace

import pytest

from scripts.run_outpatient_sync_worker import (
    build_parser,
    format_status,
    run_loop,
    validate_args,
)
from src.data_platform.outpatient_governance import OutpatientWorkerStatus


NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class _Worker:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def run_one(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_parser_defaults_to_ten_seconds_and_bounds_idle_polling() -> None:
    parser = build_parser()
    assert parser.parse_args([]).poll_interval == 10
    for interval in (4, 61):
        with pytest.raises(ValueError, match="5.*60"):
            validate_args(parser.parse_args(["--poll-interval", str(interval)]))


def test_loop_continues_after_one_worker_error() -> None:
    stop = Event()
    worker = _Worker([
        RuntimeError("driver-secret-text"),
        SimpleNamespace(status="idle"),
    ])
    waits = []

    def wait(interval):
        waits.append(interval)
        if len(waits) == 2:
            stop.set()

    completed, errors = run_loop(worker, 10, stop, wait=wait)

    assert completed == 1
    assert errors == 1
    assert waits == [10, 10]


def test_status_exposes_counts_only() -> None:
    status = OutpatientWorkerStatus(
        total_jobs=3,
        due_jobs=1,
        last_attempt_status="failed",
        last_attempt_at=NOW,
    )
    output = format_status(status)
    assert "total_jobs=3" in output
    assert "due_jobs=1" in output
    for forbidden in ("host", "username", "password", "credential"):
        assert forbidden not in output
