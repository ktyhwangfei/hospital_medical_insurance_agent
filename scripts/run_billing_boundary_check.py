"""Issue #85 收费边界解释实单自检（只读）：样例 A/B 走现有结算解释链路，逐项核对验收清单。

用法：.venv/Scripts/python.exe scripts/run_billing_boundary_check.py [--output PATH]
输出：每个问题的窗口答复（deterministic 模式）+ 验收断言结果（JSON）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ.setdefault("FEE_EXPLANATION_MODE", "deterministic")

BANNED_WORDS = ("符合", "不符合", "违规", "超收", "加收")

SAMPLES = {
    "样例A": "011100030X260417004975",
    "样例B": "011100030X260417003528",
}

# (样例, 目标行关键字, 问题, 必含片段列表, 禁含片段列表)
ACCEPTANCE = [
    ("样例A", "电子胃镜检查", "电子胃镜检查这项含什么、为什么同单还有别的收费行",
     ["不含监护、实验室检验、活检", "活检术"], []),
    ("样例A", "电子结肠镜检查", "电子结肠镜检查这项含什么、为什么同单还有别的收费行",
     ["不含监护、活检、病理学检查", "活检术"], []),
    ("样例A", "总蛋白", "总蛋白(TP)测定这笔为什么单独收费",
     ["不含监护、实验室检验、活检", "电子胃镜检查"], []),
    ("样例A", "直肠测压导管", "直肠测压导管这笔850元为什么单独收费",
     ["导管按实际消耗另收", "除外内容：导管、气囊", "850.00"], []),
    ("样例A", "真空采血管", "真空采血管这笔为什么单独收费",
     ["除外内容：采血管", "静脉采血"], []),
    ("样例A", "丙型肝炎抗体", "丙型肝炎抗体(抗HCV)测定这项含什么",
     ["包含确认试验", "不再另收"], []),
    ("样例B", "圈套器", "圈套器这笔350元为什么单独收费",
     ["套扎器（圈）", "内镜色素检查", "350.00"], []),
    ("样例B", "活检组织病理诊断", "活检组织病理诊断这项含什么",
     [], ["蜡块"]),
]

# 窗口原话，不加「第N行」前缀。
RAW_QUESTIONS = [
    ("样例A", "肠镜已经收了，活检为什么还要单收",
     ["不含监护、活检、病理学检查", "消化道内镜活检术", "电子结肠镜检查"],
     ["电子胃镜检查", "蜡块", "费用总金额"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    from src.runtime.discovery.semantic_source import SemanticDataSource
    from src.adapters.data_supply.sqlserver_direct import SqlServerDirectSupplyAdapter
    from src.domain.insurance.fee_decomposition import RoundingMode
    from src.runtime.policy_qa.fee_decomposition.snapshot_service import decompose_outpatient_trade
    from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
    from src.runtime.policy_qa.public_contract import FeeDecompositionPublic
    from src.runtime.policy_qa.fee_decomposition.model_explanation import explain_decomposition
    from src.runtime.api.policy_qa_routes import _public_text

    conn = SqlServerDirectSupplyAdapter(SemanticDataSource().connect_datasource).connect("bjybdb")
    report: dict = {"observed_at": datetime.now(timezone.utc).isoformat(),
                    "source": "bjybdb 测试库只读；deterministic 模式窗口答复",
                    "banned_words": list(BANNED_WORDS), "cases": []}
    failures: list[str] = []
    for label, trade_no in SAMPLES.items():
        outcome = decompose_outpatient_trade(
            conn, trade_no, "01110003", RoundingMode.HALF_UP,
            profile_resolver=lambda _: ("employee", "outpatient"))
        public = FeeDecompositionPublic.model_validate(to_public_contract_dict(
            outcome.result, summary_text="", summary_source="template",
            settlement_facts=outcome.facts, sanitize=_public_text))
        print(f"\n===== {label} {trade_no} 明细 {len(public.fee_items)} 行 =====")
        for index, item in enumerate(public.fee_items):
            ctx = item.payment_condition_context
            print(f"  [{index + 1:>2}] {item.item_name} 费{item.total_fee} "
                  f"内{item.observed_in_scope} 外{item.observed_out_scope}"
                  + (f" bz[{ctx.catalog_source}]" if ctx and ctx.bz else ""))
        for sample, keyword, question, must, must_not in ACCEPTANCE:
            if sample != label:
                continue
            target = next((i for i, item in enumerate(public.fee_items)
                           if keyword in (item.item_name or "")), None)
            if target is None:
                failures.append(f"{label} 未找到目标行 {keyword}")
                continue
            line_question = f"第{target + 1}行{question}"
            answer = explain_decomposition(public, line_question).answer
            missed = [text for text in must if text not in answer]
            leaked = [text for text in must_not if text in answer]
            banned = [word for word in BANNED_WORDS if word in answer]
            status = "pass" if not missed and not leaked and not banned else "fail"
            if status == "fail":
                failures.append(f"{label} 第{target + 1}行 {keyword}: missed={missed} leaked={leaked} banned={banned}")
            print(f"\n[{status}] {label} 问：{line_question}\n{answer}")
            report["cases"].append({
                "sample": label, "trade_no": trade_no, "display_no": target + 1,
                "question": line_question, "status": status,
                "must_contain": must, "must_not_contain": must_not,
                "missed": missed, "leaked": leaked, "banned_found": banned,
                "answer": answer})
        for sample, question, must, must_not in RAW_QUESTIONS:
            if sample != label:
                continue
            answer = explain_decomposition(public, question).answer
            missed = [text for text in must if text not in answer]
            leaked = [text for text in must_not if text in answer]
            banned = [word for word in BANNED_WORDS if word in answer]
            status = "pass" if not missed and not leaked and not banned else "fail"
            if status == "fail":
                failures.append(
                    f"{label} 原话 {question}: missed={missed} leaked={leaked} banned={banned}")
            print(f"\n[{status}] {label} 问：{question}\n{answer}")
            report["cases"].append({
                "sample": label, "trade_no": trade_no, "display_no": None,
                "question": question, "status": status,
                "must_contain": must, "must_not_contain": must_not,
                "missed": missed, "leaked": leaked, "banned_found": banned,
                "answer": answer})
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(f"\n证据已写入 {args.output}")
    print("\n===== 自检结果 =====")
    print("全部通过" if not failures else "\n".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
