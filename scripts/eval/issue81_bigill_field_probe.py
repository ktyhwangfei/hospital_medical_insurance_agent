"""BIG_ILL_SUM_IN / BigillComm 字段口径实证：同人连续交易差分验证。"""
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

    # 张同新（6969/5975 同一卡号）2026 年全部门诊交易的大病字段差分
    q("张同新 2026 门诊交易 BigillComm 轨迹（交易前/后）", """
        SELECT T_TradeNo, T_TradeDate, T_CureType, T_FeeAll, T_FeeIn, T_FeeOut,
               T_SelfPay2, T_BigPay, T_FundPay, NT_CivilPay,
               TB_BigillComm, TA_BigillComm, TB_BigillPay, TA_BigillPay,
               TB_CivilComm, TA_CivilComm, TB_CivilPay, TA_CivilPay
        FROM o_Trade
        WHERE P_ICNo = '10390788801S'
        ORDER BY T_TradeDate, T_TradeNo
    """)

    # 688/690/703 患者（门特登记）的登记身份列（kh/sfz）与门诊交易关联验证
    q("688/690/703 登记身份列", """
        SELECT djh, kh, cblb, FUND_TYPE, tsbqsrq, tsbjzrq FROM yb_brdjxx
        WHERE djh IN ('688','690','703','610','718')
    """)

    # 688 患者（kh 关联）的门诊交易是否也有 BigillComm 轨迹
    q("688 患者门诊交易（按 kh 关联）", """
        SELECT t.T_TradeNo, t.T_TradeDate, t.T_FeeAll, t.T_FeeIn, t.T_FundPay,
               t.TB_BigillComm, t.TA_BigillComm, t.TB_BigillPay, t.TA_BigillPay
        FROM o_Trade t
        WHERE t.P_ICNo IN (SELECT b.kh FROM yb_brdjxx b WHERE b.djh IN ('688','690','703'))
        ORDER BY t.T_TradeDate
    """)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
