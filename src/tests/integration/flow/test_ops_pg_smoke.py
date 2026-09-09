"""健康运营问题库 PG 存储活库冒烟 — issue #45。

验证 ops_findings 表 DDL（CREATE+ALTER 双写幂等）、fingerprint 唯一索引
ON CONFLICT 去重累计与过滤分页在真实 PostgreSQL 上成立。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.ops.ops_postgres import PostgresOpsFindingStorage
from src.domain.ops.models import (
    FindingDraft,
    OpsAssetType,
    OpsFindingStatus,
    OpsSeverity,
)

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
SMOKE_ASSET = "ops_pg_smoke_source"


def _pg_ready() -> bool:
    try:
        from src.data_platform.storage.postgresql.client import PostgreSQLClient

        client = PostgreSQLClient()
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL 不可用，跳过活库冒烟")


@pytest.fixture
def storage() -> PostgresOpsFindingStorage:
    return PostgresOpsFindingStorage()


@pytest.fixture(autouse=True)
def _cleanup(storage: PostgresOpsFindingStorage):
    yield
    storage._get_client().execute(
        "DELETE FROM ops_findings WHERE asset_id = %s", (SMOKE_ASSET,),
    )


def _draft(check_id: str, severity: OpsSeverity, payload: dict) -> FindingDraft:
    return FindingDraft(
        asset_type=OpsAssetType.DATA,
        asset_id=SMOKE_ASSET,
        check_id=check_id,
        severity=severity,
        payload=payload,
    )


def test_schema_idempotent_and_upsert_dedup(storage: PostgresOpsFindingStorage):
    # 二次构造触发 ensure_schema 重跑（CREATE IF NOT EXISTS + ALTER IF NOT EXISTS 幂等）
    PostgresOpsFindingStorage(client=storage._get_client())._get_client()

    first = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.WARNING, {"problem": "sync_job_degraded"}),
        seen_at=T0,
    )
    assert first.status == OpsFindingStatus.OPEN
    assert first.occurrence_count == 1

    second = storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.CRITICAL, {"problem": "sync_job_failed"}),
        seen_at=T1,
    )
    # fingerprint 唯一索引 + ON CONFLICT：同一问题累计而非新增行
    assert second.finding_id == first.finding_id
    assert second.occurrence_count == 2
    assert second.revision == 2
    assert second.first_seen_at == T0
    assert second.last_seen_at == T1
    assert second.severity is OpsSeverity.CRITICAL  # 严重度随最新证据刷新


def test_filters_and_ordering(storage: PostgresOpsFindingStorage):
    storage.upsert_finding(
        _draft("data_sync_failed", OpsSeverity.WARNING, {"problem": "sync_job_degraded"}),
        seen_at=T0,
    )
    storage.upsert_finding(
        _draft("data_source_down", OpsSeverity.CRITICAL, {"safe_probe_message": "连接超时"}),
        seen_at=T0,
    )

    critical = storage.list_findings(severity=OpsSeverity.CRITICAL, asset_type=OpsAssetType.DATA)
    assert critical.total == 1
    assert critical.items[0].check_id == "data_source_down"
    assert critical.items[0].payload["safe_probe_message"] == "连接超时"

    all_open = storage.list_findings(status=OpsFindingStatus.OPEN, page=1, page_size=1)
    assert all_open.total == 2
    assert len(all_open.items) == 1
    assert all_open.items[0].severity is OpsSeverity.CRITICAL  # critical 排序在前

    assert storage.list_findings(status=OpsFindingStatus.RESOLVED).total == 0
