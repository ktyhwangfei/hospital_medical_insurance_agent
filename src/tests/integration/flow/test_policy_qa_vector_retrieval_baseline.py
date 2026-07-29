"""政策问答·向量检索回归基线（P0-b）。

目的：固化 PolicyRulesSearchEngine 默认配置下语义向量检索的健康行为。

背景（bug）：默认/多处实例化曾用 embedding_kind="hash"(384维)，
而 policy_rules_v2 的 vector 是 bge 768 维语义向量 → 维度不匹配 →
异常被 search 的 except 吞掉 → 永远返回空。
修复：默认改为 sentence_transformer（bge 768维，与灌数据同空间）。

依赖：Milvus @ 127.0.0.1:19530（policy_rules_v2）+ sentence_transformers + 本地 bge 模型。
任一缺失则 skip，不阻塞 CI。
"""
import pytest

# 无语义栈则 skip 整个文件（已声明依赖，但环境可能未装）
pytest.importorskip("sentence_transformers")

MILVUS_URI = "http://127.0.0.1:19530"


def _policy_rules_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2)
        ok = "policy_rules_v2" in c.list_collections() and int(
            c.get_collection_stats("policy_rules_v2").get("row_count", 0)) > 0
        c.close()
        return ok
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _policy_rules_ready(),
    reason="Milvus policy_rules_v2 不可用（需 127.0.0.1:19530 + 数据）",
)


def test_default_engine_retrieves_semantic_matches():
    """默认 PolicyRulesSearchEngine()（不传 embedding_kind）必须语义召回。

    当前默认 hash(384) → 维度不匹配 → 返回空（红）。
    修复默认为 sentence_transformer(768) 后 → 命中城镇职工支付比例（绿）。
    """
    from src.runtime.policy_qa.policy_rules_search import PolicyRulesSearchEngine

    eng = PolicyRulesSearchEngine()  # 默认配置
    rules = eng.search("城镇职工住院报销比例", top_k=3)

    assert len(rules) >= 1, "默认引擎应语义召回至少 1 条规则"
    # 语义相关性：top 结果应包含城镇职工的支付比例
    hits = {
        (r.get("rule_type"), r.get("insu_type"))
        for r in rules
    }
    assert ("支付比例", "城镇职工基本医疗保险") in hits, (
        f"应命中城镇职工支付比例，实际 hits={hits}"
    )
