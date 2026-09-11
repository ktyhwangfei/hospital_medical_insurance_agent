"""健康运营问题库 PostgreSQL 存储 — issue #45 P0 + #50 生命周期 + #53 自动修复。

ops_findings 单表：fingerprint 唯一索引承载去重（ON CONFLICT 单语句
upsert，occurrence_count 原子累加）；ops_finding_events 追加留痕每次
ignore/reopen/resolved 流转；ops_remediation_runs 留痕每次 L1 自动修复
（动作前后证据 + 强制验证结果）；DDL 遵循 CREATE+ALTER 双写约定，旧库
加列不改表结构（AGENTS.md 已知陷阱）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.ops.models import (
    FindingDraft,
    FindingRevisionConflictError,
    OpsAssetType,
    OpsCheckerError,
    OpsFinding,
    OpsFindingEvent,
    OpsFindingEventType,
    OpsFindingNotFoundError,
    OpsFindingPage,
    OpsFindingStatus,
    OpsInspectionNotFoundError,
    OpsInspectionRun,
    OpsInspectionScheduleState,
    OpsInspectionStatus,
    OpsInspectionTrigger,
    OpsRemediationRun,
    OpsSeverity,
    RemediationRiskLevel,
    RemediationRunStatus,
    VerificationResult,
    finding_fingerprint,
    new_finding_id,
    new_inspection_id,
)

OPS_FINDINGS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops_findings (
        finding_id VARCHAR(64) PRIMARY KEY,
        asset_type VARCHAR(32) NOT NULL,
        asset_id VARCHAR(128) NOT NULL,
        check_id VARCHAR(64) NOT NULL,
        severity VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        fingerprint VARCHAR(256) NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        first_seen_at TIMESTAMPTZ NOT NULL,
        last_seen_at TIMESTAMPTZ NOT NULL,
        occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK(occurrence_count >= 1),
        diagnosis JSONB,
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1)
    )""",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS asset_id VARCHAR(128)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS check_id VARCHAR(64)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS severity VARCHAR(32)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'open'",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(256)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS occurrence_count INTEGER DEFAULT 1",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS diagnosis JSONB",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_findings_fingerprint ON ops_findings(fingerprint)",
    "CREATE INDEX IF NOT EXISTS idx_ops_findings_status ON ops_findings(status, last_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ops_findings_asset ON ops_findings(asset_type, severity)",
)

OPS_FINDING_EVENTS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops_finding_events (
        event_id VARCHAR(64) PRIMARY KEY,
        finding_id VARCHAR(64) NOT NULL,
        event_type VARCHAR(32) NOT NULL,
        actor VARCHAR(128) NOT NULL,
        reason TEXT,
        created_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE ops_finding_events ADD COLUMN IF NOT EXISTS event_id VARCHAR(64)",
    "ALTER TABLE ops_finding_events ADD COLUMN IF NOT EXISTS finding_id VARCHAR(64)",
    "ALTER TABLE ops_finding_events ADD COLUMN IF NOT EXISTS event_type VARCHAR(32)",
    "ALTER TABLE ops_finding_events ADD COLUMN IF NOT EXISTS actor VARCHAR(128)",
    "ALTER TABLE ops_finding_events ADD COLUMN IF NOT EXISTS reason TEXT",
    "ALTER TABLE ops_finding_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_ops_finding_events_finding ON ops_finding_events(finding_id, created_at)",
)

OPS_REMEDIATION_RUNS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops_remediation_runs (
        run_id VARCHAR(64) PRIMARY KEY,
        finding_id VARCHAR(64) NOT NULL,
        action VARCHAR(64) NOT NULL,
        risk_level VARCHAR(8) NOT NULL,
        status VARCHAR(32) NOT NULL,
        before_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        after_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        verification_result VARCHAR(16),
        created_by VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS run_id VARCHAR(64)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS finding_id VARCHAR(64)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS action VARCHAR(64)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS risk_level VARCHAR(8)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS status VARCHAR(32)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS before_evidence JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS after_evidence JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS verification_result VARCHAR(16)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS created_by VARCHAR(128)",
    "ALTER TABLE ops_remediation_runs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_ops_remediation_runs_finding ON ops_remediation_runs(finding_id, created_at)",
)

