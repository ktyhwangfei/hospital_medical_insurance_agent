"""Issue #80 城乡居民门诊费用分解：bjyb 库数据探查（只读）。

探查问题（决定居民内核设计细节）：
1. 居民门诊（P_FundType in 91/92/93, T_CureType='11'）交易总量、日期范围、险种分布
2. PN_PersonType 分布（对照 issue80 候选集合 14-20/50/70/80）
3. PN_NoRightReason 取值分布 + 非零时账面是否全额自费（T_FeeIn=0）
4. TB_Year 维护情况（=交易年的比例，决定年度累计口径）
5. 本院机构 H_LEVEL/H_TYPE（决定起付 100/550 档与比例 55%/50% 档）
6. 冲正/部分退费/负明细交易数量（不可用类别的规模）
7. 账面字段非零分布（T_BCPay/T_JCPay/T_OfficalPay 居民是否恒 0）
8. T_FundPay 与 T_BigPay 关系（居民 T_FundPay=T_BigPay 是否成立）

跑法：uv run python scripts/eval/issue80_data_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"


def main() -> int:
    source = get_semantic_data_source()
    conn = source.open_connection(DATASOURCE_ID)
    cur = conn.cursor()

    def q(label, sql, params=()):
        cur.execute(sql, params)
        rows = cur.fetchall()
        print(f"\n== {label} ==")
        for r in rows:
            print("  ", r)
        return rows

    q("总量与日期范围", """
        SELECT COUNT(*), MIN(T_TradeDate), MAX(T_TradeDate)
        FROM o_Trade WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
    """, [HOSPITAL_CODE])

    q("险种分布", """
        SELECT P_FundType, COUNT(*) FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
        GROUP BY P_FundType ORDER BY P_FundType
    """, [HOSPITAL_CODE])

    q("人员类别分布", """
        SELECT PN_PersonType, COUNT(*) FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
        GROUP BY PN_PersonType ORDER BY 2 DESC
    """, [HOSPITAL_CODE])

    q("PN_NoRightReason 分布", """
        SELECT PN_NoRightReason, COUNT(*),
               SUM(CASE WHEN T_FeeIn=0 THEN 1 ELSE 0 END) AS feein_zero,
               SUM(CASE WHEN T_FeeIn<>0 THEN 1 ELSE 0 END) AS feein_nonzero
        FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
        GROUP BY PN_NoRightReason ORDER BY 2 DESC
    """, [HOSPITAL_CODE])

    q("TB_Year 维护情况", """
        SELECT CASE WHEN TB_Year = YEAR(T_TradeDate) THEN 'maintained' ELSE 'not_maintained' END AS st,
               COUNT(*)
        FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
        GROUP BY CASE WHEN TB_Year = YEAR(T_TradeDate) THEN 'maintained' ELSE 'not_maintained' END
    """, [HOSPITAL_CODE])

    q("本院机构等级", """
        SELECT H_CODE, H_LEVEL, H_TYPE FROM m_institution WHERE H_CODE=?
    """, [HOSPITAL_CODE])

    q("冲正/退费/负明细", """
        SELECT
          SUM(CASE WHEN T_HasRefundmented='1' THEN 1 ELSE 0 END) AS refunded,
          SUM(CASE WHEN T_PartialReturnFlag='1' THEN 1 ELSE 0 END) AS partial_return,
          SUM(CASE WHEN T_OraginalTradeNo IS NOT NULL AND T_OraginalTradeNo<>'' THEN 1 ELSE 0 END) AS has_orig,
          COUNT(*) AS total
        FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
    """, [HOSPITAL_CODE])

    q("负明细交易数", """
        SELECT COUNT(DISTINCT t.T_TradeNo) FROM o_Trade t
        JOIN o_FeeItem f ON f.T_TradeNo = t.T_TradeNo
        WHERE t.P_FundType IN ('91','92','93') AND t.T_CureType='11' AND t.T_HospCode=?
          AND (f.Fee < 0 OR f.[Count] < 0)
    """, [HOSPITAL_CODE])

    q("补充待遇字段非零分布", """
        SELECT
          SUM(CASE WHEN T_BCPay<>0 THEN 1 ELSE 0 END) AS bc_nonzero,
          SUM(CASE WHEN T_JCPay<>0 THEN 1 ELSE 0 END) AS jc_nonzero,
          SUM(CASE WHEN T_OfficalPay<>0 THEN 1 ELSE 0 END) AS off_nonzero,
          SUM(CASE WHEN T_FundPay<>T_BigPay THEN 1 ELSE 0 END) AS fund_ne_big,
          SUM(CASE WHEN T_BigPay<>0 THEN 1 ELSE 0 END) AS big_nonzero,
          SUM(CASE WHEN T_FirstPay<>0 THEN 1 ELSE 0 END) AS first_nonzero,
          COUNT(*) AS total
        FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
    """, [HOSPITAL_CODE])

    q("样本交易快照 011100030X240408000002", """
        SELECT T_TradeNo, T_TradeDate, P_FundType, T_CureType, PN_PersonType, P_Birthday,
               PN_NoRightReason, TB_Year, TB_FeeIn, TB_BigPay,
               T_FeeAll, T_FeeIn, T_FeeOut, T_SelfPay2, T_FirstPay, T_BigPay, T_BigSelfPay,
               T_BCPay, T_JCPay, T_OfficalPay, T_SelfPay1, T_FundPay, T_SelfPayAll,
               T_PersonCountPay, T_CashPay
        FROM o_Trade WHERE T_TradeNo='011100030X240408000002'
    """)

    q("交易年份分布", """
        SELECT YEAR(T_TradeDate), COUNT(*) FROM o_Trade
        WHERE P_FundType IN ('91','92','93') AND T_CureType='11' AND T_HospCode=?
        GROUP BY YEAR(T_TradeDate) ORDER BY 1
    """, [HOSPITAL_CODE])

    q("明细行 ItemType 分布", """
        SELECT f.ItemType, COUNT(*) FROM o_FeeItem f
        JOIN o_Trade t ON t.T_TradeNo = f.T_TradeNo
        WHERE t.P_FundType IN ('91','92','93') AND t.T_CureType='11' AND t.T_HospCode=?
        GROUP BY f.ItemType ORDER BY 2 DESC
    """, [HOSPITAL_CODE])

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
