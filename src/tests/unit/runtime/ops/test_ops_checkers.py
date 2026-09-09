"""健康运营检查器单元测试 — issue #45（数据域首批，只读判定路径）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.adapters.insurance_interface.outpatient_source import OutpatientSourceMode
from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_governance_store import (
    OutpatientGovernanceNotFoundError,
)
from src.domain.ops.models import OpsAssetType, OpsSeverity
from src.runtime.ops.checkers import OPS_CHECKS, check_data_source, check_data_sync

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _source(status: ConnectionStatus = ConnectionStatus.HEALTHY) -> OutpatientDataSource:
    return OutpatientDataSource(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database="bjybdb",
        username="readonly",
        credential_id="credential.bjybdb",
        connection_status=status,
        cdc_status=CdcEnablementStatus.WAITING_DBA,
        safe_probe_message="探测失败：连接超时" if status is ConnectionStatus.ERROR else None,
        last_probed_at=NOW if status is ConnectionStatus.ERROR else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _job(status: SyncJobStatus, **overrides) -> OutpatientSyncJob:
    defaults = dict(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=status,
        schedule_interval_minutes=5,
        next_run_at=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )
    defaults.update(overrides)
    return OutpatientSyncJob(**defaults)


class _Reader:
    def __init__(self, sources, jobs):
        self._sources = sources
        self._jobs = jobs

    def list_sources(self):
        return list(self._sources)

    def get_job(self, source_id):
        if source_id not in self._jobs:
            raise OutpatientGovernanceNotFoundError(f"job {source_id}")
        return self._jobs[source_id]


class TestDataSyncChecker:
    def test_failed_job_critical(self):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.FAILED, last_error_code="SOURCE_TIMEOUT")})
        drafts = check_data_sync(reader, NOW)
        assert len(drafts) == 1
        assert drafts[0].severity is OpsSeverity.CRITICAL
        assert drafts[0].check_id == "data_sync_failed"
        assert drafts[0].payload["job_status"] == "failed"
        assert drafts[0].payload["last_error_code"] == "SOURCE_TIMEOUT"

    def test_degraded_job_warning(self):
        reader = _Reader([_source()], {"bjybdb": _job(SyncJobStatus.DEGRADED)})
        drafts = check_data_sync(reader, NOW)
        assert len(drafts) == 1
        assert drafts[0].severity is OpsSeverity.WARNING
        assert drafts[0].payload["problem"] == "sync_job_degraded"

    def test_lagging_job_warning_beyond_grace(self):
        # 调度间隔 5 分钟 → 宽限 max(10, 15)=15 分钟；应到时间落后 20 分钟
        job = _job(SyncJobStatus.READY, next_run_at=NOW - timedelta(minutes=20))
        reader = _Reader([_source()], {"bjybdb": job})
        drafts = check_data_sync(reader, NOW)
        assert len(drafts) == 1
        assert drafts[0].severity is OpsSeverity.WARNING
        assert drafts[0].payload["problem"] == "sync_job_lagging"
        assert drafts[0].payload["grace_minutes"] == 15

    def test_grace_scales_with_schedule_interval(self):
        # 调度间隔 60 分钟 → 宽限 120 分钟；落后 60 分钟未超宽限不算滞后
        job = _job(
            SyncJobStatus.RUNNING,
            schedule_interval_minutes=60,
            next_run_at=NOW - timedelta(minutes=60),
        )
        reader = _Reader([_source()], {"bjybdb": job})
        assert check_data_sync(reader, NOW) == []

    def test_run_once_request_overrides_schedule(self):
        job = _job(
            SyncJobStatus.READY,
            run_once_requested_at=NOW - timedelta(minutes=30),
            next_run_at=NOW + timedelta(minutes=5),
        )
        reader = _Reader([_source()], {"bjybdb": job})
        drafts = check_data_sync(reader, NOW)
        assert len(drafts) == 1
        assert drafts[0].payload["problem"] == "sync_job_lagging"

    def test_healthy_and_paused_no_finding(self):
        reader = _Reader(
            [_source()],
            {"bjybdb": _job(SyncJobStatus.PAUSED, next_run_at=NOW - timedelta(hours=3))},
        )
        assert check_data_sync(reader, NOW) == []

    def test_source_without_job_skipped(self):
        reader = _Reader([_source()], {})
        assert check_data_sync(reader, NOW) == []


class TestDataSourceChecker:
    def test_connection_error_critical_with_safe_message(self):
        reader = _Reader([_source(ConnectionStatus.ERROR)], {})
        drafts = check_data_source(reader, NOW)
        assert len(drafts) == 1
        assert drafts[0].severity is OpsSeverity.CRITICAL
        assert drafts[0].check_id == "data_source_down"
        assert drafts[0].payload["safe_probe_message"] == "探测失败：连接超时"
        assert drafts[0].asset_type is OpsAssetType.DATA

    def test_healthy_and_unknown_no_finding(self):
        reader = _Reader([_source(ConnectionStatus.HEALTHY), _source(ConnectionStatus.UNKNOWN)], {})
        assert check_data_source(reader, NOW) == []


class TestRegistry:
    def test_p0_registry_two_data_checks(self):
        assert [spec.check_id for spec in OPS_CHECKS] == ["data_sync_failed", "data_source_down"]
        assert all(spec.asset_type is OpsAssetType.DATA for spec in OPS_CHECKS)
