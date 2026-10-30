"""Issue #79 职工门特·按项目付费费用分解：bjyb 库全量回放评估（只读，门诊套表）。

范围：bjyb SQL Server 库中城镇职工（FUND_TYPE=3）× 门特（yllb='12'）且结算
费用方式为按项目付费（yb_mzjyxx.fyfs='0'）的全部结算，逐笔走
``decompose_special_mz_settlement`` 确定性分解，输出统一 CSV 供人工验收。

口径声明（评估口径，非生产启用）：
- 险种/医疗类别由 SQL WHERE 按码值筛定，profile 直接传入 ('employee','outpatient_special')
  （ESP-CODE-001/002 实测码值候选）；
- 取整模式显式 RoundingMode.HALF_UP（ESP-RND-001 待确认，属假定口径，如实标注）；
- 周期上下文：同年度、本笔流水匹配的 dyxxtsb/dyxxnd 快照按字段减本笔；缺失或负差未知；
  无行（2025 年起表未维护）→ unknown，此时 allow_observed_deductible=True
  取账面起付作条件输入（勾稽级）+ segment_coordinate_guard（坐标不可证明即不硬算）；
- 资格字段 cjjrdj/gwydybz/cblb=61 按 Issue #79 手工验证候选口径映射（留痕候选状态）。

产出（统一 CSV，验收用）：
    scripts/eval/issue79_special_mz_batch_result.csv — 全部记录：
      row_type=verdict   每笔总判定（19 个费用分解字段 matched/mismatched/not_verifiable 计数）
      row_type=field     逐字段：账面值/计算值/差异/核对状态/说明（含恒等式与支付渠道）
      row_type=calc      计算过程：公式/操作数/未取整结果/取整规则/结果
      row_type=item      费用明细行（库里面记录的各项费用）
      row_type=branch    分支轨迹：条件/实际值/命中/规则引用
    scripts/eval/issue79_special_mz_batch_summary.json — 汇总与字段级准确率

准确率定义（19个目标：明细汇总4个、基本医保和补助8个、二次大病/救助及个人应付7个）：
- matched 或 not_applicable 且与账面一致 → 准确；
- mismatched 或 not_applicable 与账面冲突 → 差异；
- not_verifiable → 不计入可判定（院端数据不可得，如实排除，不视为错误）；
- accuracy_decidable = 准确 / (准确 + 差异)；accuracy_all = 准确 / 全部字段。
支付渠道（XJZF/ZHZF 及恒等式）为信息性核对，不计入准确率
（设计：缺扣款规则与支付流水，只能说明实际支付构成）。

跑法：
    uv run python scripts/eval/fee_decomposition_special_mz_batch.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.insurance.fee_decomposition import RoundingMode  # noqa: E402
from src.runtime.discovery.semantic_source import get_semantic_data_source  # noqa: E402
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz import (  # noqa: E402
    decompose_special_mz_settlement,
)

DATASOURCE_ID = "bjybdb"
HOSPITAL_CODE = "01110003"  # 协和（m_institution H_LEVEL='02' 三级）
ROUNDING_MODE = RoundingMode.HALF_UP  # 假定口径：ESP-RND-001 待确认

# 城镇职工（FUND_TYPE=3）× 门特（yllb='12'）× 按项目付费（fyfs='0'）（Issue #79 口径）
DJH_SQL = (
    "SELECT b.djh FROM dbo.yb_brdjxx b "
    "JOIN dbo.yb_mzjyxx m ON b.djh = m.djh "
    "WHERE b.FUND_TYPE = 3 AND b.yllb = '12' AND m.fyfs = '0' AND COALESCE(b.tsb1,'') NOT IN ('503','504') AND COALESCE(b.tsb2,'') NOT IN ('503','504') AND COALESCE(b.tsb3,'') NOT IN ('503','504') ORDER BY b.djh"
)

CSV_PATH = Path(__file__).parent / "issue79_special_mz_batch_result.csv"
SUMMARY_PATH = Path(__file__).parent / "issue79_special_mz_batch_summary.json"

#: 费用分解目标字段（准确率统计范围；支付渠道与恒等式为信息性核对，不计入）
DECOMPOSITION_FIELDS = (
    "ZJE", "YBN", "YBW", "GRZIFTW",
    "YBNQFJE", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF", "BCZHF", "JCZHF", "GFYLBCHBX",
    "BIG_ILL_PAY", "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "PERSON_PAYABLE",
)

VERDICT_ACCURATE = "准确"
VERDICT_MISMATCH = "差异（实质）"
VERDICT_NOT_VERIFIABLE = "无法核对"
VERDICT_UNAVAILABLE = "不可用"
VERDICT_SCRIPT_ERROR = "脚本异常"


def _field_verdict(status: str, observed: str | None) -> str:
    """单字段判定：accurate / mismatched / not_verifiable。"""
    if status == "matched":
        return "accurate"
    if status == "not_applicable":
        # 资格不适用：账面为零 → 判定正确；账面非零 → 资格与账面冲突视为差异
        return "accurate" if observed in (None, "0", "0.0", "0.00", "0.0000") else "mismatched"
    if status == "mismatched":
        return "mismatched"
    return "not_verifiable"


def main(*, kidney_fixed: bool = False) -> int:
    query, csv_path, summary_path = DJH_SQL, CSV_PATH, SUMMARY_PATH
    trace_name = "issue79_special_mz_batch_traces.json"
    service = decompose_special_mz_settlement
    target_fields = DECOMPOSITION_FIELDS
    scope = "职工门特按项目付费（排除503/504）"
    if kidney_fixed:
        from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import KIDNEY_SCOPE_SQL
        from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_fixed_kidney import decompose_special_fixed_kidney_settlement
        service = decompose_special_fixed_kidney_settlement
        query = "SELECT b.djh FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON b.djh=m.djh WHERE b.FUND_TYPE=3 AND b.yllb='12' AND m.fyfs='0' AND " + KIDNEY_SCOPE_SQL + " ORDER BY b.djh"
        csv_path = CSV_PATH.with_name("issue82_fixed_kidney_batch_result.csv")
        summary_path = SUMMARY_PATH.with_name("issue82_fixed_kidney_batch_summary.json")
        trace_name = "issue82_fixed_kidney_batch_traces.json"
        target_fields += ("QUOTA_AMOUNT", "GRZIF1", "AGENCY_PAY")
        scope = "职工门特定额肾/肝肾移植抗排异（503/504）"
    source = get_semantic_data_source()
    conn = source.open_connection(DATASOURCE_ID)
    rows: list[dict[str, str]] = []
    traces = {}
    trade_stats: list[dict] = []
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        djh_list = [str(r[0]) for r in cursor.fetchall()]
        cursor.close()
        print(f"命中{scope}结算 {len(djh_list)} 笔", flush=True)

        for djh in djh_list:
            print(f"  djh={djh} ...", flush=True)
            try:
                result = service(
                    conn, djh, HOSPITAL_CODE, ROUNDING_MODE,
                    allow_observed_deductible=True,
                    profile=("employee", "outpatient_special"))
                result = result.result  # DecompositionOutcome 侧车：批量回放只用分解结果
            except Exception as exc:  # noqa: BLE001 — 单笔异常不中断批量
                rows.append({"row_type": "verdict", "djh": djh, "verdict": VERDICT_SCRIPT_ERROR,
                             "note": f"{type(exc).__name__}: {exc}"})
                trade_stats.append({"djh": djh, "verdict": VERDICT_SCRIPT_ERROR, "fields": {}})
                continue

            # ── 逐字段行（库里面记录的各项费用 vs 计算结果） ──
            counts = Counter()
            field_detail: dict[str, str] = {}
            for f in result.fields:
                v = _field_verdict(f.check_status, f.observed_amount)
                if f.field_code in target_fields:
                    counts[v] += 1
                    field_detail[f.field_code] = (
                        f"{f.check_status}(账{f.observed_amount}/算{f.calculated_amount})")
                rows.append({
                    "row_type": "field", "djh": djh,
                    "field_code": f.field_code, "label": f.label,
                    "check_type": f.check_type, "check_status": f.check_status,
                    "observed_amount": f.observed_amount or "",
                    "calculated_amount": f.calculated_amount or "",
                    "difference": f.difference or "",
                    "reason_code": f.reason_code or "",
                    "verdict": v if f.field_code in target_fields else "信息性",
                })

            traces[djh] = result.model_dump(mode="json")
            # ── 计算过程行 ──
            for c in result.calculations:
                rows.append({
                    "row_type": "calc", "djh": djh,
                    "calculation_id": c.calculation_id, "formula_id": c.formula_id,
                    "operands": "; ".join(f"{o.ref}={o.value}" for o in c.operands),
                    "unrounded_result": c.unrounded_result or "",
                    "rounding_rule": c.rounding_rule or "",
                    "result": c.result or "",
                })

            # ── 分支轨迹行 ──
            for b in result.branches:
                rows.append({
                    "row_type": "branch", "djh": djh,
                    "step_id": b.step_id, "outcome": b.outcome,
                    "condition": (f"{b.condition.description}|实际={b.condition.actual_value}"
                                  f"|期望={b.condition.expected_ref}") if b.condition else "",
                    "reason_code": b.reason_code or "",
                    "rule_refs": ";".join(b.rule_refs),
                })

            # ── 不确定性行 ──
            for u in result.uncertainties:
                rows.append({"row_type": "uncertainty", "djh": djh, "code": u.code,
                             "message": u.message,
                             "affected_fields": ";".join(u.affected_fields)})

            # ── 总判定行 ──
            if result.execution_status == "unavailable":
                verdict = VERDICT_UNAVAILABLE
            elif counts["mismatched"] > 0:
                verdict = VERDICT_MISMATCH
            elif counts["not_verifiable"] > 0:
                verdict = VERDICT_NOT_VERIFIABLE
            else:
                verdict = VERDICT_ACCURATE
            cycle_status = ""
            for c in result.citations:
                if c.id == "fact.cycle_context":
                    cycle_status = c.value or ""
            rows.append({
                "row_type": "verdict", "djh": djh, "verdict": verdict,
                "execution_status": result.execution_status,
                "reconciliation_status": result.reconciliation_status,
                "cycle_evidence": cycle_status,
                "accurate_fields": str(counts["accurate"]),
                "mismatched_fields": str(counts["mismatched"]),
                "not_verifiable_fields": str(counts["not_verifiable"]),
                **{f"field_{k}": field_detail.get(k, "") for k in target_fields},
            })
            trade_stats.append({"djh": djh, "verdict": verdict, "fields": field_detail,
                                "counts": dict(counts)})
            print(f"  djh={djh} → {verdict}（准确 {counts['accurate']}/"
                  f"差异 {counts['mismatched']}/不可核对 {counts['not_verifiable']}）",
                  flush=True)

            # ── 费用明细行（库里面记录的各项费用） ──
            cursor = conn.cursor()
            cursor.execute(
                "SELECT xh, cfh, xmdm, xmmc, xmlb, sflb, sfxmdj, tsbbs, dj, sl, zje, ybnje, ybwje,"
                " grziftw, fsrq FROM dbo.yb_mzfymx WHERE djh = ? ORDER BY xh", (djh,))
            for it in cursor.fetchall():
                rows.append({
                    "row_type": "item", "djh": djh, "xh": str(it[0]), "cfh": str(it[1] or ""),
                    "xmdm": it[2], "xmmc": it[3], "xmlb": it[4], "sflb": it[5], "sfxmdj": it[6],
                    "tsbbs": it[7] or "", "dj": str(it[8]), "sl": str(it[9]),
                    "zje": str(it[10]), "ybnje": str(it[11]), "ybwje": str(it[12]),
                    "grziftw": str(it[13]), "fsrq": str(it[14]),
                })
            cursor.close()
    finally:
        conn.close()

    # ── 统一 CSV（行类型各自列并集；空列留空） ──
    fieldnames = [
        "row_type", "djh", "verdict",
        "field_code", "label", "check_type", "check_status", "observed_amount",
        "calculated_amount", "difference", "reason_code",
        "calculation_id", "formula_id", "operands", "unrounded_result", "rounding_rule",
        "result",
        "step_id", "outcome", "condition", "rule_refs",
        "code", "message", "affected_fields",
        "execution_status", "reconciliation_status", "cycle_evidence",
        "accurate_fields", "mismatched_fields", "not_verifiable_fields",
        *[f"field_{k}" for k in target_fields],
        "xh", "xmdm", "xmmc", "xmlb", "sflb", "sfxmdj", "tsbbs", "dj", "sl",
        "zje", "ybnje", "ybwje", "grziftw", "fsrq",
        "cfh", "note",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # ── 汇总 ──
    verdict_counts = Counter(t["verdict"] for t in trade_stats)
    total_accurate = sum(t["counts"].get("accurate", 0) for t in trade_stats if t.get("counts"))
    total_mismatched = sum(t["counts"].get("mismatched", 0) for t in trade_stats if t.get("counts"))
    total_not_verifiable = sum(
        t["counts"].get("not_verifiable", 0) for t in trade_stats if t.get("counts"))
    field_stats: dict[str, dict[str, int]] = {}
    for code in target_fields:
        acc = sum(1 for t in trade_stats
                  if t["fields"].get(code, "").startswith(("matched", "not_applicable")))
        mis = sum(1 for t in trade_stats if t["fields"].get(code, "").startswith("mismatched"))
        nv = sum(1 for t in trade_stats if t["fields"].get(code, "").startswith("not_verifiable"))
        field_stats[code] = {"accurate": acc, "mismatched": mis, "not_verifiable": nv}
    decidable = total_accurate + total_mismatched
    summary = {
        "datasource": DATASOURCE_ID,
        "hospital_code": HOSPITAL_CODE,
        "scope": scope,
        "rounding_mode_assumed": ROUNDING_MODE.value,
        "total_settlements": len(trade_stats),
        "verdict_counts": dict(verdict_counts),
        "field_level": {
            "accurate": total_accurate,
            "mismatched": total_mismatched,
            "not_verifiable": total_not_verifiable,
            "accuracy_decidable": (total_accurate / decidable) if decidable else None,
            "accuracy_all": (total_accurate / (decidable + total_not_verifiable))
            if (decidable + total_not_verifiable) else None,
        },
        "per_field_stats": field_stats,
        "metric_note": f"按{len(target_fields)}个目标字段核对金额，含二次大病、救助及个人应付；定额链含条件核对，matched不表示日标准已独立核定；unknown不作为通过",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.with_name(trace_name).write_text(
        json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总 =====")
    print(f"verdict: {dict(verdict_counts)}")
    print(f"字段级：准确 {total_accurate} / 差异 {total_mismatched} / 不可核对 {total_not_verifiable}")
    print(f"准确率（可判定）: {summary['field_level']['accuracy_decidable']}")
    print(f"准确率（全字段）: {summary['field_level']['accuracy_all']}")
    for code, st in field_stats.items():
        print(f"  {code}: 准确 {st['accurate']} 差异 {st['mismatched']} 不可核对 {st['not_verifiable']}")
    print(f"\n统一 CSV: {csv_path}")
    print(f"汇总 JSON: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
