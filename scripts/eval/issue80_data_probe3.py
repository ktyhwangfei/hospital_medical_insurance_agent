"""Issue #80 第三轮探查：5975/6969 全字段账面 + 240914 组同患者历史。"""
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
            print("  ", dict(zip(cols, r)))

    q("5975 与 6969 全部账面列", """
        SELECT * FROM o_Trade WHERE T_TradeNo IN ('011100030X260416005975','011100030X260416006969')
    """)

    q("5975 明细行", """
        SELECT ItemId, ItemCode, ItemName, ItemType, UnitPrice, [Count], Fee, FeeIn, FeeOut,
               SelfPay2, MEDIC_L, SP_SCALE
        FROM o_FeeItem WHERE T_TradeNo = '011100030X260416005975'
    """)

    q("240914 组患者（PN=17）同年全部交易（门诊大额封顶轨迹）", """
        SELECT T_TradeNo, T_CureType, T_TradeDate, TB_FeeIn, TB_BigPay, T_FeeAll, T_FeeIn,
               T_BigPay, T_FundPay, T_SelfPayAll, PN_NoRightReason
        FROM o_Trade
        WHERE P_FundType = '92' AND PN_PersonType = '17' AND T_HospCode = '01110003'
        ORDER BY T_TradeDate
    """)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
