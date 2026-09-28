"""Issue #78 职工门诊费用分解：bjyb 库全量交易回放评估（只读）。

范围：bjyb SQL Server 库中城镇职工基本医疗保险（P_FundType='3'，码表已解析为"城镇职工"）
的普通门诊（T_CureType='11'，码表已解析为"普通门诊"）交易，逐笔走
``decompose_outpatient_trade`` 确定性分解，给每个 trade_no 打准确性标记并汇总准确率。

口径声明（评估口径，非生产启用）：
- 险种/医疗类别由 SQL WHERE 按码值筛定，profile_resolver 直接返回 ('employee','outpatient')；
  这是批量评估的合法前置（码值已经语义注册中心码表确认），不是绕过 §6.1 门控。
- 取整模式显式 RoundingMode.HALF_UP（EOP-RND-001 待确认，属假定口径，决策记录 D10）。
- 年度累计口径与待遇资格派生：accumulation_caliber_confirmed=True（TB_FeeIn/TB_BigPay
  交易前口径实证，决策记录 D3/D4/D5）、derive_eligibility_from_codes=True（院内码表列
  派生公疗/军残/退休补充资格，决策记录 D6/D7/D8）。全部为候选口径，
  逐项证据与回退方式见 docs/superpowers/specs/2026-09-29-issue78-批量评估决策与待确认.md。

verdict 定义（以**内核独立重算字段**为准；账面内部核对单列）：
- 准确：全部 independent_recalculation 字段已判定且 matched（not_applicable 且无账面冲突视同正确）
- 差异（实质）：存在内核字段 mismatched 且 |差额| ≥ 0.01 元，或资格不适用但账面非零
- 差异（亚分精度）：内核字段 mismatched 但全部 |差额| < 0.01 元
- 无法核对：存在内核字段 not_verifiable（列出 uncertainty codes）
- 不可用：unavailable（交易未找到/歧义/冲正退款/读取失败/组合不支持等）
- 脚本异常：分解过程抛出未预期异常（评估脚本自身兜底，理论上不应出现）

账面内部核对（detail_aggregation / identity_check，含 T_FundPay/T_PersonCountPay/T_CashPay
等内核不重放字段）不计入 verdict，单独汇总为 book_internal 统计——它是账面内部一致性信号，
不证明内核算错（亚分精度差为源系统明细 4 位小数 vs 交易分位的精度特征）。

准确率口径（如实呈现，不粉饰）：
- 全量口径 = 准确 / 总交易数
- 可判定口径 = 准确 / (准确 + 差异)（亚分精度差也算差异，最保守）

跑法：
    uv run python scripts/eval/fee_decomposition_batch.py

产出：
    scripts/eval/issue78_fee_decomposition_batch_result.csv  — 逐笔明细
    scripts/eval/issue78_fee_decomposition_batch_summary.json — 汇总与 uncertainty 直方图
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
from src.runtime.policy_qa.fee_decomposition.snapshot_service import (  # noqa: E402
    decompose_outpatient_trade,
)

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"  # o_Trade.T_HospCode 全库唯一值（单院区）
ROUNDING_MODE = RoundingMode.HALF_UP  # 假定口径：EOP-RND-001 待确认

# 城镇职工（P_FundType='3'）+ 普通门诊（T_CureType='11'），码值经语义注册中心码表确认
TRADE_SQL = (
    "SELECT T_TradeNo FROM o_Trade "
    "WHERE P_FundType = '3' AND T_CureType = '11' AND T_HospCode = ? "
    "ORDER BY T_TradeNo"
)

CSV_PATH = Path(__file__).parent / "issue78_fee_decomposition_batch_result.csv"
SUMMARY_PATH = Path(__file__).parent / "issue78_fee_decomposition_batch_summary.json"

VERDICT_ACCURATE = "准确"
VERDICT_MISMATCH_SUBSTANTIVE = "差异（实质）"
VERDICT_MISMATCH_SUBCENT = "差异（亚分精度）"
VERDICT_NOT_VERIFIABLE = "无法核对"
VERDICT_UNAVAILABLE = "不可用"
VERDICT_SCRIPT_ERROR = "脚本异常"

#: 亚分精度阈值：|差额| 小于一分钱的账面精度差，单独成类不作为实质差异
SUBCENT_THRESHOLD = Decimal("0.01")


def _employee_outpatient_resolver(_trade_row) -> tuple[str, str]:
    """码值已在 SQL 筛定（'3'/'11' 经码表确认），批量评估直接给出职工/门诊组合。"""
    return ("employee", "outpatient")


def _classify(result) -> tuple[str, str, str, str]:
    """结果 → (verdict, 内核 mismatched 摘要, uncertainty codes, 账面内部核对摘要)。

    verdict 只依据内核独立重算字段（independent_recalculation）；
    账面内部核对字段（detail_aggregation/identity_check）单列摘要，不进 verdict。
    """
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
            "差" not in m  # 资格冲突（无差额）按实质
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
    try:
        cursor = conn.cursor()
        cursor.execute(TRADE_SQL, [HOSPITAL_CODE])
        trade_nos = [str(r[0]) for r in cursor.fetchall()]
        cursor.close()
        print(f"命中职工普通门诊交易 {len(trade_nos)} 笔（院区 {HOSPITAL_CODE}）", flush=True)

        for i, trade_no in enumerate(trade_nos, 1):
            try:
                result = decompose_outpatient_trade(
                    conn,
                    trade_no,
                    HOSPITAL_CODE,
                    ROUNDING_MODE,
                    profile_resolver=_employee_outpatient_resolver,
                    accumulation_caliber_confirmed=True,  # 决策记录 D3/D4/D5（候选口径，待签核）
                    derive_eligibility_from_codes=True,  # 决策记录 D6/D7/D8（候选口径，待签核）
                )
                verdict, mismatched, codes, book_note = _classify(result)
                rows.append({
                    "trade_no": trade_no,
                    "execution_status": result.execution_status,
                    "reconciliation_status": result.reconciliation_status,
                    "verdict": verdict,
                    "mismatched_fields": mismatched,
                    "book_internal_note": book_note,
                    "uncertainty_codes": codes,
                })
            except Exception as exc:  # noqa: BLE001 — 单笔异常不中断批量，如实标记
                rows.append({
                    "trade_no": trade_no,
                    "execution_status": "script_error",
                    "reconciliation_status": "",
                    "verdict": VERDICT_SCRIPT_ERROR,
                    "mismatched_fields": "",
                    "book_internal_note": "",
                    "uncertainty_codes": f"{type(exc).__name__}: {exc}",
                })
            if i % 20 == 0 or i == len(trade_nos):
                print(f"  进度 {i}/{len(trade_nos)}", flush=True)
    finally:
        conn.close()

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()) if rows else [
            "trade_no", "execution_status", "reconciliation_status", "verdict",
            "mismatched_fields", "book_internal_note", "uncertainty_codes"])
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    verdict_counts = Counter(r["verdict"] for r in rows)
    accurate = verdict_counts.get(VERDICT_ACCURATE, 0)
    mismatch_substantive = verdict_counts.get(VERDICT_MISMATCH_SUBSTANTIVE, 0)
    mismatch_subcent = verdict_counts.get(VERDICT_MISMATCH_SUBCENT, 0)
    mismatched = mismatch_substantive + mismatch_subcent
    decidable = accurate + mismatched
    book_internal_mismatch_trades = sum(1 for r in rows if r["book_internal_note"])
    uncertainty_hist: Counter[str] = Counter()
    for r in rows:
        if r["verdict"] in (VERDICT_NOT_VERIFIABLE, VERDICT_UNAVAILABLE):
            for code in r["uncertainty_codes"].split("; "):
                if code:
                    uncertainty_hist[code] += 1

    summary = {
        "datasource": DATASOURCE_ID,
        "hospital_code": HOSPITAL_CODE,
        "filter": "P_FundType='3'（城镇职工） AND T_CureType='11'（普通门诊）",
        "rounding_mode_assumed": ROUNDING_MODE.value,
        "candidate_calibers": {
            "accumulation_caliber_confirmed": "TB_FeeIn/TB_BigPay 交易前口径（决策记录 D3/D4/D5，待签核）",
            "derive_eligibility_from_codes": "公疗/军残/退休补充资格由院内码表列派生（决策记录 D6/D7/D8，待签核）",
        },
        "verdict_basis": "仅内核独立重算字段（independent_recalculation）；账面内部核对单列",
        "total_trades": total,
        "verdict_counts": dict(verdict_counts),
        "accuracy_all": (accurate / total) if total else None,
        "accuracy_decidable": (accurate / decidable) if decidable else None,
        "decidable_trades": decidable,
        "book_internal_mismatch_trades": book_internal_mismatch_trades,
        "note": "detail_aggregation/identity_check 的 mismatched 是账面内部一致性信号，"
                "不计入 verdict；亚分精度差为源系统明细 4 位小数 vs 交易分位的精度特征。",
        "uncertainty_histogram": dict(uncertainty_hist.most_common()),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总 =====")
    print(f"总交易数: {total}")
    for verdict, count in verdict_counts.most_common():
        print(f"  {verdict}: {count}")
    if total:
        print(f"准确率（全量口径 准确/总数）: {accurate / total:.2%} ({accurate}/{total})")
    if decidable:
        print(f"准确率（可判定口径 准确/(准确+差异)）: {accurate / decidable:.2%} ({accurate}/{decidable})")
    else:
        print("可判定口径：无可判定交易（全部为无法核对/不可用）")
    print(f"账面内部核对存在差异的交易: {book_internal_mismatch_trades}（不计入 verdict）")
    if uncertainty_hist:
        print("\n卡点分布（uncertainty code 直方图）:")
        for code, count in uncertainty_hist.most_common():
            print(f"  {code}: {count}")
    print(f"\n明细 CSV: {CSV_PATH}")
    print(f"汇总 JSON: {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
