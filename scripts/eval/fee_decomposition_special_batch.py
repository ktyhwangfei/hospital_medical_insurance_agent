"""Issue #78 职工门特费用分解：bjyb 库全量门特结算回放评估（只读）。

范围：bjyb SQL Server 库中城镇职工基本医疗保险（FUND_TYPE=3）的门特
（yllb='16'，YLLB 码表=门特）结算，逐笔走 ``decompose_outpatient_special_settlement``
确定性分解，打准确性标记并汇总准确率。

口径声明（评估口径，非生产启用）：
- 险种/医疗类别由 SQL WHERE 按码值筛定，profile 直接传入 ('employee','outpatient_special')；
  这是批量评估的合法前置（ESP-CODE-001/002 实测码值），不是绕过门控。
- 取整模式显式 RoundingMode.HALF_UP（ESP-RND-001 尚未确认，属假定口径，如实标注）。
- 每笔跑两种模式：
  (a) strict  严格口径：周期上下文 unknown、不取账面起付——起付与统筹/大额字段
      应全部 not_verifiable（院端抽取无法重建周期/累计，这是诚实基线）；
  (b) eval    评估口径：allow_observed_deductible=True——F 取账面 ybnqfje 作条件输入
      （deductible.source=observed_book，勾稽级），验证 85%/91%/80% 比例与退休补助
      50% 的计算正确性；统筹封顶在 prior=0 下界可证未跨界时才计算。
- 已知数据源缺口：djh=681/723/813（付克琴）账面全额进大额互助段（tczhf=0），
  院端抽取中其年度统筹基金累计为 0，与「统筹封顶后直接进入大额」（ESP-DED-004）
  方向一致但数值不可证——内核按下界规则算出「应全进统筹」会与账面矛盾，
  如实记为差异（实质），注明系院端数据不完整而非规则错误。

verdict 定义与门诊批量脚本一致：准确 / 差异（实质） / 差异（亚分精度） /
无法核对 / 不可用 / 脚本异常。

跑法：
    uv run python scripts/eval/fee_decomposition_special_batch.py

产出：
    scripts/eval/issue78_special_batch_result.csv  — 逐笔×逐口径明细
    scripts/eval/issue78_special_batch_summary.json — 汇总与字段级准确率
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.insurance.fee_decomposition import (  # noqa: E402
    RoundingMode,
    SpecialCycleContext,
)
from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special import (  # noqa: E402
    decompose_outpatient_special_settlement,
)

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"  # 协和（m_institution H_LEVEL='02' 三级）
ROUNDING_MODE = RoundingMode.HALF_UP  # 假定口径：ESP-RND-001 待确认

# 城镇职工（FUND_TYPE=3）+ 门特（yllb='16'），码值经语义注册中心 YLLB 码表确认
DJH_SQL = (
    "SELECT djh FROM dbo.yb_brdjxx "
    "WHERE FUND_TYPE = 3 AND yllb = '16' ORDER BY djh"
)

CSV_PATH = Path(__file__).parent / "issue78_special_batch_result.csv"
SUMMARY_PATH = Path(__file__).parent / "issue78_special_batch_summary.json"

VERDICT_ACCURATE = "准确"
VERDICT_MISMATCH_SUBSTANTIVE = "差异（实质）"
VERDICT_MISMATCH_SUBCENT = "差异（亚分精度）"
VERDICT_NOT_VERIFIABLE = "无法核对"
VERDICT_UNAVAILABLE = "不可用"
VERDICT_SCRIPT_ERROR = "脚本异常"

SUBCENT_THRESHOLD = Decimal("0.01")

#: 独立重算关键字段（评估口径下的准确率按这些字段统计）
KEY_RECALC_FIELDS = ("YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF")

MODES = ("strict", "eval")

#: 大额段进入假定口径（仅对账面 tczhf=0 且 degwyzhf>0 的结算追加运行）：
#: 账面全额进入大额互助段 → 假定交易前年度统筹累计已达 10 万封顶（ESP-DED-004 方向；
#: 院端数据不可证，仅用于验证大额段 85%/80% 与退休补助大额段 50% 的计算正确性）；
#: 退休类别注入 normal（门诊批量评估决策 D8：cblb 21/22→普通退休的评估口径映射）。
EVAL_LARGE_POOL_PRIOR = Decimal("100000")


def _classify(result) -> tuple[str, str, str]:
    """结果 → (verdict, mismatched_fields 摘要, uncertainty codes)。"""
    mismatched_models = [f for f in result.fields if f.check_status == "mismatched"]
    mismatched = [
        f"{f.field_code}(账面{f.observed_amount}/算得{f.calculated_amount}/差{f.difference})"
        for f in mismatched_models
    ]
    codes = sorted({u.code for u in result.uncertainties})
    if result.execution_status == "unavailable":
        verdict = VERDICT_UNAVAILABLE
    elif result.reconciliation_status == "matched":
        verdict = VERDICT_ACCURATE
    elif result.reconciliation_status == "mismatched":
        substantive = any(
            f.difference is None or abs(Decimal(f.difference)) >= SUBCENT_THRESHOLD
            for f in mismatched_models
        )
        verdict = VERDICT_MISMATCH_SUBSTANTIVE if substantive else VERDICT_MISMATCH_SUBCENT
    else:
        verdict = VERDICT_NOT_VERIFIABLE
    return verdict, "; ".join(mismatched), "; ".join(codes)


def _key_field_cells(result) -> dict[str, str]:
    """关键独立重算字段 → 'matched:算得/账面' 摘要。"""
    cells: dict[str, str] = {}
    for f in result.fields:
        if f.field_code in KEY_RECALC_FIELDS and f.check_type == "independent_recalculation":
            cells[f.field_code] = (
                f"{f.check_status}"
                + (f"(算{f.calculated_amount}/账{f.observed_amount})"
                   if f.check_status in ("matched", "mismatched") else "")
            )
    return cells


def _book_all_in_large(result) -> bool:
    """账面全额进入大额互助段：tczhf=0 且 degwyzhf>0。"""
    obs: dict[str, Decimal] = {}
    for f in result.fields:
        if f.field_code in ("TCZHF", "DEGWYZHF") and f.observed_amount is not None:
            obs[f.field_code] = Decimal(f.observed_amount)
    return obs.get("TCZHF") == Decimal("0") and obs.get("DEGWYZHF", Decimal("0")) > 0


def _run_one(conn, djh: str, mode: str, rows: list[dict[str, str]]):
    """单笔单口径执行并落行；返回结果对象（脚本异常时返回 None）。"""
    kwargs: dict = {"profile": ("employee", "outpatient_special")}
    if mode in ("eval", "eval_large"):
        kwargs["allow_observed_deductible"] = True
    if mode == "eval_large":
        kwargs["cycle_context_override"] = SpecialCycleContext(
            deductible_standard=Decimal("1300"),
            prior_cycle_deductible_paid=Decimal("1300"),
            prior_annual_pool_fund_payment=EVAL_LARGE_POOL_PRIOR,
            prior_annual_large_fund_payment=Decimal("0"),
            evidence_status="assumed",
            evidence_note="评估口径：账面全额进入大额互助段且起付 0，假定交易前年度统筹累计已达 "
                          "10 万封顶、本周期起付已交足（ESP-DED-004 同向；院端数据不可证，"
                          "仅验证大额段比例计算）",
        )
        kwargs["retirement_category_override"] = "normal"  # 门诊 D8 决策的门特对应
    try:
        result = decompose_outpatient_special_settlement(
            conn, djh, HOSPITAL_CODE, ROUNDING_MODE, **kwargs)
        verdict, mismatched, codes = _classify(result)
        cells = _key_field_cells(result)
        rows.append({
            "djh": djh,
            "mode": mode,
            "execution_status": result.execution_status,
            "reconciliation_status": result.reconciliation_status,
            "verdict": verdict,
            **{f"field_{k}": cells.get(k, "") for k in KEY_RECALC_FIELDS},
            "mismatched_fields": mismatched,
            "uncertainty_codes": codes,
        })
    except Exception as exc:  # noqa: BLE001 — 单笔异常不中断批量，如实标记
        result = None
        rows.append({
            "djh": djh,
            "mode": mode,
            "execution_status": "script_error",
            "reconciliation_status": "",
            "verdict": VERDICT_SCRIPT_ERROR,
            **{f"field_{k}": "" for k in KEY_RECALC_FIELDS},
            "mismatched_fields": "",
            "uncertainty_codes": f"{type(exc).__name__}: {exc}",
        })
    print(f"  djh={djh} mode={mode} → {rows[-1]['verdict']}", flush=True)
    return result


def main() -> int:
    source = get_semantic_data_source()
    conn = source.open_connection(DATASOURCE_ID)
    rows: list[dict[str, str]] = []
    try:
        cursor = conn.cursor()
        cursor.execute(DJH_SQL)
        djh_list = [str(r[0]) for r in cursor.fetchall()]
        cursor.close()
        print(f"命中职工门特结算 {len(djh_list)} 笔（{DJH_SQL}）", flush=True)

        for djh in djh_list:
            eval_result = None
            for mode in MODES:
                result = _run_one(conn, djh, mode, rows)
                if mode == "eval":
                    eval_result = result
            # 账面全额进大额段（tczhf=0 且 degwyzhf>0）→ 追加 eval_large 假定口径，
            # 验证大额互助比例与退休补助大额段的计算正确性
            if eval_result is not None and _book_all_in_large(eval_result):
                _run_one(conn, djh, "eval_large", rows)
    finally:
        conn.close()

    fieldnames = ["djh", "mode", "execution_status", "reconciliation_status", "verdict"] + [
        f"field_{k}" for k in KEY_RECALC_FIELDS] + ["mismatched_fields", "uncertainty_codes"]
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── 汇总 ──
    summary: dict = {
        "datasource": DATASOURCE_ID,
        "hospital_code": HOSPITAL_CODE,
        "filter": "FUND_TYPE=3（城镇职工） AND yllb='16'（门特）",
        "rounding_mode_assumed": ROUNDING_MODE.value,
        "total_settlements": len({r["djh"] for r in rows}),
        "modes": {},
    }
    all_modes = list(MODES) + (["eval_large"] if any(r["mode"] == "eval_large" for r in rows) else [])
    for mode in all_modes:
        mode_rows = [r for r in rows if r["mode"] == mode]
        verdict_counts = Counter(r["verdict"] for r in mode_rows)
        accurate = verdict_counts.get(VERDICT_ACCURATE, 0)
        mismatched = (verdict_counts.get(VERDICT_MISMATCH_SUBSTANTIVE, 0)
                      + verdict_counts.get(VERDICT_MISMATCH_SUBCENT, 0))
        decidable = accurate + mismatched
        # 字段级准确率：关键独立重算字段 matched / 有计算值（matched+mismatched）
        field_stats: dict[str, dict[str, int]] = {}
        for code in KEY_RECALC_FIELDS:
            matched_n = sum(1 for r in mode_rows if r[f"field_{code}"].startswith("matched"))
            decided_n = sum(1 for r in mode_rows
                            if r[f"field_{code}"].startswith(("matched", "mismatched")))
            field_stats[code] = {"matched": matched_n, "decided": decided_n}
        summary["modes"][mode] = {
            "verdict_counts": dict(verdict_counts),
            "accuracy_all": (accurate / len(mode_rows)) if mode_rows else None,
            "accuracy_decidable": (accurate / decidable) if decidable else None,
            "key_field_stats": field_stats,
        }

    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总 =====")
    for mode in all_modes:
        m = summary["modes"][mode]
        print(f"[{mode}] verdict: {m['verdict_counts']}")
        print(f"  准确率（全量）: {m['accuracy_all']}; （可判定）: {m['accuracy_decidable']}")
        for code, st in m["key_field_stats"].items():
            print(f"  {code}: matched {st['matched']}/{st['decided']}（有计算值）")
    print(f"\n明细 CSV: {CSV_PATH}")
    print(f"汇总 JSON: {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
