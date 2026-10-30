"""交易前累计（TB_/TA_ 成对累计列）增量恒等式只读取证探针（Issue #78，阶段 E 前置）。

背景：o_Trade 的 TB_Year == YEAR(T_TradeDate) 子集疑似账面维护了交易前/后累计
（TB_FeeIn/TA_FeeIn、TB_BigPay/TA_BigPay，决策候选 D3/D4 待签核）。本探针用
**全量增量恒等式**（TA - TB == T，容差 ABS(diff) < 0.005）把"n 笔抽查"升级为
"全量证明"，并核实 TB_Year=2000 哨兵行形态与居民 L1 分档列维护情况。

纪律：
- 全部只读 SELECT，单语句，不改任何业务数据；
- 不 SELECT/输出任何患者身份列（P_ICNo/P_IDNo/P_Name/P_CardNo 等一律不出现）；
- 结果落 JSON 到 .scratch/accumulation-identity-probe/results.json，可重复跑。

连接与查询模式参照 scripts/eval/issue78_data_probe.py（pymssql，`?` 占位符）。
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"
OUT_DIR = PROJECT_ROOT / ".scratch" / "accumulation-identity-probe"

#: 恒等式容差（money/numeric 4 位小数，含退费负值；0.005 元以内视为成立）
TOLERANCE = "0.005"

#: 居民险种码（P_FundType，决策记录：91/92/93 → 城乡居民）
RESIDENT_FUND_TYPES = ("91", "92", "93")

#: 目标对账样例交易号（只列交易号与金额列，不关联患者表）
TARGET_TRADE_NOS = ("011100030X240408000002", "011100030X241118000008")


def fetch_all(conn, sql, params=None):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    rows = cur.fetchall()
    cur.close()
    return rows


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_to_dict(columns, row):
    return {c: _jsonable(v) for c, v in zip(columns, row)}


def q1_identity_counts(conn) -> dict:
    """TB_Year == YEAR(T_TradeDate) 子集的全量增量恒等式统计（FeeIn / BigPay）。"""
    metric_sql = """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN TB_FeeIn IS NULL OR TA_FeeIn IS NULL OR T_FeeIn IS NULL
                   THEN 1 ELSE 0 END) AS feein_null,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn - T_FeeIn) < {tol} THEN 1 ELSE 0 END) AS feein_ok,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn - T_FeeIn) >= {tol} THEN 1 ELSE 0 END) AS feein_fail,
          SUM(CASE WHEN TB_BigPay IS NULL OR TA_BigPay IS NULL OR T_BigPay IS NULL
                   THEN 1 ELSE 0 END) AS bigpay_null,
          SUM(CASE WHEN TB_BigPay IS NOT NULL AND TA_BigPay IS NOT NULL AND T_BigPay IS NOT NULL
                    AND ABS(TA_BigPay - TB_BigPay - T_BigPay) < {tol} THEN 1 ELSE 0 END) AS bigpay_ok,
          SUM(CASE WHEN TB_BigPay IS NOT NULL AND TA_BigPay IS NOT NULL AND T_BigPay IS NOT NULL
                    AND ABS(TA_BigPay - TB_BigPay - T_BigPay) >= {tol} THEN 1 ELSE 0 END) AS bigpay_fail
        FROM o_Trade
        WHERE T_HospCode=? AND TB_Year = YEAR(T_TradeDate)
    """.format(tol=TOLERANCE)
    row = fetch_all(conn, metric_sql, [HOSPITAL_CODE])[0]
    keys = ("total", "feein_null", "feein_ok", "feein_fail",
            "bigpay_null", "bigpay_ok", "bigpay_fail")
    counts = {k: int(v) if v is not None else 0 for k, v in zip(keys, row)}

    def samples(metric: str) -> list[dict]:
        tb, ta, t = f"TB_{metric}", f"TA_{metric}", f"T_{metric}"
        sql = f"""
            SELECT TOP 20 T_TradeNo, {tb}, {ta}, {t},
                   ({ta} - {tb} - {t}) AS diff
            FROM o_Trade
            WHERE T_HospCode=? AND TB_Year = YEAR(T_TradeDate)
              AND {tb} IS NOT NULL AND {ta} IS NOT NULL AND {t} IS NOT NULL
              AND ABS({ta} - {tb} - {t}) >= {TOLERANCE}
        """
        rows = fetch_all(conn, sql, [HOSPITAL_CODE])
        return [_row_to_dict(("trade_no", tb, ta, t, "diff"), r) for r in rows]

    return {
        "scope": "T_HospCode=01110003 且 TB_Year == YEAR(T_TradeDate)，全险种全医疗类别",
        "tolerance": TOLERANCE,
        "counts": counts,
        "by_fund_cure_type": q1b_identity_by_fund_cure(conn),
        "feein_fail_samples": samples("FeeIn"),
        "bigpay_fail_samples": samples("BigPay"),
    }


def q1b_identity_by_fund_cure(conn) -> list[dict]:
    """恒等式结果按 (险种, 医疗类别) 分组：定位不成立行的集中通道。"""
    sql = f"""
        SELECT P_FundType, T_CureType,
          COUNT(*) AS total,
          SUM(CASE WHEN TB_FeeIn IS NULL OR TA_FeeIn IS NULL OR T_FeeIn IS NULL
                   THEN 1 ELSE 0 END) AS feein_null,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn - T_FeeIn) < {TOLERANCE} THEN 1 ELSE 0 END) AS feein_ok,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn - T_FeeIn) >= {TOLERANCE} THEN 1 ELSE 0 END) AS feein_fail,
          SUM(CASE WHEN TB_BigPay IS NOT NULL AND TA_BigPay IS NOT NULL AND T_BigPay IS NOT NULL
                    AND ABS(TA_BigPay - TB_BigPay - T_BigPay) < {TOLERANCE} THEN 1 ELSE 0 END) AS bigpay_ok,
          SUM(CASE WHEN TB_BigPay IS NOT NULL AND TA_BigPay IS NOT NULL AND T_BigPay IS NOT NULL
                    AND ABS(TA_BigPay - TB_BigPay - T_BigPay) >= {TOLERANCE} THEN 1 ELSE 0 END) AS bigpay_fail
        FROM o_Trade
        WHERE T_HospCode=? AND TB_Year = YEAR(T_TradeDate)
        GROUP BY P_FundType, T_CureType
        ORDER BY P_FundType, T_CureType"""
    keys = ("fund_type", "cure_type", "total", "feein_null", "feein_ok", "feein_fail",
            "bigpay_ok", "bigpay_fail")
    return [_row_to_dict(keys, r) for r in fetch_all(conn, sql, [HOSPITAL_CODE])]


def q2_tb_year_distribution(conn) -> dict:
    """TB_Year 各取值计数（按交易日期年份分组），重点看 2000 哨兵行占比。"""
    rows = fetch_all(conn, """
        SELECT YEAR(T_TradeDate) AS trade_year, TB_Year, COUNT(*) AS n
        FROM o_Trade
        WHERE T_HospCode=?
        GROUP BY YEAR(T_TradeDate), TB_Year
        ORDER BY trade_year, TB_Year""", [HOSPITAL_CODE])
    by_year: dict[str, list[dict]] = {}
    total = 0
    sentinel = 0
    for trade_year, tb_year, n in rows:
        total += int(n)
        if tb_year == 2000:
            sentinel += int(n)
        by_year.setdefault(str(trade_year), []).append(
            {"tb_year": _jsonable(tb_year), "count": int(n)})
    return {
        "scope": "T_HospCode=01110003 全险种全医疗类别",
        "total_rows": total,
        "sentinel_2000_rows": sentinel,
        "sentinel_2000_ratio": (round(sentinel / total, 6) if total else None),
        "by_trade_year": by_year,
    }


def q3_resident_l1_columns(conn) -> dict:
    """居民险种交易按机构等级档分组：L1 分档列与主累计列的 NULL/0/非零对照。"""
    funds = ", ".join(f"'{f}'" for f in RESIDENT_FUND_TYPES)
    sql = f"""
        SELECT
          inst.H_LEVEL AS h_level_raw,
          CASE WHEN TRY_CAST(inst.H_LEVEL AS int) >= 10 THEN 'tier1_level_ge_10'
               WHEN TRY_CAST(inst.H_LEVEL AS int) IS NULL THEN 'tier_unknown'
               ELSE 'tier2_level_lt_10' END AS tier,
          COUNT(*) AS total,
          SUM(CASE WHEN t.TB_FeeInL1 IS NULL THEN 1 ELSE 0 END) AS l1_feein_null,
          SUM(CASE WHEN t.TB_FeeInL1 = 0 THEN 1 ELSE 0 END) AS l1_feein_zero,
          SUM(CASE WHEN t.TB_FeeInL1 <> 0 THEN 1 ELSE 0 END) AS l1_feein_nonzero,
          SUM(CASE WHEN t.TB_BigPayL1 IS NULL THEN 1 ELSE 0 END) AS l1_bigpay_null,
          SUM(CASE WHEN t.TB_BigPayL1 = 0 THEN 1 ELSE 0 END) AS l1_bigpay_zero,
          SUM(CASE WHEN t.TB_BigPayL1 <> 0 THEN 1 ELSE 0 END) AS l1_bigpay_nonzero,
          SUM(CASE WHEN t.TB_FeeIn IS NULL THEN 1 ELSE 0 END) AS feein_null,
          SUM(CASE WHEN t.TB_FeeIn = 0 THEN 1 ELSE 0 END) AS feein_zero,
          SUM(CASE WHEN t.TB_FeeIn <> 0 THEN 1 ELSE 0 END) AS feein_nonzero,
          SUM(CASE WHEN t.TB_BigPay IS NULL THEN 1 ELSE 0 END) AS bigpay_null,
          SUM(CASE WHEN t.TB_BigPay = 0 THEN 1 ELSE 0 END) AS bigpay_zero,
          SUM(CASE WHEN t.TB_BigPay <> 0 THEN 1 ELSE 0 END) AS bigpay_nonzero
        FROM o_Trade t
        LEFT JOIN m_institution inst ON t.T_HospCode = inst.H_CODE
        WHERE t.P_FundType IN ({funds}) AND t.T_HospCode=?
        GROUP BY inst.H_LEVEL
        ORDER BY inst.H_LEVEL"""
    rows = fetch_all(conn, sql, [HOSPITAL_CODE])
    keys = ("h_level_raw", "tier", "total",
            "l1_feein_null", "l1_feein_zero", "l1_feein_nonzero",
            "l1_bigpay_null", "l1_bigpay_zero", "l1_bigpay_nonzero",
            "feein_null", "feein_zero", "feein_nonzero",
            "bigpay_null", "bigpay_zero", "bigpay_nonzero")
    groups = [_row_to_dict(keys, r) for r in rows]
    return {
        "scope": f"P_FundType IN {RESIDENT_FUND_TYPES} 且 T_HospCode=01110003，全医疗类别",
        "tier_rule": "H_LEVEL>=10（含未评级外的数值档）=一级及以下；NULL/不可解析=unknown",
        "groups": groups,
    }


def q4_target_samples(conn) -> dict:
    """两个目标样例的 TB_/TA_/T_ 各列值 + 恒等式验证（不关联患者表）。"""
    sql = """
        SELECT T_TradeNo, T_TradeDate, TB_Year, P_FundType, T_CureType,
               TB_FeeIn, TA_FeeIn, T_FeeIn,
               TB_BigPay, TA_BigPay, T_BigPay,
               TB_FeeInL1, TA_FeeInL1, TB_BigPayL1, TA_BigPayL1
        FROM o_Trade
        WHERE T_HospCode=? AND T_TradeNo IN (?, ?)"""
    rows = fetch_all(conn, sql, [HOSPITAL_CODE, *TARGET_TRADE_NOS])
    keys = ("trade_no", "trade_date", "tb_year", "fund_type", "cure_type",
            "tb_feein", "ta_feein", "t_feein",
            "tb_bigpay", "ta_bigpay", "t_bigpay",
            "tb_feein_l1", "ta_feein_l1", "tb_bigpay_l1", "ta_bigpay_l1")
    tol = Decimal(TOLERANCE)

    def identity(tb, ta, t):
        if tb is None or ta is None or t is None:
            return "null"
        return "holds" if abs(ta - tb - t) < tol else "fails"

    samples = []
    for r in rows:
        d = _row_to_dict(keys, r)
        d["feein_identity"] = identity(r[5], r[6], r[7])
        d["bigpay_identity"] = identity(r[8], r[9], r[10])
        d["tb_year_matches_trade_year"] = (
            None if r[1] is None or r[2] is None
            else int(r[2]) == (r[1].year if isinstance(r[1], datetime) else None))
        samples.append(d)
    return {"scope": "两笔目标交易号，仅交易号+金额列", "samples": samples}


def q5_sentinel_rows(conn) -> dict:
    """TB_Year=2000 哨兵行上 TA-TB 与 T 的实际形态（预期不可用）。"""
    sql = f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN TB_FeeIn IS NULL OR TA_FeeIn IS NULL OR T_FeeIn IS NULL
                   THEN 1 ELSE 0 END) AS feein_any_null,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn - T_FeeIn) < {TOLERANCE} THEN 1 ELSE 0 END) AS feein_ta_minus_tb_eq_t,
          SUM(CASE WHEN TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - T_FeeIn) < {TOLERANCE} THEN 1 ELSE 0 END) AS feein_ta_eq_t,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn) < {TOLERANCE} THEN 1 ELSE 0 END) AS feein_ta_eq_tb,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TB_FeeIn - T_FeeIn) < {TOLERANCE} THEN 1 ELSE 0 END) AS feein_tb_eq_t,
          SUM(CASE WHEN TB_BigPay IS NULL OR TA_BigPay IS NULL OR T_BigPay IS NULL
                   THEN 1 ELSE 0 END) AS bigpay_any_null,
          SUM(CASE WHEN TB_BigPay IS NOT NULL AND TA_BigPay IS NOT NULL AND T_BigPay IS NOT NULL
                    AND ABS(TA_BigPay - TB_BigPay - T_BigPay) < {TOLERANCE} THEN 1 ELSE 0 END) AS bigpay_ta_minus_tb_eq_t
        FROM o_Trade
        WHERE T_HospCode=? AND TB_Year = 2000"""
    row = fetch_all(conn, sql, [HOSPITAL_CODE])[0]
    keys = ("total", "feein_any_null", "feein_ta_minus_tb_eq_t", "feein_ta_eq_t",
            "feein_ta_eq_tb", "feein_tb_eq_t", "bigpay_any_null", "bigpay_ta_minus_tb_eq_t")
    counts = {k: int(v) if v is not None else 0 for k, v in zip(keys, row)}

    sample_sql = """
        SELECT TOP 5 T_TradeNo, TB_FeeIn, TA_FeeIn, T_FeeIn, TB_BigPay, TA_BigPay, T_BigPay
        FROM o_Trade
        WHERE T_HospCode=? AND TB_Year = 2000"""
    samples = [_row_to_dict(
        ("trade_no", "tb_feein", "ta_feein", "t_feein", "tb_bigpay", "ta_bigpay", "t_bigpay"), r)
        for r in fetch_all(conn, sample_sql, [HOSPITAL_CODE])]
    return {"scope": "T_HospCode=01110003 且 TB_Year=2000", "counts": counts,
            "samples": samples, "tb_year_0_rows": q5b_tb_year_zero(conn)}