# #52 巡检运行记录：手动与定时统一落此表（trigger_source 区分）
OPS_INSPECTIONS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops_inspections (
        inspection_id VARCHAR(64) PRIMARY KEY,
        trigger_source VARCHAR(16) NOT NULL,
        status VARCHAR(16) NOT NULL,
        triggered_by VARCHAR(128) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        finding_count INTEGER NOT NULL DEFAULT 0,
        new_finding_count INTEGER NOT NULL DEFAULT 0,
        checker_errors JSONB NOT NULL DEFAULT '[]'::jsonb
    )""",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(16)",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS status VARCHAR(16)",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS triggered_by VARCHAR(128)",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS finding_count INTEGER DEFAULT 0",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS new_finding_count INTEGER DEFAULT 0",
    "ALTER TABLE ops_inspections ADD COLUMN IF NOT EXISTS checker_errors JSONB DEFAULT '[]'::jsonb",
    "CREATE INDEX IF NOT EXISTS idx_ops_inspections_started ON ops_inspections(started_at DESC)",
)

# #52 调度行（单行表，CHECK 约束锁死 schedule_id=1）：active_inspection_id
# 互斥位 + next_run_at 到期位，claim 用 FOR UPDATE SKIP LOCKED 抢占
OPS_INSPECTION_SCHEDULE_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops_inspection_schedule (
        schedule_id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (schedule_id = 1),
        next_run_at TIMESTAMPTZ NOT NULL,
        active_inspection_id VARCHAR(64),
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE ops_inspection_schedule ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ",
    "ALTER TABLE ops_inspection_schedule ADD COLUMN IF NOT EXISTS active_inspection_id VARCHAR(64)",
    "ALTER TABLE ops_inspection_schedule ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
)

_FINDING_COLUMNS = (
    "finding_id, asset_type, asset_id, check_id, severity, status, fingerprint, "
    "payload, first_seen_at, last_seen_at, occurrence_count, diagnosis, revision"
)

_RUN_COLUMNS = (
    "run_id, finding_id, action, risk_level, status, "
    "before_evidence, after_evidence, verification_result, created_by, created_at"
)

_INSPECTION_COLUMNS = (
    "inspection_id, trigger_source, status, triggered_by, started_at, "
    "finished_at, finding_count, new_finding_count, checker_errors"
)


def _row_to_finding(row: dict[str, Any]) -> OpsFinding:
    return OpsFinding(
        finding_id=row["finding_id"],
        asset_type=OpsAssetType(row["asset_type"]),
        asset_id=row["asset_id"],
        check_id=row["check_id"],
        severity=OpsSeverity(row["severity"]),
        status=OpsFindingStatus(row["status"]),
        fingerprint=row["fingerprint"],
        payload=row["payload"] or {},
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        occurrence_count=row["occurrence_count"],
        diagnosis=row["diagnosis"],
        revision=row["revision"],
    )


def _row_to_event(row: dict[str, Any]) -> OpsFindingEvent:
    return OpsFindingEvent(
        event_id=row["event_id"],
        finding_id=row["finding_id"],
        event_type=OpsFindingEventType(row["event_type"]),
        actor=row["actor"],
        reason=row["reason"],
        created_at=row["created_at"],
    )


def _row_to_run(row: dict[str, Any]) -> OpsRemediationRun:
    return OpsRemediationRun(
        run_id=row["run_id"],
        finding_id=row["finding_id"],
        action=row["action"],
        risk_level=RemediationRiskLevel(row["risk_level"]),
        status=RemediationRunStatus(row["status"]),
        before_evidence=row["before_evidence"] or {},
        after_evidence=row["after_evidence"] or {},
        verification_result=(
            VerificationResult(row["verification_result"])
            if row["verification_result"] else None
        ),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _row_to_inspection(row: dict[str, Any]) -> OpsInspectionRun:
    return OpsInspectionRun(
        inspection_id=row["inspection_id"],
        trigger_source=OpsInspectionTrigger(row["trigger_source"]),
        status=OpsInspectionStatus(row["status"]),
        triggered_by=row["triggered_by"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        finding_count=row["finding_count"],
        new_finding_count=row["new_finding_count"],
        checker_errors=[
            OpsCheckerError.model_validate(item) for item in (row["checker_errors"] or [])
        ],
    )


class PostgresOpsFindingStorage:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client = client
        self._schema_ensured = False

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
        if not self._schema_ensured:
            for statement in (
                *OPS_FINDINGS_TABLE_SCHEMA,
                *OPS_FINDING_EVENTS_TABLE_SCHEMA,
                *OPS_REMEDIATION_RUNS_TABLE_SCHEMA,
                *OPS_INSPECTIONS_TABLE_SCHEMA,
                *OPS_INSPECTION_SCHEDULE_TABLE_SCHEMA,
            ):
                self._client.execute(statement)
            # 调度行 bootstrap：首部署 next_run_at=now，worker 首轮即巡检
            bootstrap_at = datetime.now(timezone.utc)
            self._client.execute(
                """INSERT INTO ops_inspection_schedule (schedule_id, next_run_at, updated_at)
                   VALUES (1, %s, %s) ON CONFLICT (schedule_id) DO NOTHING""",
                (bootstrap_at, bootstrap_at),
            )
            self._schema_ensured = True
        return self._client

    def upsert_finding(self, draft: FindingDraft, *, seen_at: datetime) -> OpsFinding:
        client = self._get_client()
        fingerprint = finding_fingerprint(draft.asset_type, draft.asset_id, draft.check_id)
        rows = client.execute(
            f"""
            INSERT INTO ops_findings (
                finding_id, asset_type, asset_id, check_id, severity, status, fingerprint,
                payload, first_seen_at, last_seen_at, occurrence_count, diagnosis, revision
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint) DO UPDATE SET
                severity = EXCLUDED.severity,
                payload = EXCLUDED.payload,
                last_seen_at = EXCLUDED.last_seen_at,
                occurrence_count = ops_findings.occurrence_count + 1,
                revision = ops_findings.revision + 1
            RETURNING {_FINDING_COLUMNS}
            """,
            (
                new_finding_id(),
                draft.asset_type.value, draft.asset_id, draft.check_id,
                draft.severity.value, OpsFindingStatus.OPEN.value, fingerprint,
                json.dumps(draft.payload, ensure_ascii=False),
                seen_at, seen_at, 1, None, 1,
            ),
        )
        return _row_to_finding(rows[0])

    def list_findings(
        self,
        *,
        status: OpsFindingStatus | None = None,
        severity: OpsSeverity | None = None,
        asset_type: OpsAssetType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> OpsFindingPage:
        client = self._get_client()
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = %s")
            params.append(status.value)
        if severity is not None:
            conditions.append("severity = %s")
            params.append(severity.value)
        if asset_type is not None:
            conditions.append("asset_type = %s")
            params.append(asset_type.value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = client.execute(
            f"SELECT COUNT(*) AS total FROM ops_findings {where}", tuple(params)
        )[0]["total"]
        rows = client.execute(
            f"""
            SELECT {_FINDING_COLUMNS} FROM ops_findings {where}
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     last_seen_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params) + (page_size, (page - 1) * page_size),
        )
        return OpsFindingPage(
            items=[_row_to_finding(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_finding(self, finding_id: str) -> OpsFinding:
        rows = self._get_client().execute(
            f"SELECT {_FINDING_COLUMNS} FROM ops_findings WHERE finding_id = %s",
            (finding_id,),
        )
        if not rows:
            raise OpsFindingNotFoundError(finding_id)
        return _row_to_finding(rows[0])

    def transition_finding(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        new_status: OpsFindingStatus,
        event: OpsFindingEvent,
    ) -> OpsFinding:
        # 条件 UPDATE 承载乐观锁：revision 匹配才生效，避免「先读后写」竞态
        rows = self._get_client().execute(
            f"""
            UPDATE ops_findings SET status = %s, revision = revision + 1
            WHERE finding_id = %s AND revision = %s
            RETURNING {_FINDING_COLUMNS}
            """,
            (new_status.value, finding_id, expected_revision),
        )
        if not rows:
            current = self.get_finding(finding_id)  # 不存在则抛 NotFound
            raise FindingRevisionConflictError(finding_id, expected_revision, current.revision)
        self._get_client().execute(
            """
            INSERT INTO ops_finding_events (event_id, finding_id, event_type, actor, reason, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event.event_id,
                event.finding_id,
                event.event_type.value,
                event.actor,
                event.reason,
                event.created_at,
            ),
        )
        return _row_to_finding(rows[0])

    def list_finding_events(self, finding_id: str) -> list[OpsFindingEvent]:
        rows = self._get_client().execute(
            """
            SELECT event_id, finding_id, event_type, actor, reason, created_at
            FROM ops_finding_events WHERE finding_id = %s
            ORDER BY created_at ASC, event_id ASC
            """,
            (finding_id,),
        )
        return [_row_to_event(row) for row in rows]

    def insert_remediation_run(self, run: OpsRemediationRun) -> OpsRemediationRun:
        rows = self._get_client().execute(
            f"""
            INSERT INTO ops_remediation_runs ({_RUN_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_RUN_COLUMNS}
            """,
            (
                run.run_id,
                run.finding_id,
                run.action,
                run.risk_level.value,
                run.status.value,
                json.dumps(run.before_evidence, ensure_ascii=False),
                json.dumps(run.after_evidence, ensure_ascii=False),
                run.verification_result.value if run.verification_result else None,
                run.created_by,
                run.created_at,
            ),
        )
        return _row_to_run(rows[0])

    def list_remediation_runs(self, finding_id: str) -> list[OpsRemediationRun]:
        rows = self._get_client().execute(
            f"""
            SELECT {_RUN_COLUMNS} FROM ops_remediation_runs
            WHERE finding_id = %s
            ORDER BY created_at ASC, run_id ASC
            """,
            (finding_id,),
        )
        return [_row_to_run(row) for row in rows]

    def save_diagnosis(self, finding_id: str, diagnosis: dict[str, Any]) -> OpsFinding:
        # 诊断只读不驱动生命周期：只覆盖 diagnosis 列，不动 status/revision
        rows = self._get_client().execute(
            f"""
            UPDATE ops_findings SET diagnosis = %s
            WHERE finding_id = %s
            RETURNING {_FINDING_COLUMNS}
            """,
            (json.dumps(diagnosis, ensure_ascii=False), finding_id),
        )
        if not rows:
            raise OpsFindingNotFoundError(finding_id)
        return _row_to_finding(rows[0])

    # ── #52 定时巡检调度：claim 抢占 + 运行留痕（复用 claim_due_job 模式）──

    def claim_inspection(
        self,
        now: datetime,
        *,
        trigger_source: OpsInspectionTrigger,
        triggered_by: str,
    ) -> OpsInspectionRun | None:
        # manual 立即到期（force）；scheduled 需 next_run_at 到期。
        # FOR UPDATE SKIP LOCKED：并发/多进程抢占同一调度行时后来者直接空手而归，
        # active_inspection_id IS NULL 是第二重互斥（运行中不允许再抢）。
        force = trigger_source is OpsInspectionTrigger.MANUAL
        client = self._get_client()
        with client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT schedule_id FROM ops_inspection_schedule
                       WHERE schedule_id = 1
                         AND active_inspection_id IS NULL
                         AND (next_run_at <= %s OR %s)
                       FOR UPDATE SKIP LOCKED""",
                    (now, force),
                )
                if cursor.fetchone() is None:
                    return None
                inspection_id = new_inspection_id()
                cursor.execute(
                    """INSERT INTO ops_inspections (
                           inspection_id, trigger_source, status, triggered_by, started_at,
                           finding_count, new_finding_count, checker_errors
                       ) VALUES (%s, %s, 'running', %s, %s, 0, 0, '[]'::jsonb)""",
                    (inspection_id, trigger_source.value, triggered_by, now),
                )
                cursor.execute(
                    """UPDATE ops_inspection_schedule
                       SET active_inspection_id = %s, updated_at = %s
                       WHERE schedule_id = 1""",
                    (inspection_id, now),
                )
        return OpsInspectionRun(
            inspection_id=inspection_id,
            trigger_source=trigger_source,
            status=OpsInspectionStatus.RUNNING,
            triggered_by=triggered_by,
            started_at=now,
        )

    def complete_inspection(
        self,
        inspection_id: str,
        *,
        finished_at: datetime,
        status: OpsInspectionStatus,
        finding_count: int,
        new_finding_count: int,
        checker_errors: list[OpsCheckerError],
        next_run_at: datetime,
    ) -> OpsInspectionRun:
        client = self._get_client()
        with client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE ops_inspections SET
                           status = %s, finished_at = %s, finding_count = %s,
                           new_finding_count = %s, checker_errors = %s
                       WHERE inspection_id = %s""",
                    (
                        status.value, finished_at, finding_count, new_finding_count,
                        json.dumps(
                            [error.model_dump() for error in checker_errors],
                            ensure_ascii=False,
                        ),
                        inspection_id,
                    ),
                )
                cursor.execute(
                    """UPDATE ops_inspection_schedule SET
                           active_inspection_id = NULL, next_run_at = %s, updated_at = %s
                       WHERE active_inspection_id = %s""",
                    (next_run_at, finished_at, inspection_id),
                )
        return self.get_inspection(inspection_id)

    def get_inspection(self, inspection_id: str) -> OpsInspectionRun:
        rows = self._get_client().execute(
            f"SELECT {_INSPECTION_COLUMNS} FROM ops_inspections WHERE inspection_id = %s",
            (inspection_id,),
        )
        if not rows:
            raise OpsInspectionNotFoundError(inspection_id)
        return _row_to_inspection(rows[0])

    def get_latest_inspection(self) -> OpsInspectionRun | None:
        rows = self._get_client().execute(
            f"""SELECT {_INSPECTION_COLUMNS} FROM ops_inspections
                ORDER BY started_at DESC, inspection_id DESC LIMIT 1""",
        )
        return _row_to_inspection(rows[0]) if rows else None

    def get_inspection_schedule(self) -> OpsInspectionScheduleState:
        rows = self._get_client().execute(
            """SELECT next_run_at, active_inspection_id FROM ops_inspection_schedule
               WHERE schedule_id = 1""",
        )
        return OpsInspectionScheduleState(
            next_run_at=rows[0]["next_run_at"],
            active_inspection_id=rows[0]["active_inspection_id"],
        )
