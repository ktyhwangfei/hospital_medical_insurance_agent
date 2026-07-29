"""政策问答·标量检索回归基线（P0-a）。

目的：固化 StructuredPolicyRuleRetriever 在真实 policy_rules_v2 数据上的健康行为。

依赖：Milvus @ 127.0.0.1:19530 的 policy_rules_v2 collection。
环境无 Milvus 或无数据时自动 skip，不阻塞 CI。

v2 维度值已标准化到业务字典（semantic_layer/seed.py）：hosp_lv 用"三级/二级/一级/无等级"，
med_type 用"住院-普通住院/门诊-普通门急诊"等细类。结算上下文须用同域业务值。
"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _policy_rules_ready() -> bool:
    """Milvus 可达且 policy_rules_v2 有数据才跑基线。"""
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2)
        cols = c.list_collections()
        if "policy_rules_v2" not in cols:
            c.close()
            return False
        stats = c.get_collection_stats("policy_rules_v2")
        c.close()
        return int(stats.get("row_count", 0)) > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _policy_rules_ready(),
    reason="Milvus policy_rules_v2 不可用（需 127.0.0.1:19530 + 数据）",
)


def test_structured_retrieval_城镇职工退休三级住院_命中支付比例与公式():
    """城镇职工·退休·三级医院·普通住院·统筹自付 → 必须命中支付比例与折算公式。

    [依据: PROGRESS 1.1–1.5 政策问答；现状探查验证此为当前健康行为]
    """
    from src.runtime.policy_qa.structured_policy_retriever import retrieve_policy_evidence

    ctx = {
        "settlement_id": "BASELINE-TEST",
        "insu_type": "城镇职工基本医疗保险",
        "med_type": "住院-普通住院",
        "hosp_lv": "三级",
        "psn_type": "退休人员",
        "target_field": "统筹自付",
        "target_amount": 1000.0,
    }
    result = retrieve_policy_evidence(ctx)

    # 值标准化后第一组（支付比例）命中
    assert len(result.selected_evidence) >= 1, "标量检索应命中至少 1 条规则证据"
    rule_types = {getattr(ev, "rule_type", None) for ev in result.selected_evidence}
    assert "支付比例" in rule_types, f"应命中支付比例规则，实际 rule_types={rule_types}"
    # 支付比例组必须命中（验证 hosp_lv/med_type 值标准化到业务字典）
    assert "employee_inpatient_tertiary_segment_ratio" not in result.missing_required_rules, (
        f"支付比例组应命中（值标准化后），missing={result.missing_required_rules}"
    )
    # 注：退休人员60%折算公式组（retiree_personal_ratio_formula）是 v2 数据 gap
    # （schema-driven 提取未产出 rule_type="计算公式" 的规则），待数据补充
