"""运行健康运营定时巡检 worker（#52）。

复用门诊同步 worker 的单进程 claim 调度模式：轮询 claim 到期的
scheduled 巡检，未到期即 idle；与手动巡检（API）通过同一调度行
（active_inspection_id）互斥，多进程并发时由 FOR UPDATE SKIP LOCKED
保证同一时刻至多执行一次。
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_platform.storage.ops.ops_factory import get_ops_finding_storage
from src.runtime.ops.scheduler import OpsInspectionScheduler
from src.runtime.ops.service import OpsHealthService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="至多执行一次到期巡检")
    modes.add_argument("--status", action="store_true", help="只读输出调度与最近巡检状态")
    parser.add_argument("--poll-interval", type=int, default=30)
    return parser


def validate_args(args) -> None:
    if not 5 <= args.poll_interval <= 600:
        raise ValueError("poll-interval 必须在 5–600 秒之间")


def build_scheduler() -> OpsInspectionScheduler:
    # 巡检读取面复用治理控制面服务（与 /ops API 同一工厂，进程内单例）
    from src.runtime.api.data_governance_routes import get_data_governance_service

    storage = get_ops_finding_storage()
    health = OpsHealthService(storage, get_data_governance_service)
    return OpsInspectionScheduler(storage, health)


def run_loop(scheduler: OpsInspectionScheduler, interval: int, stop_event: Event, *, wait=None):
    wait = wait or stop_event.wait
    completed = 0
    errors = 0
    while not stop_event.is_set():
        try:
            run = scheduler.run_scheduled_once()
            if run is not None:
                completed += 1
                print(
                    "inspection_done "
                    f"id={run.inspection_id} status={run.status.value} "
                    f"finding_count={run.finding_count} new={run.new_finding_count}",
                    flush=True,
                )
        except Exception:
            errors += 1
            print("worker_error=ops_inspection_failed", file=sys.stderr, flush=True)
        if stop_event.is_set():
            break
        wait(interval)
    return completed, errors


def format_status(scheduler: OpsInspectionScheduler) -> str:
    summary = scheduler.get_summary()
    lines = [
        f"interval_minutes={summary.interval_minutes}",
        f"in_progress={summary.in_progress}",
        f"next_run_at={summary.next_run_at.isoformat() if summary.next_run_at else 'none'}",
    ]
    if summary.latest is not None:
        latest = summary.latest
        lines.append(f"last_status={latest.status.value}")
        lines.append(f"last_trigger={latest.trigger_source.value}")
        lines.append(f"last_started_at={latest.started_at.isoformat()}")
        lines.append(f"last_new_finding_count={latest.new_finding_count}")
    else:
        lines.append("last_status=none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    scheduler = build_scheduler()
    if args.status:
        print(format_status(scheduler))
        return 0
    if args.once:
        run = scheduler.run_scheduled_once()
        print("idle" if run is None else run.model_dump_json())
        return 0

    stop_event = Event()

    def request_stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    run_loop(scheduler, args.poll_interval, stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
