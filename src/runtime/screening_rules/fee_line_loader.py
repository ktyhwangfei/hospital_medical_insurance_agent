"""从 bjyb 的 SQL Server 读取一小段历史诊次。

费用行来自 dbo.o_FeeItem，结算时间来自 dbo.o_Trade。
fee_line_id 用 ItemId 的文本，问数按这个值对上费用行。
ItemId 为空时才退回 ItemNo。
就诊上下文只在药品年龄类规则需要时读取，甲状腺组合规则不碰出生日期。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from src.data_platform.storage.screening_rules.sqlserver import bind_datetime, open_bjyb
from src.domain.screening_rules.executor import FeeLine, SettlementContext

# 问数侧用 CONVERT(nvarchar(64), ItemId) 对费用行，这里写成同一个值。
FEE_LINE_SQL = """
SELECT
    CONVERT(nvarchar(64), fi.T_TradeNo) AS settlement_key,
    COALESCE(CONVERT(nvarchar(64), fi.ItemId), CONVERT(nvarchar(64), fi.ItemNo)) AS fee_line_id,
    CONVERT(nvarchar(64), fi.ItemCode) AS item_code,
    fi.ItemName AS item_name,
    fi.Fee AS amount
FROM dbo.o_FeeItem AS fi
INNER JOIN dbo.o_Trade AS t ON t.T_TradeNo = fi.T_TradeNo
WHERE t.T_TradeDate >= ? AND t.T_TradeDate <= ?
""".strip()

TRADE_CONTEXT_SQL = """
SELECT
    CONVERT(nvarchar(64), t.T_TradeNo) AS settlement_key,
    t.T_TradeDate AS trade_date,
    t.P_Birthday AS birthday,
    CONVERT(nvarchar(32), t.P_Sex) AS sex
FROM dbo.o_Trade AS t
WHERE t.T_TradeDate >= ? AND t.T_TradeDate <= ?
""".strip()

DIAGNOSIS_SQL = """
SELECT
    CONVERT(nvarchar(64), d.T_TradeNo) AS settlement_key,
    d.DiagnoseName AS diagnose_name
FROM dbo.o_Diagnose AS d
INNER JOIN dbo.o_Trade AS t ON t.T_TradeNo = d.T_TradeNo
WHERE t.T_TradeDate >= ? AND t.T_TradeDate <= ?
""".strip()


def load_fee_lines(
    time_range_start: datetime,
    time_range_end: datetime,
    *,
    connect: Callable[[], Any] | None = None,
) -> list[FeeLine]:
    rows = _query(FEE_LINE_SQL, time_range_start, time_range_end, connect=connect)
    return [
        FeeLine(
            settlement_key=str(row["settlement_key"]),
            fee_line_id=str(row["fee_line_id"] or ""),
            item_code=None if row["item_code"] is None else str(row["item_code"]),
            item_name=str(row["item_name"] or ""),
            amount=float(row["amount"]) if row["amount"] is not None else None,
        )
        for row in rows
    ]


def load_settlement_contexts(
    time_range_start: datetime,
    time_range_end: datetime,
    *,
    connect: Callable[[], Any] | None = None,
) -> dict[str, SettlementContext]:
    """结算键 → 出生日期、性别、诊断。只给需要年龄或诊断的规则用。"""
    opener = connect or open_bjyb
    contexts: dict[str, SettlementContext] = {}
    for row in _query(TRADE_CONTEXT_SQL, time_range_start, time_range_end, connect=opener):
        key = str(row["settlement_key"])
        contexts[key] = SettlementContext(
            settlement_key=key,
            trade_date=row["trade_date"],
            birthday=row["birthday"],
            sex=None if row["sex"] is None else str(row["sex"]),
        )
    for row in _query(DIAGNOSIS_SQL, time_range_start, time_range_end, connect=opener):
        key = str(row["settlement_key"])
        name = str(row["diagnose_name"] or "").strip()
        current = contexts.get(key)
        if current is None or not name:
            continue
        contexts[key] = SettlementContext(
            settlement_key=key,
            trade_date=current.trade_date,
            birthday=current.birthday,
            sex=current.sex,
            diagnoses=(*current.diagnoses, name),
        )
    return contexts


def _query(
    sql: str,
    start: datetime,
    end: datetime,
    *,
    connect: Callable[[], Any] | None,
) -> list[dict[str, Any]]:
    conn = (connect or open_bjyb)()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, [bind_datetime(start), bind_datetime(end)])
        names = [str(col[0]).lower() for col in cursor.description]
        return [dict(zip(names, record, strict=True)) for record in cursor.fetchall()]
    finally:
        conn.close()
