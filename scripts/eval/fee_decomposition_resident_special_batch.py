"""Issue #81 城乡居民门特·按项目付费费用分解：bjyb 库全量登记回放评估（只读）。

范围：bjyb SQL Server 库中城乡居民门特登记（yb_brdjxx.yllb='12' × FUND_TYPE∈{91,92,93}）
× 项目付费（yb_mzjyxx.fyfs='0'），逐 djh 走 ``decompose_special_mz_resident_settlement``
确定性分解（目录独立重算、基本医保封顶、二次大病及医疗救助、年度/周期证据），
给每个 djh 打准确性标记并汇总准确率。

口径声明（评估口径，非生产启用）：
- 险种由 SQL WHERE 按码值筛定（91/92/93 经码表确认），profile 显式 ('resident','outpatient_special')；
- 取整模式显式 RoundingMode.HALF_UP（RSP-RND-001 待确认；688 degwyzhf 837.825→837.83 实证支持）；
- 周期上下文：同年度本笔流水快照分字段推导；年度表滞后或必要字段缺失时保持未知；
- 非特殊病费用（ptybn/ptybw≠0）按普通门诊结算本期不支持（同 ESP-CAT-002 口径）。

verdict 定义（以**内核独立重算字段**为准；账面内部核对单列）——与门诊/职工门特口径一致：
- 准确：全部 independent_recalculation 字段已判定且 matched（not_applicable 且无账面冲突视同正确）
- 差异（实质）：存在内核字段 mismatched 且 |差额| ≥ 0.01 元，或资格不适用但账面非零
- 差异（亚分精度）：内核字段 mismatched 但全部 |差额| < 0.01 元
- 无法核对：存在内核字段 not_verifiable（列出 uncertainty codes）
- 不可用：unavailable（登记未找到/歧义/非项目付费/读取失败/组合不支持等）
- 脚本异常：分解过程抛出未预期异常

跑法：
    uv run python scripts/eval/fee_decomposition_resident_special_batch.py

产出：
    scripts/eval/issue81_resident_special_batch_result.csv  — 逐笔明细
    scripts/eval/issue81_resident_special_batch_summary.json — 汇总与 uncertainty 直方图
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

from src.domain.insurance.fee_decomposition import RoundingMode  # noqa: E402
from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz_resident import (  # noqa: E402
    decompose_special_mz_resident_settlement,
)

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"
ROUNDING_MODE = RoundingMode.HALF_UP  # 假定口径：RSP-RND-001 待确认

# 居民门特登记（yllb='12' × FUND_TYPE∈91/92/93），fyfs='0' 项目付费由服务层判定
DJH_SQL = (
    "SELECT djh FROM dbo.yb_brdjxx WHERE yllb = '12' AND FUND_TYPE IN ('91','92','93') "
    "ORDER BY djh"
)

CSV_PATH = Path(__file__).parent / "issue81_resident_special_batch_result.csv"
SUMMARY_PATH = Path(__file__).parent / "issue81_resident_special_batch_summary.json"

VERDICT_ACCURATE = "准确"
VERDICT_MISMATCH_SUBSTANTIVE = "差异（实质）"
VERDICT_MISMATCH_SUBCENT = "差异（亚分精度）"
VERDICT_NOT_VERIFIABLE = "无法核对"
VERDICT_UNAVAILABLE = "不可用"
VERDICT_SCRIPT_ERROR = "脚本异常"

SUBCENT_THRESHOLD = Decimal("0.01")


def _classify(result) -> tuple[str, str, str, str]:
    """结果 → (verdict, 内核 mismatched 摘要, uncertainty codes, 账面内部核对摘要)。"""
    kernel_fields = [f for f in result.fields if f.check_type == "independent_recalculation"]
    book_fields = [f for f in result.fields if f.check_type != "independent_recalculation"]

    mismatched: list[str] = []
    undecided = False
    for f in kernel_fields:
        if f.check_status == "mismatched":
            mismatched.append(
                f"{f.field_code}(账面{f.observed_amount}/算得{f.calculated_amount}/差{f.difference})")
        elif f.check_status == "not_applicable":
            if f.reason_code == "ELIGIBILITY_CONFLICT_WITH_BOOK":
                mismatched.append(f"{f.field_code}(资格不适用但账面{f.observed_amount})")
        elif f.check_status != "matched":
            undecided = True
    codes = sorted({u.code for u in result.uncertainties})

    book_mismatch = [
        f"{f.field_code}(账面{f.observed_amount}/算得{f.calculated_amount}/差{f.difference})"
        for f in book_fields if f.check_status == "mismatched"
    ]
    book_summary = f"账面内部核对差异{len(book_mismatch)}项" if book_mismatch else ""

    if result.execution_status == "unavailable":
        verdict = VERDICT_UNAVAILABLE
    elif undecided:
        verdict = VERDICT_NOT_VERIFIABLE
    elif mismatched:
        substantive = any(
            "差" not in m
            or Decimal(m.rsplit("差", 1)[1].rstrip(")")).copy_abs() >= SUBCENT_THRESHOLD
            for m in mismatched
        )
        verdict = VERDICT_MISMATCH_SUBSTANTIVE if substantive else VERDICT_MISMATCH_SUBCENT
    else:
        verdict = VERDICT_ACCURATE
    return verdict, "; ".join(mismatched), "; ".join(codes), (
        book_summary + ("：" + "; ".join(book_mismatch) if book_mismatch else ""))


def main() -> int:
    source = get_semantic_data_source()
    conn = source.open_connection(DATASOURCE_ID)
    rows: list[dict[str, str]] = []
    traces = {}
    field_stats: Counter[str] = Counter()
    try:
        cursor = conn.cursor()
        cursor.execute(DJH_SQL)
        djhs = [str(r[0]) for r in cursor.fetchall()]
        cursor.close()
        print(f"命中城乡居民门特登记 {len(djhs)} 笔（yllb=12 × FUND_TYPE∈91/92/93）", flush=True)

        for i, djh in enumerate(djhs, 1):
            try:
                result = decompose_special_mz_resident_settlement(
                    conn, djh, HOSPITAL_CODE, ROUNDING_MODE)
                result = result.result  # DecompositionOutcome 侧车：批量回放只用分解结果
                verdict, mismatched, codes, book_note = _classify(result)
                traces[djh] = result.model_dump(mode="json")
                kernel_fields = [
                    f for f in result.fields if f.check_type == "independent_recalculation"]
                for f in kernel_fields:
                    field_stats[f"{f.field_code}:{f.check_status}"] += 1
                rows.append({
                    "djh": djh,
                    "execution_status": result.execution_status,
                    "reconciliation_status": result.reconciliation_status,
                    "verdict": verdict,
                    "mismatched_fields": mismatched,
                    "book_internal_note": book_note,
                    "uncertainty_codes": codes,
                })
            except Exception as exc:  # noqa: BLE001 — 单笔异常不中断批量，如实标记
                rows.append({
                    "djh": djh,
                    "execution_status": "script_error",
                    "reconciliation_status": "",
                    "verdict": VERDICT_SCRIPT_ERROR,
                    "mismatched_fields": "",
                    "book_internal_note": "",
                    "uncertainty_codes": f"{type(exc).__name__}: {exc}",
                })
            print(f"  进度 {i}/{len(djhs)} djh={djh} {rows[-1]['verdict']}", flush=True)
    finally:
        conn.close()

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()) if rows else [
            "djh", "execution_status", "reconciliation_status", "verdict",
            "mismatched_fields", "book_internal_note", "uncertainty_codes"])
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    verdict_counts = Counter(r["verdict"] for r in rows)
    accurate = verdict_counts.get(VERDICT_ACCURATE, 0)
    mismatched = (verdict_counts.get(VERDICT_MISMATCH_SUBSTANTIVE, 0)
                  + verdict_counts.get(VERDICT_MISMATCH_SUBCENT, 0))
    decidable = accurate + mismatched
    kernel_matched = sum(v for k, v in field_stats.items() if k.endswith(":matched"))
    kernel_total = sum(
        v for k, v in field_stats.items()
        if k.endswith(":matched") or k.endswith(":mismatched"))
    kernel_mismatched = sum(v for k, v in field_stats.items() if k.endswith(":mismatched"))
    uncertainty_hist: Counter[str] = Counter()
    for r in rows:
        if r["verdict"] in (VERDICT_NOT_VERIFIABLE, VERDICT_UNAVAILABLE):
            for code in r["uncertainty_codes"].split("; "):
                if code:
                    uncertainty_hist[code] += 1

    summary = {
        "datasource": DATASOURCE_ID,
        "hospital_code": HOSPITAL_CODE,
        "filter": "yb_brdjxx.yllb='12' × FUND_TYPE∈('91','92','93') × yb_mzjyxx.fyfs='0'（项目付费）",
        "rounding_mode_assumed": ROUNDING_MODE.value,
        "candidate_calibers": {
            "cycle_derive": "同年度本笔流水快照分字段减本笔；缺失或负差保持未知，滞后原值不能认作交易前累计",
            "catalog_split": "目录独立分解复用 split_catalog（RSP-CAT-001，与居民门诊同规则）",
            "basic_pay_rate": "基本医保基金比例按机构档住院口径（三级 75%，RSP-RATE-001）；二次大病保险另按年度分段计算",
        },
        "verdict_basis": "仅内核独立重算字段（independent_recalculation）；账面内部核对单列",
        "total_registrations": total,
        "verdict_counts": dict(verdict_counts),
        "accuracy_all": (accurate / total) if total else None,
        "accuracy_decidable": (accurate / decidable) if decidable else None,
        "decidable_trades": decidable,
        "kernel_field_level": {
            "matched": kernel_matched,
            "mismatched": kernel_mismatched,
            "accuracy": (kernel_matched / kernel_total) if kernel_total else None,
        },
        "field_status_histogram": dict(sorted(field_stats.items())),
        "uncertainty_histogram": dict(uncertainty_hist.most_common()),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_PATH.with_name("issue81_resident_special_batch_traces.json").write_text(
        json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总 =====")
    print(f"总登记数: {total}")
    for verdict, count in verdict_counts.most_common():
        print(f"  {verdict}: {count}")
    if total:
        print(f"准确率（全量口径 准确/总数）: {accurate / total:.2%} ({accurate}/{total})")
    if decidable:
        print(f"准确率（可判定口径 准确/(准确+差异)）: {accurate / decidable:.2%} ({accurate}/{decidable})")
    if kernel_total:
        print(f"字段级准确率（内核独立重算字段）: {kernel_matched / kernel_total:.2%} "
              f"({kernel_matched}/{kernel_total})")
    if uncertainty_hist:
        print("\n卡点分布（uncertainty code 直方图）:")
        for code, count in uncertainty_hist.most_common():
            print(f"  {code}: {count}")
    print(f"\n明细 CSV: {CSV_PATH}")
    print(f"汇总 JSON: {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
