"""Issue #80 第二轮探查：xb 列填充率、职工集采行 SP_SCALE、职工 zfbl 空行数。"""
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

    def q(label, sql):
        print(f"== {label} ==")
        cur.execute(sql)
        for r in cur.fetchall():
            print("  ", r)

    q("yb_xzzlfwxm 的 xb 列填充情况", """
        SELECT CASE WHEN xb IS NULL THEN 'null' WHEN xb > 0 THEN 'gt0' ELSE 'zero' END AS st,
               COUNT(*)
        FROM yb_xzzlfwxm
        GROUP BY CASE WHEN xb IS NULL THEN 'null' WHEN xb > 0 THEN 'gt0' ELSE 'zero' END
    """)

    q("职工81笔集采超限价行的 SP_SCALE/MEDIC_L 与账面", """
        SELECT f.SP_SCALE, f.MEDIC_L, f.UnitPrice, c.A_mzxj, f.Fee, f.FeeIn, f.FeeOut, f.SelfPay2
        FROM o_FeeItem f
        JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
        JOIN yb_ypzdml c ON c.ypbm = f.ItemCode AND t.T_TradeDate >= c.sxrq AND t.T_TradeDate <= c.jzrq
        WHERE t.P_FundType = '3' AND t.T_CureType = '11' AND t.T_HospCode = '01110003'
          AND c.A_ypbs = '1' AND c.A_mzxj > 0 AND f.UnitPrice > c.A_mzxj
    """)

    q("职工81笔 ItemType=1/2 且 sfxmdj=2 且 zfbl空 的行数", """
        SELECT COUNT(*)
        FROM o_FeeItem f
        JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
        JOIN yb_xzzlfwxm c ON c.xmbm = f.ItemCode
        WHERE t.P_FundType = '3' AND t.T_CureType = '11' AND t.T_HospCode = '01110003'
          AND f.ItemType IN ('1', '2') AND c.sfxmdj = '2' AND (c.zfbl IS NULL OR c.zfbl = '')
    """)

    q("居民59笔中药品 SP_SCALE>0 的行（限价事实）", """
        SELECT f.T_TradeNo, f.ItemName, f.UnitPrice, f.[Count], f.Fee, f.FeeIn, f.FeeOut,
               f.SelfPay2, f.MEDIC_L, f.SP_SCALE, c.A_ypbs, c.A_mzxj, c.zfbl
        FROM o_FeeItem f
        JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
        LEFT JOIN yb_ypzdml c ON c.ypbm = f.ItemCode
        WHERE t.P_FundType IN ('91','92','93') AND t.T_HospCode = '01110003'
          AND f.ItemType = '0' AND f.SP_SCALE > 0
        ORDER BY f.T_TradeNo
    """)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
