"""门诊 CDC 事件、当前投影与原子发布批次存储。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from src.adapters.insurance_interface.outpatient_cdc import (
    OUTPATIENT_SOURCE_SPECS,
    OutpatientCdcChange,
)
from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient


_TRADE_DIRECT_COLUMNS = {
    "T_TradeNo": "trade_no",
    "T_TradeDate": "trade_date",
    "T_State": "trade_state",
    "P_FundType": "fund_type",
    "PN_PersonType": "person_type",
    "T_CureType": "cure_type",
    "T_HospCode": "hospital_code",
    "T_FeeAll": "fee_all",
    "T_FeeIn": "fee_in",
    "T_FeeOut": "fee_out",
    "T_FundPay": "fund_pay",
    "T_SelfPayAll": "self_pay_all",
    "T_SelfPay1": "self_pay_1",
    "T_SelfPay2": "self_pay_2",
    "T_BigSelfPay": "big_self_pay",
    "T_FirstPay": "first_pay",
    "T_PersonCountPay": "person_account_pay",
    "T_CashPay": "cash_pay",
}
_FEE_DIRECT_COLUMNS = {
    "T_TradeNo": "trade_no", "ItemId": "item_id", "ItemNo": "item_no",
    "ItemCode": "item_code", "StandardCode": "standard_code", "ItemName": "item_name",
    "ItemType": "item_type", "FeeType": "fee_type", "F_LEVEL": "fee_level",
    "Count": "item_count", "Fee": "fee", "FeeIn": "fee_in", "FeeOut": "fee_out",
    "SelfPay2": "self_pay_2", "State": "item_state",
}
_TRADE_TIMESTAMP_FIELDS = {"T_TradeDate", "T_OraginalTradeDate", "SETL_DATE"}
_TRADE_NUMERIC_FIELDS = {
    "T_FirstPay", "T_SelfPay1", "T_SelfPay2", "T_SelfPayAll", "T_BigPay",
    "T_BigSelfPay", "T_BeyondBig", "T_FundPay", "T_PersonCountPay", "T_CashPay",
    "PN_PersonCount", "T_PersonCountAfter", "T_BCPay", "T_JCPay", "T_FeeAll",
    "T_FeeIn", "T_FeeOut", "T_OfficalPay", "T_BigillPay", "NT_BasicPay",
    "NT_CivilPay", "NT_OtherPay", "NT_AgencySumPay", "RETIRE_OFFICER_PAY",
    "NT_OUT2_PRICE", "TB_FeeIn", "TA_FeeIn", "TB_BigPay", "TA_BigPay",
    "TB_FeeAfterBig", "TA_FeeAfterBig", "TB_BeyondFeeIn", "TA_BeyondFeeIn",
    "TB_BigillComm", "TA_BigillComm", "TB_BigillPay", "TA_BigillPay",
    "TB_CivilComm", "TA_CivilComm", "TB_CivilPay", "TA_CivilPay", "TB_FeeInL1",
    "TA_FeeInL1", "TB_BigPayL1", "TA_BigPayL1", "TB_FeeAfterBigL1",
    "TA_FeeAfterBigL1", "TB_MZTimes", "TA_MZTimes", "NT_OUT2_SCALE",
}
_FEE_NUMERIC_FIELDS = {
    "Count", "UnitPrice", "Fee", "FeeIn", "FeeOut", "SelfPay2", "FEE_SP_SCALE",
    "FEE_MEDIC_L", "MEDIC_L",
}


def _view_field(table_alias: str, column: str, direct: dict[str, str], numeric: set[str], timestamps: set[str]) -> str:
    if column in direct:
        expression = f'{table_alias}.{direct[column]}'
    elif column in numeric:
        expression = f"NULLIF({table_alias}.payload ->> '{column}', '')::NUMERIC"
    elif column in timestamps:
        expression = f"NULLIF({table_alias}.payload ->> '{column}', '')::TIMESTAMP"
    else:
        expression = f"{table_alias}.payload ->> '{column}'"
    return f'{expression} AS "{column}"'


def _build_trade_view() -> str:
    columns = [
        column for column in OUTPATIENT_SOURCE_SPECS["dbo_o_Trade"].columns
        if column not in {"PN_InsuredAreaCode", "T_HospCodeA"}
    ]
    fields = [
        _view_field("trade", column, _TRADE_DIRECT_COLUMNS, _TRADE_NUMERIC_FIELDS, _TRADE_TIMESTAMP_FIELDS)
        for column in columns
    ]
    fields.extend([
        "trade.data_batch_id", "trade.source_lsn", "trade.semantic_version",
        "trade.quality_status", "trade.context_quality", "trade.settlement_chain_id",
        "trade.settlement_lifecycle",
    ])
    return "CREATE OR REPLACE VIEW mz_trade AS\nSELECT\n    " + ",\n    ".join(fields) + (
        "\nFROM outpatient_trade_current AS trade\nWHERE NOT is_deleted"
    )


def _build_fee_view() -> str:
    fields = [
        _view_field("fee_item", column, _FEE_DIRECT_COLUMNS, _FEE_NUMERIC_FIELDS, set())
        for column in OUTPATIENT_SOURCE_SPECS["dbo_o_FeeItem"].columns
    ]
    fields.extend(["fee_item.data_batch_id", "fee_item.source_lsn", "fee_item.semantic_version"])
    return "CREATE OR REPLACE VIEW mz_fee_item AS\nSELECT\n    " + ",\n    ".join(fields) + (
        "\nFROM outpatient_fee_item_current AS fee_item\nWHERE NOT is_deleted"
    )


OUTPATIENT_SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS outpatient_sync_checkpoints (
        source_id VARCHAR(64) PRIMARY KEY,
        last_lsn BYTEA NOT NULL,
        last_batch_id VARCHAR(64) NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_sync_batches (
        batch_id VARCHAR(64) PRIMARY KEY,
        source_id VARCHAR(64) NOT NULL,
        mode VARCHAR(32) NOT NULL CHECK(mode IN ('snapshot', 'incremental', 'heartbeat')),
        from_lsn BYTEA NOT NULL,
        to_lsn BYTEA NOT NULL,
        semantic_version VARCHAR(32),
        source_committed_at TIMESTAMPTZ,
        published_at TIMESTAMPTZ NOT NULL,
        row_count INTEGER NOT NULL CHECK(row_count >= 0),
        quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        UNIQUE(source_id, from_lsn, to_lsn, mode)
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_cdc_events (
        source_id VARCHAR(64) NOT NULL,
        capture_instance VARCHAR(128) NOT NULL,
        start_lsn BYTEA NOT NULL,
        seqval BYTEA NOT NULL,
        operation INTEGER NOT NULL CHECK(operation IN (1, 2, 4)),
        commit_time TIMESTAMPTZ,
        source_key JSONB NOT NULL,
        payload JSONB NOT NULL,
        data_batch_id VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(source_id, capture_instance, start_lsn, seqval, operation)
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_trade_current (
        trade_no TEXT PRIMARY KEY,
        trade_date TIMESTAMP,
        trade_state TEXT,
        fund_type TEXT,
        person_type TEXT,
        cure_type TEXT,
        hospital_code TEXT,
        fee_all NUMERIC,
        fee_in NUMERIC,
        fee_out NUMERIC,
        fund_pay NUMERIC,
        self_pay_all NUMERIC,
        self_pay_1 NUMERIC,
        self_pay_2 NUMERIC,
        big_self_pay NUMERIC,
        first_pay NUMERIC,
        person_account_pay NUMERIC,
        cash_pay NUMERIC,
        payload JSONB NOT NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        source_lsn BYTEA NOT NULL,
        source_seqval BYTEA NOT NULL,
        source_operation INTEGER NOT NULL,
        data_batch_id VARCHAR(64) NOT NULL,
        semantic_version VARCHAR(32),
        quality_status VARCHAR(32) NOT NULL DEFAULT 'complete',
        context_quality VARCHAR(32),
        settlement_chain_id TEXT,
        settlement_lifecycle VARCHAR(32),
        diagnosis_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        section_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        section_names JSONB NOT NULL DEFAULT '[]'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_fee_item_current (
        trade_no TEXT NOT NULL,
        item_id TEXT NOT NULL,
        item_no TEXT NOT NULL,
        item_code TEXT,
        standard_code TEXT,
        item_name TEXT,
        item_type TEXT,
        fee_type TEXT,
        fee_level TEXT,
        item_count NUMERIC,
        fee NUMERIC,
        fee_in NUMERIC,
        fee_out NUMERIC,
        self_pay_2 NUMERIC,
        item_state TEXT,
        payload JSONB NOT NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        source_lsn BYTEA NOT NULL,
        source_seqval BYTEA NOT NULL,
        source_operation INTEGER NOT NULL,
        data_batch_id VARCHAR(64) NOT NULL,
        semantic_version VARCHAR(32),
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(trade_no, item_id, item_no)
    )""",
    """CREATE TABLE IF NOT EXISTS outpatient_diagnosis_current (
        trade_no TEXT NOT NULL,
        diagnose_no TEXT NOT NULL,
        recipe_no TEXT NOT NULL,
        recipe_date TIMESTAMP,
        diagnose_name TEXT,
        diagnose_code TEXT,
        section_code TEXT,
        section_name TEXT,
        his_section_name TEXT,
        diagnose_type TEXT,
        payload JSONB NOT NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        source_lsn BYTEA NOT NULL,
        source_seqval BYTEA NOT NULL,
        source_operation INTEGER NOT NULL,
        data_batch_id VARCHAR(64) NOT NULL,
        semantic_version VARCHAR(32),
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(trade_no, diagnose_no, recipe_no)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_outpatient_events_batch ON outpatient_cdc_events(data_batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_outpatient_fee_trade ON outpatient_fee_item_current(trade_no)",
    "CREATE INDEX IF NOT EXISTS idx_outpatient_diagnosis_trade ON outpatient_diagnosis_current(trade_no)",
    "ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS semantic_version VARCHAR(32) NOT NULL DEFAULT '1'",
    "ALTER TABLE outpatient_sync_batches ALTER COLUMN semantic_version DROP NOT NULL",
    "ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS source_committed_at TIMESTAMPTZ",
    "ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS quality_status VARCHAR(32) NOT NULL DEFAULT 'complete'",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS context_quality VARCHAR(32)",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS settlement_chain_id TEXT",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS settlement_lifecycle VARCHAR(32)",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS diagnosis_codes JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS section_codes JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS section_names JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE outpatient_trade_current ALTER COLUMN semantic_version DROP NOT NULL",
    "ALTER TABLE outpatient_fee_item_current ALTER COLUMN semantic_version DROP NOT NULL",
    "ALTER TABLE outpatient_diagnosis_current ALTER COLUMN semantic_version DROP NOT NULL",
    _build_trade_view(),
    _build_fee_view(),
)


@dataclass(frozen=True)
class PublishedOutpatientBatch:
    batch_id: str
    published_at: datetime
    row_count: int


@dataclass(frozen=True)
class OutpatientSyncCheckpoint:
    source_id: str
    last_lsn: bytes
    last_batch_id: str
    updated_at: datetime


class OutpatientPostgresStore:
    def __init__(
        self,
        database_url: str | None = None,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._client = client or PostgreSQLClient(database_url or DATABASE_URL)
        self._schema_ready = False

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        for statement in OUTPATIENT_SCHEMA_STATEMENTS:
            self._client.execute(statement)
        self._schema_ready = True

    def check_schema(self) -> bool:
        rows = self._client.execute(
            """SELECT COUNT(*) AS present
               FROM unnest(ARRAY[
                   'outpatient_sync_checkpoints', 'outpatient_sync_batches',
                   'outpatient_cdc_events', 'outpatient_trade_current',
                   'outpatient_fee_item_current', 'outpatient_diagnosis_current',
                   'mz_trade', 'mz_fee_item'
               ]) AS expected(name)
               WHERE to_regclass(expected.name) IS NOT NULL"""
        )
        return bool(rows and int(rows[0]["present"]) == 8)

    def get_checkpoint(self, source_id: str) -> OutpatientSyncCheckpoint | None:
        self.ensure_schema()
        rows = self._client.execute(
            """SELECT source_id, last_lsn, last_batch_id, updated_at
               FROM outpatient_sync_checkpoints WHERE source_id = %s""",
            (source_id,),
        )
        return OutpatientSyncCheckpoint(**rows[0]) if rows else None

    def load_projection_rows(
        self, trade_nos: set[str]
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        """读取受影响交易及同链事实，供下一批确定性重算。"""
        if not trade_nos:
            return {capture: () for capture in OUTPATIENT_SOURCE_SPECS}
        requested = sorted(trade_nos)
        trade_rows = self._client.execute(
            """SELECT payload FROM outpatient_trade_current
               WHERE NOT is_deleted
                 AND (trade_no = ANY(%s) OR payload ->> 'T_OraginalTradeNo' = ANY(%s))""",
            (requested, requested),
        )
        trades = tuple(_payload(row["payload"]) for row in trade_rows)
        chain_trade_nos = sorted({
            str(row.get("T_TradeNo")) for row in trades if row.get("T_TradeNo") is not None
        } | set(requested))
        fee_rows = self._client.execute(
            """SELECT payload FROM outpatient_fee_item_current
               WHERE NOT is_deleted AND trade_no = ANY(%s)""",
            (chain_trade_nos,),
        )
        diagnosis_rows = self._client.execute(
            """SELECT payload FROM outpatient_diagnosis_current
               WHERE NOT is_deleted AND trade_no = ANY(%s)""",
            (chain_trade_nos,),
        )
        return {
            "dbo_o_Trade": trades,
            "dbo_o_FeeItem": tuple(_payload(row["payload"]) for row in fee_rows),
            "dbo_o_Diagnose": tuple(_payload(row["payload"]) for row in diagnosis_rows),
        }

    def publish_batch(
        self,
        *,
        source_id: str,
        mode: str,
        from_lsn: bytes,
        to_lsn: bytes,
        semantic_version: str | None,
        changes: tuple[OutpatientCdcChange, ...],
        quality_summary: dict[str, Any],
        projection_metadata: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] | None = None,
    ) -> PublishedOutpatientBatch:
        self.ensure_schema()
        batch_id = str(uuid4())
        published_at = datetime.now(timezone.utc)
        source_committed_at = max(
            (change.commit_time for change in changes if change.commit_time is not None),
            default=None,
        )
        projection_metadata = projection_metadata or {}
        with self._client.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"outpatient-sync:{source_id}",),
                )
                cursor.execute(
                    """SELECT batch_id, published_at, row_count
                       FROM outpatient_sync_batches
                       WHERE source_id = %s AND from_lsn = %s AND to_lsn = %s AND mode = %s""",
                    (source_id, from_lsn, to_lsn, mode),
                )
                existing = cursor.fetchone()
                if existing:
                    return PublishedOutpatientBatch(
                        batch_id=existing[0], published_at=existing[1], row_count=existing[2]
                    )
                for change in changes:
                    self._insert_event(cursor, source_id, batch_id, change)
                    metadata = projection_metadata.get(
                        (change.capture_instance, change.source_key), {}
                    )
                    self._upsert_projection(
                        cursor, batch_id, semantic_version, quality_summary, change, metadata
                    )
                for (capture_instance, source_key), metadata in projection_metadata.items():
                    if capture_instance == "dbo_o_Trade" and source_key:
                        self._update_trade_metadata(
                            cursor, str(source_key[0]), batch_id, semantic_version, metadata
                        )
                cursor.execute(
                    """INSERT INTO outpatient_sync_batches
                       (batch_id, source_id, mode, from_lsn, to_lsn, semantic_version,
                        source_committed_at, row_count, quality_summary, published_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
                    (
                        batch_id, source_id, mode, from_lsn, to_lsn, semantic_version,
                        source_committed_at, len(changes), _json_dumps(quality_summary), published_at,
                    ),
                )
                cursor.execute(
                    """INSERT INTO outpatient_sync_checkpoints
                       (source_id, last_lsn, last_batch_id, updated_at)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (source_id) DO UPDATE SET
                           last_lsn = EXCLUDED.last_lsn,
                           last_batch_id = EXCLUDED.last_batch_id,
                           updated_at = EXCLUDED.updated_at
                       WHERE EXCLUDED.last_lsn >= outpatient_sync_checkpoints.last_lsn""",
                    (source_id, to_lsn, batch_id, published_at),
                )
        return PublishedOutpatientBatch(
            batch_id=batch_id, published_at=published_at, row_count=len(changes)
        )

    @staticmethod
    def _insert_event(cursor, source_id: str, batch_id: str, change: OutpatientCdcChange) -> None:
        cursor.execute(
            """INSERT INTO outpatient_cdc_events
               (source_id, capture_instance, start_lsn, seqval, operation, commit_time,
                source_key, payload, data_batch_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
               ON CONFLICT (source_id, capture_instance, start_lsn, seqval, operation) DO NOTHING""",
            (
                source_id, change.capture_instance, change.start_lsn, change.seqval,
                change.operation, change.commit_time, _json_dumps(change.source_key),
                _json_dumps(change.payload), batch_id,
            ),
        )

    def _upsert_projection(
        self,
        cursor,
        batch_id: str,
        semantic_version: str,
        quality_summary: dict[str, Any],
        change: OutpatientCdcChange,
        metadata: dict[str, Any],
    ) -> None:
        if metadata.get("skip_projection"):
            return
        if change.capture_instance == "dbo_o_Trade":
            self._upsert_trade(
                cursor, batch_id, semantic_version, quality_summary, change, metadata
            )
        elif change.capture_instance == "dbo_o_FeeItem":
            self._upsert_fee_item(cursor, batch_id, semantic_version, change)
        elif change.capture_instance == "dbo_o_Diagnose":
            self._upsert_diagnosis(cursor, batch_id, semantic_version, change)
        else:
            raise ValueError(f"unsupported capture instance: {change.capture_instance}")

    @staticmethod
    def _update_trade_metadata(
        cursor,
        trade_no: str,
        batch_id: str,
        semantic_version: str | None,
        metadata: dict[str, Any],
    ) -> None:
        cursor.execute(
            """UPDATE outpatient_trade_current SET
                   data_batch_id = %s, semantic_version = %s, quality_status = %s,
                   context_quality = %s, settlement_chain_id = %s,
                   settlement_lifecycle = %s, diagnosis_codes = %s::jsonb,
                   section_codes = %s::jsonb, section_names = %s::jsonb,
                   updated_at = %s
               WHERE trade_no = %s""",
            (
                batch_id, semantic_version, metadata.get("quality_status", "complete"),
                metadata.get("context_quality"), metadata.get("settlement_chain_id"),
                metadata.get("settlement_lifecycle"),
                _json_dumps(metadata.get("diagnosis_codes", [])),
                _json_dumps(metadata.get("section_codes", [])),
                _json_dumps(metadata.get("section_names", [])),
                datetime.now(timezone.utc), trade_no,
            ),
        )

    @staticmethod
    def _upsert_trade(cursor, batch_id, semantic_version, quality_summary, change, metadata) -> None:
        payload = change.payload
        cursor.execute(
            """INSERT INTO outpatient_trade_current
               (trade_no, trade_date, trade_state, fund_type, person_type, cure_type,
                hospital_code, fee_all, fee_in, fee_out, fund_pay, self_pay_all,
                self_pay_1, self_pay_2, big_self_pay, first_pay, person_account_pay,
                cash_pay, payload, is_deleted, source_lsn, source_seqval, source_operation,
                data_batch_id, semantic_version, quality_status, context_quality,
                settlement_chain_id, settlement_lifecycle, diagnosis_codes,
                section_codes, section_names, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
               ON CONFLICT (trade_no) DO UPDATE SET
                   trade_date=EXCLUDED.trade_date, trade_state=EXCLUDED.trade_state,
                   fund_type=EXCLUDED.fund_type, person_type=EXCLUDED.person_type,
                   cure_type=EXCLUDED.cure_type, hospital_code=EXCLUDED.hospital_code,
                   fee_all=EXCLUDED.fee_all, fee_in=EXCLUDED.fee_in, fee_out=EXCLUDED.fee_out,
                   fund_pay=EXCLUDED.fund_pay, self_pay_all=EXCLUDED.self_pay_all,
                   self_pay_1=EXCLUDED.self_pay_1, self_pay_2=EXCLUDED.self_pay_2,
                   big_self_pay=EXCLUDED.big_self_pay, first_pay=EXCLUDED.first_pay,
                   person_account_pay=EXCLUDED.person_account_pay, cash_pay=EXCLUDED.cash_pay,
                   payload=EXCLUDED.payload, is_deleted=EXCLUDED.is_deleted,
                   source_lsn=EXCLUDED.source_lsn, source_seqval=EXCLUDED.source_seqval,
                   source_operation=EXCLUDED.source_operation, data_batch_id=EXCLUDED.data_batch_id,
                   semantic_version=EXCLUDED.semantic_version, quality_status=EXCLUDED.quality_status,
                   context_quality=EXCLUDED.context_quality,
                   settlement_chain_id=EXCLUDED.settlement_chain_id,
                   settlement_lifecycle=EXCLUDED.settlement_lifecycle,
                   diagnosis_codes=EXCLUDED.diagnosis_codes,
                   section_codes=EXCLUDED.section_codes, section_names=EXCLUDED.section_names,
                   updated_at=EXCLUDED.updated_at
               WHERE (EXCLUDED.source_lsn, EXCLUDED.source_seqval) >=
                     (outpatient_trade_current.source_lsn, outpatient_trade_current.source_seqval)""",
            (
                _text(payload.get("T_TradeNo")), payload.get("T_TradeDate"),
                _text(payload.get("T_State")), _text(payload.get("P_FundType")),
                _text(payload.get("PN_PersonType")), _text(payload.get("T_CureType")),
                _text(payload.get("T_HospCode")), payload.get("T_FeeAll"),
                payload.get("T_FeeIn"), payload.get("T_FeeOut"), payload.get("T_FundPay"),
                payload.get("T_SelfPayAll"), payload.get("T_SelfPay1"),
                payload.get("T_SelfPay2"), payload.get("T_BigSelfPay"),
                payload.get("T_FirstPay"), payload.get("T_PersonCountPay"),
                payload.get("T_CashPay"), _json_dumps(payload), change.operation == 1,
                change.start_lsn, change.seqval, change.operation, batch_id, semantic_version,
                metadata.get("quality_status", quality_summary.get("status", "complete")),
                metadata.get("context_quality"), metadata.get("settlement_chain_id"),
                metadata.get("settlement_lifecycle"),
                _json_dumps(metadata.get("diagnosis_codes", [])),
                _json_dumps(metadata.get("section_codes", [])),
                _json_dumps(metadata.get("section_names", [])), datetime.now(timezone.utc),
            ),
        )

    @staticmethod
    def _upsert_fee_item(cursor, batch_id, semantic_version, change) -> None:
        payload = change.payload
        cursor.execute(
            """INSERT INTO outpatient_fee_item_current
               (trade_no, item_id, item_no, item_code, standard_code, item_name, item_type,
                fee_type, fee_level, item_count, fee, fee_in, fee_out, self_pay_2, item_state,
                payload, is_deleted, source_lsn, source_seqval, source_operation,
                data_batch_id, semantic_version, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (trade_no, item_id, item_no) DO UPDATE SET
                   item_code=EXCLUDED.item_code, standard_code=EXCLUDED.standard_code,
                   item_name=EXCLUDED.item_name, item_type=EXCLUDED.item_type,
                   fee_type=EXCLUDED.fee_type, fee_level=EXCLUDED.fee_level,
                   item_count=EXCLUDED.item_count, fee=EXCLUDED.fee,
                   fee_in=EXCLUDED.fee_in, fee_out=EXCLUDED.fee_out,
                   self_pay_2=EXCLUDED.self_pay_2, item_state=EXCLUDED.item_state,
                   payload=EXCLUDED.payload, is_deleted=EXCLUDED.is_deleted,
                   source_lsn=EXCLUDED.source_lsn, source_seqval=EXCLUDED.source_seqval,
                   source_operation=EXCLUDED.source_operation, data_batch_id=EXCLUDED.data_batch_id,
                   semantic_version=EXCLUDED.semantic_version, updated_at=EXCLUDED.updated_at
               WHERE (EXCLUDED.source_lsn, EXCLUDED.source_seqval) >=
                     (outpatient_fee_item_current.source_lsn, outpatient_fee_item_current.source_seqval)""",
            (
                _text(payload.get("T_TradeNo")), _text(payload.get("ItemId")),
                _text(payload.get("ItemNo")), _text(payload.get("ItemCode")),
                _text(payload.get("StandardCode")), _text(payload.get("ItemName")),
                _text(payload.get("ItemType")), _text(payload.get("FeeType")),
                _text(payload.get("F_LEVEL")), payload.get("Count"), payload.get("Fee"),
                payload.get("FeeIn"), payload.get("FeeOut"), payload.get("SelfPay2"),
                _text(payload.get("State")), _json_dumps(payload), change.operation == 1,
                change.start_lsn, change.seqval, change.operation, batch_id, semantic_version,
                datetime.now(timezone.utc),
            ),
        )

    @staticmethod
    def _upsert_diagnosis(cursor, batch_id, semantic_version, change) -> None:
        payload = change.payload
        cursor.execute(
            """INSERT INTO outpatient_diagnosis_current
               (trade_no, diagnose_no, recipe_no, recipe_date, diagnose_name, diagnose_code,
                section_code, section_name, his_section_name, diagnose_type, payload, is_deleted,
                source_lsn, source_seqval, source_operation, data_batch_id, semantic_version,
                updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                       %s, %s, %s, %s)
               ON CONFLICT (trade_no, diagnose_no, recipe_no) DO UPDATE SET
                   recipe_date=EXCLUDED.recipe_date, diagnose_name=EXCLUDED.diagnose_name,
                   diagnose_code=EXCLUDED.diagnose_code, section_code=EXCLUDED.section_code,
                   section_name=EXCLUDED.section_name, his_section_name=EXCLUDED.his_section_name,
                   diagnose_type=EXCLUDED.diagnose_type, payload=EXCLUDED.payload,
                   is_deleted=EXCLUDED.is_deleted, source_lsn=EXCLUDED.source_lsn,
                   source_seqval=EXCLUDED.source_seqval,
                   source_operation=EXCLUDED.source_operation, data_batch_id=EXCLUDED.data_batch_id,
                   semantic_version=EXCLUDED.semantic_version, updated_at=EXCLUDED.updated_at
               WHERE (EXCLUDED.source_lsn, EXCLUDED.source_seqval) >=
                     (outpatient_diagnosis_current.source_lsn, outpatient_diagnosis_current.source_seqval)""",
            (
                _text(payload.get("T_TradeNo")), _text(payload.get("DiagnoseNo")),
                _text(payload.get("RecipeNo")), payload.get("RecipeDate"),
                _text(payload.get("DiagnoseName")), _text(payload.get("DiagnoseCode")),
                _text(payload.get("SectionCode")), _text(payload.get("Sectionname")),
                _text(payload.get("HISSectionName")), _text(payload.get("DiagnoseType")),
                _json_dumps(payload), change.operation == 1, change.start_lsn, change.seqval,
                change.operation, batch_id, semantic_version, datetime.now(timezone.utc),
            ),
        )


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    raise TypeError("outpatient projection payload must be a JSON object")
