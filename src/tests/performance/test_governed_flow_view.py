"""Issue #65 Phase 4：已部署 Governed Flow View 的真实 PG 性能基准。"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.data_platform.storage.flow.flow_view_reader import PostgresFlowViewReader
from src.data_platform.storage.postgresql.client import PostgreSQLClient


VIEW_NAME = "v_flow_flow_op_outpatient_processed"
COLUMNS = ["op_valid_settle_count", "op_total_fee", "op_fund_pay", "op_self_pay"]
P95_THRESHOLD_MS = 300
SEQUENTIAL_SAMPLES = 30
CONCURRENT_WORKERS = 10
SAMPLES_PER_WORKER = 5


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * percentile / 100) - 1)]


@pytest.fixture(scope="module")
def pg_view_ready():
    client = PostgreSQLClient()
    try:
        exists = client.execute(
            "SELECT to_regclass(%s) AS view_name",
            (f"public.{VIEW_NAME}",),
        )[0]["view_name"]
    except Exception as exc:
        pytest.skip(f"PostgreSQL/View 不可用：{exc}")
    finally:
        client.close()
    if exists is None:
        pytest.skip(f"View 不存在：{VIEW_NAME}")


def _timed_read(reader: PostgresFlowViewReader) -> float:
    started = time.perf_counter()
    reader.read(VIEW_NAME, COLUMNS)
    return (time.perf_counter() - started) * 1000


def _concurrent_worker() -> list[float]:
    client = PostgreSQLClient()
    reader = PostgresFlowViewReader(client)
    try:
        reader.read(VIEW_NAME, COLUMNS)  # 排除连接建立时间，只测查询热路径
        return [_timed_read(reader) for _ in range(SAMPLES_PER_WORKER)]
    finally:
        client.close()


def test_governed_flow_view_p95_under_readonly_threshold(pg_view_ready):
    """View 查询满足只读 P95 300ms，作为是否物化的唯一第一道证据。"""
    sequential_client = PostgreSQLClient()
    sequential_reader = PostgresFlowViewReader(sequential_client)
    try:
        sequential_reader.read(VIEW_NAME, COLUMNS)
        sequential = [
            _timed_read(sequential_reader) for _ in range(SEQUENTIAL_SAMPLES)
        ]
    finally:
        sequential_client.close()

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        concurrent = [
            sample
            for worker_samples in executor.map(
                lambda _: _concurrent_worker(), range(CONCURRENT_WORKERS)
            )
            for sample in worker_samples
        ]

    metrics = {
        "sequential_p50_ms": _percentile(sequential, 50),
        "sequential_p95_ms": _percentile(sequential, 95),
        "concurrent_p50_ms": _percentile(concurrent, 50),
        "concurrent_p95_ms": _percentile(concurrent, 95),
        "concurrency": CONCURRENT_WORKERS,
        "samples": len(concurrent),
    }
    print(f"\n[Issue #65 Phase 4] {metrics}")
    assert metrics["sequential_p95_ms"] <= P95_THRESHOLD_MS
    assert metrics["concurrent_p95_ms"] <= P95_THRESHOLD_MS
