"""政策问答·标量检索回归基线（P0-a）。

目的：固化 StructuredPolicyRuleRetriever 在真实 policy_rules_v2 数据上的健康行为。

依赖：Milvus @ 127.0.0.1:19530 的 policy_rules_v2 collection。
环境无 Milvus 或无数据时自动 skip，不阻塞 CI。

⚠️ v2 数据 gap（xfail）：schema-driven 提取的政策原文中，hosp_lv 用简写
（如"三级"而非业务值"三级医院"），med_type 普遍低填充。导致按结算上下文
（hosp_lv="三级医院"、med_type="住院-普通住院"）的精确结构化检索 0 命中。
旧 policy_rules（迁移时标准化为业务值）有 4 条三级医院 / 25 条普通住院，
切换 v2 后该精确场景失效。待数据标准化（值映射 + med_type 补充）后转回 pass。
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


@pytest.mark.xfail(
    reason="v2 数据 gap：hosp_lv 用政策简写（'三级'非'三级医院'）+ med_type 低填充，"
           "精确结构化检索 0 命中，待数据标准化（值映射 + med_type 补充）",
    strict=True,
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
        "hosp_lv": "三级医院",
        "psn_type": "退休人员",
        "target_field": "统筹自付",
        "target_amount": 1000.0,
    }
    result = retrieve_policy_evidence(ctx)

    # 命中证据非空
    assert len(result.selected_evidence) >= 1, "标量检索应命中至少 1 条规则证据"
    # 必含「支付比例」类规则（核心检索维度）
    rule_types = {getattr(ev, "rule_type", None) for ev in result.selected_evidence}
    assert "支付比例" in rule_types, f"应命中支付比例规则，实际 rule_types={rule_types}"
    # 必需查询无缺失（plan_queries 的两条 required 查询都命中）
    assert result.missing_required_rules == [], (
        f"必需规则缺失：{result.missing_required_rules}"
    )
