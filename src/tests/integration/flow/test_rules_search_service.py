"""RulesSearchService 集成测试（P6，§4.2）。

依赖 Milvus，不可用则 skip。用临时 collection 隔离。

三模式统一在 policy_rules_v2（自带 vector 复用 + 核心维度）：
- precise: 标量过滤
- semantic: 向量召回
- hybrid: 向量 + 标量过滤
"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _milvus_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2)
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用")


def _seed_test_data(rules_col_name: str, facts_col_name: str):
    """写入测试数据：2 facts + 3 rules（不同险种/规则类型）。占位向量（precise 不需要真实向量）。"""
    from pymilvus import connections
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection, upsert_facts,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection, rule_to_entity, upsert_rules,
    )
    connections.connect(alias="default", host="127.0.0.1", port="19530")
    facts_col = create_policy_facts_collection(collection_name=facts_col_name, drop_existing=True)
    rules_col = create_policy_rules_v2_collection(collection_name=rules_col_name, drop_existing=True)
    upsert_facts(facts_col, [
        {"fact_id": "f_test_1", "doc_id": "d_test",
         "fact_text": "城镇职工住院起付标准1300元", "vector": [0.1] * 768, "created_at": "2026-07-24"},
        {"fact_id": "f_test_2", "doc_id": "d_test",
         "fact_text": "城乡居民门诊统筹支付50%", "vector": [0.2] * 768, "created_at": "2026-07-24"},
    ])
    rules = [
        rule_to_entity({"rule_id": "r1", "fact_id": "f_test_1", "rule_type": "起付线",
                        "insu_type": "城镇职工基本医疗保险", "hosp_lv": "三级医院",
                        "deductible_amount": "1300元"}, vector=[0.1] * 768, extracted_at="2026-07-24"),
        rule_to_entity({"rule_id": "r2", "fact_id": "f_test_1", "rule_type": "支付比例",
                        "insu_type": "城镇职工基本医疗保险", "hosp_lv": "三级医院",
                        "payment_ratio": "85%"}, vector=[0.1] * 768, extracted_at="2026-07-24"),
        rule_to_entity({"rule_id": "r3", "fact_id": "f_test_2", "rule_type": "支付比例",
                        "insu_type": "城乡居民基本医疗保险", "hosp_lv": "一级医院",
                        "payment_ratio": "50%"}, vector=[0.2] * 768, extracted_at="2026-07-24"),
    ]
    for r in rules:
        r["doc_id"] = "d_test"  # LLM 不产 doc_id，由编排填
    upsert_rules(rules_col, rules)


def test_search_precise_filters_and_groups():
    """precise 标量过滤 + 按 fact 分组 + join fact_text。"""
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService
    connections.connect(alias="default", host="127.0.0.1", port="19530")
    rcol, fcol = "_test_rules_search_r", "_test_rules_search_f"
    try:
        _seed_test_data(rcol, fcol)
        svc = RulesSearchService(rules_col_name=rcol, facts_col_name=fcol)
        groups = svc.search_precise({"insu_type": "城镇职工基本医疗保险"}, top_k=20)
        # 只命中 f_test_1 的 2 条规则，聚合为 1 个 group
        assert len(groups) == 1, f"应只命中城镇职工 1 个 fact，实际 {len(groups)} 个 group"
        g = groups[0]
        assert g["fact_id"] == "f_test_1"
        assert g["fact_text"] == "城镇职工住院起付标准1300元"  # join 了 fact_text
        assert len(g["rules"]) == 2
        types = {r["rule_type"] for r in g["rules"]}
        assert types == {"起付线", "支付比例"}
    finally:
        for n in (rcol, fcol):
            if utility.has_collection(n):
                utility.drop_collection(n)


def test_search_semantic_and_hybrid():
    """semantic 向量召回 + hybrid 标量过滤+向量。需真实向量化（加载模型）。"""
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
        get_embedding_provider,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection, upsert_facts,
    )
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection, rule_to_entity, upsert_rules,
    )
    from src.knowledge_extension.rule_explanation.rules_search_service import RulesSearchService

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    rcol, fcol = "_test_rules_sem_r", "_test_rules_sem_f"
    try:
        provider = get_embedding_provider()
        # 真实向量化 fact_text（语义区分依赖真实向量）
        v1 = provider.encode(["城镇职工住院起付标准1300元"])[0]
        v2 = provider.encode(["城乡居民门诊统筹支付50%"])[0]
        facts_col = create_policy_facts_collection(collection_name=fcol, drop_existing=True)
        rules_col = create_policy_rules_v2_collection(collection_name=rcol, drop_existing=True)
        upsert_facts(facts_col, [
            {"fact_id": "f_sem_1", "doc_id": "d_sem", "fact_text": "城镇职工住院起付标准1300元",
             "vector": v1, "created_at": "t"},
            {"fact_id": "f_sem_2", "doc_id": "d_sem", "fact_text": "城乡居民门诊统筹支付50%",
             "vector": v2, "created_at": "t"},
        ])
        rules = [
            rule_to_entity({"rule_id": "rs1", "fact_id": "f_sem_1", "rule_type": "起付线",
                            "insu_type": "城镇职工基本医疗保险", "deductible_amount": "1300元"},
                           vector=v1, extracted_at="t"),
            rule_to_entity({"rule_id": "rs2", "fact_id": "f_sem_2", "rule_type": "支付比例",
                            "insu_type": "城乡居民基本医疗保险", "payment_ratio": "50%"},
                           vector=v2, extracted_at="t"),
        ]
        for r in rules:
            r["doc_id"] = "d_sem"
        upsert_rules(rules_col, rules)

        svc = RulesSearchService(rules_col_name=rcol, facts_col_name=fcol)

        # semantic：语义查询“职工住院起付”应召回 f_sem_1（城镇职工起付）
        sem_groups = svc.search_semantic("职工住院起付标准", top_k=5)
        assert len(sem_groups) >= 1
        top_fact = sem_groups[0]["fact_id"]
        assert top_fact == "f_sem_1", f"语义召回应首选城镇职工起付，实际={top_fact}"
        assert sem_groups[0]["rules"][0]["score"] > 0  # 带 score

        # hybrid：向量 + insu_type 过滤
        hyb_groups = svc.search_hybrid("住院", {"insu_type": "城镇职工基本医疗保险"}, top_k=5)
        for g in hyb_groups:
            for r in g["rules"]:
                assert r["insu_type"] == "城镇职工基本医疗保险"
    finally:
        for n in (rcol, fcol):
            if utility.has_collection(n):
                utility.drop_collection(n)
