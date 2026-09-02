"""以独立进程运行门诊 CDC 同步或查看新鲜度状态。"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.insurance_interface.outpatient_cdc import SqlServerOutpatientCdcSource
from src.data_platform.outpatient_sync import OutpatientSyncService
from src.data_platform.storage.postgresql.outpatient_store import (
    OutpatientPostgresStore,
    OutpatientSyncStatus,
)
from src.runtime.discovery.semantic_source import SemanticDataSource
from src.semantic_layer.registry import get_semantic_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="只执行一个批次")
    modes.add_argument("--status", action="store_true", help="只读输出新鲜度状态")
    parser.add_argument("--source-id", default="bjybdb")
    parser.add_argument("--interval", type=int, default=45)
    return parser


def validate_args(args) -> None:
    if not args.once and not args.status and not 30 <= args.interval <= 60:
        raise ValueError("循环同步 interval 必须在 30–60 秒之间")


def run_once(service):
    return service.run_once()


def run_loop(service, interval: int, stop_event: Event, *, wait=None):
    wait = wait or stop_event.wait
    completed = 0
    errors: list[str] = []
    while not stop_event.is_set():
        try:
            result = service.run_once()
            completed += 1
            print(_format_result(result), flush=True)
        except Exception as exc:
            error = getattr(exc, "error_code", None) or str(exc) or type(exc).__name__
            errors.append(error)
            print(f"sync_error={error}", file=sys.stderr, flush=True)
        if stop_event.is_set():
            break
        wait(interval)
    return completed, errors


def format_status(status: OutpatientSyncStatus) -> str:
    return "\n".join((
        f"source_id={status.source_id}",
        f"last_batch_id={status.last_batch_id or 'none'}",
        f"last_mode={status.last_mode or 'none'}",
        f"checkpoint_kind={status.checkpoint_kind or 'none'}",
        f"last_published_at={_iso(status.last_published_at)}",
        f"last_non_empty_latency_seconds={_number(status.last_non_empty_latency_seconds)}",
        f"sample_count={status.non_empty_sample_count}",
        f"p95_latency_seconds={_number(status.p95_latency_seconds)}",
        f"quality_status={status.quality_status or 'none'}",
        f"semantic_version={status.semantic_version or 'none'}",
    ))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    store = OutpatientPostgresStore()
    if args.status:
        print(format_status(store.get_sync_status(args.source_id)))
        return 0

    semantic_source = SemanticDataSource()
    source = SqlServerOutpatientCdcSource(
        lambda: semantic_source.connect_datasource(args.source_id)
    )
    service = OutpatientSyncService(
        source, store, get_semantic_registry(), source_id=args.source_id,
    )
    if args.once:
        print(_format_result(run_once(service)))
        return 0

    stop_event = Event()

    def request_stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    run_loop(service, args.interval, stop_event)
    return 0


def _format_result(result) -> str:
    return (
        f"batch_id={result.batch_id} mode={result.mode} row_count={result.row_count} "
        f"quality_status={result.quality_status} "
        f"semantic_version={result.semantic_version or 'none'}"
    )


def _iso(value) -> str:
    return value.isoformat() if value else "none"


def _number(value) -> str:
    return "none" if value is None else str(round(value, 3))


if __name__ == "__main__":
    raise SystemExit(main())
