"""Issue #78 数据探针：为批量评估卡点决策取证（只读，一次性）。

探查问题：
Q1 o_FeeItem.ItemType 取值分布 + 各取值编码在药品/诊疗目录的命中率（决定非药品分流）
Q2 药品目录 sflb 与明细 FeeType 真实取值分布（决定 CLASSIFICATION_UNKNOWN 映射）
Q3 o_Trade.TB_FeeIn 口径验证：同人同年按日期排序后 TB_FeeIn[n] 是否等于此前 T_FeeIn 累计
Q4 o_Trade 是否存在基金累计类列（TB_FundPay 等）；T_JCPay/T_OfficalPay/T_BCPay 非零率
Q5 交易年度分布与 PN_PersonType 分布（在职/退休、年龄档）
"""
from __future__ import annotations

import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"


def fetch_all(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    rows = cur.fetchall()
    cur.close()
    return rows


def main() -> int:
    source = get_semantic_data_source()
    conn = source.open_connection(DATASOURCE_ID)
    try:
        print("== Q1a ItemType 分布（职工普通门诊 81 笔的明细） ==")
        rows = fetch_all(conn, """
            SELECT f.ItemType, COUNT(*) FROM o_FeeItem f
            JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
            WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
            GROUP BY f.ItemType""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  ItemType={r[0]!r}: {r[1]}")

        print("\n== Q1b 非0 ItemType 编码在 yb_xzzlfwxm（诊疗目录）命中率 ==")
        rows = fetch_all(conn, """
            SELECT f.ItemType, COUNT(DISTINCT f.ItemCode),
                   SUM(CASE WHEN x.xmbm IS NULL THEN 0 ELSE 1 END),
                   COUNT(DISTINCT f.ItemCode) - SUM(CASE WHEN x.xmbm IS NULL THEN 0 ELSE 1 END)
            FROM (SELECT DISTINCT f.ItemType, f.ItemCode FROM o_FeeItem f
                  JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
                  WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?) f
            LEFT JOIN yb_xzzlfwxm x ON f.ItemCode = x.xmbm
            GROUP BY f.ItemType""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  ItemType={r[0]!r}: distinct_codes={r[1]} 命中诊疗目录={r[2]} 未命中={r[3]}")

        print("\n== Q1c ItemType=0 编码在 yb_ypzdml（药品目录）命中率 ==")
        rows = fetch_all(conn, """
            SELECT COUNT(DISTINCT f.ItemCode),
                   SUM(CASE WHEN y.ypbm IS NULL THEN 0 ELSE 1 END)
            FROM (SELECT DISTINCT f.ItemCode FROM o_FeeItem f
                  JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
                  WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
                    AND f.ItemType = '0') f
            LEFT JOIN yb_ypzdml y ON f.ItemCode = y.ypbm""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  distinct_codes={r[0]} 命中药品目录={r[1]}")

        print("\n== Q2a 药品目录 sflb 取值分布（被本批命中的编码，按费用发生日有效版本） ==")
        rows = fetch_all(conn, """
            SELECT y.sflb, COUNT(*) FROM yb_ypzdml y
            WHERE y.ypbm IN (SELECT DISTINCT f.ItemCode FROM o_FeeItem f
                  JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
                  WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
                    AND f.ItemType='0')
            GROUP BY y.sflb""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  sflb={r[0]!r}: {r[1]}")

        print("\n== Q2b 明细 FeeType 取值分布（按 ItemType） ==")
        rows = fetch_all(conn, """
            SELECT f.ItemType, f.FeeType, COUNT(*) FROM o_FeeItem f
            JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
            WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
            GROUP BY f.ItemType, f.FeeType""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  ItemType={r[0]!r} FeeType={r[1]!r}: {r[2]}")

        print("\n== Q2c 诊疗目录 sfxmdj 取值分布（全表） ==")
        rows = fetch_all(conn, "SELECT sfxmdj, COUNT(*) FROM yb_xzzlfwxm GROUP BY sfxmdj")
        for r in rows:
            print(f"  sfxmdj={r[0]!r}: {r[1]} (全表)")

        print("\n== Q2d 本批命中诊疗编码的 sfxmdj/zfbl 分布 ==")
        rows = fetch_all(conn, """
            SELECT x.sfxmdj, x.zfbl, COUNT(*) FROM yb_xzzlfwxm x
            WHERE x.xmbm IN (SELECT DISTINCT f.ItemCode FROM o_FeeItem f
                  JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
                  WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
                    AND f.ItemType IN ('1','2','3'))
            GROUP BY x.sfxmdj, x.zfbl""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  sfxmdj={r[0]!r} zfbl={r[1]!r}: {r[2]}")

        print("\n== Q2e 本批命中药品编码的 sflb/zfbl 分布 ==")
        rows = fetch_all(conn, """
            SELECT y.sflb, y.zfbl, COUNT(*) FROM yb_ypzdml y
            WHERE y.ypbm IN (SELECT DISTINCT f.ItemCode FROM o_FeeItem f
                  JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
                  WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
                    AND f.ItemType='0')
            GROUP BY y.sflb, y.zfbl""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  sflb={r[0]!r} zfbl={r[1]!r}: {r[2]}")

        print("\n== Q2f 药品目录版本有效期（空截止日期比例） ==")
        rows = fetch_all(conn, """
            SELECT SUM(CASE WHEN jzrq IS NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sxrq IS NULL THEN 1 ELSE 0 END), COUNT(*)
            FROM yb_ypzdml y
            WHERE y.ypbm IN (SELECT DISTINCT f.ItemCode FROM o_FeeItem f
                  JOIN o_Trade t ON f.T_TradeNo = t.T_TradeNo
                  WHERE t.P_FundType='3' AND t.T_CureType='11' AND t.T_HospCode=?
                    AND f.ItemType='0')""", [HOSPITAL_CODE])
        r = rows[0]
        print(f"  空截止={r[0]} 空生效={r[1]} 总行={r[2]}")
        rows = fetch_all(conn, """
            SELECT SUM(CASE WHEN jzrq IS NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sxrq IS NULL THEN 1 ELSE 0 END), COUNT(*)
            FROM yb_xzzlfwxm""")
        r = rows[0]
        print(f"  诊疗目录：空截止={r[0]} 空生效={r[1]} 总行={r[2]}")

        print("\n== Q3 TB_FeeIn 口径验证：同人同年（按交易日期年份、全医疗类别）逐笔检查 ==")
        rows = fetch_all(conn, """
            SELECT P_ICNo, T_TradeNo, T_TradeDate, T_CureType,
                   TB_FeeIn, T_FeeIn, TB_BigPay, T_BigPay, TB_Year
            FROM o_Trade
            WHERE P_FundType='3' AND T_HospCode=?
            ORDER BY P_ICNo, T_TradeDate, T_TradeNo""", [HOSPITAL_CODE])
        # 同人同年：TB_FeeIn[n] == Σ T_FeeIn[0..n-1]（交易前累计）？全 CureType 参与
        from collections import defaultdict
        by_person_year: dict[tuple, list] = defaultdict(list)
        for r in rows:
            yr = r[2].year if r[2] is not None else None
            by_person_year[(str(r[0]).strip() if r[0] else None, yr)].append(r)
        pre_ok = post_ok = neither = no_prior = 0
        big_pre_ok = big_neither = 0
        diffs: list[str] = []
        for key, trades in by_person_year.items():
            cum = Decimal("0")
            cum_big = Decimal("0")
            for t in trades:
                tb = Decimal(str(t[4])) if t[4] is not None else None
                fee_in = Decimal(str(t[5])) if t[5] is not None else None
                tbb = Decimal(str(t[6])) if t[6] is not None else None
                big = Decimal(str(t[7])) if t[7] is not None else None
                if tb is None or fee_in is None:
                    no_prior += 1
                elif tb == cum:
                    pre_ok += 1
                elif tb == cum + fee_in:
                    post_ok += 1
                else:
                    neither += 1
                    if len(diffs) < 12:
                        diffs.append(
                            f"    {key} {t[1]} ct={t[3]} date={t[2]} TB_FeeIn={tb} 期望前={cum} 后={cum + fee_in}")
                if tbb is not None and big is not None:
                    if tbb == cum_big:
                        big_pre_ok += 1
                    else:
                        big_neither += 1
                if fee_in is not None:
                    cum += fee_in
                if big is not None:
                    cum_big += big
        print(f"  TB_FeeIn: 交易前吻合={pre_ok} 交易后吻合={post_ok} 均不吻合={neither} 缺值={no_prior}")
        print(f"  TB_BigPay: 交易前吻合={big_pre_ok} 不吻合={big_neither}（同人同年本院累计口径；跨院会不吻合）")
        for d in diffs:
            print(d)

        print("\n== Q3b TB_Year=2000 交易的 TB_FeeIn/TB_BigPay 取值 ==")
        rows = fetch_all(conn, """
            SELECT TB_Year, COUNT(*), SUM(CASE WHEN TB_FeeIn IS NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN TB_FeeIn = 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN TB_BigPay IS NULL THEN 1 ELSE 0 END),
                   SUM(CASE WHEN TB_BigPay = 0 THEN 1 ELSE 0 END)
            FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?
            GROUP BY TB_Year ORDER BY TB_Year""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  TB_Year={r[0]}: n={r[1]} FeeIn缺={r[2]} FeeIn零={r[3]} BigPay缺={r[4]} BigPay零={r[5]}")

        print("\n== Q3c TB_Year vs 交易日期年份不一致样本 ==")
        rows = fetch_all(conn, """
            SELECT TOP 8 T_TradeNo, T_TradeDate, TB_Year, TB_MZTimes, TB_FeeIn, T_FeeIn
            FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?
              AND TB_Year <> YEAR(T_TradeDate)""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  {r[0]} date={r[1]} TB_Year={r[2]} MZTimes={r[3]} TB_FeeIn={r[4]} T_FeeIn={r[5]}")

        print("\n== Q8a T_OfficalPay 非零交易明细（公疗资格线索） ==")
        rows = fetch_all(conn, """
            SELECT T_TradeNo, T_TradeDate, PN_PersonType, P_Official, P_OfficialCode,
                   T_FeeAll, T_FeeIn, T_BigPay, T_OfficalPay, T_BCPay, T_SelfPay1
            FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=? AND T_OfficalPay <> 0""",
            [HOSPITAL_CODE])
        for r in rows:
            print(f"  {r[0]} {r[1]} PT={r[2]!r} Official={r[3]!r} OfficialCode={r[4]!r} "
                  f"FeeAll={r[5]} FeeIn={r[6]} Big={r[7]} Offical={r[8]} BC={r[9]} SP1={r[10]}")

        print("\n== Q8b P_Official / P_OfficialCode 取值分布（职工普通门诊） ==")
        rows = fetch_all(conn, """
            SELECT P_Official, P_OfficialCode, COUNT(*),
                   SUM(CASE WHEN T_OfficalPay <> 0 THEN 1 ELSE 0 END)
            FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?
            GROUP BY P_Official, P_OfficialCode""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  Official={r[0]!r} OfficialCode={r[1]!r}: n={r[2]} OfficalPay非零={r[3]}")

        print("\n== Q8c T_BCPay 非零交易明细（退休补充线索） ==")
        rows = fetch_all(conn, """
            SELECT T_TradeNo, T_TradeDate, PN_PersonType, P_Birthday,
                   T_FeeIn, TB_FeeIn, T_BigPay, T_BCPay, T_BigSelfPay, TB_BigPay
            FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=? AND T_BCPay <> 0""",
            [HOSPITAL_CODE])
        for r in rows:
            print(f"  {r[0]} {r[1]} PT={r[2]!r} FeeIn={r[4]} TB_FeeIn={r[5]} Big={r[6]} BC={r[7]} BigSP={r[8]} TB_BigPay={r[9]}")

        print("\n== Q6 机构表（找 H_CODE 所在表） ==")
        rows = fetch_all(conn, """
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE COLUMN_NAME='H_CODE' GROUP BY TABLE_NAME""")
        tables = [r[0] for r in rows]
        print(f"  含 H_CODE 的表: {tables}")
        for tb in tables:
            try:
                rows = fetch_all(conn, f"SELECT TOP 5 H_CODE, H_LEVEL FROM {tb}")
                for r in rows:
                    print(f"  {tb}: {r[0]!r} H_LEVEL={r[1]!r}")
            except Exception as exc:
                print(f"  {tb}: 读取失败 {exc}")
        # H_TYPE 所在列
        rows = fetch_all(conn, """
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE COLUMN_NAME='H_TYPE' GROUP BY TABLE_NAME""")
        print(f"  含 H_TYPE 的表: {[r[0] for r in rows]}")
        for tb in [r[0] for r in rows]:
            try:
                rows = fetch_all(conn, f"SELECT TOP 5 H_CODE, H_TYPE, H_LEVEL FROM {tb} WHERE H_CODE=?",
                                 [HOSPITAL_CODE])
                for r in rows:
                    print(f"  {tb}: {r[0]!r} H_TYPE={r[1]!r} H_LEVEL={r[2]!r}")
            except Exception as exc:
                print(f"  {tb}: 读取失败 {exc}")

        print("\n== Q4a o_Trade 全部列名（找基金累计类列） ==")
        rows = fetch_all(conn, """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME='o_Trade' ORDER BY ORDINAL_POSITION""")
        cols = [r[0] for r in rows]
        print("  " + ", ".join(cols))

        print("\n== Q4b T_JCPay/T_OfficalPay/T_BCPay/T_BigPay 非零统计（职工普通门诊全量） ==")
        rows = fetch_all(conn, """
            SELECT
              SUM(CASE WHEN T_JCPay <> 0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN T_OfficalPay <> 0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN T_BCPay <> 0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN T_BigPay <> 0 THEN 1 ELSE 0 END),
              COUNT(*)
            FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?""", [HOSPITAL_CODE])
        r = rows[0]
        print(f"  JCPay非零={r[0]} OfficalPay非零={r[1]} BCPay非零={r[2]} BigPay非零={r[3]} 总={r[4]}")

        print("\n== Q4c 全库（不限院区/险种）JCPay/OfficalPay 非零是否存在 ==")
        rows = fetch_all(conn, """
            SELECT
              SUM(CASE WHEN T_JCPay <> 0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN T_OfficalPay <> 0 THEN 1 ELSE 0 END),
              COUNT(*)
            FROM o_Trade""")
        r = rows[0]
        print(f"  JCPay非零={r[0]} OfficalPay非零={r[1]} 全库总={r[2]}")

        print("\n== Q5a 交易年度分布 ==")
        rows = fetch_all(conn, """
            SELECT TB_Year, COUNT(*) FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?
            GROUP BY TB_Year ORDER BY TB_Year""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  {r[0]}: {r[1]}")

        print("\n== Q5b PN_PersonType 分布 ==")
        rows = fetch_all(conn, """
            SELECT PN_PersonType, COUNT(*) FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?
            GROUP BY PN_PersonType""", [HOSPITAL_CODE])
        for r in rows:
            print(f"  {r[0]!r}: {r[1]}")

        print("\n== Q5c 出生日期缺失情况 ==")
        rows = fetch_all(conn, """
            SELECT SUM(CASE WHEN P_Birthday IS NULL THEN 1 ELSE 0 END), COUNT(*) FROM o_Trade
            WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=?""", [HOSPITAL_CODE])
        r = rows[0]
        print(f"  出生日期缺失={r[0]} / {r[1]}")

        print("\n== Q6b 机构表（上面 Q6 已查） ==")

        print("\n== Q7 TB_FundPay 类累计列取值检查（若存在） ==")
        tb_cols = [c for c in cols if c.upper().startswith("TB_")]
        print(f"  TB_ 前缀列: {tb_cols}")
        for c in tb_cols:
            rows = fetch_all(conn, f"""
                SELECT TOP 3 {c} FROM o_Trade
                WHERE P_FundType='3' AND T_CureType='11' AND T_HospCode=? AND {c} IS NOT NULL""",
                [HOSPITAL_CODE])
            sample = [str(r[0]) for r in rows]
            print(f"  {c}: 样本={sample}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
