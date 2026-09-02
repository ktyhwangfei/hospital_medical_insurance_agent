"""单院门诊 SQL Server CDC 只读源。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from src.adapters.insurance_interface.outpatient_source import (
    OUTPATIENT_SOURCE_SPECS,
    CheckpointKind,
    OutpatientChange,
    OutpatientCheckpoint,
    OutpatientSourceBatch,
    OutpatientSourceMode,
    OutpatientSourceSpec,
)


class CdcRetentionGapError(RuntimeError):
    error_code = "cdc_retention_gap"


class SourceContractMismatchError(RuntimeError):
    error_code = "source_contract_mismatch"


@dataclass(frozen=True)
class OutpatientCdcProbe:
    status: str
    database_enabled: bool
    ready_captures: tuple[str, ...]
    missing_captures: tuple[str, ...]
    retention_minutes: int | None
    safe_message: str
    checked_at: datetime


class SqlServerOutpatientCdcSource:
    """固定读取 bjyb 三张门诊源表及其 CDC capture instance。"""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def read(self, checkpoint: OutpatientCheckpoint | None) -> OutpatientSourceBatch:
        if checkpoint is None:
            return self._read_snapshot()
        if checkpoint.kind is not CheckpointKind.LSN:
            raise ValueError("CDC source requires an LSN checkpoint")
        return self._read_changes(bytes.fromhex(checkpoint.value))

    def probe_cdc(self) -> OutpatientCdcProbe:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            database_enabled = bool(self._read_scalar(
                cursor,
                "SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME()",
            ))
            if not database_enabled:
                return _cdc_probe(
                    status="waiting_dba",
                    database_enabled=False,
                    safe_message="数据库尚未开启 CDC",
                )
            cursor.execute(
                """SELECT ct.capture_instance, captured.column_name
                   FROM cdc.change_tables AS ct
                   JOIN cdc.captured_columns AS captured ON captured.object_id = ct.object_id
                   WHERE ct.capture_instance IN (?, ?, ?)""",
                *OUTPATIENT_SOURCE_SPECS,
            )
            captured_columns: dict[str, set[str]] = {}
            for row in self._rows_as_dicts(cursor):
                captured_columns.setdefault(row["capture_instance"], set()).add(
                    row["column_name"]
                )
            ready = tuple(sorted(
                capture
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
                if captured_columns.get(capture) == set(spec.columns)
            ))
            missing = tuple(sorted(set(OUTPATIENT_SOURCE_SPECS) - set(captured_columns)))
            retention = self._read_scalar(
                cursor,
                """SELECT retention FROM msdb.dbo.cdc_jobs
                   WHERE database_id = DB_ID() AND job_type = N'cleanup'""",
            )
            if len(ready) == len(OUTPATIENT_SOURCE_SPECS) and retention == 4320:
                return _cdc_probe(
                    status="ready",
                    database_enabled=True,
                    ready_captures=ready,
                    retention_minutes=retention,
                    safe_message="CDC 已按受控模板开通",
                )
            return _cdc_probe(
                status="invalid",
                database_enabled=True,
                ready_captures=ready,
                missing_captures=missing,
                retention_minutes=retention,
                safe_message="CDC 配置与受控模板不一致",
            )
        except Exception:
            return _cdc_probe(
                status="invalid",
                database_enabled=False,
                safe_message="CDC 状态检查失败",
            )
        finally:
            connection.close()

    def _read_snapshot(self) -> OutpatientSourceBatch:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            self._validate_source_contract(cursor)
            checkpoint_lsn = self._read_scalar(
                cursor, "SELECT sys.fn_cdc_get_max_lsn() AS max_lsn"
            )
            self._read_min_lsns(cursor)
            rows_by_capture = {
                capture: tuple(self._read_current_rows(cursor, spec))
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
            }
            return OutpatientSourceBatch(
                mode=OutpatientSourceMode.CDC,
                checkpoint=_lsn_checkpoint(checkpoint_lsn),
                snapshot_rows=rows_by_capture,
                is_baseline=True,
            )
        finally:
            connection.close()

    def _read_changes(self, last_lsn: bytes) -> OutpatientSourceBatch:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            self._validate_source_contract(cursor)
            min_lsn_by_capture = self._read_min_lsns(cursor)
            gaps = self._retention_gaps(last_lsn, min_lsn_by_capture)
            if gaps:
                raise CdcRetentionGapError(
                    "cdc_retention_gap: checkpoint is older than " + ", ".join(gaps)
                )
            from_lsn = self._read_scalar(
                cursor, "SELECT sys.fn_cdc_increment_lsn(?) AS from_lsn", last_lsn
            )
            to_lsn = self._read_scalar(
                cursor, "SELECT sys.fn_cdc_get_max_lsn() AS max_lsn"
            )
            changes: list[OutpatientChange] = []
            if from_lsn <= to_lsn:
                try:
                    for spec in OUTPATIENT_SOURCE_SPECS.values():
                        changes.extend(self._read_capture(cursor, spec, from_lsn, to_lsn))
                except Exception as exc:
                    current_min_lsns = self._read_min_lsns(cursor)
                    gaps = self._retention_gaps(last_lsn, current_min_lsns)
                    if gaps:
                        raise CdcRetentionGapError(
                            "cdc_retention_gap: checkpoint is older than " + ", ".join(gaps)
                        ) from exc
                    raise
            changes.sort(key=lambda item: (item.source_cursor, item.capture_instance))
            return OutpatientSourceBatch(
                mode=OutpatientSourceMode.CDC,
                checkpoint=_lsn_checkpoint(to_lsn),
                changes=tuple(changes),
            )
        finally:
            connection.close()

    @staticmethod
    def _validate_source_contract(cursor) -> None:
        table_names = tuple(spec.table_name for spec in OUTPATIENT_SOURCE_SPECS.values())
        cursor.execute(
            """SELECT TABLE_NAME, COLUMN_NAME
               FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = ? AND TABLE_NAME IN (?, ?, ?)""",
            "dbo", *table_names,
        )
        available: dict[str, set[str]] = {table: set() for table in table_names}
        for table_name, column_name in cursor.fetchall():
            available.setdefault(table_name, set()).add(column_name)
        missing = [
            f"{spec.table_name}.{column}"
            for spec in OUTPATIENT_SOURCE_SPECS.values()
            for column in spec.columns
            if column not in available.get(spec.table_name, set())
        ]
        if missing:
            raise SourceContractMismatchError(
                "source_contract_mismatch: missing " + ", ".join(missing)
            )

    @staticmethod
    def _read_scalar(cursor, sql: str, *params):
        cursor.execute(sql, *params)
        row = cursor.fetchone()
        if row is None or row[0] is None:
            raise SourceContractMismatchError("source_contract_mismatch: CDC LSN unavailable")
        return row[0]

    def _read_min_lsns(self, cursor) -> dict[str, bytes]:
        return {
            capture: self._read_scalar(
                cursor, "SELECT sys.fn_cdc_get_min_lsn(?) AS min_lsn", capture
            )
            for capture in OUTPATIENT_SOURCE_SPECS
        }

    @staticmethod
    def _retention_gaps(last_lsn: bytes, min_lsn_by_capture: dict[str, bytes]) -> list[str]:
        return [
            capture for capture, min_lsn in min_lsn_by_capture.items()
            if last_lsn < min_lsn
        ]

    @staticmethod
    def _read_current_rows(cursor, spec: OutpatientSourceSpec) -> list[dict[str, Any]]:
        columns = ", ".join(f"[{column}]" for column in spec.columns)
        cursor.execute(f"SELECT {columns} FROM [dbo].[{spec.table_name}]")
        return SqlServerOutpatientCdcSource._rows_as_dicts(cursor)

    @staticmethod
    def _read_capture(
        cursor,
        spec: OutpatientSourceSpec,
        from_lsn: bytes,
        to_lsn: bytes,
    ) -> list[OutpatientChange]:
        columns = ", ".join(f"[{column}]" for column in spec.columns)
        cursor.execute(
            f"""SELECT [__$start_lsn] AS start_lsn,
                       [__$seqval] AS seqval,
                       [__$operation] AS operation,
                       sys.fn_cdc_map_lsn_to_time([__$start_lsn]) AS commit_time,
                       {columns}
                FROM cdc.fn_cdc_get_all_changes_{spec.capture_instance}(?, ?, N'all')
                WHERE [__$operation] IN (1, 2, 4)
                ORDER BY [__$start_lsn], [__$seqval], [__$operation]""",
            from_lsn, to_lsn,
        )
        changes = []
        for row in SqlServerOutpatientCdcSource._rows_as_dicts(cursor):
            operation = int(row["operation"])
            if operation not in {1, 2, 4}:
                continue
            payload = {column: row.get(column) for column in spec.columns}
            changes.append(OutpatientChange(
                capture_instance=spec.capture_instance,
                source_cursor=row["start_lsn"] + row["seqval"],
                operation=operation,
                commit_time=row.get("commit_time"),
                source_key=tuple(payload[column] for column in spec.key_columns),
                payload=payload,
            ))
        return changes

    @staticmethod
    def _rows_as_dicts(cursor) -> list[dict[str, Any]]:
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def _lsn_checkpoint(value: bytes) -> OutpatientCheckpoint:
    return OutpatientCheckpoint(
        kind=CheckpointKind.LSN,
        value=value.hex(),
        observed_at=datetime.now(timezone.utc),
    )


def _cdc_probe(
    *,
    status: str,
    database_enabled: bool,
    safe_message: str,
    ready_captures: tuple[str, ...] = (),
    missing_captures: tuple[str, ...] = (),
    retention_minutes: int | None = None,
) -> OutpatientCdcProbe:
    return OutpatientCdcProbe(
        status=status,
        database_enabled=database_enabled,
        ready_captures=ready_captures,
        missing_captures=missing_captures,
        retention_minutes=retention_minutes,
        safe_message=safe_message,
        checked_at=datetime.now(timezone.utc),
    )
