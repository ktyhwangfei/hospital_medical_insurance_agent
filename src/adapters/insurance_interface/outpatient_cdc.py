"""单院门诊 SQL Server CDC 只读源。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


def _columns(value: str) -> tuple[str, ...]:
    return tuple(value.split(","))


@dataclass(frozen=True)
class OutpatientSourceSpec:
    table_name: str
    capture_instance: str
    key_columns: tuple[str, ...]
    columns: tuple[str, ...]


OUTPATIENT_SOURCE_SPECS = {
    "dbo_o_Trade": OutpatientSourceSpec(
        table_name="o_Trade",
        capture_instance="dbo_o_Trade",
        key_columns=("T_TradeNo",),
        columns=_columns(
            "T_SetTid,T_TradeNo,T_TradeDate,T_State,T_HasRefundmented,T_PartialReturnFlag,"
            "T_OraginalTradeNo,T_OraginalTradeDate,NP_Settle_State,SETL_DATE,NT_ReTradeFlag,"
            "T_DiagType,T_FeeNo,P_FundType,PN_PersonType,T_CureType,P_JCLevel,P_HospFlag,"
            "PN_OutTransaction,PN_NationFundType,PN_ChronicFlag,PN_ChronicCode,"
            "PN_IsChronicHosp,P_Official,P_retirementflag,P_CivilFlag,P_CivilType,"
            "RETIRE_OFFICER_FLAG,T_GFBelongFlag,T_CompHospFlag,T_SpSetlFlag,T_pneno,"
            "NT_AllSelfPayFlag,PN_NoRightReason,T_FeeAll,T_FeeIn,T_FeeOut,T_FirstPay,"
            "T_SelfPay1,T_SelfPay2,T_SelfPayAll,T_BigPay,T_BigSelfPay,T_BeyondBig,T_FundPay,"
            "T_PersonCountPay,T_CashPay,PN_PersonCount,T_PersonCountAfter,T_BCPay,T_JCPay,"
            "T_OfficalPay,T_BigillPay,NT_BasicPay,NT_CivilPay,NT_OtherPay,NT_AgencySumPay,"
            "RETIRE_OFFICER_PAY,NT_OUT2_SCALE,NT_OUT2_PRICE,TB_FeeIn,TA_FeeIn,TB_BigPay,"
            "TA_BigPay,TB_FeeAfterBig,TA_FeeAfterBig,TB_MZTimes,TA_MZTimes,TB_BeyondFeeIn,"
            "TA_BeyondFeeIn,TB_BigillComm,TA_BigillComm,TB_BigillPay,TA_BigillPay,"
            "TB_CivilComm,TA_CivilComm,TB_CivilPay,TA_CivilPay,TB_FeeInL1,TA_FeeInL1,"
            "TB_BigPayL1,TA_BigPayL1,TB_FeeAfterBigL1,TA_FeeAfterBigL1,PN_InsuredAreaCode,"
            "T_HospCode,T_HospCodeA"
        ),
    ),
    "dbo_o_FeeItem": OutpatientSourceSpec(
        table_name="o_FeeItem",
        capture_instance="dbo_o_FeeItem",
        key_columns=("T_TradeNo", "ItemId", "ItemNo"),
        columns=_columns(
            "T_TradeNo,ItemId,ItemNo,ItemCode,StandardCode,ItemName,ItemType,FeeType,F_LEVEL,"
            "Count,UnitPrice,Fee,FeeIn,FeeOut,SelfPay2,FEE_SP_SCALE,FEE_MEDIC_L,MEDIC_L,"
            "SPEDRUG_FLAG,State"
        ),
    ),
    "dbo_o_Diagnose": OutpatientSourceSpec(
        table_name="o_Diagnose",
        capture_instance="dbo_o_Diagnose",
        key_columns=("T_TradeNo", "DiagnoseNo", "RecipeNo"),
        columns=_columns(
            "T_TradeNo,DiagnoseNo,RecipeNo,RecipeDate,DiagnoseName,DiagnoseCode,SectionCode,"
            "Sectionname,HISSectionName,DiagnoseType"
        ),
    ),
}


class CdcRetentionGapError(RuntimeError):
    error_code = "cdc_retention_gap"


class SourceContractMismatchError(RuntimeError):
    error_code = "source_contract_mismatch"


@dataclass(frozen=True)
class OutpatientSnapshot:
    checkpoint_lsn: bytes
    min_lsn_by_capture: dict[str, bytes]
    rows_by_capture: dict[str, tuple[dict[str, Any], ...]]


@dataclass(frozen=True)
class OutpatientCdcChange:
    capture_instance: str
    start_lsn: bytes
    seqval: bytes
    operation: int
    commit_time: datetime | None
    source_key: tuple[Any, ...]
    payload: dict[str, Any]


@dataclass(frozen=True)
class OutpatientCdcBatch:
    from_lsn: bytes
    to_lsn: bytes
    min_lsn_by_capture: dict[str, bytes]
    changes: tuple[OutpatientCdcChange, ...]


class SqlServerOutpatientCdcSource:
    """固定读取 bjyb 三张门诊源表及其 CDC capture instance。"""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def read_snapshot(self) -> OutpatientSnapshot:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            self._validate_source_contract(cursor)
            checkpoint_lsn = self._read_scalar(
                cursor, "SELECT sys.fn_cdc_get_max_lsn() AS max_lsn"
            )
            min_lsn_by_capture = self._read_min_lsns(cursor)
            rows_by_capture = {
                capture: tuple(self._read_current_rows(cursor, spec))
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
            }
            return OutpatientSnapshot(
                checkpoint_lsn=checkpoint_lsn,
                min_lsn_by_capture=min_lsn_by_capture,
                rows_by_capture=rows_by_capture,
            )
        finally:
            connection.close()

    def read_changes(self, last_lsn: bytes) -> OutpatientCdcBatch:
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
            changes: list[OutpatientCdcChange] = []
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
            changes.sort(key=lambda item: (item.start_lsn, item.seqval, item.capture_instance))
            return OutpatientCdcBatch(
                from_lsn=from_lsn,
                to_lsn=to_lsn,
                min_lsn_by_capture=min_lsn_by_capture,
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
    ) -> list[OutpatientCdcChange]:
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
            changes.append(OutpatientCdcChange(
                capture_instance=spec.capture_instance,
                start_lsn=row["start_lsn"],
                seqval=row["seqval"],
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
