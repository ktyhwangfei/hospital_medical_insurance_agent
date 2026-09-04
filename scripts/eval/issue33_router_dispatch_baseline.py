"""Issue #33 路由/拒答最小实现：路由三口径首轮基线（先记录不定标，架构条件2）。

口径定义（对应 docs/issue33-router-dispatch.md 第4节 P@3 让位的三口径）：
- 路由准确率 router_accuracy：期望 structured 的用例中，实际 route=structured 且证据非空的比例
- 误路由率 misroute_rate：全部用例中，路由到 structured 但本应拒答（期望 refuse）或证据为空的比例
- 确定性拒答率 deterministic_refusal_rate：期望拒答的用例中，实际落到确定性拒答
  （route=refuse 或 broad_kept_closed，含三判据/结构化漏空/broad 兜底关闭）的比例

跑法（真实语料只读加载，复用 issue25 脚本的 _FakeMilvusClient/_ExprMatcher/_load_real_corpus）：
    .venv/Scripts/python.exe scripts/eval/issue33_router_dispatch_baseline.py

产出：scripts/eval/issue33_router_baseline_result.json（三口径 + 每用例落点 + 既有四基线引用并列）
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

# 复用 issue25 基线脚本的 fake Milvus、expr 求值器与真实语料加载
sys.path.insert(0, str(Path(__file__).parent))
import issue25_retrieval_baseline as issue25  # noqa: E402

from src.runtime.policy_qa.broad_query_router import route_broad_question  # noqa: E402
from src.runtime.policy_qa.structured_policy_retriever import (  # noqa: E402
    NormalizedPolicyContext,
    StructuredPolicyRuleRetriever,
)

REPORT_PATH = Path(__file__).parent / "issue33_router_baseline_result.json"
PRIOR_BASELINE_PATH = Path(__file__).parent / "issue33_real_baseline_result.json"


@dataclass
class RouterCase:
    case_id: str
    question: str
    expected: str  # "structured" | "refuse"


# 黄金用例集：A/B 期望走 structured 且取回证据；C 期望确定性拒答；
# CLOSED 期望 broad 兜底关闭（同样计入确定性拒答口径）
ROUTER_CASES: list[RouterCase] = [
    # A 向：险种+医疗类别+行为齐备
    RouterCase("A_RATIO_EMPLOYEE", "在职职工门诊三级医院报销比例是多少", "structured"),
    RouterCase("A_RATIO_RETIREE", "退休人员门诊报销比例是多少", "structured"),
    # B 向：域内宽泛（无险种限定 → 职工/居民 all）
    RouterCase("B_RATIO_GENERIC", "门诊报销比例是多少", "structured"),
    RouterCase("B_CAP", "医保门诊最高限额是多少", "structured"),
    RouterCase("B_DEDUCTIBLE", "门诊起付线是多少", "structured"),
    RouterCase("B_REMOTE_PROCESS", "异地就医备案流程是什么", "structured"),
    # C 向·时间/版本判据（语料全 published+expiry=9999，无该时间档实体）
    RouterCase("C_TIME_EXPLICIT_YEAR", "2023年的门诊政策还有效吗", "refuse"),
    RouterCase("C_TIME_LAST_YEAR", "去年的门诊报销比例是多少", "refuse"),
    RouterCase("C_TIME_DRAFT", "门诊统筹新规什么时候实施", "refuse"),
    # C 向·地域判据（明确非本统筹区 / 异地比例待遇）
    RouterCase("C_REGION_SHANGHAI", "上海医保门诊报销比例是多少", "refuse"),
    RouterCase("C_REGION_REMOTE_RATIO", "异地就医报销比例是多少", "refuse"),
    # C 向·范围判据（住院在 #33 门诊+通用范围纪律之外）
    RouterCase("C_SCOPE_INPATIENT", "职工医保住院报销比例是多少", "refuse"),
    # broad 兜底关闭（域外问题，无门诊信号）
    RouterCase("CLOSED_FUND_GOVERNANCE", "医保基金是怎么管理的", "refuse"),
]


def _build_fake_retriever(entities: list[dict[str, Any]], collection_name: str):
    """用真实语料实体 + fake client 构造 structured 检索器（不打真实 Milvus 查询路径）。"""
    fake = issue25._FakeMilvusClient()
    fields = set(entities[0].keys()) if entities else set()
    fake.register_collection(
        collection_name,
        entities,
        fields=fields,
        enable_dynamic_field=True,
    )
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.client = fake
    retriever.collection_name = collection_name
    retriever._collection_fields = None
    retriever._enable_applicability_fields = True

    def structured_retrieve(decision):
        ctx = NormalizedPolicyContext(settlement_id="", region="北京")
        return retriever.retrieve(
            ctx, target_field="统筹自付", custom_queries=decision.structured_queries
        )

    return structured_retrieve


def _load_prior_baselines() -> dict[str, Any]:
    """既有四基线指标（并列展示用；文件缺失时留空）。"""
    if not PRIOR_BASELINE_PATH.exists():
        return {}
    try:
        prior = json.loads(PRIOR_BASELINE_PATH.read_text(encoding="utf-8"))
        summary: dict[str, Any] = {}
        for name in ("text_only", "current_hybrid", "enhanced_hybrid", "broad_hybrid"):
            metrics = prior.get(name)
            if not isinstance(metrics, dict):
                continue
            summary[name] = {
                key: metrics.get(key)
                for key in ("precision_at_k", "recall", "far", "honest_refusal_rate")
                if key in metrics
            }
        return summary
    except Exception as exc:  # 基线引用失败不阻塞本轮报告
        return {"error": str(exc)}


def run_router_baseline() -> dict[str, Any]:
    entities, collection_name = issue25._load_real_corpus()
    structured_retrieve = _build_fake_retriever(entities, collection_name)

    audit_log: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    current_year = date.today().year

    for case in ROUTER_CASES:
        decision = route_broad_question(
            case.question,
            structured_retrieve=structured_retrieve,
            audit_sink=audit_log.append,
            current_year=current_year,
        )
        case_results.append({
            "case_id": case.case_id,
            "question": case.question,
            "expected": case.expected,
            "landing": decision.landing,
            "route": decision.route,
            "refusal_reason": decision.refusal_reason,
            "evidence_count": len(decision.evidence),
            "top_evidence": [
                (ev.source_text or "")[:80] for ev in decision.evidence[:3]
            ],
        })

    expected_structured = [c for c in case_results if c["expected"] == "structured"]
    expected_refuse = [c for c in case_results if c["expected"] == "refuse"]
    structured_landings = [c for c in case_results if c["route"] == "structured"]

    correct_structured = [
        c for c in expected_structured if c["route"] == "structured" and c["evidence_count"] > 0
    ]
    misrouted = [
        c
        for c in case_results
        if c["route"] == "structured" and (c["expected"] == "refuse" or c["evidence_count"] == 0)
    ]
    refused = [
        c
        for c in expected_refuse
        if c["route"] in ("refuse", "broad_kept_closed")
    ]

    landing_distribution: dict[str, int] = {}
    for c in case_results:
        landing_distribution[c["landing"]] = landing_distribution.get(c["landing"], 0) + 1

    metrics = {
        "router_accuracy": round(len(correct_structured) / len(expected_structured), 4) if expected_structured else None,
        "misroute_rate": round(len(misrouted) / len(case_results), 4) if case_results else None,
        "deterministic_refusal_rate": round(len(refused) / len(expected_refuse), 4) if expected_refuse else None,
        "router_accuracy_n": len(expected_structured),
        "misroute_n": len(misrouted),
        "deterministic_refusal_n": len(refused),
        "total_cases": len(case_results),
        "note": "首轮基线只记录不定阈值（架构条件2），门禁留给加固后统一复测",
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "corpus_collection": collection_name,
        "corpus_entities": len(entities),
        "current_year": current_year,
        "metrics": metrics,
        "landing_distribution": landing_distribution,
        "cases": case_results,
        "audit_log": audit_log,
        "existing_baselines_for_reference": _load_prior_baselines(),
    }


def main() -> None:
    report = run_router_baseline()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics = report["metrics"]
    print("=== Issue #33 路由三口径首轮基线（只记录不定标）===")
    print(f"语料: {report['corpus_collection']} ({report['corpus_entities']} 条)")
    print(f"路由准确率       router_accuracy            = {metrics['router_accuracy']}")
    print(f"误路由率         misroute_rate              = {metrics['misroute_rate']}")
    print(f"确定性拒答率     deterministic_refusal_rate = {metrics['deterministic_refusal_rate']}")
    print(f"落点分布: {report['landing_distribution']}")
    for case in report["cases"]:
        print(
            f"  {case['case_id']:<24} expected={case['expected']:<10} "
            f"landing={case['landing']:<16} route={case['route']:<16} "
            f"evidence={case['evidence_count']} {case['refusal_reason']}"
        )
    print(f"报告已写入: {REPORT_PATH}")


if __name__ == "__main__":
    main()
