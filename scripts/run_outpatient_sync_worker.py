"""运行门诊数据治理同步 worker。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.outpatient_governance import OutpatientWorkerStatus
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceStore,
)
from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
from src.runtime.data_governance.service import DataGovernanceService
from src.runtime.data_governance.worker import OutpatientSyncWorker, run_outpatient_job
from src.runtime.discovery.sqlserver_source import _try_connect
from src.semantic_layer.registry import get_semantic_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="至多执行一个到期任务")
    modes.add_argument("--status", action="store_true", help="只读输出 worker 状态")
    parser.add_argument("--poll-interval", type=int, default=10)
    return parser


def validate_args(args) -> None:
    if not 5 <= args.poll_interval <= 60:
        raise ValueError("poll-interval 必须在 5–60 秒之间")


def run_loop(worker, interval: int, stop_event: Event, *, wait=None):
    wait = wait or stop_event.wait
    completed = 0
    errors = 0
    while not stop_event.is_set():
        try:
            worker.run_one()
            completed += 1
        except Exception:
            errors += 1
            print("worker_error=sync_worker_failed", file=sys.stderr, flush=True)
        if stop_event.is_set():
            break
        wait(interval)
    return completed, errors


def format_status(status: OutpatientWorkerStatus) -> str:
    return "\n".join((
        f"total_jobs={status.total_jobs}",
        f"due_jobs={status.due_jobs}",
        f"last_attempt_status={status.last_attempt_status or 'none'}",
        f"last_attempt_at={status.last_attempt_at.isoformat() if status.last_attempt_at else 'none'}",
    ))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    governance_store = OutpatientGovernanceStore()
    if args.status:
        print(format_status(governance_store.get_worker_status(datetime.now(timezone.utc))))
        return 0

    data_store = OutpatientPostgresStore()

    def connect(source, password):
        connection, _driver = _try_connect({
            "host": source.host,
            "port": source.port,
            "database": source.database,
            "user": source.username,
            "password": password,
        })
        return connection

    governance_service = DataGovernanceService(
        governance_store,
        data_store,
        connect,
    )
    runner = partial(
        run_outpatient_job,
        governance_service=governance_service,
        data_store=data_store,
        semantic_registry=get_semantic_registry(),
    )
    worker = OutpatientSyncWorker(governance_store, runner)
    if args.once:
        print(worker.run_one().model_dump_json())
        return 0

    stop_event = Event()

    def request_stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    run_loop(worker, args.poll_interval, stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
