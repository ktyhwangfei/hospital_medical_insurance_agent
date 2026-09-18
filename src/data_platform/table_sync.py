"""选表同步（Selected Table Sync）：探查后选择表的全量直通同步通道。

定位（架构设计 V3.0 数据接入阶段）：与门诊定制契约管道（o_Trade 三表 +
定制落地 mz_trade/mz_fee_item + 质量门）并行的**通用通道**——
探查画像后人工选表，源表全列直通落地 PG 同名表，供数据建模/加工消费。

边界（冻结）：
- 全量覆盖策略（快照替换，单事务）；增量/CDC 由 CDC 通道承接（占位）；
- 只读源库，不在源库执行任何 DDL；
- 落地表名 = 源表名小写；列类型按 sys.types 映射（int/money→数值，datetime→时间戳，其余文本）；
- 落地表仅供治理链路消费，不回写。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field

_IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_@$#]{0,127}$"


class SyncTableStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class SyncMode(StrEnum):
    """同步模式：incremental 需 time_column；无时间字段降级 full（限频日同步）。"""

    FULL = "full"
    INCREMENTAL = "incremental"


class SyncPurpose(StrEnum):
    """落地目的：governed（默认，可建模可消费）/ reference（裸对照，禁止建模）。"""

    GOVERNED = "governed"
    REFERENCE = "reference"


class SelectedSyncTable(BaseModel):
    """一张选中同步表的配置（实体）。"""

    source_id: str = Field(min_length=1, max_length=64)
    table_name: str = Field(pattern=_IDENTIFIER)
    target_table: str = Field(pattern=_IDENTIFIER)
    key_columns: list[str] = Field(default_factory=list)
    time_column: Optional[str] = None
    sync_mode: SyncMode = SyncMode.FULL
    lookback_minutes: int = Field(default=5, ge=0, le=1440)
    purpose: SyncPurpose = SyncPurpose.GOVERNED
    status: SyncTableStatus = SyncTableStatus.ACTIVE
    revision: int = Field(default=1, ge=1)
    updated_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    last_row_count: Optional[int] = None
    last_error: Optional[str] = None
    last_watermark: Optional[str] = None

    @property
    def effective_mode(self) -> SyncMode:
        """无时间字段的表强制降级全量（增量无从谈起）。"""
        if self.sync_mode is SyncMode.INCREMENTAL and not self.time_column:
            return SyncMode.FULL
        return self.sync_mode


class TableSyncRunResult(BaseModel):
    table_name: str
    target_table: str
    row_count: int
    duration_ms: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# SQL Server sys.types → PG 落地列类型（直通映射，宁宽勿窄）
_PG_TYPE_MAP = {
    "int": "BIGINT",
    "bigint": "BIGINT",
    "smallint": "INTEGER",
    "tinyint": "INTEGER",
    "numeric": "NUMERIC",
    "decimal": "NUMERIC",
    "money": "NUMERIC",
    "smallmoney": "NUMERIC",
    "float": "DOUBLE PRECISION",
    "real": "DOUBLE PRECISION",
    "datetime": "TIMESTAMP",
    "datetime2": "TIMESTAMP",
    "smalldatetime": "TIMESTAMP",
    "date": "DATE",
    "bit": "BOOLEAN",
}


def pg_column_type(sqlserver_type: str) -> str:
    return _PG_TYPE_MAP.get(sqlserver_type.lower(), "TEXT")


def quote_ident(name: str) -> str:
    """PG 标识符双引号（列名保留大小写，裸引用会被折叠小写）。"""
    return '"' + name.replace('"', '""') + '"'