def q5b_tb_year_zero(conn) -> dict:
    """TB_Year=0 行（另一大类哨兵值）的 TB/TA 列形态。"""
    sql = f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN TB_FeeIn IS NULL THEN 1 ELSE 0 END) AS tb_feein_null,
          SUM(CASE WHEN TB_FeeIn = 0 THEN 1 ELSE 0 END) AS tb_feein_zero,
          SUM(CASE WHEN TA_FeeIn IS NULL THEN 1 ELSE 0 END) AS ta_feein_null,
          SUM(CASE WHEN TA_FeeIn = 0 THEN 1 ELSE 0 END) AS ta_feein_zero,
          SUM(CASE WHEN TB_BigPay IS NULL THEN 1 ELSE 0 END) AS tb_bigpay_null,
          SUM(CASE WHEN TB_BigPay = 0 THEN 1 ELSE 0 END) AS tb_bigpay_zero,
          SUM(CASE WHEN TB_FeeIn IS NOT NULL AND TA_FeeIn IS NOT NULL AND T_FeeIn IS NOT NULL
                    AND ABS(TA_FeeIn - TB_FeeIn - T_FeeIn) < {TOLERANCE} THEN 1 ELSE 0 END) AS feein_identity_ok
        FROM o_Trade
        WHERE T_HospCode=? AND TB_Year = 0"""
    row = fetch_all(conn, sql, [HOSPITAL_CODE])[0]
    keys = ("total", "tb_feein_null", "tb_feein_zero", "ta_feein_null", "ta_feein_zero",
            "tb_bigpay_null", "tb_bigpay_zero", "feein_identity_ok")
    return {k: int(v) if v is not None else 0 for k, v in zip(keys, row)}


def main() -> int:
    source = get_semantic_data_source()
    conn = source.open_connection(DATASOURCE_ID)
    results: dict = {"datasource": DATASOURCE_ID, "hospital_code": HOSPITAL_CODE,
                     "read_at": datetime.now().isoformat(timespec="seconds")}
    try:
        print("== Q1 增量恒等式全量验证（TB_Year==交易年子集） ==")
        results["q1_identity"] = q1_identity_counts(conn)
        c = results["q1_identity"]["counts"]
        print(f"  总行={c['total']} FeeIn: 成立={c['feein_ok']} 不成立={c['feein_fail']} NULL={c['feein_null']}")
        print(f"  BigPay: 成立={c['bigpay_ok']} 不成立={c['bigpay_fail']} NULL={c['bigpay_null']}")
        for g in results["q1_identity"]["by_fund_cure_type"]:
            print(f"    fund={g['fund_type']} cure={g['cure_type']}: n={g['total']} "
                  f"feein 成立={g['feein_ok']} 不成立={g['feein_fail']}")

        print("== Q2 TB_Year 分布（按交易年分组） ==")
        results["q2_tb_year_distribution"] = q2_tb_year_distribution(conn)
        q2 = results["q2_tb_year_distribution"]
        print(f"  总行={q2['total_rows']} 哨兵2000={q2['sentinel_2000_rows']} ({q2['sentinel_2000_ratio']})")

        print("== Q3 居民 L1 分档列维护情况 ==")
        results["q3_resident_l1"] = q3_resident_l1_columns(conn)
        for g in results["q3_resident_l1"]["groups"]:
            print(f"  {g['tier']} h_level={g['h_level_raw']!r} n={g['total']} "
                  f"L1_FeeIn 非零={g['l1_feein_nonzero']} L1_BigPay 非零={g['l1_bigpay_nonzero']}")

        print("== Q4 目标样例逐字段对账 ==")
        results["q4_target_samples"] = q4_target_samples(conn)
        for s in results["q4_target_samples"]["samples"]:
            print(f"  {s['trade_no']} feein_identity={s['feein_identity']} "
                  f"bigpay_identity={s['bigpay_identity']} tb_year={s['tb_year']}")

        print("== Q5 TB_Year=2000 哨兵行形态 ==")
        results["q5_sentinel_rows"] = q5_sentinel_rows(conn)
        c5 = results["q5_sentinel_rows"]["counts"]
        print(f"  总行={c5['total']} TA-TB=T 成立={c5['feein_ta_minus_tb_eq_t']} "
              f"TA=T {c5['feein_ta_eq_t']} TA=TB {c5['feein_ta_eq_tb']} NULL={c5['feein_any_null']}")
    finally:
        conn.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=_jsonable),
                        encoding="utf-8")
    print(f"\n结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
