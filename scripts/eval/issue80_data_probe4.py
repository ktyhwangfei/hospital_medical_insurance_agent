"""Issue #80 第四轮探查：NT_* 渠道列分布 + 240914 组渠道归属。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402


def main() -> int:
    conn = get_semantic_data_source().open_connection("bjybdb")
    cur = conn.cursor()

    def q(label, sql, params=()):
        print(f"== {label} ==")
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        for r in cur.fetchall():
            print("  ", dict(zip(cols, (str(v) for v in r))))

    q("59 笔 NT_* 渠道列非零分布", """
        SELECT
          SUM(CASE WHEN NT_CivilPay IS NOT NULL AND NT_CivilPay <> 0 THEN 1 ELSE 0 END) AS civil_nonzero,
          SUM(CASE WHEN NT_BasicPay IS NOT NULL AND NT_BasicPay <> 0 THEN 1 ELSE 0 END) AS basic_nonzero,
          SUM(CASE WHEN NT_AgencySumPay IS NOT NULL AND NT_AgencySumPay <> 0 THEN 1 ELSE 0 END) AS agency_nonzero,
          SUM(CASE WHEN NT_OtherPay IS NOT NULL AND NT_OtherPay <> 0 THEN 1 ELSE 0 END) AS other_nonzero,
          SUM(CASE WHEN T_BigillPay IS NOT NULL AND T_BigillPay <> 0 THEN 1 ELSE 0 END) AS bigill_nonzero,
          COUNT(*) AS total
        FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_HospCode = '01110003'
    """)

    q("NT_CivilPay 非零交易清单 + 渠道归属", """
        SELECT T_TradeNo, T_CureType, PN_PersonType, T_FeeAll, T_FeeIn, T_FeeOut,
               T_BigPay, NT_CivilPay, T_FundPay, T_SelfPayAll, TB_BigPay, TB_CivilPay, TA_CivilPay,
               P_CivilFlag, PN_NoRightReason
        FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_HospCode = '01110003'
          AND NT_CivilPay IS NOT NULL AND NT_CivilPay <> 0
        ORDER BY T_TradeNo
    """)

    q("240914 组渠道归属（NT_CivilPay?）", """
        SELECT T_TradeNo, T_BigPay, NT_CivilPay, NT_BasicPay, T_FundPay, TB_CivilPay, TA_CivilPay,
               TB_BigillComm, TB_CivilComm, P_CivilFlag, P_CivilType
        FROM o_Trade
        WHERE T_TradeNo IN ('011100030X240914000002','011100030X240914000003','011100030X240914000004')
    """)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
